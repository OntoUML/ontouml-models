"""Generate OntoUML/UFO Catalog model-level metadata.ttl files from metadata.yaml.

The converter treats metadata.yaml as the single source of editable model-level
metadata and writes metadata.ttl next to it. It intentionally generates
metadata.ttl, not metadata-turtle.ttl, which is the distribution metadata file for
ontology.ttl.

The tool is intended for repository maintenance and later CI/workflow use. It can
process one or more selected dataset folders or every dataset folder under
models/. Existing metadata.ttl files are read only to preserve stable catalog
identifiers and catalog-managed values that are not present in metadata.yaml.

Typical usage from the repository root:

    python scripts/metadata_yaml_to_ttl.py models/amaral2019rot
    python scripts/metadata_yaml_to_ttl.py models/a models/b
    python scripts/metadata_yaml_to_ttl.py --all --models-dir models
    python scripts/metadata_yaml_to_ttl.py --all --allow-missing-license
    python scripts/metadata_yaml_to_ttl.py models/example --check

Exit codes:

    0  conversion completed successfully and, in --check mode, no changes are needed
    1  conversion failed for at least one dataset, or --check detected changes
    2  command-line, discovery, or write problem prevented normal execution
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence
from urllib.parse import urlparse

try:
    import yaml
except (
    ImportError
) as exc:  # pragma: no cover - exercised only when dependency is missing
    raise SystemExit(
        "PyYAML is required. Install it with: python -m pip install -r scripts/requirements.txt"
    ) from exc

try:
    from rdflib import Graph, Literal, Namespace, URIRef
    from rdflib.namespace import RDF, RDFS, SKOS, XSD
except (
    ImportError
) as exc:  # pragma: no cover - exercised only when dependency is missing
    raise SystemExit(
        "RDFLib is required. Install it with: python -m pip install -r scripts/requirements.txt"
    ) from exc

DCAT = Namespace("http://www.w3.org/ns/dcat#")
DCT = Namespace("http://purl.org/dc/terms/")
FDPO = Namespace("https://w3id.org/fdp/fdp-o#")
LCC = Namespace("http://id.loc.gov/authorities/classification/")
MOD = Namespace("https://w3id.org/mod#")
OCMV = Namespace("https://w3id.org/ontouml-models/vocabulary#")

DEFAULT_CATALOG_IRI = (
    "https://w3id.org/ontouml-models/catalog/b663ca18-8085-44a7-bcfe-2c2b5ba1faa8"
)
DEFAULT_MODEL_IRI_BASE = "https://w3id.org/ontouml-models/model"
DEFAULT_REPOSITORY = "OntoUML/ontouml-models"
DEFAULT_BRANCH = "master"
DEFAULT_MODELS_DIR = "models"
OUTPUT_FILE_NAME = "metadata.ttl"

DATE_YEAR_RE = re.compile(r"^\d{4}$")
DATE_YEAR_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
DATE_TIME_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T"
    r"(\d{2}):(\d{2}):(\d{2})"
    r"(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2})?$"
)
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
MODEL_IRI_RE = re.compile(
    r"<(https://w3id\.org/ontouml-models/model/[^>]+/?)>\s+a\s+[^.;]*\bdcat:Dataset\b",
    re.S,
)
DISTRIBUTION_STATEMENT_RE = re.compile(
    r"<([^>]+)>\s+dcat:distribution\s+(.+?)(?:\s+\.\s*|\s*\Z)", re.S
)
URI_RE = re.compile(r"<([^>]+)>")
PREFIXED_DATETIME_RE_TEMPLATE = r"\bfdpo:{name}\s+\"([^\"]+)\"\^\^xsd:dateTime"
FULL_DATETIME_RE_TEMPLATE = (
    r"<https://w3id\.org/fdp/fdp-o#{name}>\s+\"([^\"]+)\"\^\^"
    r"<http://www\.w3\.org/2001/XMLSchema#dateTime>"
)
STORAGE_LITERAL_RE = re.compile(r"\bocmv:storageUrl\s+\"([^\"]+)\"\^\^xsd:anyURI", re.S)
LCC_URI_RE = re.compile(
    r"^https?://id\.loc\.gov/authorities/classification/([A-Z][A-Z0-9.-]*)/?$",
    re.I,
)
STORAGE_URI_RE = re.compile(r"\bocmv:storageUrl\s+<([^>]+)>", re.S)
IS_PART_OF_RE = re.compile(r"\bdct:isPartOf\s+<([^>]+)>", re.S)
LICENSE_RE = re.compile(r"\bdct:license\s+<([^>]+)>", re.S)

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    # Keep this list aligned with scripts/validate_metadata_yaml.py.
    # The converter intentionally accepts only repository-facing model-level
    # metadata.yaml fields, not RDF predicate aliases or converter-only fields.
    "title": ("title",),
    "acronym": ("acronym",),
    "issued": ("issued",),
    "modified": ("modified",),
    "contributor": ("contributor",),
    "keyword": ("keyword",),
    "theme": ("theme",),
    "editorial_note": ("editorialNote",),
    "ontology_type": ("ontologyType",),
    "language": ("language",),
    "designed_for_task": ("designedForTask",),
    "context": ("context",),
    "source": ("source",),
    "representation_style": ("representationStyle",),
    "landing_page": ("landingPage",),
    "license": ("license",),
}

KNOWN_TOP_LEVEL_FIELDS: set[str] = {
    alias for aliases in FIELD_ALIASES.values() for alias in aliases
}


DESIGNED_FOR_TASKS: dict[str, URIRef] = {
    "conceptualclarification": OCMV.ConceptualClarification,
    "datapublication": OCMV.DataPublication,
    "decisionsupportsystem": OCMV.DecisionSupportSystem,
    "example": OCMV.Example,
    "informationretrieval": OCMV.InformationRetrieval,
    "interoperability": OCMV.Interoperability,
    "languageengineering": OCMV.LanguageEngineering,
    "learning": OCMV.Learning,
    "ontologicalanalysis": OCMV.OntologicalAnalysis,
    "softwareengineering": OCMV.SoftwareEngineering,
}
CONTEXTS: dict[str, URIRef] = {
    "classroom": OCMV.Classroom,
    "industry": OCMV.Industry,
    "research": OCMV.Research,
}
REPRESENTATION_STYLES: dict[str, URIRef] = {
    "ontouml": OCMV.OntoumlStyle,
    "ontoumlstyle": OCMV.OntoumlStyle,
    "ufo": OCMV.UfoStyle,
    "ufostyle": OCMV.UfoStyle,
}
ONTOLOGY_TYPES: dict[str, URIRef] = {
    "application": OCMV.Application,
    "core": OCMV.Core,
    "domain": OCMV.Domain,
}

LCC_CLASSES: dict[str, str] = {
    "A": "General Works",
    "B": "Philosophy, Psychology, Religion",
    "C": "Auxiliary Sciences of History",
    "D": "World History and History of Europe, Asia, Africa, Australia, New Zealand, etc.",
    "E": "History of the Americas",
    "F": "History of the Americas",
    "G": "Geography, Anthropology, and Recreation",
    "H": "Social Sciences",
    "J": "Political Science",
    "K": "Law",
    "L": "Education",
    "M": "Music",
    "N": "Fine Arts",
    "P": "Language and Literature",
    "Q": "Science",
    "R": "Medicine",
    "S": "Agriculture",
    "T": "Technology",
    "U": "Military Science",
    "V": "Naval Science",
    "Z": "Bibliography, Library Science, and General Information Resources",
}

LICENSE_ALIASES: dict[str, str] = {
    "ccby40": "https://creativecommons.org/licenses/by/4.0/",
    "creativecommonsattribution40international": "https://creativecommons.org/licenses/by/4.0/",
    "ccbysa40": "https://creativecommons.org/licenses/by-sa/4.0/",
    "creativecommonsattributionsharealike40international": "https://creativecommons.org/licenses/by-sa/4.0/",
    "ccbysa30": "https://creativecommons.org/licenses/by-sa/3.0/",
    "creativecommonsattributionsharealike30unported": "https://creativecommons.org/licenses/by-sa/3.0/",
    "cc010": "https://creativecommons.org/publicdomain/zero/1.0/",
    "creativecommonszero10universaldomainpublicdedication": "https://creativecommons.org/publicdomain/zero/1.0/",
    "mit": "http://spdx.org/licenses/MIT",
}


class MetadataYamlLoader(yaml.SafeLoader):
    """Safe YAML loader preserving date-like scalar lexical forms."""


MetadataYamlLoader.yaml_implicit_resolvers = {
    key: [
        resolver
        for resolver in resolvers
        if resolver[0] != "tag:yaml.org,2002:timestamp"
    ]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _construct_mapping_no_duplicates(
    loader: MetadataYamlLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


MetadataYamlLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping_no_duplicates,
)


class MetadataConversionError(RuntimeError):
    """Raised when a dataset metadata file cannot be converted."""


class MetadataSetupError(RuntimeError):
    """Raised when CLI setup, discovery, or writing prevents normal execution."""


@dataclass(frozen=True)
class ExistingMetadata:
    """Catalog-managed metadata read from an existing metadata.ttl file."""

    model_iri: Optional[URIRef] = None
    distribution_subject_iri: Optional[URIRef] = None
    catalog_iri: Optional[URIRef] = None
    storage_url: Optional[str] = None
    metadata_issued: Optional[Literal] = None
    metadata_modified: Optional[Literal] = None
    license_iri: Optional[URIRef] = None
    distributions: tuple[URIRef, ...] = ()


@dataclass(frozen=True)
class Config:
    """Runtime conversion configuration."""

    models_dir_name: str = DEFAULT_MODELS_DIR
    repository: str = DEFAULT_REPOSITORY
    branch: str = DEFAULT_BRANCH
    model_iri_base: str = DEFAULT_MODEL_IRI_BASE
    catalog_iri: str = DEFAULT_CATALOG_IRI
    allow_missing_license: bool = False
    check: bool = False
    dry_run: bool = False
    metadata_timestamp: Optional[str] = None
    preserve_existing: bool = True
    emit_diff: bool = True
    quiet: bool = False


@dataclass
class ConversionResult:
    """Conversion result for one dataset folder."""

    dataset_path: Path
    yaml_path: Path
    ttl_path: Path
    triple_count: int
    changed: bool
    written: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["dataset_path"] = str(self.dataset_path)
        data["yaml_path"] = str(self.yaml_path)
        data["ttl_path"] = str(self.ttl_path)
        return data


def bind_prefixes(graph: Graph) -> None:
    """Bind prefixes used in model-level catalog metadata."""

    graph.bind("dcat", DCAT)
    graph.bind("dct", DCT)
    graph.bind("fdpo", FDPO)
    graph.bind("lcc", LCC)
    graph.bind("mod", MOD)
    graph.bind("ocmv", OCMV)
    graph.bind("rdf", RDF)
    graph.bind("rdfs", RDFS)
    graph.bind("skos", SKOS)
    graph.bind("xsd", XSD)


def namespace_manager():
    graph = Graph()
    bind_prefixes(graph)
    return graph.namespace_manager


NS_MANAGER = namespace_manager()


def canonical_token(value: Any) -> str:
    """Normalize values for alias and controlled-vocabulary matching."""

    text = str(value).strip()
    if text.startswith("ocmv:"):
        text = text.split(":", 1)[1]
    elif text.startswith(str(OCMV)):
        text = text[len(str(OCMV)) :]
    return re.sub(r"[^a-z0-9]", "", text.lower())


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return len(value) == 0
    return False


def mapping_get_normalized(mapping: Mapping[str, Any], key: str) -> Any:
    wanted = canonical_token(key)
    for candidate, value in mapping.items():
        if canonical_token(candidate) == wanted:
            return value
    return None


def canonical_value(data: Mapping[str, Any], canonical: str) -> Any:
    """Return a value using the strict validator-compatible field names."""

    for key in FIELD_ALIASES[canonical]:
        if key in data:
            return data[key]
    return None


def scalar_text(value: Any) -> str:
    return str(value).strip()


def first_text(value: Any) -> Optional[str]:
    """Extract a display text from common scalar, list, or language-map values."""

    if value is None:
        return None
    if isinstance(value, Mapping):
        for key in ("value", "en", "eng", "english", "label", "title", "name"):
            nested = mapping_get_normalized(value, key)
            text = first_text(nested)
            if text:
                return text
        for nested in value.values():
            text = first_text(nested)
            if text:
                return text
        return None
    if isinstance(value, list):
        for item in value:
            text = first_text(item)
            if text:
                return text
        return None
    text = scalar_text(value)
    return text or None


def is_http_uri(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def make_uri(
    value: Any,
    *,
    field_name: str,
    allowed_schemes: Sequence[str] = ("http", "https"),
) -> URIRef:
    if not isinstance(value, str):
        raise MetadataConversionError(
            f"Field '{field_name}' must be a URI string; got {type(value).__name__}."
        )
    text = value.strip()
    parsed = urlparse(text)
    if not parsed.scheme or parsed.scheme not in allowed_schemes:
        schemes = ", ".join(f"{scheme}:" for scheme in allowed_schemes)
        raise MetadataConversionError(
            f"Field '{field_name}' must be an absolute URI using {schemes}; got {value!r}."
        )
    if parsed.scheme in {"http", "https"} and not parsed.netloc:
        raise MetadataConversionError(
            f"Field '{field_name}' must be an absolute HTTP(S) URI; got {value!r}."
        )
    if parsed.scheme == "mailto" and not parsed.path:
        raise MetadataConversionError(
            f"Field '{field_name}' must be a non-empty mailto URI."
        )
    return URIRef(text)


def license_uri(value: Any, *, allow_missing: bool) -> Optional[URIRef]:
    """Return the model license URI from a repository-style scalar value.

    The YAML validator/fixer expects ``license`` to be a single scalar HTTP(S) URI
    and can normalize supported scalar shorthands such as ``CC-BY-4.0``. Mapping
    forms such as ``license: {id: CC-BY-4.0}`` are intentionally rejected here so
    the converter does not accept syntax that the validator/fixer would flag.
    """

    if is_missing(value):
        if allow_missing:
            return None
        raise MetadataConversionError(
            "Missing mandatory metadata field(s): license. "
            "Use --allow-missing-license only for legacy datasets that intentionally lack license metadata."
        )
    if isinstance(value, (Mapping, list)) or isinstance(value, bool):
        raise MetadataConversionError(
            "Field 'license' must be a single scalar HTTP(S) URI or supported license identifier."
        )
    text = scalar_text(value)
    if not text:
        if allow_missing:
            return None
        raise MetadataConversionError("Field 'license' is empty or unreadable.")
    if is_http_uri(text):
        return URIRef(text.strip())
    normalized = canonical_token(text)
    if normalized in LICENSE_ALIASES:
        return URIRef(LICENSE_ALIASES[normalized])
    raise MetadataConversionError(
        f"Field 'license' must be an absolute HTTP(S) URI or a supported scalar license identifier; got {text!r}."
    )


def date_literal(value: Any, field_name: str) -> Literal:
    if is_missing(value):
        raise MetadataConversionError(
            f"Missing mandatory metadata field(s): {field_name}."
        )
    text = scalar_text(value)
    if DATE_YEAR_RE.fullmatch(text):
        return Literal(text, datatype=XSD.gYear, normalize=False)
    year_month = DATE_YEAR_MONTH_RE.fullmatch(text)
    if year_month:
        try:
            date(int(year_month.group(1)), int(year_month.group(2)), 1)
        except ValueError as exc:
            raise MetadataConversionError(
                f"Invalid calendar date in field '{field_name}': {text}"
            ) from exc
        return Literal(text, datatype=XSD.gYearMonth, normalize=False)
    date_match = DATE_RE.fullmatch(text)
    if date_match:
        try:
            date.fromisoformat(text)
        except ValueError as exc:
            raise MetadataConversionError(
                f"Invalid calendar date in field '{field_name}': {text}"
            ) from exc
        return Literal(text, datatype=XSD.date, normalize=False)
    date_time = DATE_TIME_RE.fullmatch(text)
    if date_time:
        try:
            date.fromisoformat(date_time.group(1))
            datetime(2000, 1, 1, *map(int, date_time.group(2, 3, 4)))
        except ValueError as exc:
            raise MetadataConversionError(
                f"Invalid xsd:dateTime-like value in field '{field_name}': {text}"
            ) from exc
        return Literal(text, datatype=XSD.dateTime, normalize=False)
    raise MetadataConversionError(
        f"Field '{field_name}' has unsupported date value {text!r}. "
        "Use YYYY, YYYY-MM, YYYY-MM-DD, or an xsd:dateTime-like value."
    )


def configured_datetime_literal(value: str, option_name: str) -> Literal:
    if not DATE_TIME_RE.fullmatch(value):
        raise MetadataConversionError(
            f"{option_name} must be an xsd:dateTime lexical value, for example 2024-01-02T03:04:05Z."
        )
    return Literal(value, datatype=XSD.dateTime, normalize=False)


def current_datetime_literal() -> Literal:
    """Return current UTC timestamp. Used only when explicitly requested by CLI."""

    value = (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    return Literal(value, datatype=XSD.dateTime, normalize=False)


def _literal_scalar_text(value: Any, field_name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise MetadataConversionError(
            f"Field '{field_name}' literal values must be strings or scalar numbers."
        )
    return str(value)


def _validate_language_tag(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not LANGUAGE_RE.fullmatch(value.strip()):
        raise MetadataConversionError(
            f"Field '{field_name}' must use a language tag such as 'en' or 'pt-BR'."
        )
    return value.strip()


def literal_values(
    value: Any, field_name: str, *, default_lang: Optional[str] = None
) -> Iterable[Literal]:
    """Yield RDF literals from validator-compatible YAML literal forms."""

    if default_lang:
        default_lang = _validate_language_tag(default_lang, f"{field_name}.language")

    for item in as_list(value):
        if item is None:
            continue
        if isinstance(item, Mapping):
            if "value" in item:
                item_value = item.get("value")
                literal_text = _literal_scalar_text(item_value, f"{field_name}.value")
                lang = item.get("lang") or item.get("language")
                datatype_value = item.get("datatype")
                if lang and datatype_value:
                    raise MetadataConversionError(
                        f"Field '{field_name}' cannot define both language and datatype for one literal."
                    )
                if lang:
                    yield Literal(
                        literal_text,
                        lang=_validate_language_tag(lang, f"{field_name}.lang"),
                    )
                elif datatype_value:
                    yield Literal(
                        literal_text,
                        datatype=make_uri(
                            str(datatype_value), field_name=f"{field_name}.datatype"
                        ),
                    )
                elif default_lang:
                    yield Literal(literal_text, lang=default_lang)
                else:
                    yield Literal(literal_text)
            else:
                for lang, literal_value in item.items():
                    literal_text = _literal_scalar_text(
                        literal_value, f"{field_name}.{lang}"
                    )
                    yield Literal(
                        literal_text,
                        lang=_validate_language_tag(lang, f"{field_name}.{lang}"),
                    )
            continue

        literal_text = _literal_scalar_text(item, field_name)
        if default_lang:
            yield Literal(literal_text, lang=default_lang)
        else:
            yield Literal(literal_text)


def language_values(value: Any) -> list[str]:
    values: list[str] = []
    for item in as_list(value):
        if is_missing(item):
            continue
        if not isinstance(item, str):
            raise MetadataConversionError(
                "Field 'language' must contain language-tag strings."
            )
        parts = item.split(",") if "," in item else [item]
        for part in parts:
            if part.strip():
                values.append(_validate_language_tag(part.strip(), "language"))
    return values


def first_language(data: Mapping[str, Any]) -> Optional[str]:
    languages = language_values(canonical_value(data, "language"))
    return languages[0] if languages else None


def normalize_enum(value: Any, allowed: dict[str, URIRef], field_name: str) -> URIRef:
    if not isinstance(value, str) or not value.strip():
        raise MetadataConversionError(
            f"Field '{field_name}' must contain non-empty controlled-value strings."
        )
    text = value.strip()
    if is_http_uri(text):
        uri = URIRef(text)
        if uri in allowed.values():
            return uri
        raise MetadataConversionError(
            f"Unsupported URI for field '{field_name}': {text}"
        )
    token = canonical_token(text)
    if token in allowed:
        return allowed[token]
    supported = ", ".join(sorted(allowed))
    raise MetadataConversionError(
        f"Unsupported value for field '{field_name}': {text!r}. Supported normalized values: {supported}."
    )


def normalize_theme(value: Any) -> URIRef:
    if not isinstance(value, str) or not value.strip():
        raise MetadataConversionError(
            "Field 'theme' must contain one scalar Library of Congress Classification value."
        )
    text = value.strip()
    if is_http_uri(text):
        match = LCC_URI_RE.fullmatch(text)
        if not match:
            raise MetadataConversionError(
                f"Field 'theme' must use the Library of Congress Classification namespace; got {text!r}."
            )
        return URIRef(str(LCC) + match.group(1).upper())
    label_match = re.fullmatch(r"Class\s+([A-Z])\s+-\s+.+", text, re.I)
    if label_match:
        code = label_match.group(1).upper()
        return URIRef(str(LCC) + code)
    if text.lower().startswith("lcc:"):
        text = text.split(":", 1)[1]
    code = text.strip().strip("/").upper()
    if re.fullmatch(r"[A-Z][A-Z0-9.-]*", code) and code[0] in LCC_CLASSES:
        return URIRef(str(LCC) + code)
    raise MetadataConversionError(
        "Field 'theme' must be an LCC label such as 'Class H - Social Sciences', "
        "a compact code such as 'H', or a full LCC URI."
    )


def deterministic_model_iri(dataset_folder: Path, model_iri_base: str) -> URIRef:
    slug = dataset_folder.name.strip().strip("/")
    if not slug:
        raise MetadataConversionError(
            "Could not infer model IRI because the dataset folder has no name."
        )
    generated_uuid = uuid.uuid5(
        uuid.NAMESPACE_URL, f"{model_iri_base.rstrip('/')}|{slug}"
    )
    return URIRef(f"{model_iri_base.rstrip('/')}/{generated_uuid}/")


def yaml_model_iri(
    data: Mapping[str, Any], dataset_folder: Path, model_iri_base: str
) -> URIRef:
    # metadata.yaml no longer exposes a model IRI field. Existing metadata.ttl
    # preserves stable UUID-based IRIs; new datasets receive deterministic UUIDv5 IRIs.
    return deterministic_model_iri(dataset_folder, model_iri_base)


def normalized_model_iri(model_iri: URIRef) -> URIRef:
    return URIRef(str(model_iri).rstrip("/"))


def default_storage_url(dataset_folder: Path, config: Config) -> str:
    parts = dataset_folder.as_posix().split("/")
    model_path = f"{config.models_dir_name.strip('/')}/{dataset_folder.name}"
    if config.models_dir_name in parts:
        idx = len(parts) - 1 - list(reversed(parts)).index(config.models_dir_name)
        model_path = (
            "/".join(parts[idx : idx + 2]) if idx + 1 < len(parts) else model_path
        )
    return f"https://github.com/{config.repository}/tree/{config.branch}/{model_path}"


def prefixed_datetime_literal_from_text(
    text: str, local_name: str
) -> Optional[Literal]:
    patterns = [
        PREFIXED_DATETIME_RE_TEMPLATE.format(name=re.escape(local_name)),
        FULL_DATETIME_RE_TEMPLATE.format(name=re.escape(local_name)),
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return Literal(match.group(1), datatype=XSD.dateTime, normalize=False)
    return None


def unique_uri_refs(values: Iterable[str]) -> tuple[URIRef, ...]:
    seen: set[str] = set()
    result: list[URIRef] = []
    for value in values:
        if value not in seen:
            result.append(URIRef(value))
            seen.add(value)
    return tuple(result)


def read_existing_metadata(ttl_path: Path) -> ExistingMetadata:
    """Read catalog-managed values from an existing metadata.ttl file.

    The reader is deliberately tolerant. Some legacy metadata.ttl files contain
    formatting that RDFLib may reject, so regex extraction is used for the values
    that must be preserved during regeneration.
    """

    if not ttl_path.exists():
        return ExistingMetadata()
    try:
        text = ttl_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MetadataSetupError(
            f"Could not read existing metadata.ttl {ttl_path}: {exc}"
        ) from exc

    model_match = MODEL_IRI_RE.search(text)
    model_iri = URIRef(model_match.group(1)) if model_match else None

    distribution_subject_iri = None
    distributions: tuple[URIRef, ...] = ()
    dist_match = DISTRIBUTION_STATEMENT_RE.search(text)
    if dist_match:
        distribution_subject_iri = URIRef(dist_match.group(1))
        distributions = unique_uri_refs(URI_RE.findall(dist_match.group(2)))

    catalog_iri = None
    is_part_of_match = IS_PART_OF_RE.search(text)
    if is_part_of_match:
        catalog_iri = URIRef(is_part_of_match.group(1))

    storage_url = None
    storage_literal = STORAGE_LITERAL_RE.search(text)
    storage_uri = STORAGE_URI_RE.search(text)
    if storage_literal:
        storage_url = storage_literal.group(1)
    elif storage_uri:
        storage_url = storage_uri.group(1)

    return ExistingMetadata(
        model_iri=model_iri,
        distribution_subject_iri=distribution_subject_iri,
        catalog_iri=catalog_iri,
        storage_url=storage_url,
        metadata_issued=prefixed_datetime_literal_from_text(text, "metadataIssued"),
        metadata_modified=prefixed_datetime_literal_from_text(text, "metadataModified"),
        license_iri=URIRef(LICENSE_RE.search(text).group(1))
        if LICENSE_RE.search(text)
        else None,
        distributions=distributions,
    )


def metadata_timestamp_literals(
    existing: ExistingMetadata, config: Config, ttl_path: Path
) -> tuple[Literal, Literal]:
    if existing.metadata_issued is not None:
        metadata_issued = existing.metadata_issued
    elif config.metadata_timestamp == "now":
        metadata_issued = current_datetime_literal()
    elif config.metadata_timestamp:
        metadata_issued = configured_datetime_literal(
            config.metadata_timestamp, "--metadata-timestamp"
        )
    else:
        raise MetadataConversionError(
            f"No fdpo:metadataIssued value is available for {ttl_path}. "
            "Existing metadata.ttl files that lack FDP metadata timestamps and new metadata.ttl files "
            "must be regenerated with --metadata-timestamp, for example "
            "--metadata-timestamp 2026-01-31T12:00:00Z."
        )

    if existing.metadata_modified is not None:
        metadata_modified = existing.metadata_modified
    elif config.metadata_timestamp == "now":
        metadata_modified = metadata_issued
    elif config.metadata_timestamp:
        metadata_modified = configured_datetime_literal(
            config.metadata_timestamp, "--metadata-timestamp"
        )
    else:
        metadata_modified = metadata_issued

    return metadata_issued, metadata_modified


def validate_supported_yaml_fields(data: Mapping[str, Any]) -> None:
    unexpected: list[str] = []
    for key in data:
        if not isinstance(key, str):
            raise MetadataConversionError(
                f"Top-level metadata.yaml key {key!r} must be a string."
            )
        if key not in KNOWN_TOP_LEVEL_FIELDS:
            unexpected.append(key)
    if unexpected:
        quoted = ", ".join(repr(key) for key in sorted(unexpected))
        raise MetadataConversionError(
            "Unsupported metadata.yaml field(s): "
            + quoted
            + ". Run scripts/validate_metadata_yaml.py and keep only fields defined by the catalog metadata.yaml template."
        )


def validate_minimum_convertible_fields(
    data: Mapping[str, Any], *, allow_missing_license: bool
) -> None:
    missing = [
        field
        for field in ("title", "issued", "theme", "keyword")
        if is_missing(canonical_value(data, field))
    ]
    if missing:
        raise MetadataConversionError(
            "Missing mandatory metadata field(s): " + ", ".join(missing) + "."
        )
    if is_missing(canonical_value(data, "license")) and not allow_missing_license:
        raise MetadataConversionError(
            "Missing mandatory metadata field(s): license. "
            "Use --allow-missing-license only for legacy datasets that intentionally lack license metadata."
        )


def append_predicate(
    statements: list[tuple[URIRef, list[Any]]],
    predicate: URIRef,
    objects: Iterable[Any],
) -> None:
    values = [obj for obj in objects if obj is not None]
    if values:
        statements.append((predicate, values))


def uri_objects(value: Any, field_name: str) -> list[URIRef]:
    return [
        make_uri(str(item), field_name=field_name)
        for item in as_list(value)
        if not is_missing(item)
    ]


def literal_objects(
    value: Any, field_name: str, *, default_lang: Optional[str] = None
) -> list[Literal]:
    if value is None:
        return []
    return list(literal_values(value, field_name, default_lang=default_lang))


def keyword_literal_objects(value: Any) -> list[Literal]:
    """Return dcat:keyword literals with the catalog-mandated English tag.

    Keywords in metadata.yaml are maintained in English, regardless of the
    model's dct:language value. Even if a validator-compatible literal mapping
    includes a language tag, generated dcat:keyword values are emitted as @en.
    """

    if value is None:
        return []

    literals: list[Literal] = []
    for item in as_list(value):
        if item is None:
            continue
        if isinstance(item, Mapping):
            if "value" in item:
                if item.get("lang"):
                    _validate_language_tag(item.get("lang"), "keyword.lang")
                if item.get("language"):
                    _validate_language_tag(item.get("language"), "keyword.language")
                if item.get("datatype"):
                    make_uri(str(item.get("datatype")), field_name="keyword.datatype")
                text = _literal_scalar_text(item.get("value"), "keyword.value")
                literals.append(Literal(text, lang="en"))
            else:
                for lang, literal_value in item.items():
                    _validate_language_tag(lang, f"keyword.{lang}")
                    text = _literal_scalar_text(literal_value, f"keyword.{lang}")
                    literals.append(Literal(text, lang="en"))
            continue

        text = _literal_scalar_text(item, "keyword")
        literals.append(Literal(text, lang="en"))

    return literals


DISTRIBUTION_IRI_RE = re.compile(r"<([^>]+)>\s+a\s+[^.;]*\bdcat:Distribution\b", re.S)


def read_distribution_iri_from_metadata_file(path: Path) -> Optional[URIRef]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MetadataSetupError(
            f"Could not read distribution metadata file {path}: {exc}"
        ) from exc
    match = DISTRIBUTION_IRI_RE.search(text)
    return URIRef(match.group(1)) if match else None


def discover_distribution_iris(dataset_folder: Path) -> tuple[URIRef, ...]:
    """Discover distribution IRIs from distribution-specific metadata files.

    metadata.yaml no longer contains distribution links. For new datasets, this
    lets metadata.ttl aggregate distribution metadata generated earlier in the
    workflow, such as metadata-json.ttl, metadata-turtle.ttl, metadata-vpp.ttl,
    and metadata-png-*.ttl.
    """

    candidates = sorted(
        path
        for path in dataset_folder.glob("metadata-*.ttl")
        if path.name != OUTPUT_FILE_NAME
    )
    return unique_uri_refs(
        str(uri)
        for path in candidates
        for uri in [read_distribution_iri_from_metadata_file(path)]
        if uri is not None
    )


def combined_distribution_iris(
    dataset_folder: Path, existing: ExistingMetadata
) -> tuple[URIRef, ...]:
    distributions = list(existing.distributions)
    distributions.extend(discover_distribution_iris(dataset_folder))
    return unique_uri_refs(str(uri) for uri in distributions)


def term_n3(term: Any) -> str:
    if isinstance(term, str) and term.startswith("["):
        return term
    if isinstance(term, URIRef):
        return term.n3(NS_MANAGER)
    if isinstance(term, Literal):
        return term.n3(NS_MANAGER)
    raise TypeError(f"Unsupported RDF term type: {type(term).__name__}")


def render_predicate_object(
    predicate: URIRef, objects: list[Any], *, final: bool
) -> str:
    predicate_text = predicate.n3(NS_MANAGER)
    object_texts = [term_n3(obj) for obj in objects]
    suffix = " ." if final else ";"
    if len(object_texts) == 1:
        return f"    {predicate_text} {object_texts[0]}{suffix}"
    joined = (",\n" + " " * (len(predicate_text) + 5)).join(object_texts)
    return f"    {predicate_text} {joined}{suffix}"


def render_turtle(
    subject: URIRef,
    distribution_subject: URIRef,
    statements: list[tuple[URIRef, list[Any]]],
    distributions: Sequence[URIRef],
) -> str:
    lines = [
        "@prefix fdpo: <https://w3id.org/fdp/fdp-o#> .",
        "@prefix dcat: <http://www.w3.org/ns/dcat#> .",
        "@prefix dct: <http://purl.org/dc/terms/> .",
        "@prefix lcc: <http://id.loc.gov/authorities/classification/> .",
        "@prefix mod: <https://w3id.org/mod#> .",
        "@prefix ocmv: <https://w3id.org/ontouml-models/vocabulary#> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
        f"{subject.n3(NS_MANAGER)} a dcat:Dataset, mod:SemanticArtefact, dcat:Resource;",
    ]
    for index, (predicate, objects) in enumerate(statements):
        lines.append(
            render_predicate_object(
                predicate, objects, final=index == len(statements) - 1
            )
        )
    if distributions:
        lines.extend(
            [
                "",
                render_predicate_object(
                    DCAT.distribution, list(distributions), final=True
                ).replace(
                    "    dcat:distribution",
                    f"{distribution_subject.n3(NS_MANAGER)} dcat:distribution",
                    1,
                ),
            ]
        )
    return "\n".join(lines) + "\n"


def build_turtle(
    data: Mapping[str, Any],
    dataset_folder: Path,
    existing: ExistingMetadata,
    config: Config,
) -> tuple[str, int, list[str]]:
    validate_supported_yaml_fields(data)
    validate_minimum_convertible_fields(
        data, allow_missing_license=config.allow_missing_license
    )

    warnings: list[str] = []
    yaml_subject = yaml_model_iri(data, dataset_folder, config.model_iri_base)
    subject = (
        existing.model_iri
        if config.preserve_existing and existing.model_iri
        else yaml_subject
    )
    distribution_subject = (
        existing.distribution_subject_iri
        if config.preserve_existing and existing.distribution_subject_iri
        else normalized_model_iri(subject)
    )
    catalog_iri = (
        existing.catalog_iri
        if config.preserve_existing and existing.catalog_iri
        else make_uri(str(config.catalog_iri), field_name="catalog_iri")
    )
    metadata_issued, metadata_modified = metadata_timestamp_literals(
        existing if config.preserve_existing else ExistingMetadata(),
        config,
        dataset_folder / OUTPUT_FILE_NAME,
    )
    storage_url = (
        existing.storage_url
        if config.preserve_existing and existing.storage_url
        else default_storage_url(dataset_folder, config)
    )
    if not storage_url or not is_http_uri(storage_url):
        raise MetadataConversionError(
            f"Field 'storage_url' must resolve to an HTTP(S) URL; got {storage_url!r}."
        )

    yaml_license = canonical_value(data, "license")
    if not is_missing(yaml_license):
        # When a license is present in metadata.yaml, generate dct:license
        # regardless of --allow-missing-license. The flag only relaxes missing
        # license handling; it must not suppress available license metadata.
        license_ref = license_uri(yaml_license, allow_missing=False)
    elif (
        config.allow_missing_license
        and config.preserve_existing
        and existing.license_iri
    ):
        license_ref = existing.license_iri
        warnings.append(
            "License metadata preserved from existing metadata.ttl because metadata.yaml has no license and --allow-missing-license was used."
        )
    else:
        license_ref = license_uri(
            yaml_license, allow_missing=config.allow_missing_license
        )

    statements: list[tuple[URIRef, list[Any]]] = []
    append_predicate(statements, DCT.isPartOf, [catalog_iri])
    append_predicate(
        statements, DCT.title, literal_objects(canonical_value(data, "title"), "title")
    )
    append_predicate(
        statements,
        MOD.acronym,
        literal_objects(canonical_value(data, "acronym"), "acronym"),
    )
    append_predicate(
        statements,
        DCT.issued,
        [date_literal(canonical_value(data, "issued"), "issued")],
    )
    if not is_missing(canonical_value(data, "modified")):
        append_predicate(
            statements,
            DCT.modified,
            [date_literal(canonical_value(data, "modified"), "modified")],
        )
    append_predicate(
        statements, DCAT.theme, [normalize_theme(canonical_value(data, "theme"))]
    )
    append_predicate(
        statements,
        SKOS.editorialNote,
        literal_objects(canonical_value(data, "editorial_note"), "editorial_note"),
    )
    append_predicate(
        statements,
        DCT.language,
        [
            Literal(language)
            for language in language_values(canonical_value(data, "language"))
        ],
    )
    landing_page = canonical_value(data, "landing_page")
    if not is_missing(landing_page):
        append_predicate(
            statements,
            DCAT.landingPage,
            uri_objects(landing_page, "landing_page"),
        )
    if license_ref is not None:
        append_predicate(statements, DCT.license, [license_ref])
    else:
        warnings.append(
            "License metadata omitted because metadata.yaml has no license and --allow-missing-license was used."
        )
    append_predicate(
        statements,
        DCT.contributor,
        uri_objects(canonical_value(data, "contributor"), "contributor"),
    )
    append_predicate(
        statements,
        DCAT.keyword,
        keyword_literal_objects(canonical_value(data, "keyword")),
    )
    append_predicate(
        statements, DCT.source, uri_objects(canonical_value(data, "source"), "source")
    )
    append_predicate(
        statements,
        MOD.designedForTask,
        [
            normalize_enum(item, DESIGNED_FOR_TASKS, "designed_for_task")
            for item in as_list(canonical_value(data, "designed_for_task"))
        ],
    )
    append_predicate(
        statements,
        OCMV.context,
        [
            normalize_enum(item, CONTEXTS, "context")
            for item in as_list(canonical_value(data, "context"))
        ],
    )
    append_predicate(
        statements,
        OCMV.representationStyle,
        [
            normalize_enum(item, REPRESENTATION_STYLES, "representation_style")
            for item in as_list(canonical_value(data, "representation_style"))
        ],
    )
    append_predicate(
        statements,
        OCMV.ontologyType,
        [
            normalize_enum(item, ONTOLOGY_TYPES, "ontology_type")
            for item in as_list(canonical_value(data, "ontology_type"))
        ],
    )
    append_predicate(
        statements, OCMV.storageUrl, [Literal(storage_url.strip(), datatype=XSD.anyURI)]
    )
    append_predicate(statements, FDPO.metadataIssued, [metadata_issued])
    append_predicate(statements, FDPO.metadataModified, [metadata_modified])

    distributions = combined_distribution_iris(
        dataset_folder, existing if config.preserve_existing else ExistingMetadata()
    )
    turtle = render_turtle(subject, distribution_subject, statements, distributions)

    # Verify generated Turtle is parseable even though rendering is manual for stable ordering.
    graph = Graph()
    bind_prefixes(graph)
    try:
        graph.parse(data=turtle, format="turtle")
    except Exception as exc:  # noqa: BLE001 - surface RDFLib parse errors clearly
        raise MetadataConversionError(
            f"Generated Turtle is not parseable: {exc}"
        ) from exc

    return turtle, len(graph), warnings


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=MetadataYamlLoader)
    except yaml.YAMLError as exc:
        raise MetadataConversionError(
            f"Could not parse YAML file {path}: {exc}"
        ) from exc
    except OSError as exc:
        raise MetadataSetupError(f"Could not read YAML file {path}: {exc}") from exc
    if data is None:
        raise MetadataConversionError(f"YAML file is empty: {path}")
    if not isinstance(data, dict):
        raise MetadataConversionError(
            f"Top-level YAML content must be a mapping: {path}"
        )
    return data


def validate_dataset_folder(dataset_folder: Path) -> Path:
    dataset_folder = dataset_folder.resolve()
    if not dataset_folder.exists():
        raise MetadataSetupError(f"Dataset folder does not exist: {dataset_folder}")
    if not dataset_folder.is_dir():
        raise MetadataSetupError(f"Dataset path is not a directory: {dataset_folder}")
    if not (dataset_folder / "metadata.yaml").exists():
        raise MetadataSetupError(
            f"Missing metadata.yaml in dataset folder: {dataset_folder}"
        )
    return dataset_folder


def discover_datasets(models_dir: Path) -> list[Path]:
    models_dir = models_dir.resolve()
    if not models_dir.exists():
        raise MetadataSetupError(f"Models directory does not exist: {models_dir}")
    if not models_dir.is_dir():
        raise MetadataSetupError(f"Models path is not a directory: {models_dir}")
    return sorted(
        path
        for path in models_dir.iterdir()
        if path.is_dir() and (path / "metadata.yaml").exists()
    )


def resolve_datasets(
    paths: Sequence[Path], *, all_datasets: bool, models_dir: Path
) -> list[Path]:
    if all_datasets:
        if paths:
            raise MetadataSetupError("Use either dataset paths or --all, not both.")
        datasets = discover_datasets(models_dir)
    else:
        if not paths:
            raise MetadataSetupError(
                "Provide at least one dataset folder or use --all."
            )
        datasets = [validate_dataset_folder(path) for path in paths]
    if not datasets:
        raise MetadataSetupError("No dataset folders with metadata.yaml were found.")
    return datasets


def convert_dataset(dataset_folder: Path, config: Config) -> ConversionResult:
    dataset_folder = validate_dataset_folder(dataset_folder)
    yaml_path = dataset_folder / "metadata.yaml"
    ttl_path = dataset_folder / OUTPUT_FILE_NAME
    data = read_yaml(yaml_path)
    existing = (
        read_existing_metadata(ttl_path)
        if config.preserve_existing
        else ExistingMetadata()
    )
    turtle, triple_count, warnings = build_turtle(
        data, dataset_folder, existing, config
    )

    old_text = ttl_path.read_text(encoding="utf-8") if ttl_path.exists() else None
    changed = old_text != turtle
    written = False

    if config.dry_run:
        print(turtle)
    elif config.check:
        if changed:
            if old_text is not None and config.emit_diff:
                diff = difflib.unified_diff(
                    old_text.splitlines(),
                    turtle.splitlines(),
                    fromfile=str(ttl_path),
                    tofile=f"{ttl_path} (generated)",
                    lineterm="",
                )
                for line in diff:
                    print(line)
            elif config.emit_diff:
                print(f"Would create {ttl_path}")
    else:
        if changed:
            try:
                ttl_path.write_text(turtle, encoding="utf-8")
            except OSError as exc:
                raise MetadataSetupError(
                    f"Could not write metadata.ttl {ttl_path}: {exc}"
                ) from exc
            written = True

    return ConversionResult(
        dataset_path=dataset_folder,
        yaml_path=yaml_path,
        ttl_path=ttl_path,
        triple_count=triple_count,
        changed=changed,
        written=written,
        warnings=warnings,
    )


def result_status(result: ConversionResult, *, check: bool) -> str:
    if check:
        return "needs update" if result.changed else "up to date"
    if result.written:
        return "generated"
    if result.changed:
        return "changed"
    return "unchanged"


def print_progress_result(result: ConversionResult, *, check: bool) -> None:
    status = result_status(result, check=check)
    severity = "WARNING" if result.warnings else "OK"
    warning_suffix = f", {len(result.warnings)} warning(s)" if result.warnings else ""
    print(
        f"{severity} {status}: {result.dataset_path} -> {result.ttl_path} "
        f"({result.triple_count} triples{warning_suffix})"
    )
    for warning in result.warnings:
        print(f"WARNING {result.yaml_path}: {warning}", file=sys.stderr)


def print_text_summary(
    results: Sequence[ConversionResult], *, error_count: int, check: bool, dry_run: bool
) -> None:
    if dry_run:
        return
    total = len(results) + error_count
    warnings = sum(len(result.warnings) for result in results)
    changed = sum(1 for result in results if result.changed)
    written = sum(1 for result in results if result.written)
    needs_update = sum(1 for result in results if result.changed) if check else 0
    if check:
        print(
            f"Summary: {total} processed, {len(results)} succeeded, "
            f"{error_count} error(s), {warnings} warning(s), "
            f"{needs_update} file(s) need update."
        )
    else:
        print(
            f"Summary: {total} processed, {len(results)} succeeded, "
            f"{error_count} error(s), {warnings} warning(s), "
            f"{written} written, {changed} changed."
        )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate OntoUML/UFO Catalog metadata.ttl files from metadata.yaml.",
    )
    parser.add_argument(
        "datasets",
        nargs="*",
        type=Path,
        help="One or more dataset/model folders containing metadata.yaml.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process every direct dataset folder below --models-dir that contains metadata.yaml.",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=Path(DEFAULT_MODELS_DIR),
        help=f"Catalog models directory used with --all. Default: {DEFAULT_MODELS_DIR}.",
    )
    parser.add_argument(
        "--allow-missing-license",
        action="store_true",
        help="Allow conversion of legacy datasets without license metadata; otherwise license is mandatory.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write files; exit 1 if any metadata.ttl would change.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated Turtle to stdout instead of writing metadata.ttl.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Summary output format. Default: text.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        "--silent",
        action="store_true",
        help="Suppress per-dataset progress logs and the final text summary. Errors are still printed to stderr.",
    )
    parser.add_argument(
        "--repository",
        default=DEFAULT_REPOSITORY,
        help=f"GitHub repository used for generated storage URLs. Default: {DEFAULT_REPOSITORY}.",
    )
    parser.add_argument(
        "--branch",
        default=DEFAULT_BRANCH,
        help=f"Repository branch used for generated storage URLs. Default: {DEFAULT_BRANCH}.",
    )
    parser.add_argument(
        "--model-iri-base",
        default=DEFAULT_MODEL_IRI_BASE,
        help=f"Base IRI used for deterministic UUIDv5 model IRIs when no existing metadata.ttl is present. Default: {DEFAULT_MODEL_IRI_BASE}.",
    )
    parser.add_argument(
        "--catalog-iri",
        default=DEFAULT_CATALOG_IRI,
        help="Catalog IRI used for dct:isPartOf when no existing metadata.ttl value is available.",
    )
    parser.add_argument(
        "--metadata-timestamp",
        help=(
            "xsd:dateTime value to use for fdpo:metadataIssued/fdpo:metadataModified when creating "
            "a new metadata.ttl or regenerating an existing one without FDP timestamps. Use 'now' only "
            "when non-deterministic current timestamps are intentionally desired."
        ),
    )
    parser.add_argument(
        "--no-preserve-existing",
        action="store_true",
        help="Do not read existing metadata.ttl values. Intended only for deliberate regeneration experiments.",
    )
    args = parser.parse_args(argv)
    if args.check and args.dry_run:
        parser.error("--check and --dry-run cannot be used together.")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    config = Config(
        models_dir_name=args.models_dir.name,
        repository=args.repository,
        branch=args.branch,
        model_iri_base=args.model_iri_base,
        catalog_iri=args.catalog_iri,
        allow_missing_license=args.allow_missing_license,
        check=args.check,
        dry_run=args.dry_run,
        metadata_timestamp=args.metadata_timestamp,
        preserve_existing=not args.no_preserve_existing,
        emit_diff=args.format == "text" and not args.quiet,
        quiet=args.quiet,
    )
    try:
        datasets = resolve_datasets(
            args.datasets, all_datasets=args.all, models_dir=args.models_dir
        )
        results: list[ConversionResult] = []
        errors: list[dict[str, str]] = []
        progress_enabled = args.format == "text" and not args.quiet and not args.dry_run
        for dataset in datasets:
            try:
                result = convert_dataset(dataset, config)
                results.append(result)
                if progress_enabled:
                    print_progress_result(result, check=args.check)
            except MetadataConversionError as exc:
                errors.append({"dataset": str(dataset), "error": str(exc)})
                print(f"ERROR {dataset}: {exc}", file=sys.stderr)

        if args.format == "json":
            print(
                json.dumps(
                    {
                        "ok": not errors
                        and not (
                            args.check and any(result.changed for result in results)
                        ),
                        "results": [result.to_dict() for result in results],
                        "errors": errors,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        elif not args.quiet:
            print_text_summary(
                results,
                error_count=len(errors),
                check=args.check,
                dry_run=args.dry_run,
            )

        if errors:
            return 1
        if args.check and any(result.changed for result in results):
            return 1
        return 0
    except MetadataSetupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

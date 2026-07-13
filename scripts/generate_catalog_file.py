"""Generate the OntoUML/UFO Catalog metadata file deterministically.

``catalog.yaml`` is the authoritative source for non-derived catalog-level
metadata. Dataset membership is discovered from the exact ``dcat:Dataset``
subjects in ``models/*/metadata.ttl``. Catalog contributors are derived from
all ``dct:contributor`` values in those files. ``dct:modified`` and
``fdpo:metadataModified`` are managed from semantic changes relative to the
existing output. The generated ``catalog.ttl`` must not be edited manually.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlparse

try:
    import yaml
    from rdflib import Graph, Literal, URIRef
    from rdflib.compare import to_isomorphic
    from rdflib.namespace import DCAT, DCTERMS, RDF, XSD
except ImportError as exc:  # pragma: no cover - dependency failure only
    raise SystemExit(
        "PyYAML and RDFLib are required. Install them with: "
        "python -m pip install -r scripts/requirements.txt"
    ) from exc


DCAT_DATASET = DCAT.Dataset
CATALOG_TYPE_IRIS = (DCAT.Resource, DCAT.Catalog, DCAT.Dataset)
FDPO_METADATA_MODIFIED = URIRef("https://w3id.org/fdp/fdp-o#metadataModified")
CHECK_TIMESTAMP = "1970-01-01T00:00:00Z"
REQUIRED_SOURCE_FIELDS = {
    "catalog_iri",
    "title",
    "alternative",
    "description",
    "language",
    "storage_url",
    "theme_taxonomy",
    "bibliographic_citation",
    "license",
    "access_rights",
    "issued",
    "contact_point",
    "publisher",
    "creators",
    "is_part_of",
    "metadata_issued",
}
CONTACT_FIELDS = {"name", "email"}
LANGUAGE_TAG_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2})$"
)


class CatalogYamlLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def construct_unique_mapping(
    loader: CatalogYamlLoader, node: yaml.nodes.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


CatalogYamlLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_unique_mapping
)


class CatalogGenerationError(RuntimeError):
    """Raised when catalog generation cannot be completed safely."""


@dataclass(frozen=True)
class Config:
    repository_path: Path
    source_path: Path
    output_path: Path
    models_path: Path
    check: bool = False
    generation_timestamp: Optional[str] = None


@dataclass(frozen=True)
class CatalogSource:
    catalog_iri: str
    title: str
    alternative: str
    description: str
    language: str
    storage_url: str
    theme_taxonomy: str
    bibliographic_citation: str
    license: str
    access_rights: str
    issued: str
    contact_name: str
    contact_email: str
    publisher: str
    creators: tuple[str, ...]
    is_part_of: str
    metadata_issued: str


@dataclass(frozen=True)
class CatalogTimestamps:
    modified: Literal
    metadata_modified: Literal


@dataclass(frozen=True)
class CatalogChanges:
    first_generation: bool
    membership_changed: bool
    metadata_changed: bool

    @property
    def semantic_change(self) -> bool:
        return self.first_generation or self.membership_changed or self.metadata_changed

    @property
    def reason(self) -> str:
        if self.first_generation:
            return "catalog output is missing"
        if self.membership_changed:
            return "catalog membership changed"
        if self.metadata_changed:
            return "catalog metadata changed"
        return "generated serialization differs"


def resolve_under_repository(repository_path: Path, raw_path: Path) -> Path:
    """Resolve a relative path below the repository, rejecting path escapes."""

    repository_path = repository_path.resolve()
    candidate = raw_path if raw_path.is_absolute() else repository_path / raw_path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(repository_path)
    except ValueError as exc:
        raise CatalogGenerationError(
            f"Path must remain inside the repository: {raw_path}"
        ) from exc
    return resolved


def config_from_args(args: argparse.Namespace) -> Config:
    repository_path = Path(args.repository_path).resolve()
    if not repository_path.exists():
        raise CatalogGenerationError(
            f"Repository path does not exist: {repository_path}"
        )
    if not repository_path.is_dir():
        raise CatalogGenerationError(
            f"Repository path is not a directory: {repository_path}"
        )
    return Config(
        repository_path=repository_path,
        source_path=resolve_under_repository(repository_path, Path(args.source)),
        output_path=resolve_under_repository(repository_path, Path(args.output)),
        models_path=resolve_under_repository(repository_path, Path(args.models_dir)),
        check=args.check,
        generation_timestamp=(
            require_datetime(args.generation_timestamp, "generation_timestamp")
            if args.generation_timestamp is not None
            else None
        ),
    )


def require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CatalogGenerationError(f"Field '{field_name}' must be a mapping.")
    return value


def require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogGenerationError(
            f"Field '{field_name}' must be a non-empty string."
        )
    return value.strip()


def require_http_iri(value: Any, field_name: str) -> str:
    text = require_string(value, field_name)
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CatalogGenerationError(
            f"Field '{field_name}' must be an absolute HTTP(S) IRI; got {text!r}."
        )
    return text


def require_mailto_iri(value: Any, field_name: str) -> str:
    text = require_string(value, field_name)
    parsed = urlparse(text)
    if parsed.scheme != "mailto" or not parsed.path or "@" not in parsed.path:
        raise CatalogGenerationError(
            f"Field '{field_name}' must be a mailto IRI; got {text!r}."
        )
    return text


def require_date(value: Any, field_name: str) -> str:
    text = require_string(value, field_name)
    if not DATE_RE.fullmatch(text):
        raise CatalogGenerationError(
            f"Field '{field_name}' must use YYYY-MM-DD; got {text!r}."
        )
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise CatalogGenerationError(
            f"Field '{field_name}' must use YYYY-MM-DD; got {text!r}."
        ) from exc
    return text


def require_datetime(value: Any, field_name: str) -> str:
    text = require_string(value, field_name)
    if not DATETIME_RE.fullmatch(text):
        raise CatalogGenerationError(
            f"Field '{field_name}' must use an extended ISO 8601 date-time "
            f"with seconds and a UTC offset or Z suffix; got {text!r}."
        )
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise CatalogGenerationError(
            f"Field '{field_name}' must use an extended ISO 8601 date-time "
            f"with seconds and a UTC offset or Z suffix; got {text!r}."
        ) from exc
    offset = parsed.utcoffset()
    if offset is None or abs(offset) > timedelta(hours=14):
        raise CatalogGenerationError(
            f"Field '{field_name}' must use a valid XML Schema date-time "
            f"timezone offset; got {text!r}."
        )
    return text


def require_iri_list(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise CatalogGenerationError(
            f"Field '{field_name}' must be a non-empty list of HTTP(S) IRIs."
        )
    values = tuple(
        require_http_iri(item, f"{field_name}[{index}]")
        for index, item in enumerate(value)
    )
    if len(set(values)) != len(values):
        raise CatalogGenerationError(f"Field '{field_name}' contains duplicate IRIs.")
    return values


def validate_exact_fields(
    data: Mapping[str, Any], expected: set[str], context: str
) -> None:
    keys = set(data)
    missing = sorted(expected - keys)
    unexpected = sorted(keys - expected)
    problems: list[str] = []
    if missing:
        problems.append("missing: " + ", ".join(missing))
    if unexpected:
        problems.append("unsupported: " + ", ".join(unexpected))
    if problems:
        raise CatalogGenerationError(
            f"Invalid {context} fields ({'; '.join(problems)})."
        )


def load_catalog_source(path: Path) -> CatalogSource:
    if not path.exists():
        raise CatalogGenerationError(f"Catalog source file does not exist: {path}")
    if not path.is_file():
        raise CatalogGenerationError(f"Catalog source path is not a file: {path}")
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=CatalogYamlLoader)
    except UnicodeDecodeError as exc:
        raise CatalogGenerationError(
            f"Catalog source is not valid UTF-8: {path}: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise CatalogGenerationError(
            f"Could not parse catalog source YAML {path}: {exc}"
        ) from exc
    except OSError as exc:
        raise CatalogGenerationError(
            f"Could not read catalog source {path}: {exc}"
        ) from exc

    source = require_mapping(data, "catalog source")
    validate_exact_fields(source, REQUIRED_SOURCE_FIELDS, "catalog source")

    language = require_string(source["language"], "language")
    if not LANGUAGE_TAG_RE.fullmatch(language):
        raise CatalogGenerationError(
            f"Field 'language' must be a valid language tag; got {language!r}."
        )

    contact = require_mapping(source["contact_point"], "contact_point")
    validate_exact_fields(contact, CONTACT_FIELDS, "contact_point")

    return CatalogSource(
        catalog_iri=require_http_iri(source["catalog_iri"], "catalog_iri"),
        title=require_string(source["title"], "title"),
        alternative=require_string(source["alternative"], "alternative"),
        description=require_string(source["description"], "description"),
        language=language,
        storage_url=require_http_iri(source["storage_url"], "storage_url"),
        theme_taxonomy=require_http_iri(source["theme_taxonomy"], "theme_taxonomy"),
        bibliographic_citation=require_string(
            source["bibliographic_citation"], "bibliographic_citation"
        ),
        license=require_http_iri(source["license"], "license"),
        access_rights=require_http_iri(source["access_rights"], "access_rights"),
        issued=require_date(source["issued"], "issued"),
        contact_name=require_string(contact["name"], "contact_point.name"),
        contact_email=require_mailto_iri(contact["email"], "contact_point.email"),
        publisher=require_http_iri(source["publisher"], "publisher"),
        creators=require_iri_list(source["creators"], "creators"),
        is_part_of=require_http_iri(source["is_part_of"], "is_part_of"),
        metadata_issued=require_datetime(source["metadata_issued"], "metadata_issued"),
    )


def canonical_datetime_lexical(value: str) -> str:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized).astimezone(timezone.utc)
    lexical = parsed.strftime("%Y-%m-%dT%H:%M:%S")
    if parsed.microsecond:
        lexical += f".{parsed.microsecond:06d}".rstrip("0")
    return lexical + "Z"


def datetime_literal(value: str) -> Literal:
    return Literal(
        canonical_datetime_lexical(value),
        datatype=XSD.dateTime,
        normalize=False,
    )


def resolve_generation_timestamp(config: Config) -> Literal:
    """Return the timestamp to use for an actual semantic write."""

    if config.generation_timestamp is not None:
        return datetime_literal(config.generation_timestamp)
    value = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    return datetime_literal(value.replace("+00:00", "Z"))


def read_existing_catalog(path: Path) -> tuple[str, Optional[Graph]]:
    """Read and parse the current catalog, or return an empty state if absent."""

    if not path.exists():
        return "", None
    if not path.is_file():
        raise CatalogGenerationError(f"Catalog output path is not a file: {path}")
    try:
        current = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise CatalogGenerationError(
            f"Catalog output is not valid UTF-8: {path}: {exc}"
        ) from exc
    except OSError as exc:
        raise CatalogGenerationError(
            f"Could not read catalog output {path}: {exc}"
        ) from exc

    graph = Graph()
    try:
        graph.parse(data=current, format="turtle")
    except Exception as exc:  # noqa: BLE001 - RDFLib raises several exception types
        raise CatalogGenerationError(
            f"Could not parse existing catalog Turtle {path}: {exc}"
        ) from exc
    return current, graph


def require_single_literal(
    graph: Graph, subject: URIRef, predicate: URIRef, field_name: str
) -> Literal:
    values = list(graph.objects(subject, predicate))
    if len(values) != 1:
        raise CatalogGenerationError(
            f"Existing catalog must contain exactly one {field_name} value; "
            f"found {len(values)}."
        )
    value = values[0]
    if not isinstance(value, Literal):
        raise CatalogGenerationError(
            f"Existing catalog {field_name} value must be a literal."
        )
    if value.language is not None:
        raise CatalogGenerationError(
            f"Existing catalog {field_name} value must not have a language tag."
        )
    return value


def read_existing_timestamps(
    graph: Graph, catalog_iri: str
) -> Optional[CatalogTimestamps]:
    """Read and validate the state-carrying timestamps in an existing catalog."""

    catalog_ref = URIRef(catalog_iri)
    if not any(graph.predicate_objects(catalog_ref)):
        return None
    modified = require_single_literal(
        graph, catalog_ref, DCTERMS.modified, "dct:modified"
    )
    if modified.datatype == XSD.date:
        require_date(str(modified), "existing dct:modified")
    elif modified.datatype == XSD.dateTime:
        require_datetime(str(modified), "existing dct:modified")
    else:
        raise CatalogGenerationError(
            "Existing catalog dct:modified must use xsd:date or xsd:dateTime."
        )

    metadata_modified = require_single_literal(
        graph, catalog_ref, FDPO_METADATA_MODIFIED, "fdpo:metadataModified"
    )
    if metadata_modified.datatype != XSD.dateTime:
        raise CatalogGenerationError(
            "Existing catalog fdpo:metadataModified must use xsd:dateTime."
        )
    require_datetime(str(metadata_modified), "existing fdpo:metadataModified")

    return CatalogTimestamps(
        modified=(
            datetime_literal(str(modified))
            if modified.datatype == XSD.dateTime
            else Literal(str(modified), datatype=XSD.date, normalize=False)
        ),
        metadata_modified=datetime_literal(str(metadata_modified)),
    )


def graph_without_dynamic_catalog_statements(graph: Graph, catalog_iri: str) -> Graph:
    """Project catalog metadata excluding membership and dynamic timestamps."""

    catalog_ref = URIRef(catalog_iri)
    excluded = {
        DCTERMS.modified,
        FDPO_METADATA_MODIFIED,
        DCAT.dataset,
    }
    projected = Graph()
    for subject, predicate, obj in graph:
        if subject == catalog_ref and predicate in excluded:
            continue
        projected.add((subject, predicate, obj))
    return projected


def catalog_membership(graph: Graph, catalog_iri: str) -> set[Any]:
    return set(graph.objects(URIRef(catalog_iri), DCAT.dataset))


def classify_catalog_changes(
    existing_graph: Optional[Graph], candidate_graph: Graph, catalog_iri: str
) -> CatalogChanges:
    if existing_graph is None:
        return CatalogChanges(
            first_generation=True,
            membership_changed=True,
            metadata_changed=True,
        )

    membership_changed = catalog_membership(
        existing_graph, catalog_iri
    ) != catalog_membership(candidate_graph, catalog_iri)
    metadata_changed = to_isomorphic(
        graph_without_dynamic_catalog_statements(existing_graph, catalog_iri)
    ) != to_isomorphic(
        graph_without_dynamic_catalog_statements(candidate_graph, catalog_iri)
    )
    return CatalogChanges(
        first_generation=False,
        membership_changed=membership_changed,
        metadata_changed=metadata_changed,
    )


def timestamps_for_write(
    config: Config,
    existing: Optional[CatalogTimestamps],
    changes: CatalogChanges,
) -> CatalogTimestamps:
    if existing is None:
        generated = resolve_generation_timestamp(config)
        return CatalogTimestamps(generated, generated)

    if not changes.semantic_change:
        return existing

    generated = resolve_generation_timestamp(config)
    return CatalogTimestamps(
        modified=generated if changes.membership_changed else existing.modified,
        metadata_modified=generated,
    )


def timestamps_for_check(
    config: Config, existing: Optional[CatalogTimestamps]
) -> CatalogTimestamps:
    """Provide stable comparison values without consulting the current clock."""

    if existing is not None:
        return existing
    value = config.generation_timestamp or CHECK_TIMESTAMP
    placeholder = datetime_literal(value)
    return CatalogTimestamps(placeholder, placeholder)


def contributor_equivalence_key(value: str) -> tuple[str, str, str, str]:
    """Return a conservative key for simple contributor-IRI variants.

    HTTP and HTTPS forms are treated as equivalent, as are values that differ
    only by trailing slashes. Path case, query strings, and fragments remain
    significant.
    """

    parsed = urlparse(value)
    path = parsed.path.rstrip("/")
    return (parsed.netloc.lower(), path, parsed.query, parsed.fragment)


def contributor_preference_key(value: str) -> tuple[int, int, str]:
    """Rank equivalent contributor IRIs deterministically.

    Prefer HTTPS to HTTP and a form without a trailing slash when both forms
    occur. The original IRI is retained; no synthetic normalized IRI is made.
    """

    parsed = urlparse(value)
    return (
        0 if parsed.scheme == "https" else 1,
        0 if not parsed.path.endswith("/") else 1,
        value,
    )


def deduplicate_contributor_iris(values: Sequence[str]) -> tuple[str, ...]:
    """Deduplicate contributor IRIs, including simple scheme/slash variants."""

    grouped: dict[tuple[str, str, str, str], list[str]] = {}
    for value in values:
        grouped.setdefault(contributor_equivalence_key(value), []).append(value)
    selected = [
        min(group, key=contributor_preference_key) for group in grouped.values()
    ]
    return tuple(sorted(selected))


def discover_catalog_members(
    models_path: Path, catalog_iri: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return exact dataset IRIs and derived contributor IRIs from model metadata."""

    if not models_path.exists():
        raise CatalogGenerationError(f"Models directory does not exist: {models_path}")
    if not models_path.is_dir():
        raise CatalogGenerationError(f"Models path is not a directory: {models_path}")

    metadata_paths = sorted(
        path
        for path in models_path.glob("*/metadata.ttl")
        if path.is_file() and path.parent.parent == models_path
    )
    if not metadata_paths:
        raise CatalogGenerationError(
            f"No model-level metadata.ttl files were found under: {models_path}"
        )

    catalog_ref = URIRef(catalog_iri)
    discovered: dict[str, Path] = {}
    contributor_iris: list[str] = []
    for metadata_path in metadata_paths:
        graph = Graph()
        try:
            graph.parse(metadata_path, format="turtle")
        except Exception as exc:  # noqa: BLE001 - RDFLib raises several exception types
            raise CatalogGenerationError(
                f"Could not parse model metadata {metadata_path}: {exc}"
            ) from exc

        subjects = sorted(
            {
                str(subject)
                for subject in graph.subjects(RDF.type, DCAT_DATASET)
                if isinstance(subject, URIRef)
            }
        )
        if len(subjects) != 1:
            raise CatalogGenerationError(
                f"Expected exactly one IRI subject typed dcat:Dataset in "
                f"{metadata_path}; found {len(subjects)}."
            )
        dataset_iri = subjects[0]
        dataset_ref = URIRef(dataset_iri)
        if (dataset_ref, DCTERMS.isPartOf, catalog_ref) not in graph:
            raise CatalogGenerationError(
                f"Dataset {dataset_iri} in {metadata_path} must declare "
                f"dct:isPartOf <{catalog_iri}>."
            )
        if dataset_iri in discovered:
            raise CatalogGenerationError(
                f"Duplicate dataset IRI {dataset_iri} found in "
                f"{discovered[dataset_iri]} and {metadata_path}."
            )
        discovered[dataset_iri] = metadata_path

        for contributor in graph.objects(predicate=DCTERMS.contributor):
            if not isinstance(contributor, URIRef):
                raise CatalogGenerationError(
                    f"Model metadata {metadata_path} has a dct:contributor value "
                    "that is not an IRI."
                )
            contributor_iris.append(
                require_http_iri(str(contributor), f"{metadata_path}: dct:contributor")
            )

    return tuple(sorted(discovered)), deduplicate_contributor_iris(contributor_iris)


def iri_n3(value: str) -> str:
    return URIRef(value).n3()


def literal_n3(
    value: str, *, language: Optional[str] = None, datatype: Any = None
) -> str:
    literal = Literal(value, lang=language, datatype=datatype, normalize=False)
    rendered = literal.n3()
    if datatype == XSD.date:
        return rendered.rsplit("^^", 1)[0] + "^^xsd:date"
    if datatype == XSD.dateTime:
        return rendered.rsplit("^^", 1)[0] + "^^xsd:dateTime"
    return rendered


def timestamp_literal_n3(value: Literal) -> str:
    if value.datatype == XSD.date:
        return literal_n3(str(value), datatype=XSD.date)
    if value.datatype == XSD.dateTime:
        return literal_n3(str(value), datatype=XSD.dateTime)
    raise ValueError(f"Unsupported timestamp datatype: {value.datatype}")


def render_object_list(
    predicate: str, objects: Sequence[str], *, final: bool, indent: int = 4
) -> list[str]:
    if not objects:
        raise ValueError(f"Cannot render empty object list for {predicate}")
    padding = " " * indent
    continuation = " " * (indent + len(predicate) + 1)
    suffix = " ." if final else ";"
    if len(objects) == 1:
        return [f"{padding}{predicate} {objects[0]}{suffix}"]
    lines = [f"{padding}{predicate} {objects[0]},"]
    lines.extend(
        f"{continuation}{obj}{',' if index < len(objects) - 1 else suffix}"
        for index, obj in enumerate(objects[1:], start=1)
    )
    return lines


def render_catalog(
    source: CatalogSource,
    dataset_iris: Sequence[str],
    contributor_iris: Sequence[str],
    timestamps: CatalogTimestamps,
) -> str:
    """Render a stable Turtle serialization with a deterministic dataset list."""

    lang = source.language
    lines = [
        "@prefix dcat: <http://www.w3.org/ns/dcat#> .",
        "@prefix dct: <http://purl.org/dc/terms/> .",
        "@prefix fdpo: <https://w3id.org/fdp/fdp-o#> .",
        "@prefix ocmv: <https://w3id.org/ontouml-models/vocabulary#> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix vcard: <http://www.w3.org/2006/vcard/ns#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
        f"{iri_n3(source.catalog_iri)} a dcat:Resource, dcat:Catalog, dcat:Dataset;",
        f"    dct:title {literal_n3(source.title, language=lang)};",
        f"    rdfs:label {literal_n3(source.title, language=lang)};",
        f"    dct:alternative {literal_n3(source.alternative, language=lang)};",
        f"    rdfs:label {literal_n3(source.alternative, language=lang)};",
        f"    dct:description {literal_n3(source.description, language=lang)};",
        f"    ocmv:storageUrl {iri_n3(source.storage_url)};",
        f"    dcat:themeTaxonomy {iri_n3(source.theme_taxonomy)};",
        "    dct:bibliographicCitation "
        f"{literal_n3(source.bibliographic_citation, language=lang)};",
        f"    dct:license {iri_n3(source.license)};",
        f"    dct:accessRights {iri_n3(source.access_rights)};",
        f"    dct:issued {literal_n3(source.issued, datatype=XSD.date)};",
        f"    dct:modified {timestamp_literal_n3(timestamps.modified)};",
        "    dcat:contactPoint [",
        "        rdf:type vcard:Individual;",
        f"        vcard:fn {literal_n3(source.contact_name)};",
        f"        vcard:hasEmail {iri_n3(source.contact_email)}",
        "    ];",
        f"    dct:publisher {iri_n3(source.publisher)};",
    ]
    lines.extend(
        render_object_list(
            "dct:creator", [iri_n3(value) for value in source.creators], final=False
        )
    )
    if contributor_iris:
        lines.extend(
            render_object_list(
                "dct:contributor",
                [iri_n3(value) for value in contributor_iris],
                final=False,
            )
        )
    lines.extend(
        [
            f"    dct:isPartOf {iri_n3(source.is_part_of)};",
            "    fdpo:metadataIssued "
            f"{literal_n3(source.metadata_issued, datatype=XSD.dateTime)};",
            "    fdpo:metadataModified "
            f"{timestamp_literal_n3(timestamps.metadata_modified)};",
        ]
    )
    lines.extend(
        render_object_list(
            "dcat:dataset", [iri_n3(value) for value in dataset_iris], final=True
        )
    )
    return "\n".join(lines) + "\n"


def validate_generated_turtle(
    turtle: str,
    source: CatalogSource,
    dataset_iris: Sequence[str],
    contributor_iris: Sequence[str],
    timestamps: CatalogTimestamps,
) -> Graph:
    graph = Graph()
    try:
        graph.parse(data=turtle, format="turtle")
    except Exception as exc:  # noqa: BLE001 - RDFLib raises several exception types
        raise CatalogGenerationError(
            f"Generated catalog Turtle is not parseable: {exc}"
        ) from exc

    catalog_ref = URIRef(source.catalog_iri)
    for type_iri in CATALOG_TYPE_IRIS:
        if (catalog_ref, RDF.type, type_iri) not in graph:
            raise CatalogGenerationError(
                f"Generated catalog is missing rdf:type {type_iri}."
            )
    generated_datasets = {
        str(value)
        for value in graph.objects(catalog_ref, DCAT.dataset)
        if isinstance(value, URIRef)
    }
    if generated_datasets != set(dataset_iris):
        raise CatalogGenerationError(
            "Generated catalog dataset membership does not match discovered "
            "model metadata."
        )
    generated_contributors = {
        str(value)
        for value in graph.objects(catalog_ref, DCTERMS.contributor)
        if isinstance(value, URIRef)
    }
    if generated_contributors != set(contributor_iris):
        raise CatalogGenerationError(
            "Generated catalog contributors do not match model-level metadata."
        )
    generated_modified = list(graph.objects(catalog_ref, DCTERMS.modified))
    if len(generated_modified) != 1 or not generated_modified[0].eq(
        timestamps.modified
    ):
        raise CatalogGenerationError(
            "Generated catalog dct:modified does not match the selected timestamp."
        )
    generated_metadata_modified = list(
        graph.objects(catalog_ref, FDPO_METADATA_MODIFIED)
    )
    if len(generated_metadata_modified) != 1 or not generated_metadata_modified[0].eq(
        timestamps.metadata_modified
    ):
        raise CatalogGenerationError(
            "Generated catalog fdpo:metadataModified does not match the selected "
            "timestamp."
        )
    return graph


def unified_diff(current: str, expected: str, output_path: Path) -> str:
    return "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            expected.splitlines(keepends=True),
            fromfile=str(output_path),
            tofile=f"{output_path} (generated)",
        )
    )


def write_text_atomically(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def generate_catalog(config: Config) -> bool:
    """Generate or check catalog.ttl; return True when it was already current."""

    source = load_catalog_source(config.source_path)
    dataset_iris, contributor_iris = discover_catalog_members(
        config.models_path, source.catalog_iri
    )
    current, existing_graph = read_existing_catalog(config.output_path)
    existing_timestamps = (
        read_existing_timestamps(existing_graph, source.catalog_iri)
        if existing_graph is not None
        else None
    )

    comparison_timestamps = timestamps_for_check(config, existing_timestamps)
    comparison = render_catalog(
        source, dataset_iris, contributor_iris, comparison_timestamps
    )
    candidate_graph = validate_generated_turtle(
        comparison,
        source,
        dataset_iris,
        contributor_iris,
        comparison_timestamps,
    )
    changes = classify_catalog_changes(
        existing_graph, candidate_graph, source.catalog_iri
    )

    timestamps = (
        comparison_timestamps
        if config.check
        else timestamps_for_write(config, existing_timestamps, changes)
    )
    expected = render_catalog(source, dataset_iris, contributor_iris, timestamps)
    validate_generated_turtle(
        expected, source, dataset_iris, contributor_iris, timestamps
    )

    if config.check and not changes.semantic_change:
        print(
            f"Catalog is semantically synchronized: {config.output_path} "
            f"({len(dataset_iris)} datasets, {len(contributor_iris)} contributors)."
        )
        return True

    if current == expected:
        print(
            f"Catalog is synchronized: {config.output_path} "
            f"({len(dataset_iris)} datasets, {len(contributor_iris)} contributors)."
        )
        return True

    if config.check:
        print(
            f"ERROR: Catalog is not synchronized: {config.output_path} "
            f"({changes.reason}).",
            file=sys.stderr,
        )
        diff = unified_diff(current, expected, config.output_path)
        if diff:
            print(diff, end="" if diff.endswith("\n") else "\n", file=sys.stderr)
        return False

    try:
        write_text_atomically(config.output_path, expected)
    except OSError as exc:
        raise CatalogGenerationError(
            f"Could not write catalog output {config.output_path}: {exc}"
        ) from exc
    print(
        f"Catalog synchronized: {config.output_path} "
        f"({len(dataset_iris)} datasets, {len(contributor_iris)} contributors)."
    )
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate catalog.ttl from catalog.yaml plus the exact dcat:Dataset "
            "subjects and dct:contributor IRIs in models/*/metadata.ttl."
        )
    )
    parser.add_argument(
        "repository_path",
        nargs="?",
        default=".",
        help="Repository root. Default: current directory.",
    )
    parser.add_argument(
        "--source",
        default="catalog.yaml",
        help="Repository-relative catalog metadata source. Default: catalog.yaml.",
    )
    parser.add_argument(
        "--output",
        default="catalog.ttl",
        help="Repository-relative generated catalog file. Default: catalog.ttl.",
    )
    parser.add_argument(
        "--models-dir",
        default="models",
        help="Repository-relative model directory. Default: models.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail without writing when catalog.ttl differs from generated output.",
    )
    parser.add_argument(
        "--generation-timestamp",
        help=(
            "UTC-offset or Z-suffixed xsd:dateTime value to use when a write "
            "initializes or updates dynamic modification timestamps. By default, "
            "the current UTC time is captured only when a semantic change requires it."
        ),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = config_from_args(args)
        synchronized = generate_catalog(config)
        if args.check and not synchronized:
            return 1
        return 0
    except CatalogGenerationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Generate OntoUML/UFO Catalog dataset metadata.ttl files from metadata.yaml.

Usage examples:

  # Generate metadata.ttl for one dataset folder
  python scripts/metadata_yaml_to_ttl.py models/amaral2019rot

  # Generate metadata.ttl for every metadata.yaml found under models/
  python scripts/metadata_yaml_to_ttl.py models --recursive

  # Validate and print Turtle without writing metadata.ttl
  python scripts/metadata_yaml_to_ttl.py models/amaral2019rot --dry-run

The script expects each dataset folder to contain a metadata.yaml file and writes
metadata.ttl next to it. It uses RDFLib to build an RDF graph and serialize it as
Turtle. The YAML schema is documented in documentation/metadata-yaml.md.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlparse

import yaml



class MetadataYamlLoader(yaml.SafeLoader):
    """YAML loader that keeps date-like scalar values as strings.

    PyYAML's SafeLoader converts unquoted ISO-like dates/timestamps into Python
    date/datetime objects, which can alter lexical forms such as FDP nanosecond
    timestamps. Metadata conversion must preserve the author's lexical date value
    so that RDF literals can match repository metadata.ttl files.
    """


MetadataYamlLoader.yaml_implicit_resolvers = {
    key: [
        resolver
        for resolver in resolvers
        if resolver[0] != "tag:yaml.org,2002:timestamp"
    ]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}

from rdflib import BNode, Graph, Literal, Namespace, RDF, URIRef
from rdflib.namespace import XSD

# Namespaces used by the OntoUML/UFO Catalog metadata schema.
DCAT = Namespace("http://www.w3.org/ns/dcat#")
DCT = Namespace("http://purl.org/dc/terms/")
FDPO = Namespace("https://w3id.org/fdp/fdp-o#")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")
LCC = Namespace("http://id.loc.gov/authorities/classification/")
MOD = Namespace("https://w3id.org/mod#")
OCMV = Namespace("https://w3id.org/ontouml-models/vocabulary#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
VCARD = Namespace("http://www.w3.org/2006/vcard/ns#")

DEFAULT_MODEL_IRI_BASE = "https://w3id.org/ontouml-models/model/"
DEFAULT_REPOSITORY_URL = "https://github.com/OntoUML/ontouml-models"
DEFAULT_BRANCH = "master"

# XSD date-like lexical spaces used in the catalog metadata. DateTime validation
# intentionally accepts long fractional seconds because existing FDP metadata may
# include nanosecond-precision timestamps. Date literals are created with
# normalize=False so RDFLib does not rewrite existing catalog lexical forms.
GYEAR_RE = re.compile(r"^\d{4}$")
GYEARMONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
DATETIME_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T"
    r"(\d{2}):(\d{2}):(\d{2})"
    r"(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2})?$"
)

DESIGNED_FOR_TASK = {
    "ConceptualClarification": OCMV.ConceptualClarification,
    "DataPublication": OCMV.DataPublication,
    "DecisionSupportSystem": OCMV.DecisionSupportSystem,
    "Example": OCMV.Example,
    "InformationRetrieval": OCMV.InformationRetrieval,
    "Interoperability": OCMV.Interoperability,
    "LanguageEngineering": OCMV.LanguageEngineering,
    "Learning": OCMV.Learning,
    "OntologicalAnalysis": OCMV.OntologicalAnalysis,
    "SoftwareEngineering": OCMV.SoftwareEngineering,
}

CONTEXT = {
    "Classroom": OCMV.Classroom,
    "Industry": OCMV.Industry,
    "Research": OCMV.Research,
}

REPRESENTATION_STYLE = {
    "OntoumlStyle": OCMV.OntoumlStyle,
    "UfoStyle": OCMV.UfoStyle,
}

ONTOLOGY_TYPE = {
    "Domain": OCMV.Domain,
    "Application": OCMV.Application,
    "Core": OCMV.Core,
}

ALIASES = {
    "iri": ["iri", "uri", "model_iri", "identifier", "id"],
    "title": ["title", "dct:title"],
    "alternative": ["alternative", "alternative_title", "dct:alternative"],
    "description": ["description", "dct:description"],
    "issued": ["issued", "dct:issued"],
    "modified": ["modified", "dct:modified"],
    "license": ["license", "dct:license"],
    "access_rights": ["access_rights", "accessRights", "dct:accessRights"],
    "editorial_note": ["editorial_note", "editorialNote", "skos:editorialNote"],
    "creator": ["creator", "creators", "dct:creator"],
    "contributor": ["contributor", "contributors", "dct:contributor"],
    "publisher": ["publisher", "dct:publisher"],
    "metadata_issued": ["metadata_issued", "metadataIssued", "fdpo:metadataIssued"],
    "metadata_modified": ["metadata_modified", "metadataModified", "fdpo:metadataModified"],
    "landing_page": ["landing_page", "landingPage", "dcat:landingPage"],
    "bibliographic_citation": ["bibliographic_citation", "bibliographicCitation", "dct:bibliographicCitation"],
    "storage_url": ["storage_url", "storageUrl", "ocmv:storageUrl"],
    "contact_points": ["contact_points", "contactPoints", "dcat:contactPoint"],
    "keyword": ["keyword", "keywords", "dcat:keyword"],
    "acronym": ["acronym", "mod:acronym"],
    "source": ["source", "sources", "dct:source"],
    "language": ["language", "languages", "dct:language"],
    "theme": ["theme", "dcat:theme"],
    "designed_for_task": ["designed_for_task", "designedForTask", "mod:designedForTask"],
    "context": ["context", "ocmv:context"],
    "representation_style": ["representation_style", "representationStyle", "ocmv:representationStyle"],
    "ontology_type": ["ontology_type", "ontologyType", "ocmv:ontologyType"],
    "is_part_of": ["is_part_of", "isPartOf", "dct:isPartOf"],
    "distribution": ["distribution", "distributions", "dcat:distribution"],
}

KNOWN_KEYS = {alias for aliases in ALIASES.values() for alias in aliases}

# Fields that correspond to current SHACL minCount constraints for semantic artefact metadata.
REQUIRED_FIELDS = ("title", "issued", "license", "theme", "keyword")


class MetadataError(Exception):
    """Raised when metadata.yaml cannot be converted safely."""


@dataclass(frozen=True)
class ConversionResult:
    folder: Path
    yaml_path: Path
    ttl_path: Path
    triple_count: int
    warnings: tuple[str, ...]


def canonical_key(data: dict[str, Any], canonical: str) -> Any:
    """Return a YAML value using a canonical key and its supported aliases."""
    for key in ALIASES[canonical]:
        if key in data:
            return data[key]
    return None


def as_list(value: Any) -> list[Any]:
    """Normalize scalar-or-list YAML values to a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def normalize_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def make_uri(
    value: Any,
    *,
    field_name: str,
    allowed_schemes: Sequence[str] = ("http", "https"),
) -> URIRef:
    """Create a URIRef and validate its URI scheme.

    Catalog metadata normally uses HTTP(S) identifiers. mailto: is accepted only
    for contact e-mail IRIs, where callers pass allowed_schemes=("mailto",).
    """
    if not isinstance(value, str):
        raise MetadataError(f"Field '{field_name}' must be a URI string; got {type(value).__name__}.")
    stripped = value.strip()
    parsed = urlparse(stripped)
    if not parsed.scheme or parsed.scheme not in allowed_schemes:
        schemes = ", ".join(f"'{scheme}:'" for scheme in allowed_schemes)
        raise MetadataError(f"Field '{field_name}' must be an absolute URI using {schemes}; got '{value}'.")
    if parsed.scheme in {"http", "https"} and not parsed.netloc:
        raise MetadataError(f"Field '{field_name}' must be an absolute HTTP(S) URI; got '{value}'.")
    if parsed.scheme == "mailto" and not parsed.path:
        raise MetadataError(f"Field '{field_name}' must be a non-empty mailto URI; got '{value}'.")
    return URIRef(stripped)


def is_http_uri(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def infer_model_iri(data: dict[str, Any], dataset_folder: Path, model_iri_base: str) -> URIRef:
    explicit = canonical_key(data, "iri")
    if explicit:
        explicit_text = str(explicit).strip()
        if is_http_uri(explicit_text):
            return URIRef(explicit_text)
        if ":" in explicit_text:
            raise MetadataError("Field 'iri' must be an absolute HTTP(S) URI or a slug without a prefix.")
        return URIRef(model_iri_base.rstrip("/") + "/" + explicit_text.strip("/") + "/")

    slug = dataset_folder.name
    if not slug:
        raise MetadataError("Could not infer model IRI because the dataset folder has no name.")
    return URIRef(model_iri_base.rstrip("/") + "/" + slug.strip("/") + "/")


def _validate_calendar_date(year: str, month: str, day: str | None = None) -> None:
    try:
        if day is None:
            date(int(year), int(month), 1)
        else:
            date(int(year), int(month), int(day))
    except ValueError as exc:
        raise MetadataError(f"Invalid calendar date: {year}-{month}" + (f"-{day}" if day else "")) from exc


def date_literal(value: Any, field_name: str) -> Literal:
    text = str(value).strip()
    if GYEAR_RE.match(text):
        return Literal(text, datatype=XSD.gYear, normalize=False)

    gyear_month = GYEARMONTH_RE.match(text)
    if gyear_month:
        _validate_calendar_date(gyear_month.group(1), gyear_month.group(2))
        return Literal(text, datatype=XSD.gYearMonth, normalize=False)

    date_match = DATE_RE.match(text)
    if date_match:
        _validate_calendar_date(date_match.group(1), date_match.group(2), date_match.group(3))
        return Literal(text, datatype=XSD.date, normalize=False)

    datetime_match = DATETIME_RE.match(text)
    if datetime_match:
        date_part = datetime_match.group(1)
        year, month, day = date_part.split("-")
        _validate_calendar_date(year, month, day)
        hour, minute, second = map(int, datetime_match.group(2, 3, 4))
        try:
            datetime(2000, 1, 1, hour, minute, second)
        except ValueError as exc:
            raise MetadataError(f"Invalid time in field '{field_name}': {text}") from exc
        return Literal(text, datatype=XSD.dateTime, normalize=False)

    raise MetadataError(
        f"Field '{field_name}' has unsupported date value '{text}'. "
        "Use YYYY, YYYY-MM, YYYY-MM-DD, or an xsd:dateTime-like value."
    )


def literal_values(value: Any, field_name: str) -> Iterable[Literal]:
    """Yield RDF literals from flexible YAML literal syntax.

    Supported forms:
      title: My title
      title: {value: My title, lang: en}
      title: {en: My title, pt: Meu titulo}
      title:
        - {value: My title, lang: en}
        - {value: Otro titulo, lang: es}
    """
    for item in as_list(value):
        if isinstance(item, dict):
            if "value" in item:
                literal_value = item["value"]
                lang = item.get("lang") or item.get("language")
                datatype_value = item.get("datatype")
                if lang and datatype_value:
                    raise MetadataError(f"Field '{field_name}' cannot define both 'lang' and 'datatype' for one literal.")
                if lang:
                    yield Literal(str(literal_value), lang=str(lang))
                elif datatype_value:
                    yield Literal(str(literal_value), datatype=make_uri(str(datatype_value), field_name=field_name))
                else:
                    yield Literal(str(literal_value))
            else:
                # Language map, e.g., {en: "Title", pt: "Titulo"}.
                for lang, literal_value in item.items():
                    if literal_value is None:
                        continue
                    yield Literal(str(literal_value), lang=str(lang))
        else:
            yield Literal(str(item))


def check_unique_title_language(value: Any) -> None:
    """Enforce the catalog guideline: at most one dct:title per language.

    Untagged title literals are treated as belonging to the same no-language bucket.
    """
    seen: set[str | None] = set()
    for literal in literal_values(value, "title"):
        bucket = literal.language
        if bucket in seen:
            label = bucket if bucket is not None else "without a language tag"
            raise MetadataError(f"Field 'title' must have at most one value per language; duplicate: {label}.")
        seen.add(bucket)


def add_literals(graph: Graph, subject: URIRef | BNode, predicate: URIRef, value: Any, field_name: str) -> None:
    if value is None:
        return
    for literal in literal_values(value, field_name):
        graph.add((subject, predicate, literal))


def add_uris(graph: Graph, subject: URIRef | BNode, predicate: URIRef, value: Any, field_name: str) -> None:
    for item in as_list(value):
        graph.add((subject, predicate, make_uri(item, field_name=field_name)))


def normalize_ocmv_enum(value: Any, allowed: dict[str, URIRef], field_name: str) -> URIRef:
    if isinstance(value, URIRef):
        return value
    text = str(value).strip()
    if is_http_uri(text):
        uri = URIRef(text)
        if uri in allowed.values():
            return uri
        raise MetadataError(f"Unsupported value for '{field_name}': {text}")
    if text.startswith("ocmv:"):
        text = text.split(":", 1)[1]
    normalized_allowed = {normalize_token(key): uri for key, uri in allowed.items()}
    normalized_input = normalize_token(text)
    if normalized_input in normalized_allowed:
        return normalized_allowed[normalized_input]
    supported = ", ".join(sorted(allowed.keys()))
    raise MetadataError(f"Unsupported value for '{field_name}': {value}. Supported values: {supported}.")


def add_ocmv_enums(graph: Graph, subject: URIRef, predicate: URIRef, value: Any, allowed: dict[str, URIRef], field_name: str) -> None:
    for item in as_list(value):
        graph.add((subject, predicate, normalize_ocmv_enum(item, allowed, field_name)))


def normalize_theme(value: Any) -> URIRef:
    text = str(value).strip()
    if is_http_uri(text):
        if not text.startswith(str(LCC)):
            raise MetadataError(f"Field 'theme' must use the Library of Congress Classification URI namespace; got '{text}'.")
        return URIRef(text)
    if text.startswith("lcc:"):
        text = text.split(":", 1)[1]
    text = text.strip("/").upper()
    if not re.match(r"^[A-Z]+[A-Z0-9.-]*$", text):
        raise MetadataError(f"Field 'theme' must be an LCC class such as 'H', 'T', 'lcc:H', or a full LCC URI; got '{value}'.")
    return URIRef(str(LCC) + text)


def bind_prefixes(graph: Graph) -> None:
    graph.bind("dcat", DCAT)
    graph.bind("dct", DCT)
    graph.bind("fdpo", FDPO)
    graph.bind("foaf", FOAF)
    graph.bind("lcc", LCC)
    graph.bind("mod", MOD)
    graph.bind("ocmv", OCMV)
    graph.bind("rdf", RDF)
    graph.bind("skos", SKOS)
    graph.bind("vcard", VCARD)
    graph.bind("xsd", XSD)


def validate_required_fields(data: dict[str, Any]) -> None:
    missing = [field for field in REQUIRED_FIELDS if canonical_key(data, field) in (None, "", [])]
    if missing:
        raise MetadataError("Missing mandatory metadata field(s): " + ", ".join(missing) + ".")


def add_contact_points(graph: Graph, subject: URIRef, value: Any) -> None:
    for index, item in enumerate(as_list(value), start=1):
        if not isinstance(item, dict):
            raise MetadataError("Each contact point must be a mapping with at least an 'email' field.")
        email = item.get("email") or item.get("hasEmail") or item.get("vcard:hasEmail")
        name = item.get("name") or item.get("fn") or item.get("vcard:fn")
        if not email:
            raise MetadataError(f"Contact point #{index} is missing an email.")
        email_text = str(email).strip()
        if not email_text.startswith("mailto:"):
            email_text = "mailto:" + email_text
        contact = BNode()
        graph.add((subject, DCAT.contactPoint, contact))
        graph.add((contact, RDF.type, VCARD.VCard))
        graph.add((contact, VCARD.hasEmail, make_uri(email_text, field_name="contact_points.email", allowed_schemes=("mailto",))))
        if name:
            graph.add((contact, VCARD.fn, Literal(str(name))))


def distribution_iri(model_iri: URIRef, item: Any, index: int) -> URIRef:
    if isinstance(item, str):
        return make_uri(item, field_name="distribution")
    if not isinstance(item, dict):
        raise MetadataError("Each distribution must be a URI string or a mapping.")
    explicit = item.get("iri") or item.get("uri") or item.get("id")
    if explicit:
        explicit_text = str(explicit).strip()
        if is_http_uri(explicit_text):
            return URIRef(explicit_text)
        if ":" in explicit_text:
            raise MetadataError("Distribution id must be an HTTP(S) URI or a local slug.")
        slug = explicit_text.strip("/")
    else:
        slug = str(item.get("name") or item.get("key") or index).strip("/")
    if not slug:
        raise MetadataError("Distribution id/name cannot be empty.")
    base = str(model_iri).rstrip("/")
    return URIRef(f"{base}/distribution/{slug}")


def add_distributions(graph: Graph, subject: URIRef, value: Any) -> None:
    for index, item in enumerate(as_list(value), start=1):
        dist = distribution_iri(subject, item, index)
        graph.add((subject, DCAT.distribution, dist))
        if isinstance(item, str):
            continue
        graph.add((dist, RDF.type, DCAT.Distribution))
        add_literals(graph, dist, DCT.title, item.get("title"), "distribution.title")
        if item.get("license"):
            graph.add((dist, DCT.license, make_uri(item["license"], field_name="distribution.license")))
        if item.get("media_type") or item.get("mediaType") or item.get("dcat:mediaType"):
            media_type = item.get("media_type") or item.get("mediaType") or item.get("dcat:mediaType")
            graph.add((dist, DCAT.mediaType, make_uri(media_type, field_name="distribution.media_type")))
        if item.get("format"):
            graph.add((dist, DCT.format, make_uri(item["format"], field_name="distribution.format")))
        if item.get("download_url") or item.get("downloadURL") or item.get("dcat:downloadURL"):
            download_url = item.get("download_url") or item.get("downloadURL") or item.get("dcat:downloadURL")
            graph.add((dist, DCAT.downloadURL, make_uri(download_url, field_name="distribution.download_url")))
        if "is_complete" in item or "isComplete" in item or "ocmv:isComplete" in item:
            is_complete = item.get("is_complete", item.get("isComplete", item.get("ocmv:isComplete")))
            if not isinstance(is_complete, bool):
                raise MetadataError("distribution.is_complete must be a boolean.")
            graph.add((dist, OCMV.isComplete, Literal(is_complete, datatype=XSD.boolean)))
        if item.get("conforms_to_schema") or item.get("conformsToSchema") or item.get("ocmv:conformsToSchema"):
            schema = item.get("conforms_to_schema") or item.get("conformsToSchema") or item.get("ocmv:conformsToSchema")
            graph.add((dist, OCMV.conformsToSchema, make_uri(schema, field_name="distribution.conforms_to_schema")))


def default_storage_url(dataset_folder: Path, repository_url: str, branch: str) -> Literal:
    # Try to compute a stable repository-relative path. If dataset_folder is absolute,
    # only the trailing models/<slug> segment is preserved when present.
    parts = list(dataset_folder.as_posix().split("/"))
    if "models" in parts:
        idx = parts.index("models")
        rel_path = "/".join(parts[idx:])
    else:
        rel_path = dataset_folder.name
    url = f"{repository_url.rstrip('/')}/tree/{branch}/{rel_path}"
    return Literal(url, datatype=XSD.anyURI)


def unknown_key_warnings(data: dict[str, Any]) -> list[str]:
    unknown = sorted(str(key) for key in data if str(key) not in KNOWN_KEYS)
    if not unknown:
        return []
    return ["Unknown top-level metadata field(s): " + ", ".join(unknown) + ". Check for typos."]


def build_graph(
    data: dict[str, Any],
    dataset_folder: Path,
    *,
    model_iri_base: str = DEFAULT_MODEL_IRI_BASE,
    repository_url: str = DEFAULT_REPOSITORY_URL,
    branch: str = DEFAULT_BRANCH,
    add_default_storage_url: bool = False,
) -> tuple[Graph, tuple[str, ...]]:
    validate_required_fields(data)
    check_unique_title_language(canonical_key(data, "title"))
    warnings = unknown_key_warnings(data)

    graph = Graph()
    bind_prefixes(graph)

    subject = infer_model_iri(data, dataset_folder, model_iri_base)
    graph.add((subject, RDF.type, DCAT.Dataset))
    graph.add((subject, RDF.type, MOD.SemanticArtefact))
    graph.add((subject, RDF.type, DCAT.Resource))

    # dcat:Resource fields.
    add_literals(graph, subject, DCT.title, canonical_key(data, "title"), "title")
    add_literals(graph, subject, DCT.alternative, canonical_key(data, "alternative"), "alternative")
    add_literals(graph, subject, DCT.description, canonical_key(data, "description"), "description")
    graph.add((subject, DCT.issued, date_literal(canonical_key(data, "issued"), "issued")))
    if canonical_key(data, "modified"):
        graph.add((subject, DCT.modified, date_literal(canonical_key(data, "modified"), "modified")))
    graph.add((subject, DCT.license, make_uri(canonical_key(data, "license"), field_name="license")))
    access_rights = canonical_key(data, "access_rights")
    if access_rights:
        for item in as_list(access_rights):
            if isinstance(item, str) and is_http_uri(item):
                graph.add((subject, DCT.accessRights, URIRef(item.strip())))
            else:
                graph.add((subject, DCT.accessRights, Literal(str(item))))
    add_literals(graph, subject, SKOS.editorialNote, canonical_key(data, "editorial_note"), "editorial_note")
    add_uris(graph, subject, DCT.creator, canonical_key(data, "creator"), "creator")
    add_uris(graph, subject, DCT.contributor, canonical_key(data, "contributor"), "contributor")
    publisher = canonical_key(data, "publisher")
    if publisher:
        publisher_items = as_list(publisher)
        if len(publisher_items) > 1:
            raise MetadataError("Field 'publisher' must have at most one URI.")
        graph.add((subject, DCT.publisher, make_uri(publisher_items[0], field_name="publisher")))
    if canonical_key(data, "metadata_issued"):
        graph.add((subject, FDPO.metadataIssued, date_literal(canonical_key(data, "metadata_issued"), "metadata_issued")))
    if canonical_key(data, "metadata_modified"):
        graph.add((subject, FDPO.metadataModified, date_literal(canonical_key(data, "metadata_modified"), "metadata_modified")))

    # dcat:Dataset fields.
    landing_page = canonical_key(data, "landing_page")
    if landing_page:
        graph.add((subject, DCAT.landingPage, make_uri(landing_page, field_name="landing_page")))
    add_literals(graph, subject, DCT.bibliographicCitation, canonical_key(data, "bibliographic_citation"), "bibliographic_citation")
    storage_url = canonical_key(data, "storage_url")
    if storage_url:
        if not is_http_uri(str(storage_url)):
            raise MetadataError(f"Field 'storage_url' must be an HTTP(S) URL; got '{storage_url}'.")
        graph.add((subject, OCMV.storageUrl, Literal(str(storage_url).strip(), datatype=XSD.anyURI)))
    elif add_default_storage_url:
        graph.add((subject, OCMV.storageUrl, default_storage_url(dataset_folder, repository_url, branch)))
    contact_points = canonical_key(data, "contact_points")
    if contact_points:
        add_contact_points(graph, subject, contact_points)

    # mod:SemanticArtefact fields.
    add_literals(graph, subject, DCAT.keyword, canonical_key(data, "keyword"), "keyword")
    add_literals(graph, subject, MOD.acronym, canonical_key(data, "acronym"), "acronym")
    add_uris(graph, subject, DCT.source, canonical_key(data, "source"), "source")
    language = canonical_key(data, "language")
    if language:
        # Existing catalog metadata serializes dct:language as a plain lexical
        # string literal, e.g., dct:language "en". Keep that convention for
        # repository fidelity even though the SHACL shape constrains the value
        # to xsd:string. In RDF 1.1, simple string literals are treated as
        # xsd:string literals semantically.
        for item in as_list(language):
            graph.add((subject, DCT.language, Literal(str(item))))
    else:
        warnings.append("Recommended field 'language' is missing.")

    themes = as_list(canonical_key(data, "theme"))
    if len(themes) != 1:
        raise MetadataError("Field 'theme' must have exactly one value.")
    graph.add((subject, DCAT.theme, normalize_theme(themes[0])))

    add_ocmv_enums(graph, subject, MOD.designedForTask, canonical_key(data, "designed_for_task"), DESIGNED_FOR_TASK, "designed_for_task")
    add_ocmv_enums(graph, subject, OCMV.context, canonical_key(data, "context"), CONTEXT, "context")
    add_ocmv_enums(graph, subject, OCMV.representationStyle, canonical_key(data, "representation_style"), REPRESENTATION_STYLE, "representation_style")
    add_ocmv_enums(graph, subject, OCMV.ontologyType, canonical_key(data, "ontology_type"), ONTOLOGY_TYPE, "ontology_type")

    is_part_of = canonical_key(data, "is_part_of")
    if is_part_of:
        graph.add((subject, DCT.isPartOf, make_uri(is_part_of, field_name="is_part_of")))

    distributions = canonical_key(data, "distribution")
    if distributions:
        add_distributions(graph, subject, distributions)

    return graph, tuple(warnings)


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = yaml.load(stream, Loader=MetadataYamlLoader)
    except yaml.YAMLError as exc:
        raise MetadataError(f"Invalid YAML in {path}: {exc}") from exc
    except OSError as exc:
        raise MetadataError(f"Could not read {path}: {exc}") from exc

    if data is None:
        raise MetadataError(f"YAML file is empty: {path}")
    if not isinstance(data, dict):
        raise MetadataError(f"Top-level YAML content must be a mapping: {path}")
    return data


def metadata_yaml_paths(input_path: Path, recursive: bool) -> list[Path]:
    if input_path.is_file():
        if input_path.name != "metadata.yaml":
            raise MetadataError("Input file must be named metadata.yaml.")
        return [input_path]

    if not input_path.exists():
        raise MetadataError(f"Path does not exist: {input_path}")

    if recursive:
        return sorted(input_path.rglob("metadata.yaml"))

    yaml_path = input_path / "metadata.yaml"
    if not yaml_path.exists():
        raise MetadataError(f"Missing metadata.yaml in dataset folder: {input_path}")
    return [yaml_path]


def convert_yaml_file(
    yaml_path: Path,
    *,
    output_name: str,
    overwrite: bool,
    dry_run: bool,
    model_iri_base: str,
    repository_url: str,
    branch: str,
    add_default_storage_url: bool,
) -> ConversionResult:
    dataset_folder = yaml_path.parent
    ttl_path = dataset_folder / output_name
    if ttl_path.exists() and not overwrite and not dry_run:
        raise MetadataError(f"Refusing to overwrite existing file: {ttl_path}")

    data = read_yaml(yaml_path)
    graph, warnings = build_graph(
        data,
        dataset_folder,
        model_iri_base=model_iri_base,
        repository_url=repository_url,
        branch=branch,
        add_default_storage_url=add_default_storage_url,
    )

    turtle = graph.serialize(format="turtle", encoding=None)
    if dry_run:
        print(turtle)
    else:
        ttl_path.write_text(turtle, encoding="utf-8")

    return ConversionResult(
        folder=dataset_folder,
        yaml_path=yaml_path,
        ttl_path=ttl_path,
        triple_count=len(graph),
        warnings=warnings,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate OntoUML/UFO Catalog metadata.ttl files from metadata.yaml using RDFLib.")
    parser.add_argument("path", type=Path, help="Dataset folder, metadata.yaml file, or parent folder when --recursive is used.")
    parser.add_argument("--recursive", action="store_true", help="Find and convert every metadata.yaml below PATH.")
    parser.add_argument("--output-name", default="metadata.ttl", help="Output file name. Default: metadata.ttl.")
    parser.add_argument("--overwrite", dest="overwrite", action="store_true", default=True, help="Overwrite existing output files. Default: true.")
    parser.add_argument("--no-overwrite", dest="overwrite", action="store_false", help="Fail if the output file already exists.")
    parser.add_argument("--dry-run", action="store_true", help="Print generated Turtle instead of writing files.")
    parser.add_argument("--model-iri-base", default=DEFAULT_MODEL_IRI_BASE, help=f"Base IRI used when metadata.yaml has no explicit IRI. Default: {DEFAULT_MODEL_IRI_BASE}")
    parser.add_argument("--repository-url", default=DEFAULT_REPOSITORY_URL, help=f"Repository URL used for generated storage_url values. Default: {DEFAULT_REPOSITORY_URL}")
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help=f"Repository branch used for generated storage_url values. Default: {DEFAULT_BRANCH}")
    parser.add_argument("--add-default-storage-url", action="store_true", help="Add ocmv:storageUrl when metadata.yaml does not define storage_url.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        yaml_paths = metadata_yaml_paths(args.path, args.recursive)
        if not yaml_paths:
            raise MetadataError(f"No metadata.yaml files found under {args.path}.")

        results: list[ConversionResult] = []
        for yaml_path in yaml_paths:
            result = convert_yaml_file(
                yaml_path,
                output_name=args.output_name,
                overwrite=args.overwrite,
                dry_run=args.dry_run,
                model_iri_base=args.model_iri_base,
                repository_url=args.repository_url,
                branch=args.branch,
                add_default_storage_url=args.add_default_storage_url,
            )
            results.append(result)
            for warning in result.warnings:
                print(f"WARNING {result.yaml_path}: {warning}", file=sys.stderr)

        if not args.dry_run:
            for result in results:
                print(f"Generated {result.ttl_path} ({result.triple_count} triples)")
        return 0
    except MetadataError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

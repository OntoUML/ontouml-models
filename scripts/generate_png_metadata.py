"""Generate RDF/Turtle metadata for OntoUML catalog PNG diagram distributions.

The script scans one or more model dataset folders and creates one metadata file
for each PNG diagram found in these source folders:

- original-diagrams/<diagram>.png -> metadata-png-o-<diagram>.ttl
- new-diagrams/<diagram>.png      -> metadata-png-n-<diagram>.ttl

Run from the repository root, for example:

    python scripts/generate_png_metadata.py models/amaral2019rot
    python scripts/generate_png_metadata.py --all --models-dir models
    python scripts/generate_png_metadata.py --all --models-dir models --allow-missing-license

The model-level source of truth is metadata.yaml. Existing metadata-png-*.ttl
files are read only to preserve stable distribution identifiers, existing model
W3IDs used by dct:isPartOf, and curated PNG-level values during regeneration.
The script does not update metadata.ttl; it only reads an existing metadata.ttl
as a compatibility fallback when no existing PNG metadata file exposes the
model W3ID.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import struct
import sys
import uuid
import zlib
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence
from urllib.parse import quote

try:
    import yaml
except ImportError as exc:  # pragma: no cover - dependency failure only
    raise SystemExit(
        "PyYAML is required. Install it with: python -m pip install -r scripts/requirements.txt"
    ) from exc

try:
    from rdflib import BNode, Graph, Literal, Namespace, URIRef
    from rdflib.namespace import DCTERMS as DCT, RDF, SKOS, XSD
except ImportError as exc:  # pragma: no cover - dependency failure only
    raise SystemExit(
        "RDFLib is required. Install it with: python -m pip install -r scripts/requirements.txt"
    ) from exc

DCAT = Namespace("http://www.w3.org/ns/dcat#")
FDPO = Namespace("https://w3id.org/fdp/fdp-o#")
OCMV = Namespace("https://w3id.org/ontouml-models/vocabulary#")
SPDX = Namespace("http://spdx.org/rdf/terms#")
SCHEMA = Namespace("https://schema.org/")

PNG_MEDIA_TYPE = URIRef("https://www.iana.org/assignments/media-types/image/png")
DISTRIBUTION_BASE = "https://w3id.org/ontouml-models/distribution/"
DEFAULT_REPOSITORY = "OntoUML/ontouml-models"
DEFAULT_BRANCH = "master"
DEFAULT_MODELS_DIR = "models"
DEFAULT_MODEL_IRI_BASE = "https://w3id.org/ontouml-models/model"

DIAGRAM_SOURCES = {
    "original-diagrams": "o",
    "new-diagrams": "n",
}

SOURCE_VERSION_LABELS = {
    "o": "original version",
    "n": "Visual Paradigm version",
}

EDITORIAL_NOTES = {
    "o": "This image depicts the diagram as originally represented by its author(s).",
    "n": "This image depicts a version of the original diagram re-created in the Visual Paradigm editor.",
}

LICENSE_ALIASES = {
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

CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
DATE_YEAR_RE = re.compile(r"^\d{4}$")
DATE_YEAR_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
XSD_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)
HTTP_URI_RE = re.compile(r"^https?://", re.I)
DISTRIBUTION_IRI_RE = re.compile(r"<([^>]+)>\s+a\s+[^.;]*\bdcat:Distribution\b", re.S)
URI_RE = re.compile(r"<([^>]+)>")
MODEL_IRI_RE = re.compile(
    r"<(?P<iri>https://w3id\.org/ontouml-models/model/[^>]+/?)>\s+a\s+[^.;]*\bdcat:Dataset\b",
    re.S,
)
IS_PART_OF_RE = re.compile(r"\bdct:isPartOf\s+<([^>]+)>", re.S)
FULL_IS_PART_OF_RE = re.compile(
    r"<http://purl\.org/dc/terms/isPartOf>\s+<([^>]+)>", re.S
)
PREFIXED_DATETIME_RE_TEMPLATE = r"\bfdpo:{name}\s+\"([^\"]+)\"\^\^xsd:dateTime"
FULL_DATETIME_RE_TEMPLATE = (
    r"<https://w3id\.org/fdp/fdp-o#{name}>\s+\"([^\"]+)\"\^\^"
    r"<http://www\.w3\.org/2001/XMLSchema#dateTime>"
)


class MetadataSetupError(RuntimeError):
    """Raised when command-line or discovery setup prevents execution."""


class MetadataGenerationError(RuntimeError):
    """Raised when a dataset cannot be processed safely."""


@dataclass(frozen=True)
class Config:
    """Configuration for PNG metadata generation."""

    repository: str = DEFAULT_REPOSITORY
    branch: str = DEFAULT_BRANCH
    models_dir_name: str = DEFAULT_MODELS_DIR
    model_iri_base: str = DEFAULT_MODEL_IRI_BASE
    overwrite: bool = True
    strict: bool = False
    dry_run: bool = False
    check: bool = False
    include_file_metadata: bool = False
    metadata_timestamp: Optional[str] = None
    allow_missing_license: bool = False
    # Deprecated compatibility shim for older callers that used Config(require_license=True).
    require_license: Optional[bool] = None
    emit_diff: bool = False
    quiet: bool = False


@dataclass(frozen=True)
class ModelMetadata:
    """Minimum model metadata required to describe its PNG distributions."""

    uri: URIRef
    title: str
    license_uri: Optional[URIRef]
    issued: Literal


@dataclass(frozen=True)
class ExistingDistributionMetadata:
    """Reusable metadata found in an existing distribution metadata file."""

    uri: Optional[URIRef] = None
    model_uri: Optional[URIRef] = None
    title: Optional[Literal] = None
    editorial_note: Optional[Literal] = None
    download_url: Optional[URIRef] = None
    license_uri: Optional[URIRef] = None
    metadata_issued: Optional[Literal] = None
    metadata_modified: Optional[Literal] = None


@dataclass(frozen=True)
class DiagramFile:
    """A discovered PNG diagram and the catalog naming data derived from it."""

    source_dir: str
    prefix: str
    path: Path
    stem: str
    output_path: Path
    distribution_uri: URIRef
    download_url: URIRef
    existing_metadata: ExistingDistributionMetadata


@dataclass(frozen=True)
class GeneratedFile:
    """Result of generating or checking one metadata file."""

    diagram_path: Path
    metadata_path: Path
    distribution_uri: URIRef
    changed: bool
    written: bool

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["diagram_path"] = str(self.diagram_path)
        data["metadata_path"] = str(self.metadata_path)
        data["distribution_uri"] = str(self.distribution_uri)
        return data


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
    """Construct YAML mappings while rejecting duplicate keys."""

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


def bind_prefixes(graph: Graph) -> None:
    """Bind prefixes used by catalog distribution metadata."""

    graph.bind("dcat", DCAT)
    graph.bind("dct", DCT)
    graph.bind("fdpo", FDPO)
    graph.bind("ocmv", OCMV)
    graph.bind("skos", SKOS)
    graph.bind("xsd", XSD)
    graph.bind("spdx", SPDX)
    graph.bind("schema", SCHEMA)


def effective_allow_missing_license(config: Config) -> bool:
    """Return the active missing-license policy."""

    if config.require_license is True:
        return False
    return config.allow_missing_license


def validate_dataset_folder(
    dataset_folder: Path, *, require_metadata_yaml: bool = True
) -> Path:
    """Return a normalized dataset folder path or raise a setup error."""

    dataset_folder = dataset_folder.resolve()
    if not dataset_folder.exists():
        raise MetadataSetupError(f"Dataset folder does not exist: {dataset_folder}")
    if not dataset_folder.is_dir():
        raise MetadataSetupError(f"Dataset path is not a directory: {dataset_folder}")
    if require_metadata_yaml and not (dataset_folder / "metadata.yaml").exists():
        raise MetadataSetupError(
            f"Missing metadata.yaml in dataset folder: {dataset_folder}"
        )
    return dataset_folder


def normalize_model_uri(uri: URIRef) -> URIRef:
    """Normalize model URIs for distribution metadata."""

    return URIRef(str(uri).rstrip("/"))


def load_yaml_mapping(path: Path) -> Mapping[str, Any]:
    """Load a YAML file and ensure its root node is a mapping."""

    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=MetadataYamlLoader)
    except yaml.YAMLError as exc:
        raise MetadataGenerationError(f"Could not parse {path}: {exc}") from exc
    except OSError as exc:
        raise MetadataGenerationError(f"Could not read {path}: {exc}") from exc

    if data is None:
        raise MetadataGenerationError(f"Canonical metadata file is empty: {path}")
    if not isinstance(data, Mapping):
        raise MetadataGenerationError(
            f"Canonical metadata file must contain a YAML mapping: {path}"
        )
    return data


def canonical_key(value: object) -> str:
    """Return a normalized key or identifier for permissive matching."""

    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def yaml_mapping_get(mapping: Mapping[str, Any], key: str) -> Any:
    """Return a mapping value using case-insensitive key matching."""

    wanted = canonical_key(key)
    for candidate, value in mapping.items():
        if canonical_key(candidate) == wanted:
            return value
    return None


def yaml_value_at_path(data: Any, path: Sequence[str]) -> Any:
    current = data
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = yaml_mapping_get(current, key)
        if current is None:
            return None
    return current


def yaml_first_value(data: Mapping[str, Any], paths: Sequence[Sequence[str]]) -> Any:
    for path in paths:
        value = yaml_value_at_path(data, path)
        if value is not None:
            return value
    return None


def yaml_text(value: Any) -> Optional[str]:
    """Extract human-readable text from common YAML scalar or language-map forms."""

    if value is None:
        return None
    if isinstance(value, Mapping):
        for key in ("en", "eng", "english", "value", "label", "title", "name"):
            text = yaml_text(yaml_mapping_get(value, key))
            if text:
                return text
        for nested in value.values():
            text = yaml_text(nested)
            if text:
                return text
        return None
    if isinstance(value, list):
        for item in value:
            text = yaml_text(item)
            if text:
                return text
        return None
    text = str(value).strip()
    return text or None


def yaml_issued_literal(value: Any) -> Optional[Literal]:
    """Return an RDF literal for a model issued value."""

    if value is None:
        return None
    if isinstance(value, datetime):
        text = value.isoformat()
        return Literal(text, datatype=XSD.dateTime, normalize=False)
    if isinstance(value, date):
        return Literal(value.isoformat(), datatype=XSD.date, normalize=False)

    text = yaml_text(value)
    if not text:
        return None
    if DATE_YEAR_RE.match(text):
        return Literal(text, datatype=XSD.gYear, normalize=False)
    if DATE_YEAR_MONTH_RE.match(text):
        return Literal(text, datatype=XSD.gYearMonth, normalize=False)
    if DATE_RE.match(text):
        return Literal(text, datatype=XSD.date, normalize=False)
    if XSD_DATETIME_RE.match(text):
        return Literal(text, datatype=XSD.dateTime, normalize=False)
    raise MetadataGenerationError(
        f"Unsupported issued date value {text!r}; expected YYYY, YYYY-MM, YYYY-MM-DD, or xsd:dateTime."
    )


def uri_from_text(value: str, *, field_name: str) -> URIRef:
    text = value.strip()
    if not HTTP_URI_RE.match(text):
        raise MetadataGenerationError(
            f"Field '{field_name}' must be an HTTP(S) URI; got {text!r}."
        )
    return URIRef(text)


def deterministic_model_uri(dataset_folder: Path, model_iri_base: str) -> URIRef:
    """Return the converter-compatible deterministic model URI for a new dataset."""

    slug = dataset_folder.name.strip().strip("/")
    if not slug:
        raise MetadataGenerationError(
            "Could not infer model URI because the dataset folder has no name."
        )
    base = model_iri_base.rstrip("/")
    generated_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"{base}|{slug}")
    return URIRef(f"{base}/{generated_uuid}")


def yaml_model_uri(value: Any, dataset_folder: Path, model_iri_base: str) -> URIRef:
    """Return an explicit YAML model URI or the converter-compatible deterministic URI."""

    text = yaml_text(value)
    if text and HTTP_URI_RE.match(text):
        return normalize_model_uri(URIRef(text))
    return deterministic_model_uri(dataset_folder, model_iri_base)


def yaml_license_uri(value: Any) -> Optional[URIRef]:
    """Return a license URI from common scalar or mapping forms."""

    if value is None:
        return None
    if isinstance(value, Mapping):
        for key in ("uri", "url", "id", "identifier", "license", "value"):
            result = yaml_license_uri(yaml_mapping_get(value, key))
            if result is not None:
                return result
        return None
    if isinstance(value, list):
        for item in value:
            result = yaml_license_uri(item)
            if result is not None:
                return result
        return None

    text = str(value).strip()
    if not text:
        return None
    if HTTP_URI_RE.match(text):
        return URIRef(text)
    alias = LICENSE_ALIASES.get(canonical_key(text))
    if alias:
        return URIRef(alias)
    raise MetadataGenerationError(
        f"Unsupported license value {text!r}; use a license URI or a supported alias such as CC-BY-4.0."
    )


def load_model_metadata(dataset_folder: Path, config: Config) -> ModelMetadata:
    """Load model URI, title, issued date, and optional license from metadata.yaml."""

    metadata_path = dataset_folder / "metadata.yaml"
    if not metadata_path.exists():
        raise MetadataGenerationError(
            f"Missing required canonical metadata file: {metadata_path}"
        )

    data = load_yaml_mapping(metadata_path)
    title = yaml_text(
        yaml_first_value(
            data,
            (
                ("title",),
                ("model", "title"),
                ("metadata", "title"),
                ("resource", "title"),
                ("ontology", "title"),
                ("name",),
            ),
        )
    )
    if not title:
        raise MetadataGenerationError(f"Missing required title in {metadata_path}")

    issued_literal = yaml_issued_literal(
        yaml_first_value(
            data,
            (
                ("issued",),
                ("dateIssued",),
                ("issuedDate",),
                ("issued_date",),
                ("date",),
                ("metadata", "issued"),
                ("metadata", "dateIssued"),
                ("metadata", "date"),
                ("model", "issued"),
                ("model", "dateIssued"),
                ("resource", "issued"),
                ("resource", "dateIssued"),
                ("publication", "issued"),
                ("publication", "date"),
                ("publicationDate",),
            ),
        )
    )
    if issued_literal is None:
        raise MetadataGenerationError(
            f"Missing required issued date in {metadata_path}"
        )

    model_uri = yaml_model_uri(
        yaml_first_value(
            data,
            (
                ("uri",),
                ("modelUri",),
                ("model", "uri"),
                ("metadata", "uri"),
                ("resource", "uri"),
            ),
        ),
        dataset_folder,
        config.model_iri_base,
    )

    license_ref = yaml_license_uri(
        yaml_first_value(
            data,
            (
                ("license",),
                ("licenseUrl",),
                ("licenseUri",),
                ("metadata", "license"),
                ("metadata", "licenseUrl"),
                ("metadata", "licenseUri"),
                ("model", "license"),
                ("resource", "license"),
                ("rights", "license"),
                ("rights", "licenseUrl"),
                ("rights", "licenseUri"),
            ),
        )
    )
    if license_ref is None and not effective_allow_missing_license(config):
        raise MetadataGenerationError(
            "Missing mandatory metadata field(s): license. "
            "Use --allow-missing-license only for legacy datasets that intentionally lack license metadata."
        )

    return ModelMetadata(
        uri=model_uri,
        title=title,
        license_uri=license_ref,
        issued=issued_literal,
    )


def is_part_of_uri_from_text(text: str) -> Optional[URIRef]:
    """Extract a distribution dct:isPartOf URI from Turtle text without full parsing."""

    match = IS_PART_OF_RE.search(text) or FULL_IS_PART_OF_RE.search(text)
    return normalize_model_uri(URIRef(match.group(1))) if match else None


def model_uri_from_metadata_ttl(path: Path) -> Optional[URIRef]:
    """Extract the model dataset URI from an existing model-level metadata.ttl file."""

    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MetadataGenerationError(
            f"Could not read existing metadata.ttl {path}: {exc}"
        ) from exc
    match = MODEL_IRI_RE.search(text)
    return normalize_model_uri(URIRef(match.group("iri"))) if match else None


def unique_existing_model_uri(
    uris: Iterable[URIRef], source_description: str
) -> Optional[URIRef]:
    """Return one existing model URI or fail on conflicting preserved values."""

    normalized = sorted(
        {str(normalize_model_uri(uri)) for uri in uris if uri is not None}
    )
    if not normalized:
        return None
    if len(normalized) > 1:
        raise MetadataGenerationError(
            f"Conflicting model URIs found in {source_description}: "
            + ", ".join(normalized)
        )
    return URIRef(normalized[0])


def discover_existing_png_model_uri(dataset_folder: Path) -> Optional[URIRef]:
    """Discover the preserved model URI from existing PNG metadata files, if any."""

    model_uris: list[URIRef] = []
    for path in sorted(dataset_folder.glob("metadata-png-*.ttl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise MetadataGenerationError(
                f"Could not read existing PNG metadata {path}: {exc}"
            ) from exc
        uri = is_part_of_uri_from_text(text)
        if uri is not None:
            model_uris.append(uri)
    return unique_existing_model_uri(
        model_uris, f"existing PNG metadata files in {dataset_folder}"
    )


def resolve_model_uri(dataset_folder: Path, yaml_uri: URIRef) -> URIRef:
    """Return the model URI to use in PNG distribution metadata.

    Existing catalog datasets historically use UUID-based model W3IDs. Because
    metadata.yaml does not contain those identifiers, preserve them from existing
    metadata.ttl when available. This also repairs accidental slug-based
    dct:isPartOf values produced by earlier regeneration attempts. If metadata.ttl
    is absent, preserve the URI from existing PNG distribution metadata when
    possible. If neither exists, use the same deterministic UUIDv5 model URI
    strategy as metadata_yaml_to_ttl.py for new datasets.
    """

    existing_model_ttl_uri = model_uri_from_metadata_ttl(
        dataset_folder / "metadata.ttl"
    )
    if existing_model_ttl_uri is not None:
        return existing_model_ttl_uri
    existing_png_uri = discover_existing_png_model_uri(dataset_folder)
    if existing_png_uri is not None:
        return existing_png_uri
    return yaml_uri


def prefixed_datetime_literal_from_text(text: str, name: str) -> Optional[Literal]:
    """Preserve exact xsd:dateTime lexical forms from existing Turtle text."""

    patterns = (
        PREFIXED_DATETIME_RE_TEMPLATE.format(name=name),
        FULL_DATETIME_RE_TEMPLATE.format(name=name),
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.S)
        if match:
            return Literal(match.group(1), datatype=XSD.dateTime, normalize=False)
    return None


def first_object(graph: Graph, subject: URIRef, predicate: URIRef) -> Any:
    for obj in graph.objects(subject, predicate):
        return obj
    return None


def read_existing_metadata(path: Path) -> ExistingDistributionMetadata:
    """Read reusable values from an existing PNG distribution metadata file."""

    if not path.exists():
        return ExistingDistributionMetadata()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MetadataGenerationError(
            f"Could not read existing metadata file {path}: {exc}"
        ) from exc

    graph = Graph()
    bind_prefixes(graph)
    try:
        graph.parse(data=text, format="turtle")
    except Exception as exc:  # noqa: BLE001 - surface RDFLib parse errors clearly
        raise MetadataGenerationError(
            f"Could not parse existing PNG metadata {path}: {exc}"
        ) from exc

    subjects = list(graph.subjects(RDF.type, DCAT.Distribution))
    if subjects:
        subject = subjects[0]
    else:
        match = DISTRIBUTION_IRI_RE.search(text)
        subject = URIRef(match.group(1)) if match else None

    if subject is None:
        raise MetadataGenerationError(
            f"Existing PNG metadata has no dcat:Distribution subject: {path}"
        )

    download_url = first_object(graph, subject, DCAT.downloadURL)
    license_uri = first_object(graph, subject, DCT.license)
    model_uri = first_object(graph, subject, DCT.isPartOf) or is_part_of_uri_from_text(
        text
    )
    return ExistingDistributionMetadata(
        uri=URIRef(subject),
        model_uri=normalize_model_uri(URIRef(model_uri))
        if model_uri is not None
        else None,
        title=first_object(graph, subject, DCT.title),
        editorial_note=first_object(graph, subject, SKOS.editorialNote),
        download_url=URIRef(download_url) if download_url is not None else None,
        license_uri=URIRef(license_uri) if license_uri is not None else None,
        metadata_issued=prefixed_datetime_literal_from_text(text, "metadataIssued")
        or first_object(graph, subject, FDPO.metadataIssued),
        metadata_modified=prefixed_datetime_literal_from_text(text, "metadataModified")
        or first_object(graph, subject, FDPO.metadataModified),
    )


def deterministic_distribution_uri(
    model: ModelMetadata, source_dir: str, filename: str
) -> URIRef:
    """Return a deterministic distribution URI for a new PNG metadata file."""

    seed = f"{model.uri}|{source_dir}/{filename}"
    return URIRef(f"{DISTRIBUTION_BASE}{uuid.uuid5(uuid.NAMESPACE_URL, seed)}/")


def quote_path_segment(segment: str) -> str:
    """Quote a URL path segment while preserving commas for catalog compatibility."""

    return quote(segment, safe=",-_.~()")


def split_path_like(value: str) -> list[str]:
    """Split a slash-separated path-like CLI value into non-empty segments."""

    return [segment for segment in value.strip("/").split("/") if segment]


def default_download_url(
    dataset_folder: Path, source_dir: str, filename: str, config: Config
) -> URIRef:
    """Return the raw GitHub download URL for a PNG diagram."""

    parts = (
        ["https://raw.githubusercontent.com"]
        + [quote_path_segment(part) for part in split_path_like(config.repository)]
        + [quote_path_segment(config.branch.strip("/"))]
        + [quote_path_segment(part) for part in split_path_like(config.models_dir_name)]
        + [
            quote_path_segment(dataset_folder.name),
            quote_path_segment(source_dir),
            quote_path_segment(filename),
        ]
    )
    return URIRef("/".join(parts))


def validate_png(path: Path) -> tuple[int, int]:
    """Validate a PNG file and return its width and height."""

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise MetadataGenerationError(f"Could not read PNG file {path}: {exc}") from exc

    signature = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(signature):
        raise MetadataGenerationError(f"File is not a valid PNG image: {path}")

    offset = len(signature)
    width: Optional[int] = None
    height: Optional[int] = None
    seen_ihdr = False
    seen_iend = False

    while offset < len(data):
        if offset + 8 > len(data):
            raise MetadataGenerationError(
                f"File has a truncated PNG chunk header: {path}"
            )
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        offset += 8
        if offset + length + 4 > len(data):
            raise MetadataGenerationError(f"File has a truncated PNG chunk: {path}")
        chunk_data = data[offset : offset + length]
        crc_bytes = data[offset + length : offset + length + 4]
        actual_crc = struct.unpack(">I", crc_bytes)[0]
        expected_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise MetadataGenerationError(f"File has an invalid PNG CRC: {path}")
        offset += length + 4

        if chunk_type == b"IHDR":
            if seen_ihdr:
                raise MetadataGenerationError(
                    f"File has more than one PNG IHDR chunk: {path}"
                )
            if length != 13:
                raise MetadataGenerationError(
                    f"File has an invalid PNG IHDR chunk: {path}"
                )
            width, height = struct.unpack(">II", chunk_data[:8])
            if width <= 0 or height <= 0:
                raise MetadataGenerationError(
                    f"File has invalid PNG dimensions: {path}"
                )
            seen_ihdr = True
        elif not seen_ihdr:
            raise MetadataGenerationError(f"File has no leading PNG IHDR chunk: {path}")
        elif chunk_type == b"IEND":
            seen_iend = True
            break

    if not seen_ihdr or width is None or height is None:
        raise MetadataGenerationError(f"File has no PNG IHDR chunk: {path}")
    if not seen_iend:
        raise MetadataGenerationError(f"File has no PNG IEND chunk: {path}")
    return width, height


def sha256_hex(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_diagrams(
    dataset_folder: Path, model: ModelMetadata, config: Config
) -> list[DiagramFile]:
    """Collect PNG diagrams and derive their output metadata paths."""

    diagrams: list[DiagramFile] = []
    missing_or_empty: list[str] = []

    for source_dir, prefix in DIAGRAM_SOURCES.items():
        folder = dataset_folder / source_dir
        if not folder.exists() or not folder.is_dir():
            missing_or_empty.append(source_dir)
            continue
        pngs = sorted(
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() == ".png"
        )
        if not pngs:
            missing_or_empty.append(source_dir)
            continue
        for path in pngs:
            if CONTROL_CHARS.search(path.name):
                raise MetadataGenerationError(
                    f"PNG filename contains control characters: {path}"
                )
            validate_png(path)
            output = dataset_folder / f"metadata-png-{prefix}-{path.stem}.ttl"
            existing = read_existing_metadata(output)
            diagrams.append(
                DiagramFile(
                    source_dir=source_dir,
                    prefix=prefix,
                    path=path,
                    stem=path.stem,
                    output_path=output,
                    distribution_uri=existing.uri
                    or deterministic_distribution_uri(model, source_dir, path.name),
                    download_url=existing.download_url
                    or default_download_url(
                        dataset_folder, source_dir, path.name, config
                    ),
                    existing_metadata=existing,
                )
            )

    if config.strict and missing_or_empty:
        raise MetadataGenerationError(
            "Missing or empty expected diagram folder(s): "
            + ", ".join(missing_or_empty)
        )
    if not diagrams:
        raise MetadataGenerationError(f"No PNG diagrams found in {dataset_folder}")

    output_paths = [diagram.output_path for diagram in diagrams]
    duplicated_outputs = sorted(
        {path for path in output_paths if output_paths.count(path) > 1}
    )
    if duplicated_outputs:
        raise MetadataGenerationError(
            "Duplicate generated metadata path(s): "
            + ", ".join(str(path) for path in duplicated_outputs)
        )
    distribution_uris = [diagram.distribution_uri for diagram in diagrams]
    duplicated_uris = sorted(
        {uri for uri in distribution_uris if distribution_uris.count(uri) > 1}
    )
    if duplicated_uris:
        raise MetadataGenerationError(
            "Duplicate generated distribution URI(s): "
            + ", ".join(str(uri) for uri in duplicated_uris)
        )
    return diagrams


def current_metadata_timestamp() -> Literal:
    """Return the current UTC timestamp as xsd:dateTime."""

    value = (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    return Literal(value, datatype=XSD.dateTime, normalize=False)


def configured_metadata_timestamp(config: Config, target: Path) -> Literal:
    """Return the explicit run timestamp used for FDP timestamp changes."""

    if config.metadata_timestamp == "now":
        return current_metadata_timestamp()
    if config.metadata_timestamp:
        if not XSD_DATETIME_RE.match(config.metadata_timestamp):
            raise MetadataGenerationError(
                "--metadata-timestamp must be an xsd:dateTime lexical value, "
                "for example 2024-01-02T03:04:05Z. Use 'now' only when a "
                "non-deterministic current timestamp is intentionally desired."
            )
        return Literal(
            config.metadata_timestamp, datatype=XSD.dateTime, normalize=False
        )
    raise MetadataGenerationError(
        f"No run timestamp is available to initialize fdpo:metadataIssued or update "
        f"fdpo:metadataModified in {target}. Provide --metadata-timestamp, for example "
        "--metadata-timestamp 2026-01-31T12:00:00Z. Use --metadata-timestamp now "
        "only when a non-deterministic execution timestamp is acceptable."
    )


def diagram_label(stem: str) -> str:
    """Return a human-readable diagram label derived from a filename stem."""

    return re.sub(r"[\s_-]+", " ", stem).strip()


def source_version_label(prefix: str) -> str:
    return SOURCE_VERSION_LABELS.get(prefix, prefix)


def editorial_note(prefix: str) -> str:
    return EDITORIAL_NOTES.get(
        prefix, "This image depicts a diagram distribution of the model."
    )


def diagram_title(model: ModelMetadata, diagram: DiagramFile) -> str:
    """Return a catalog-style title for a PNG diagram distribution."""

    return (
        f"PNG distribution of diagram '{diagram_label(diagram.stem)}' from the "
        f"{model.title} ({source_version_label(diagram.prefix)})"
    )


def build_distribution_graph(
    model: ModelMetadata,
    diagram: DiagramFile,
    config: Config,
    *,
    update_metadata_modified: bool = False,
) -> Graph:
    """Build RDF metadata for one PNG diagram distribution."""

    graph = Graph()
    bind_prefixes(graph)

    run_timestamp: Optional[Literal] = None

    def get_run_timestamp() -> Literal:
        nonlocal run_timestamp
        if run_timestamp is None:
            run_timestamp = configured_metadata_timestamp(config, diagram.output_path)
        return run_timestamp

    metadata_issued = diagram.existing_metadata.metadata_issued or get_run_timestamp()
    if update_metadata_modified:
        metadata_modified = get_run_timestamp()
    else:
        metadata_modified = (
            diagram.existing_metadata.metadata_modified or metadata_issued
        )
    license_uri = diagram.existing_metadata.license_uri or model.license_uri

    graph.add((diagram.distribution_uri, RDF.type, DCAT.Distribution))
    graph.add((diagram.distribution_uri, DCT.isPartOf, model.uri))
    graph.add((diagram.distribution_uri, DCT.issued, model.issued))
    if license_uri is not None:
        graph.add((diagram.distribution_uri, DCT.license, license_uri))
    graph.add((diagram.distribution_uri, DCAT.mediaType, PNG_MEDIA_TYPE))
    graph.add(
        (
            diagram.distribution_uri,
            OCMV.isComplete,
            Literal(False, datatype=XSD.boolean),
        )
    )
    graph.add(
        (
            diagram.distribution_uri,
            DCT.title,
            diagram.existing_metadata.title
            or Literal(diagram_title(model, diagram), lang="en"),
        )
    )
    graph.add((diagram.distribution_uri, DCAT.downloadURL, diagram.download_url))
    graph.add(
        (
            diagram.distribution_uri,
            SKOS.editorialNote,
            diagram.existing_metadata.editorial_note
            or Literal(editorial_note(diagram.prefix), lang="en"),
        )
    )
    graph.add((diagram.distribution_uri, FDPO.metadataIssued, metadata_issued))
    graph.add((diagram.distribution_uri, FDPO.metadataModified, metadata_modified))

    if config.include_file_metadata:
        width, height = validate_png(diagram.path)
        graph.add(
            (
                diagram.distribution_uri,
                DCAT.byteSize,
                Literal(Decimal(os.path.getsize(diagram.path)), datatype=XSD.decimal),
            )
        )
        graph.add(
            (
                diagram.distribution_uri,
                SCHEMA.width,
                Literal(width, datatype=XSD.integer),
            )
        )
        graph.add(
            (
                diagram.distribution_uri,
                SCHEMA.height,
                Literal(height, datatype=XSD.integer),
            )
        )
        checksum = BNode()
        graph.add((diagram.distribution_uri, SPDX.checksum, checksum))
        graph.add((checksum, RDF.type, SPDX.Checksum))
        graph.add((checksum, SPDX.algorithm, SPDX.checksumAlgorithm_sha256))
        graph.add((checksum, SPDX.checksumValue, Literal(sha256_hex(diagram.path))))

    return graph


def serialize_graph(graph: Graph) -> str:
    return graph.serialize(format="turtle")


def write_graph(graph: Graph, target: Path, config: Config) -> None:
    """Serialize a graph to Turtle."""

    if target.exists() and not config.overwrite:
        raise MetadataGenerationError(
            f"Metadata file already exists and overwrite is disabled: {target}"
        )
    if config.dry_run or config.check:
        return
    target.write_text(serialize_graph(graph), encoding="utf-8")


def process_dataset(dataset_folder: Path, config: Config) -> list[GeneratedFile]:
    """Generate PNG distribution metadata files for one dataset folder."""

    dataset_folder = validate_dataset_folder(dataset_folder)
    model = load_model_metadata(dataset_folder, config)
    resolved_uri = resolve_model_uri(dataset_folder, model.uri)
    if resolved_uri != model.uri:
        model = ModelMetadata(
            uri=resolved_uri,
            title=model.title,
            license_uri=model.license_uri,
            issued=model.issued,
        )
    diagrams = collect_diagrams(dataset_folder, model, config)

    existing_targets = [
        diagram.output_path for diagram in diagrams if diagram.output_path.exists()
    ]
    if existing_targets and not config.overwrite:
        raise MetadataGenerationError(
            "Metadata file already exists and overwrite is disabled: "
            + ", ".join(str(path) for path in existing_targets)
        )

    initial_plans = [
        (diagram, build_distribution_graph(model, diagram, config))
        for diagram in diagrams
    ]

    final_plans: list[tuple[DiagramFile, Graph, str | None, str, bool]] = []
    for diagram, graph in initial_plans:
        old_text = (
            diagram.output_path.read_text(encoding="utf-8")
            if diagram.output_path.exists()
            else None
        )
        initial_text = serialize_graph(graph)
        changed = old_text != initial_text
        if changed:
            graph = build_distribution_graph(
                model,
                diagram,
                config,
                update_metadata_modified=True,
            )
        final_text = serialize_graph(graph)
        changed = old_text != final_text
        final_plans.append((diagram, graph, old_text, final_text, changed))

    generated: list[GeneratedFile] = []
    for diagram, graph, old_text, new_text, changed in final_plans:
        if config.check and changed and config.emit_diff:
            if old_text is None:
                print(f"Would create {diagram.output_path}")
            else:
                diff = difflib.unified_diff(
                    old_text.splitlines(),
                    new_text.splitlines(),
                    fromfile=str(diagram.output_path),
                    tofile=f"{diagram.output_path} (generated)",
                    lineterm="",
                )
                for line in diff:
                    print(line)
        if changed:
            write_graph(graph, diagram.output_path, config)
        generated.append(
            GeneratedFile(
                diagram_path=diagram.path,
                metadata_path=diagram.output_path,
                distribution_uri=diagram.distribution_uri,
                changed=changed,
                written=changed and not config.dry_run and not config.check,
            )
        )
    return generated


def discover_datasets(models_dir: Path) -> list[Path]:
    """Discover model dataset folders under models_dir by metadata.yaml presence."""

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


def resolve_targets(args: argparse.Namespace) -> list[Path]:
    if args.all:
        if args.datasets:
            raise MetadataSetupError(
                "Use either --all or explicit dataset folders, not both."
            )
        datasets = discover_datasets(args.models_dir)
    elif args.datasets:
        datasets = [validate_dataset_folder(path) for path in args.datasets]
    else:
        cwd = Path.cwd()
        if (cwd / "metadata.yaml").exists():
            datasets = [cwd]
        else:
            raise MetadataSetupError(
                "No dataset folder provided. Pass one or more model folders, use --all, or run from a dataset folder."
            )
    if not datasets:
        raise MetadataSetupError("No dataset folders with metadata.yaml were found.")
    return datasets


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate metadata-png-o-*.ttl and metadata-png-n-*.ttl files from diagram PNG files.",
    )
    parser.add_argument(
        "datasets",
        nargs="*",
        type=Path,
        help="Dataset folder(s) to process. If omitted, the current directory is used when it contains metadata.yaml.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all dataset folders below --models-dir.",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=Path(DEFAULT_MODELS_DIR),
        help=f"Models directory used with --all. Default: {DEFAULT_MODELS_DIR}.",
    )
    parser.add_argument(
        "--allow-missing-license",
        action="store_true",
        help="Allow generation for legacy datasets without license metadata; otherwise license is mandatory.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write files; exit 1 if any PNG metadata file would change.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and report files that would be generated without writing them.",
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
        help="Suppress per-file progress logs and the final text summary. Errors are still printed to stderr.",
    )
    parser.add_argument(
        "--repository",
        default=DEFAULT_REPOSITORY,
        help=f"GitHub repository used for dcat:downloadURL. Default: {DEFAULT_REPOSITORY}.",
    )
    parser.add_argument(
        "--branch",
        default=DEFAULT_BRANCH,
        help=f"Git branch used for dcat:downloadURL. Default: {DEFAULT_BRANCH}.",
    )
    parser.add_argument(
        "--models-dir-name",
        default=DEFAULT_MODELS_DIR,
        help=f"Repository-relative models path used inside generated dcat:downloadURL values. Default: {DEFAULT_MODELS_DIR}.",
    )
    parser.add_argument(
        "--model-iri-base",
        default=DEFAULT_MODEL_IRI_BASE,
        help=f"Base IRI used for deterministic UUIDv5 model IRIs when no existing catalog model IRI is available. Default: {DEFAULT_MODEL_IRI_BASE}.",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Fail if a target metadata file already exists.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if expected diagram folders are missing or empty.",
    )
    parser.add_argument(
        "--include-file-metadata",
        action="store_true",
        help="Also add optional byte size, SHA-256 checksum, width, and height triples.",
    )
    parser.add_argument(
        "--metadata-timestamp",
        help=(
            "xsd:dateTime value used to initialize missing fdpo:metadataIssued values and "
            "update fdpo:metadataModified when an existing metadata file changes. Required when "
            "creating new metadata files, when existing files lack fdpo:metadataIssued, or when "
            "existing files need regeneration changes. Use 'now' only when a non-deterministic "
            "current timestamp is intentionally desired."
        ),
    )
    parser.add_argument(
        "--require-license",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    if args.check and args.dry_run:
        parser.error("--check and --dry-run cannot be used together.")
    if args.allow_missing_license and args.require_license:
        parser.error(
            "--allow-missing-license and --require-license cannot be used together."
        )
    return args


def action_label(config: Config, item: GeneratedFile) -> str:
    if config.dry_run:
        return "would generate"
    if config.check:
        return "needs update" if item.changed else "up to date"
    return "generated" if item.written else "unchanged"


def print_progress(item: GeneratedFile, config: Config) -> None:
    print(f"{action_label(config, item)}: {item.metadata_path} <- {item.diagram_path}")


def print_summary(
    results: Sequence[GeneratedFile], error_count: int, config: Config
) -> None:
    if config.dry_run:
        return
    changed = sum(1 for item in results if item.changed)
    written = sum(1 for item in results if item.written)
    total = len(results) + error_count
    if config.check:
        print(
            f"Summary: {total} file(s) processed, {len(results)} succeeded, "
            f"{error_count} error(s), {changed} file(s) need update."
        )
    else:
        print(
            f"Summary: {total} file(s) processed, {len(results)} succeeded, "
            f"{error_count} error(s), {written} written, {changed} changed."
        )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    config = Config(
        repository=args.repository,
        branch=args.branch,
        models_dir_name=args.models_dir_name,
        model_iri_base=args.model_iri_base,
        overwrite=not args.no_overwrite,
        strict=args.strict,
        dry_run=args.dry_run,
        check=args.check,
        include_file_metadata=args.include_file_metadata,
        metadata_timestamp=args.metadata_timestamp,
        allow_missing_license=args.allow_missing_license,
        require_license=args.require_license or None,
        emit_diff=args.format == "text" and not args.quiet,
        quiet=args.quiet,
    )

    try:
        targets = resolve_targets(args)
    except MetadataSetupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    results: list[GeneratedFile] = []
    errors: list[dict[str, str]] = []
    progress_enabled = args.format == "text" and not args.quiet
    for target in targets:
        try:
            generated = process_dataset(target, config)
            results.extend(generated)
            if progress_enabled:
                for item in generated:
                    print_progress(item, config)
        except MetadataGenerationError as exc:
            errors.append({"dataset": str(target), "error": str(exc)})
            print(f"ERROR {target}: {exc}", file=sys.stderr)

    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": not errors
                    and not (config.check and any(item.changed for item in results)),
                    "results": [item.to_dict() for item in results],
                    "errors": errors,
                },
                indent=2,
                sort_keys=True,
            )
        )
    elif not args.quiet:
        print_summary(results, len(errors), config)

    if errors:
        return 1
    if config.check and any(item.changed for item in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Generate RDF/Turtle metadata for OntoUML catalog PNG diagram distributions.

The script scans one or more model dataset folders and creates one metadata file
for each PNG diagram found in these source folders:

- original-diagrams/<diagram>.png -> metadata-png-o-<diagram>.ttl
- new-diagrams/<diagram>.png      -> metadata-png-n-<diagram>.ttl

Run from the repository root, for example:

    python scripts/generate_png_metadata.py models/amaral2019rot
    python scripts/generate_png_metadata.py --all --models-dir models

The generated RDF follows the distribution metadata pattern already used in the
catalog for JSON, Turtle, VPP, and PNG distributions:

- the distribution is typed as dcat:Distribution;
- the distribution points back to the model with dct:isPartOf;
- model-level dct:issued is copied from metadata.yaml to the distribution;
- model-level dct:license is copied from metadata.yaml when available;
- the distribution receives dcat:mediaType, dcat:downloadURL, dct:title,
  skos:editorialNote, ocmv:isComplete, fdpo:metadataIssued, and
  fdpo:metadataModified.

The model-level source of truth is metadata.yaml. Existing metadata-png-*.ttl
files are read only to preserve stable distribution identifiers and curated
PNG-level values during regeneration. The script does not read or update
metadata.ttl.

RDFLib is used for RDF graph creation and Turtle serialization. PyYAML is used
for metadata.yaml parsing. PNG validation and dimension extraction are performed
with the Python standard library so that no image-processing dependency is
needed.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import struct
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote

import yaml
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS as DCT, RDF, SKOS, XSD

DCAT = Namespace("http://www.w3.org/ns/dcat#")
FDPO = Namespace("https://w3id.org/fdp/fdp-o#")
OCMV = Namespace("https://w3id.org/ontouml-models/vocabulary#")
SPDX = Namespace("http://spdx.org/rdf/terms#")
SCHEMA = Namespace("https://schema.org/")

PNG_MEDIA_TYPE = URIRef("https://www.iana.org/assignments/media-types/image/png")
DISTRIBUTION_BASE = "https://w3id.org/ontouml-models/distribution/"

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

CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
XSD_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)


class MetadataGenerationError(RuntimeError):
    """Raised when a dataset cannot be processed safely."""


@dataclass(frozen=True)
class Config:
    """Configuration for PNG metadata generation."""

    repository: str = "OntoUML/ontouml-models"
    branch: str = "master"
    models_dir_name: str = "models"
    overwrite: bool = True
    strict: bool = False
    dry_run: bool = False
    include_file_metadata: bool = False
    metadata_timestamp: Optional[str] = None
    require_license: bool = False


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

    uri: Optional[URIRef]
    title: Optional[Literal]
    editorial_note: Optional[Literal]
    download_url: Optional[URIRef]
    license_uri: Optional[URIRef]
    metadata_issued: Optional[Literal]
    metadata_modified: Optional[Literal]


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
    """Result of generating one metadata file."""

    diagram_path: Path
    metadata_path: Path
    distribution_uri: URIRef


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


def validate_dataset_folder(dataset_folder: Path) -> Path:
    """Return a normalized dataset folder path or raise a clear error."""

    dataset_folder = dataset_folder.resolve()
    if not dataset_folder.exists():
        raise MetadataGenerationError(
            f"Dataset folder does not exist: {dataset_folder}"
        )
    if not dataset_folder.is_dir():
        raise MetadataGenerationError(
            f"Dataset path is not a directory: {dataset_folder}"
        )
    return dataset_folder


def normalize_model_uri(uri: URIRef) -> URIRef:
    """Normalize model URIs for distribution metadata.

    Some catalog metadata files contain the model subject with a trailing slash,
    while existing distribution metadata files use dct:isPartOf with the same URI
    without that trailing slash. Distribution files generated here follow the
    existing distribution-file convention.
    """

    return URIRef(str(uri).rstrip("/"))


def load_model_metadata(dataset_folder: Path, config: Config) -> ModelMetadata:
    """Load model URI, title, issued date, and optional license from metadata.yaml."""

    metadata_path = dataset_folder / "metadata.yaml"
    if not metadata_path.exists():
        raise MetadataGenerationError(
            f"Missing required canonical metadata file: {metadata_path}"
        )

    data = load_yaml_mapping(metadata_path)

    title_value = yaml_first_value(
        data,
        paths=(
            ("title",),
            ("model", "title"),
            ("metadata", "title"),
            ("resource", "title"),
            ("ontology", "title"),
            ("name",),
        ),
        recursive_keys=("title", "name"),
    )
    title = yaml_text(title_value)
    if not title:
        raise MetadataGenerationError(f"Missing required title in {metadata_path}")

    issued_value = yaml_first_value(
        data,
        paths=(
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
        recursive_keys=("issued", "dateIssued", "issuedDate", "publicationDate"),
    )
    issued_literal = yaml_issued_literal(issued_value)
    if issued_literal is None:
        raise MetadataGenerationError(
            f"Missing required issued date in {metadata_path}"
        )

    uri_value = yaml_first_value(
        data,
        paths=(
            ("uri",),
            ("modelUri",),
            ("model", "uri"),
            ("model", "id"),
            ("metadata", "uri"),
            ("resource", "uri"),
            ("id",),
        ),
        recursive_keys=("modelUri", "uri"),
    )
    model_uri = yaml_model_uri(uri_value, dataset_folder.name)

    license_value = yaml_first_value(
        data,
        paths=(
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
        recursive_keys=("license", "licenseUrl", "licenseUri"),
    )
    license_ref = yaml_license_uri(license_value)
    if license_ref is None and config.require_license:
        raise MetadataGenerationError(f"Missing required license in {metadata_path}")

    return ModelMetadata(
        uri=model_uri,
        title=title,
        license_uri=license_ref,
        issued=issued_literal,
    )


def load_yaml_mapping(path: Path) -> Mapping[str, Any]:
    """Load a YAML file and ensure its root node is a mapping."""

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
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


def canonical_yaml_key(value: object) -> str:
    """Return a normalized key for permissive YAML field matching."""

    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def yaml_mapping_get(mapping: Mapping[str, Any], key: str) -> Any:
    """Return a mapping value using case-insensitive, punctuation-insensitive key matching."""

    wanted = canonical_yaml_key(key)
    for candidate, value in mapping.items():
        if canonical_yaml_key(candidate) == wanted:
            return value
    return None


def yaml_value_at_path(data: Any, path: Sequence[str]) -> Any:
    """Return a YAML value by a normalized key path, or None when absent."""

    current = data
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = yaml_mapping_get(current, key)
        if current is None:
            return None
    return current


def yaml_recursive_find(data: Any, keys: Sequence[str]) -> Any:
    """Return the first scalar-like value found recursively for one of the given keys."""

    wanted = {canonical_yaml_key(key) for key in keys}
    if isinstance(data, Mapping):
        for key, value in data.items():
            if canonical_yaml_key(key) in wanted and value is not None:
                return value
        for value in data.values():
            found = yaml_recursive_find(value, keys)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data:
            found = yaml_recursive_find(value, keys)
            if found is not None:
                return found
    return None


def yaml_first_value(
    data: Mapping[str, Any],
    *,
    paths: Sequence[Sequence[str]],
    recursive_keys: Sequence[str] = (),
) -> Any:
    """Return the first matching value from explicit paths, then from recursive key search."""

    for path in paths:
        value = yaml_value_at_path(data, path)
        if value is not None:
            return value
    if recursive_keys:
        return yaml_recursive_find(data, recursive_keys)
    return None


def yaml_text(value: Any) -> Optional[str]:
    """Extract human-readable text from common YAML scalar or language-map forms."""

    if value is None:
        return None
    if isinstance(value, Mapping):
        for key in ("en", "eng", "english", "value", "label", "title", "name"):
            nested = yaml_mapping_get(value, key)
            text = yaml_text(nested)
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
    """Convert a YAML issued-date value to the RDF literal used for dct:issued."""

    text = yaml_text(value)
    if not text:
        return None
    if re.fullmatch(r"\d{4}", text):
        return Literal(text, datatype=XSD.gYear)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return Literal(text, datatype=XSD.date)
    if XSD_DATETIME.match(text):
        return Literal(text, datatype=XSD.dateTime, normalize=False)
    return Literal(text)


def yaml_model_uri(value: Any, dataset_slug: str) -> URIRef:
    """Return the model URI from YAML, falling back to the dataset folder name."""

    text = yaml_text(value)
    if text and re.match(r"https?://", text):
        return normalize_model_uri(URIRef(text))
    if text and "/ontouml-models/model/" in text:
        return normalize_model_uri(URIRef(text))

    # If the canonical YAML does not expose the full IRI, the catalog folder name
    # is the stable model slug used in the standard model URI pattern.
    slug = text or dataset_slug
    slug = str(slug).strip().strip("/")
    if not slug:
        slug = dataset_slug
    return normalize_model_uri(URIRef(f"https://w3id.org/ontouml-models/model/{slug}/"))


def yaml_license_uri(value: Any) -> Optional[URIRef]:
    """Extract a license URI from common YAML license forms."""

    text = yaml_license_text(value)
    if not text:
        return None
    text = text.strip()
    if re.match(r"https?://", text):
        return URIRef(text)

    licenses = {
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
    return (
        URIRef(licenses[canonical_yaml_key(text)])
        if canonical_yaml_key(text) in licenses
        else None
    )


def yaml_license_text(value: Any) -> Optional[str]:
    """Extract a license string, preferring URI/URL fields over labels."""

    if value is None:
        return None
    if isinstance(value, Mapping):
        for key in (
            "uri",
            "url",
            "licenseUri",
            "licenseUrl",
            "id",
            "identifier",
            "spdx",
            "value",
        ):
            text = yaml_license_text(yaml_mapping_get(value, key))
            if text:
                return text
        for nested in value.values():
            text = yaml_license_text(nested)
            if text:
                return text
        return None
    if isinstance(value, list):
        for item in value:
            text = yaml_license_text(item)
            if text:
                return text
        return None
    text = str(value).strip()
    return text or None


def first_literal(
    graph: Graph, subject: URIRef, predicate: URIRef
) -> Optional[Literal]:
    """Return the first literal object for subject/predicate, if present."""

    for value in graph.objects(subject, predicate):
        if isinstance(value, Literal):
            return value
    return None


def first_uri(graph: Graph, subject: URIRef, predicate: URIRef) -> Optional[URIRef]:
    """Return the first URIRef object for subject/predicate, if present."""

    for value in graph.objects(subject, predicate):
        if isinstance(value, URIRef):
            return value
    return None


def validate_png_name(path: Path) -> str:
    """Validate a PNG filename and return the stem used in metadata names."""

    if path.suffix.lower() != ".png":
        raise MetadataGenerationError(
            f"Unsupported diagram file extension; expected .png: {path}"
        )

    name = path.name
    stem = path.stem
    if not stem:
        raise MetadataGenerationError(
            f"Unsupported PNG filename with empty stem: {path}"
        )
    if CONTROL_CHARS.search(name):
        raise MetadataGenerationError(
            f"Unsupported PNG filename with control characters: {path}"
        )
    if name in {".", ".."} or stem in {".", ".."}:
        raise MetadataGenerationError(f"Unsupported PNG filename: {path}")
    return stem


def read_png_dimensions(path: Path) -> Tuple[int, int]:
    """Return PNG width and height after validating PNG chunk structure.

    The validator checks the PNG signature, IHDR chunk, chunk boundaries, chunk
    CRC values, and the presence of the terminal IEND chunk. It does not decode
    the compressed image payload; the goal is to reject unreadable or truncated
    files without adding an image-processing dependency.
    """

    signature = b"\x89PNG\r\n\x1a\n"

    try:
        with path.open("rb") as stream:
            if stream.read(8) != signature:
                raise MetadataGenerationError(f"Unreadable or invalid PNG file: {path}")

            chunk_type, chunk_data = read_png_chunk(stream, path)
            if chunk_type != b"IHDR" or len(chunk_data) != 13:
                raise MetadataGenerationError(
                    f"PNG file does not contain a valid IHDR chunk: {path}"
                )

            width, height = struct.unpack(">II", chunk_data[:8])
            if width <= 0 or height <= 0:
                raise MetadataGenerationError(
                    f"PNG file has invalid dimensions {width}x{height}: {path}"
                )

            while True:
                chunk_type, _chunk_data = read_png_chunk(stream, path)
                if chunk_type == b"IEND":
                    break

    except OSError as exc:
        raise MetadataGenerationError(f"Could not read PNG file {path}: {exc}") from exc

    return width, height


def read_png_chunk(stream, path: Path) -> Tuple[bytes, bytes]:
    """Read one PNG chunk and validate its CRC."""

    length_bytes = stream.read(4)
    if len(length_bytes) != 4:
        raise MetadataGenerationError(f"Unreadable or truncated PNG file: {path}")

    length = struct.unpack(">I", length_bytes)[0]
    chunk_type = stream.read(4)
    if len(chunk_type) != 4:
        raise MetadataGenerationError(
            f"Unreadable or truncated PNG chunk header: {path}"
        )

    chunk_data = stream.read(length)
    if len(chunk_data) != length:
        raise MetadataGenerationError(f"Unreadable or truncated PNG chunk data: {path}")

    crc_bytes = stream.read(4)
    if len(crc_bytes) != 4:
        raise MetadataGenerationError(f"Unreadable or truncated PNG chunk CRC: {path}")

    stored_crc = struct.unpack(">I", crc_bytes)[0]
    computed_crc = crc32(chunk_type + chunk_data)
    if stored_crc != computed_crc:
        raise MetadataGenerationError(f"Invalid PNG chunk CRC in {path}")

    return chunk_type, chunk_data


def crc32(data: bytes) -> int:
    """Return an unsigned PNG CRC-32 value."""

    import zlib

    return zlib.crc32(data) & 0xFFFFFFFF


def sha256_hex(path: Path) -> str:
    """Compute a SHA-256 checksum for a file."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quoted_path(*segments: str) -> str:
    """Quote URL path segments while preserving path separators.

    Commas are left unescaped because they are valid path characters and existing
    catalog raw GitHub URLs use them unescaped in diagram filenames.
    """

    return "/".join(quote(segment, safe=",") for segment in segments)


def split_repository_path(path: str) -> List[str]:
    """Split a repository-relative path option into URL path segments."""

    return [segment for segment in path.replace("\\", "/").split("/") if segment]


def new_distribution_uri(model_uri: URIRef, source_dir: str, filename: str) -> URIRef:
    """Create a deterministic distribution URI for a PNG diagram.

    Existing catalog distribution URIs use UUIDs under
    https://w3id.org/ontouml-models/distribution/. For new PNG metadata files,
    a UUIDv5 value makes generation reproducible. If a target metadata file
    already exists, its distribution URI is preserved instead.
    """

    name = f"{model_uri}|{source_dir}/{filename}"
    return URIRef(f"{DISTRIBUTION_BASE}{uuid.uuid5(uuid.NAMESPACE_URL, name)}/")


def download_url(
    config: Config, dataset_folder: Path, source_dir: str, filename: str
) -> URIRef:
    """Create the raw GitHub download URL for a diagram file."""

    model_slug = dataset_folder.name
    path = quoted_path(
        *split_repository_path(config.models_dir_name), model_slug, source_dir, filename
    )
    return URIRef(
        f"https://raw.githubusercontent.com/{config.repository}/{config.branch}/{path}"
    )


def read_existing_distribution_metadata(path: Path) -> ExistingDistributionMetadata:
    """Read reusable metadata from an existing target file, if present.

    RDFLib normalizes xsd:dateTime values when parsing, which can shorten
    nanosecond timestamps such as 2023-04-14T17:33:22.898648451Z. The catalog
    already contains such lexical forms, so timestamp literals are extracted from
    the original Turtle text and reinserted with normalize=False.
    """

    if not path.exists():
        return ExistingDistributionMetadata(
            uri=None,
            title=None,
            editorial_note=None,
            download_url=None,
            license_uri=None,
            metadata_issued=None,
            metadata_modified=None,
        )

    graph = Graph()
    try:
        graph.parse(path)
    except Exception as exc:  # noqa: BLE001 - surface RDFLib parse errors clearly
        raise MetadataGenerationError(
            f"Could not parse existing metadata file {path}: {exc}"
        ) from exc

    subjects = [
        subject
        for subject in graph.subjects(RDF.type, DCAT.Distribution)
        if isinstance(subject, URIRef)
    ]
    if len(subjects) > 1:
        raise MetadataGenerationError(
            f"Expected at most one dcat:Distribution in {path}, found {len(subjects)}"
        )

    distribution = subjects[0] if subjects else None
    if distribution and not str(distribution).startswith(DISTRIBUTION_BASE):
        raise MetadataGenerationError(
            f"Existing distribution URI does not follow catalog distribution URI pattern in {path}: {distribution}"
        )

    text = path.read_text(encoding="utf-8")
    title = first_literal(graph, distribution, DCT.title) if distribution else None
    editorial = (
        first_literal(graph, distribution, SKOS.editorialNote) if distribution else None
    )
    download = (
        first_uri(graph, distribution, DCAT.downloadURL) if distribution else None
    )
    license_uri = first_uri(graph, distribution, DCT.license) if distribution else None
    metadata_issued = existing_datetime_literal(text, "metadataIssued")
    metadata_modified = existing_datetime_literal(text, "metadataModified")

    return ExistingDistributionMetadata(
        uri=distribution,
        title=title,
        editorial_note=editorial,
        download_url=download,
        license_uri=license_uri,
        metadata_issued=metadata_issued,
        metadata_modified=metadata_modified,
    )


def existing_datetime_literal(turtle_text: str, local_name: str) -> Optional[Literal]:
    """Return an existing fdpo dateTime literal while preserving its lexical form."""

    patterns = [
        rf"\bfdpo:{re.escape(local_name)}\s+\"([^\"]+)\"\^\^xsd:dateTime",
        rf"<https://w3id\.org/fdp/fdp-o#{re.escape(local_name)}>\s+\"([^\"]+)\"\^\^<http://www\.w3\.org/2001/XMLSchema#dateTime>",
    ]
    for pattern in patterns:
        match = re.search(pattern, turtle_text)
        if match:
            return Literal(match.group(1), datatype=XSD.dateTime, normalize=False)
    return None


def collect_diagrams(
    dataset_folder: Path, model: ModelMetadata, config: Config
) -> List[DiagramFile]:
    """Collect diagram files in catalog-supported diagram folders.

    All diagram-level validation is completed before any output file is written.
    This prevents partial generation when a later diagram is invalid, when strict
    mode fails, or when duplicate metadata targets/URIs are detected.
    """

    seen_outputs: dict[Path, Path] = {}
    seen_uris: dict[URIRef, Path] = {}
    missing_or_empty: List[str] = []
    diagrams: List[DiagramFile] = []

    for source_dir, prefix in DIAGRAM_SOURCES.items():
        folder = dataset_folder / source_dir
        if not folder.exists():
            missing_or_empty.append(f"missing folder: {folder}")
            continue
        if not folder.is_dir():
            raise MetadataGenerationError(
                f"Diagram path exists but is not a directory: {folder}"
            )

        png_files = sorted(
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() == ".png"
        )
        if not png_files:
            missing_or_empty.append(f"empty folder: {folder}")
            continue

        for png_path in png_files:
            stem = validate_png_name(png_path)
            # Validate PNG before generating metadata; dimensions can optionally
            # be emitted with --include-file-metadata.
            read_png_dimensions(png_path)

            output_path = dataset_folder / f"metadata-png-{prefix}-{stem}.ttl"
            if output_path.exists() and not config.overwrite:
                existing = ExistingDistributionMetadata(
                    uri=None,
                    title=None,
                    editorial_note=None,
                    download_url=None,
                    license_uri=None,
                    metadata_issued=None,
                    metadata_modified=None,
                )
                dist_uri = new_distribution_uri(model.uri, source_dir, png_path.name)
            else:
                existing = read_existing_distribution_metadata(output_path)
                dist_uri = existing.uri or new_distribution_uri(
                    model.uri, source_dir, png_path.name
                )
            generated_download_url = download_url(
                config, dataset_folder, source_dir, png_path.name
            )
            dload = existing.download_url or generated_download_url

            existing_output = seen_outputs.get(output_path)
            if existing_output is not None:
                raise MetadataGenerationError(
                    f"Duplicate metadata target {output_path} for {existing_output} and {png_path}"
                )
            seen_outputs[output_path] = png_path

            existing_uri = seen_uris.get(dist_uri)
            if existing_uri is not None:
                raise MetadataGenerationError(
                    f"Duplicate distribution URI {dist_uri} for {existing_uri} and {png_path}"
                )
            seen_uris[dist_uri] = png_path

            diagrams.append(
                DiagramFile(
                    source_dir=source_dir,
                    prefix=prefix,
                    path=png_path,
                    stem=stem,
                    output_path=output_path,
                    distribution_uri=dist_uri,
                    download_url=dload,
                    existing_metadata=existing,
                )
            )

    if not diagrams:
        details = (
            "; ".join(missing_or_empty) if missing_or_empty else "no PNG files found"
        )
        raise MetadataGenerationError(
            f"No PNG diagrams found in {dataset_folder} ({details})"
        )

    if config.strict and missing_or_empty:
        raise MetadataGenerationError(
            f"Strict mode failed for {dataset_folder}: " + "; ".join(missing_or_empty)
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


def configured_metadata_timestamp(config: Config) -> Literal:
    """Return a configured or current fdpo metadata timestamp."""

    if config.metadata_timestamp:
        if not XSD_DATETIME.match(config.metadata_timestamp):
            raise MetadataGenerationError(
                "--metadata-timestamp must be an xsd:dateTime lexical value, "
                "for example 2024-01-02T03:04:05Z"
            )
        return Literal(
            config.metadata_timestamp, datatype=XSD.dateTime, normalize=False
        )
    return current_metadata_timestamp()


def build_distribution_graph(
    model: ModelMetadata, diagram: DiagramFile, config: Config
) -> Graph:
    """Build RDF metadata for one PNG diagram distribution."""

    graph = Graph()
    bind_prefixes(graph)

    title = diagram_title(model, diagram)
    metadata_timestamp = configured_metadata_timestamp(config)
    metadata_issued = diagram.existing_metadata.metadata_issued or metadata_timestamp
    # Preserve existing metadataModified by default to make regeneration stable.
    # Pass --metadata-timestamp with a new value after intentional changes if a
    # maintained modified timestamp is required.
    metadata_modified = (
        diagram.existing_metadata.metadata_modified or metadata_timestamp
    )

    graph.add((diagram.distribution_uri, RDF.type, DCAT.Distribution))
    graph.add((diagram.distribution_uri, DCT.isPartOf, model.uri))
    graph.add((diagram.distribution_uri, DCT.issued, model.issued))
    license_uri = diagram.existing_metadata.license_uri or model.license_uri
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
            diagram.existing_metadata.title or Literal(title, lang="en"),
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
        width, height = read_png_dimensions(diagram.path)
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


def diagram_title(model: ModelMetadata, diagram: DiagramFile) -> str:
    """Return a catalog-style title for a PNG diagram distribution."""

    label = diagram_label(diagram.stem)
    version = source_version_label(diagram.prefix)
    return f"PNG distribution of diagram '{label}' from the {model.title} ({version})"


def diagram_label(stem: str) -> str:
    """Return a human-readable diagram label derived from a filename stem."""

    return re.sub(r"[\s_-]+", " ", stem).strip()


def source_version_label(prefix: str) -> str:
    """Return the catalog label used for the source diagram version."""

    return SOURCE_VERSION_LABELS.get(prefix, prefix)


def editorial_note(prefix: str) -> str:
    """Return the catalog editorial note used for the source diagram version."""

    return EDITORIAL_NOTES.get(
        prefix, "This image depicts a diagram distribution of the model."
    )


def write_graph(graph: Graph, target: Path, config: Config) -> None:
    """Serialize a graph to Turtle."""

    if target.exists() and not config.overwrite:
        raise MetadataGenerationError(
            f"Metadata file already exists and overwrite is disabled: {target}"
        )
    if config.dry_run:
        return

    target.write_text(graph.serialize(format="turtle"), encoding="utf-8")


def process_dataset(dataset_folder: Path, config: Config) -> List[GeneratedFile]:
    """Generate PNG distribution metadata files for one dataset folder.

    The function validates all inputs and builds all RDF graphs before writing any
    target file. This keeps generation atomic at dataset level for validation
    errors and for --no-overwrite failures.
    """

    dataset_folder = validate_dataset_folder(dataset_folder)
    model = load_model_metadata(dataset_folder, config)
    diagrams = collect_diagrams(dataset_folder, model, config)

    existing_targets = [
        diagram.output_path for diagram in diagrams if diagram.output_path.exists()
    ]
    if existing_targets and not config.overwrite:
        joined = ", ".join(str(path) for path in existing_targets)
        raise MetadataGenerationError(
            f"Metadata file already exists and overwrite is disabled: {joined}"
        )

    planned = [
        (diagram, build_distribution_graph(model, diagram, config))
        for diagram in diagrams
    ]

    generated: List[GeneratedFile] = []
    for diagram, graph in planned:
        write_graph(graph, diagram.output_path, config)
        generated.append(
            GeneratedFile(
                diagram_path=diagram.path,
                metadata_path=diagram.output_path,
                distribution_uri=diagram.distribution_uri,
            )
        )
    return generated


def discover_datasets(models_dir: Path) -> List[Path]:
    """Discover model dataset folders under models_dir by metadata.yaml presence."""

    if not models_dir.exists():
        raise MetadataGenerationError(f"Models directory does not exist: {models_dir}")
    if not models_dir.is_dir():
        raise MetadataGenerationError(f"Models path is not a directory: {models_dir}")
    return sorted(
        path
        for path in models_dir.iterdir()
        if path.is_dir() and (path / "metadata.yaml").exists()
    )


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
        default=Path("models"),
        help="Models directory used with --all. Default: models.",
    )
    parser.add_argument(
        "--repository",
        default="OntoUML/ontouml-models",
        help="GitHub repository used for dcat:downloadURL. Default: OntoUML/ontouml-models.",
    )
    parser.add_argument(
        "--branch",
        default="master",
        help="Git branch used for dcat:downloadURL. Default: master.",
    )
    parser.add_argument(
        "--models-dir-name",
        default="models",
        help="Repository-relative models path used inside generated dcat:downloadURL values. Default: models.",
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
        "--dry-run",
        action="store_true",
        help="Validate inputs and report files that would be generated without writing them.",
    )
    parser.add_argument(
        "--include-file-metadata",
        action="store_true",
        help="Also add optional byte size, SHA-256 checksum, width, and height triples.",
    )
    parser.add_argument(
        "--metadata-timestamp",
        help="xsd:dateTime value used for fdpo:metadataIssued and fdpo:metadataModified on new files.",
    )
    parser.add_argument(
        "--require-license",
        action="store_true",
        help="Fail if metadata.yaml does not provide a usable license. By default, missing licenses are tolerated and dct:license is omitted unless an existing PNG metadata file already has one.",
    )
    return parser.parse_args(argv)


def resolve_targets(args: argparse.Namespace) -> List[Path]:
    if args.all:
        if args.datasets:
            raise MetadataGenerationError(
                "Use either --all or explicit dataset folders, not both."
            )
        return discover_datasets(args.models_dir)

    if args.datasets:
        return list(args.datasets)

    cwd = Path.cwd()
    if (cwd / "metadata.yaml").exists():
        return [cwd]

    raise MetadataGenerationError(
        "No dataset folder provided. Pass one or more model folders, use --all, or run from a dataset folder."
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    config = Config(
        repository=args.repository,
        branch=args.branch,
        models_dir_name=args.models_dir_name,
        overwrite=not args.no_overwrite,
        strict=args.strict,
        dry_run=args.dry_run,
        include_file_metadata=args.include_file_metadata,
        metadata_timestamp=args.metadata_timestamp,
        require_license=args.require_license,
    )

    try:
        targets = resolve_targets(args)
        generated_all: List[GeneratedFile] = []
        for target in targets:
            generated_all.extend(process_dataset(target, config))
    except MetadataGenerationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    action = "would generate" if config.dry_run else "generated"
    for item in generated_all:
        print(f"{action}: {item.metadata_path} <- {item.diagram_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

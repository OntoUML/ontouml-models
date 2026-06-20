#!/usr/bin/env python3
"""
Generate OntoUML/UFO Catalog metadata for Visual Paradigm project distributions.

This script creates or updates `metadata-vpp.ttl` for dataset folders that contain
an `ontology.vpp` file and a model-level `metadata.ttl` file.

Typical usage from the repository root:

    python scripts/generate_vpp_metadata.py models/amaral2019rot
    python scripts/generate_vpp_metadata.py models --recursive
    python scripts/generate_vpp_metadata.py models --recursive --dry-run

The script does not parse the proprietary VPP project structure. It treats
`ontology.vpp` as a binary distribution and generates file-level distribution
metadata consistent with the OntoUML/UFO Catalog metadata pattern.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, SKOS, XSD

# Reused catalog vocabularies.
DCAT = Namespace("http://www.w3.org/ns/dcat#")
DCT = Namespace("http://purl.org/dc/terms/")
FDPO = Namespace("https://w3id.org/fdp/fdp-o#")
MOD = Namespace("https://w3id.org/mod#")
OCMV = Namespace("https://w3id.org/ontouml-models/vocabulary#")
OWL = Namespace("http://www.w3.org/2002/07/owl#")
SPDX = Namespace("http://spdx.org/rdf/terms#")

CATALOG_DISTRIBUTION_BASE = "https://w3id.org/ontouml-models/distribution/"
DEFAULT_DOWNLOAD_BASE_URL = "https://raw.githubusercontent.com/OntoUML/ontouml-models/master"
VPP_FORMAT_URI = URIRef("https://www.file-extension.info/format/vpp")
OCTET_STREAM_URI = URIRef("https://www.iana.org/assignments/media-types/application/octet-stream")


class VppMetadataError(RuntimeError):
    """Raised when VPP metadata cannot be generated safely."""


@dataclass(frozen=True)
class DatasetMetadata:
    """Model-level metadata needed to generate VPP distribution metadata."""

    dataset_uri: URIRef
    title: str
    license_uri: URIRef
    issued: Optional[Literal]


@dataclass(frozen=True)
class GeneratedFile:
    """Description of one generated `metadata-vpp.ttl` file."""

    dataset_dir: Path
    output_path: Path
    distribution_uri: URIRef


def bind_prefixes(graph: Graph) -> None:
    """Bind prefixes used in existing catalog metadata files."""

    graph.bind("fdpo", FDPO)
    graph.bind("dcat", DCAT)
    graph.bind("dct", DCT)
    graph.bind("mod", MOD)
    graph.bind("ocmv", OCMV)
    graph.bind("owl", OWL)
    graph.bind("rdf", RDF)
    graph.bind("rdfs", RDFS)
    graph.bind("skos", SKOS)
    graph.bind("spdx", SPDX)
    graph.bind("xsd", XSD)


def utc_now_literal() -> Literal:
    """Return the current UTC time as an xsd:dateTime literal."""

    value = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return Literal(value, datatype=XSD.dateTime)


def sha256_file(path: Path) -> str:
    """Compute a SHA-256 checksum for a file without loading it all into memory."""

    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def parse_graph(path: Path) -> Graph:
    """Parse a Turtle file and add catalog prefixes to the resulting graph."""

    graph = Graph()
    bind_prefixes(graph)
    try:
        graph.parse(path, format="turtle")
    except Exception as exc:  # RDFLib raises several parser exceptions.
        raise VppMetadataError(f"Could not parse Turtle file: {path}: {exc}") from exc
    return graph


def _select_preferred_title(graph: Graph, subject: URIRef, metadata_path: Path) -> Literal:
    """Select one title literal deterministically, preferring English."""

    titles = [value for value in graph.objects(subject, DCT.title) if isinstance(value, Literal)]
    if not titles:
        raise VppMetadataError(f"Missing required dct:title for model dataset in {metadata_path}")

    def rank(value: Literal) -> tuple[int, str, str]:
        language = (value.language or "").lower()
        if language == "en" or language.startswith("en-"):
            priority = 0
        elif language == "":
            priority = 1
        else:
            priority = 2
        return (priority, language, str(value))

    return sorted(titles, key=rank)[0]


def _candidate_dataset_subjects(graph: Graph) -> list[URIRef]:
    """Return likely model-level metadata subjects, excluding distributions."""

    candidates: list[URIRef] = []

    for subject in graph.subjects(RDF.type, MOD.SemanticArtefact):
        if isinstance(subject, URIRef):
            candidates.append(subject)

    if not candidates:
        for subject in graph.subjects(RDF.type, DCAT.Dataset):
            if isinstance(subject, URIRef) and (subject, RDF.type, DCAT.Distribution) not in graph:
                candidates.append(subject)

    # Remove duplicates while preserving order.
    seen: set[str] = set()
    unique: list[URIRef] = []
    for subject in candidates:
        key = str(subject)
        if key not in seen:
            unique.append(subject)
            seen.add(key)
    return unique


def read_dataset_metadata(dataset_dir: Path) -> DatasetMetadata:
    """Read model-level metadata from `metadata.ttl` in a dataset folder."""

    metadata_path = dataset_dir / "metadata.ttl"
    if not metadata_path.exists():
        raise VppMetadataError(f"Missing required model metadata file: {metadata_path}")
    if not metadata_path.is_file():
        raise VppMetadataError(f"Model metadata path is not a file: {metadata_path}")

    graph = parse_graph(metadata_path)
    subjects = _candidate_dataset_subjects(graph)
    if not subjects:
        raise VppMetadataError(
            f"Could not identify a model dataset subject in {metadata_path}. "
            "Expected a subject typed as mod:SemanticArtefact or dcat:Dataset."
        )
    if len(subjects) > 1:
        formatted = ", ".join(str(subject) for subject in subjects)
        raise VppMetadataError(
            f"Ambiguous model dataset subject in {metadata_path}. Candidates: {formatted}"
        )

    dataset_uri = URIRef(str(subjects[0]).rstrip("/"))

    title_literal = _select_preferred_title(graph, subjects[0], metadata_path)
    title = str(title_literal)
    license_values = list(graph.objects(subjects[0], DCT.license))
    if not license_values:
        raise VppMetadataError(
            f"Missing dct:license for model dataset in {metadata_path}. "
            "The VPP distribution reuses the model license and requires it to be an IRI."
        )
    if len(license_values) > 1:
        formatted = ", ".join(str(value) for value in license_values)
        raise VppMetadataError(
            f"Ambiguous dct:license for model dataset in {metadata_path}. "
            f"Expected one value, found: {formatted}"
        )
    license_uri = license_values[0]
    if not isinstance(license_uri, URIRef):
        raise VppMetadataError(
            f"Unsupported dct:license value for model dataset in {metadata_path}: {license_uri}. "
            "Expected an IRI."
        )

    issued_values = list(graph.objects(subjects[0], DCT.issued))
    if len(issued_values) > 1:
        formatted = ", ".join(str(value) for value in issued_values)
        raise VppMetadataError(
            f"Ambiguous dct:issued for model dataset in {metadata_path}. "
            f"Expected at most one value, found: {formatted}"
        )
    issued = issued_values[0] if issued_values else None
    if issued is not None and not isinstance(issued, Literal):
        raise VppMetadataError(
            f"Unsupported dct:issued value for model dataset in {metadata_path}: {issued}"
        )

    return DatasetMetadata(
        dataset_uri=dataset_uri,
        title=title,
        license_uri=license_uri,
        issued=issued,
    )


def existing_distribution_uri(metadata_vpp_path: Path) -> Optional[URIRef]:
    """Return the existing dcat:Distribution URI from `metadata-vpp.ttl`, if present."""

    if not metadata_vpp_path.exists():
        return None
    graph = parse_graph(metadata_vpp_path)
    distributions = [subject for subject in graph.subjects(RDF.type, DCAT.Distribution) if isinstance(subject, URIRef)]
    if not distributions:
        raise VppMetadataError(
            f"Existing VPP metadata file does not declare a dcat:Distribution: {metadata_vpp_path}"
        )
    if len(distributions) > 1:
        formatted = ", ".join(str(subject) for subject in distributions)
        raise VppMetadataError(
            f"Ambiguous existing VPP distribution metadata in {metadata_vpp_path}. "
            f"Found multiple dcat:Distribution subjects: {formatted}"
        )
    return distributions[0]


def existing_metadata_issued(metadata_vpp_path: Path) -> Optional[Literal]:
    """Preserve fdpo:metadataIssued from an existing generated file, if available."""

    if not metadata_vpp_path.exists():
        return None
    graph = parse_graph(metadata_vpp_path)
    distributions = [subject for subject in graph.subjects(RDF.type, DCAT.Distribution) if isinstance(subject, URIRef)]
    if not distributions:
        raise VppMetadataError(
            f"Existing VPP metadata file does not declare a dcat:Distribution: {metadata_vpp_path}"
        )
    if len(distributions) > 1:
        formatted = ", ".join(str(subject) for subject in distributions)
        raise VppMetadataError(
            f"Ambiguous existing VPP distribution metadata in {metadata_vpp_path}. "
            f"Found multiple dcat:Distribution subjects: {formatted}"
        )
    values = [value for value in graph.objects(distributions[0], FDPO.metadataIssued) if isinstance(value, Literal)]
    if len(values) > 1:
        formatted = ", ".join(str(value) for value in values)
        raise VppMetadataError(
            f"Ambiguous fdpo:metadataIssued values in {metadata_vpp_path}. "
            f"Expected at most one value, found: {formatted}"
        )
    return values[0] if values else None


def deterministic_distribution_uri(dataset_uri: URIRef, relative_vpp_path: str) -> URIRef:
    """Create a stable catalog distribution URI for a VPP file.

    Existing catalog examples use UUID-based distribution URIs. For new generated
    files, this function uses UUIDv5 so repeated generation is stable and does
    not create unnecessary URI churn.
    """

    seed = f"{str(dataset_uri).rstrip('/')}|{relative_vpp_path}"
    distribution_id = uuid.uuid5(uuid.NAMESPACE_URL, seed)
    return URIRef(f"{CATALOG_DISTRIBUTION_BASE}{distribution_id}/")


def relative_posix_path(path: Path, root: Path) -> str:
    """Return a POSIX-style path relative to the repository root."""

    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise VppMetadataError(f"Path {path} is not inside repository root {root}") from exc


def download_url_for(relative_path: str, base_download_url: str) -> URIRef:
    """Build the raw GitHub download URL for a repository-relative file path."""

    base = base_download_url.strip().rstrip("/")
    if not base.startswith(("https://", "http://")):
        raise VppMetadataError(
            "Unsupported base download URL. Expected an absolute HTTP(S) URL, "
            f"got: {base_download_url!r}"
        )
    return URIRef(f"{base}/{relative_path}")


def create_vpp_metadata_graph(
    *,
    dataset: DatasetMetadata,
    distribution_uri: URIRef,
    vpp_path: Path,
    relative_vpp_path: str,
    base_download_url: str,
    metadata_issued: Optional[Literal] = None,
    include_file_metadata: bool = True,
) -> Graph:
    """Create the RDF graph for one `metadata-vpp.ttl` file."""

    graph = Graph()
    bind_prefixes(graph)

    now = utc_now_literal()
    metadata_issued = metadata_issued or now

    graph.add((distribution_uri, RDF.type, DCAT.Distribution))
    graph.add((distribution_uri, DCT.isPartOf, dataset.dataset_uri))
    if dataset.issued is not None:
        graph.add((distribution_uri, DCT.issued, dataset.issued))
    graph.add((distribution_uri, DCAT.mediaType, OCTET_STREAM_URI))
    graph.add((distribution_uri, DCT.license, dataset.license_uri))
    graph.add((distribution_uri, DCT["format"], VPP_FORMAT_URI))
    graph.add(
        (
            distribution_uri,
            DCT.title,
            Literal(f"Visual Paradigm distribution of {dataset.title}", lang="en"),
        )
    )
    graph.add((distribution_uri, DCAT.downloadURL, download_url_for(relative_vpp_path, base_download_url)))
    graph.add((distribution_uri, OCMV.isComplete, Literal(True, datatype=XSD.boolean)))
    graph.add((distribution_uri, FDPO.metadataIssued, metadata_issued))
    graph.add((distribution_uri, FDPO.metadataModified, now))

    if include_file_metadata:
        try:
            size = vpp_path.stat().st_size
        except OSError as exc:
            raise VppMetadataError(f"Could not stat VPP file: {vpp_path}: {exc}") from exc
        graph.add((distribution_uri, DCAT.byteSize, Literal(size, datatype=XSD.decimal)))

        checksum = BNode()
        graph.add((distribution_uri, SPDX.checksum, checksum))
        graph.add((checksum, RDF.type, SPDX.Checksum))
        graph.add((checksum, SPDX.algorithm, SPDX.checksumAlgorithm_sha256))
        graph.add((checksum, SPDX.checksumValue, Literal(sha256_file(vpp_path), datatype=XSD.hexBinary)))

    return graph


def write_graph(graph: Graph, path: Path) -> None:
    """Serialize a graph as Turtle to the given path."""

    try:
        path.write_text(graph.serialize(format="turtle"), encoding="utf-8")
    except OSError as exc:
        raise VppMetadataError(f"Could not write generated metadata file: {path}: {exc}") from exc


def ensure_vpp_file(vpp_path: Path) -> None:
    """Validate that `ontology.vpp` exists and can be read as a binary file."""

    if not vpp_path.exists():
        raise VppMetadataError(f"Missing required VPP file: {vpp_path}")
    if not vpp_path.is_file():
        raise VppMetadataError(f"VPP path is not a file: {vpp_path}")
    try:
        size = vpp_path.stat().st_size
    except OSError as exc:
        raise VppMetadataError(f"Could not stat VPP file: {vpp_path}: {exc}") from exc
    if size == 0:
        raise VppMetadataError(f"VPP file is empty: {vpp_path}")
    try:
        with vpp_path.open("rb") as stream:
            stream.read(1)
    except OSError as exc:
        raise VppMetadataError(f"Could not read VPP file: {vpp_path}: {exc}") from exc


def generate_for_dataset(
    dataset_dir: Path,
    *,
    repository_root: Path,
    base_download_url: str = DEFAULT_DOWNLOAD_BASE_URL,
    dry_run: bool = False,
    include_file_metadata: bool = True,
) -> GeneratedFile:
    """Generate `metadata-vpp.ttl` for one dataset folder."""

    dataset_dir = dataset_dir.resolve()
    repository_root = repository_root.resolve()

    if not dataset_dir.exists():
        raise VppMetadataError(f"Dataset folder does not exist: {dataset_dir}")
    if not dataset_dir.is_dir():
        raise VppMetadataError(f"Dataset path is not a folder: {dataset_dir}")

    vpp_path = dataset_dir / "ontology.vpp"
    ensure_vpp_file(vpp_path)

    dataset = read_dataset_metadata(dataset_dir)
    output_path = dataset_dir / "metadata-vpp.ttl"
    relative_vpp_path = relative_posix_path(vpp_path, repository_root)

    distribution_uri = existing_distribution_uri(output_path) or deterministic_distribution_uri(
        dataset.dataset_uri, relative_vpp_path
    )
    metadata_issued = existing_metadata_issued(output_path)

    graph = create_vpp_metadata_graph(
        dataset=dataset,
        distribution_uri=distribution_uri,
        vpp_path=vpp_path,
        relative_vpp_path=relative_vpp_path,
        base_download_url=base_download_url,
        metadata_issued=metadata_issued,
        include_file_metadata=include_file_metadata,
    )

    if not dry_run:
        write_graph(graph, output_path)

    return GeneratedFile(dataset_dir=dataset_dir, output_path=output_path, distribution_uri=distribution_uri)


def discover_dataset_dirs(path: Path, recursive: bool) -> list[Path]:
    """Discover dataset folders from a supplied path.

    If the supplied path itself contains `ontology.vpp`, it is treated as one
    dataset folder. Otherwise, recursive discovery searches for all matching
    `ontology.vpp` files below the supplied path.
    """

    if not path.exists():
        raise VppMetadataError(f"Input path does not exist: {path}")
    if path.is_file():
        if path.name != "ontology.vpp":
            raise VppMetadataError(f"Input file is not ontology.vpp: {path}")
        return [path.parent]
    if (path / "ontology.vpp").is_file():
        return [path]
    if not recursive:
        raise VppMetadataError(
            f"Input folder does not contain ontology.vpp: {path}. "
            "Use --recursive to process dataset folders below this path."
        )
    return sorted({candidate.parent for candidate in path.rglob("ontology.vpp")})


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate metadata-vpp.ttl files for OntoUML/UFO Catalog dataset folders."
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Dataset folder(s), ontology.vpp file(s), or parent folder(s) to process.",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root used to compute raw GitHub download paths. Defaults to the current directory.",
    )
    parser.add_argument(
        "--base-download-url",
        default=DEFAULT_DOWNLOAD_BASE_URL,
        help="Base URL prepended to repository-relative file paths for dcat:downloadURL.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Search recursively for dataset folders containing ontology.vpp.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report generated files without writing metadata-vpp.ttl.",
    )
    parser.add_argument(
        "--no-file-metadata",
        action="store_true",
        help="Do not add dcat:byteSize or spdx:checksum metadata.",
    )
    return parser.parse_args(argv)


def run(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    include_file_metadata = not args.no_file_metadata

    try:
        dataset_dirs: list[Path] = []
        for path in args.paths:
            dataset_dirs.extend(discover_dataset_dirs(path, recursive=args.recursive))

        # Remove duplicates while preserving sorted/path order.
        unique_dirs: list[Path] = []
        seen: set[Path] = set()
        for directory in dataset_dirs:
            resolved = directory.resolve()
            if resolved not in seen:
                unique_dirs.append(directory)
                seen.add(resolved)

        if not unique_dirs:
            raise VppMetadataError("No dataset folders containing ontology.vpp were found.")

        for dataset_dir in unique_dirs:
            generated = generate_for_dataset(
                dataset_dir,
                repository_root=args.repository_root,
                base_download_url=args.base_download_url,
                dry_run=args.dry_run,
                include_file_metadata=include_file_metadata,
            )
            action = "Would generate" if args.dry_run else "Generated"
            print(f"{action}: {generated.output_path} ({generated.distribution_uri})")

    except VppMetadataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(run())

#!/usr/bin/env python3
"""Generate OntoUML/UFO Catalog metadata for ontology.ttl distributions.

This script creates `metadata-turtle.ttl` files for catalog dataset folders.
It reads the model-level `metadata.ttl`, validates the existing `ontology.ttl`,
and writes RDF/DCAT metadata for the Turtle distribution using RDFLib.

Typical usage from the repository root:

    python tools/generate_metadata_turtle.py models/example-model
    python tools/generate_metadata_turtle.py models --recursive --overwrite

The script intentionally does not generate `ontology.ttl` from `ontology.json`.
It only generates metadata for an already existing `ontology.ttl` file.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional, Sequence

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, XSD
from rdflib.term import Node

DCAT = Namespace("http://www.w3.org/ns/dcat#")
DCT = Namespace("http://purl.org/dc/terms/")
FDPO = Namespace("https://w3id.org/fdp/fdp-o#")
MOD = Namespace("https://w3id.org/mod#")
OCMV = Namespace("https://w3id.org/ontouml-models/vocabulary#")
OWL = Namespace("http://www.w3.org/2002/07/owl#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")

IANA_TURTLE_MEDIA_TYPE = URIRef("https://www.iana.org/assignments/media-types/text/turtle")
DATE_LITERAL_DATATYPES = {XSD.dateTime, XSD.date, XSD.gYearMonth, XSD.gYear}
DEFAULT_RAW_BASE_URL = "https://raw.githubusercontent.com/OntoUML/ontouml-models/master"
DISTRIBUTION_URI_BASE = "https://w3id.org/ontouml-models/distribution/"

# Stable namespace for deterministic distribution URI generation.
# The namespace value itself is arbitrary but fixed; changing it would change
# generated distribution URIs for previously unseen folders.
DISTRIBUTION_UUID_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://w3id.org/ontouml-models/metadata-turtle-distribution"
)


class CatalogMetadataError(Exception):
    """Raised when a catalog folder cannot be processed safely."""


@dataclass
class GenerationResult:
    """Summary of one generated metadata file."""

    dataset_dir: Path
    output_path: Path
    distribution_uri: URIRef
    warnings: list[str] = field(default_factory=list)
    wrote_file: bool = False
    updated_model_metadata: bool = False


@dataclass
class ModelMetadata:
    """Model-level metadata required to generate distribution metadata."""

    model_uri: URIRef
    canonical_model_uri: URIRef
    title: Literal
    issued: Literal
    license: URIRef


def now_utc_literal() -> Literal:
    """Return an xsd:dateTime literal for the current UTC instant."""

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return Literal(timestamp, datatype=XSD.dateTime)


def bind_catalog_prefixes(graph: Graph) -> None:
    """Bind prefixes used by existing catalog distribution metadata files."""

    graph.bind("fdpo", FDPO)
    graph.bind("dcat", DCAT)
    graph.bind("dct", DCT)
    graph.bind("ocmv", OCMV)
    graph.bind("owl", OWL)
    graph.bind("rdf", RDF)
    graph.bind("rdfs", RDFS)
    graph.bind("skos", SKOS)
    graph.bind("xsd", XSD)


def parse_turtle(path: Path, *, purpose: str) -> Graph:
    """Parse a Turtle file with RDFLib and wrap errors with context."""

    graph = Graph()
    try:
        graph.parse(path, format="turtle")
    except FileNotFoundError as exc:
        raise CatalogMetadataError(f"Missing {purpose}: {path}") from exc
    except Exception as exc:  # RDFLib raises several parser-specific exceptions.
        raise CatalogMetadataError(f"Invalid Turtle in {purpose} ({path}): {exc}") from exc
    return graph


def require_file(path: Path, *, description: str) -> None:
    """Fail if a required file is missing."""

    if not path.exists():
        raise CatalogMetadataError(f"Missing {description}: {path}")
    if not path.is_file():
        raise CatalogMetadataError(f"Expected {description} to be a file: {path}")


def canonicalize_model_uri(uri: URIRef) -> URIRef:
    """Normalize model URIs for dct:isPartOf.

    Existing catalog distribution metadata commonly uses the model URI without a
    trailing slash, even when the model-level metadata subject has one. This
    function preserves that convention while keeping non-matching URIs intact.
    """

    return URIRef(str(uri).rstrip("/"))


def select_one_uri(values: Sequence[Node], *, field_name: str, source: URIRef) -> URIRef:
    """Select exactly one URI value for a required metadata field."""

    if not values:
        raise CatalogMetadataError(f"Missing required {field_name} for {source}")
    if len(values) > 1:
        raise CatalogMetadataError(f"Expected exactly one {field_name} for {source}, found {len(values)}")
    value = values[0]
    if not isinstance(value, URIRef):
        raise CatalogMetadataError(f"Expected {field_name} for {source} to be an IRI, found {value!r}")
    return value


def validate_date_literal(value: Literal, *, field_name: str, source: URIRef) -> None:
    """Validate date/dateTime literals allowed by the catalog resource shape."""

    if value.datatype not in DATE_LITERAL_DATATYPES:
        raise CatalogMetadataError(
            f"Expected {field_name} for {source} to use one of "
            "xsd:dateTime, xsd:date, xsd:gYearMonth, or xsd:gYear; "
            f"found datatype {value.datatype!r}"
        )


def select_one_literal(
    values: Sequence[Node],
    *,
    field_name: str,
    source: URIRef,
    prefer_title: bool = False,
    require_date_datatype: bool = False,
) -> Literal:
    """Select one required literal value and validate its kind when needed."""

    if not values:
        raise CatalogMetadataError(f"Missing required {field_name} for {source}")

    literal_values = [v for v in values if isinstance(v, Literal)]
    if len(literal_values) != len(values):
        bad_values = [repr(v) for v in values if not isinstance(v, Literal)]
        raise CatalogMetadataError(
            f"Expected {field_name} for {source} to contain only literals; found {', '.join(bad_values)}"
        )

    if len(literal_values) > 1:
        if prefer_title:
            # Titles may legitimately exist in different languages. The current
            # distribution-title convention requires one model title, so prefer
            # English, then language-neutral titles, then the first available title.
            selected = choose_preferred_title(literal_values)
        else:
            raise CatalogMetadataError(
                f"Expected exactly one {field_name} for {source}, found {len(literal_values)}"
            )
    else:
        selected = literal_values[0]

    if require_date_datatype:
        validate_date_literal(selected, field_name=field_name, source=source)

    return selected


def choose_preferred_title(titles: Sequence[Literal]) -> Optional[Literal]:
    """Prefer English or language-neutral titles when several titles exist."""

    if not titles:
        return None
    for lang in ("en", None, ""):
        for title in titles:
            if title.language == lang:
                return title
    return None


def find_model_resource(metadata_graph: Graph) -> URIRef:
    """Find the model resource described in a dataset-level metadata.ttl file."""

    candidates = set(metadata_graph.subjects(RDF.type, MOD.SemanticArtefact))
    candidates.update(metadata_graph.subjects(RDF.type, DCAT.Dataset))

    # Exclude catalog resources if a catalog-level file is accidentally passed.
    candidates = {
        subject
        for subject in candidates
        if isinstance(subject, URIRef) and (subject, RDF.type, DCAT.Catalog) not in metadata_graph
    }

    semantic_candidates = {
        subject for subject in candidates if (subject, RDF.type, MOD.SemanticArtefact) in metadata_graph
    }
    if semantic_candidates:
        candidates = semantic_candidates

    if not candidates:
        raise CatalogMetadataError(
            "Could not find a model resource in metadata.ttl. Expected a subject typed as mod:SemanticArtefact."
        )
    if len(candidates) > 1:
        ordered = ", ".join(sorted(str(candidate) for candidate in candidates))
        raise CatalogMetadataError(f"Found multiple possible model resources in metadata.ttl: {ordered}")

    return next(iter(candidates))


def read_model_metadata(dataset_dir: Path) -> tuple[Graph, ModelMetadata]:
    """Read the model-level metadata needed for distribution generation."""

    metadata_path = dataset_dir / "metadata.ttl"
    require_file(metadata_path, description="model metadata.ttl")
    graph = parse_turtle(metadata_path, purpose="model metadata.ttl")

    model_uri = find_model_resource(graph)
    title = select_one_literal(
        list(graph.objects(model_uri, DCT.title)),
        field_name="dct:title",
        source=model_uri,
        prefer_title=True,
    )
    issued = select_one_literal(
        list(graph.objects(model_uri, DCT.issued)),
        field_name="dct:issued",
        source=model_uri,
        require_date_datatype=True,
    )
    license_uri = select_one_uri(list(graph.objects(model_uri, DCT.license)), field_name="dct:license", source=model_uri)

    return graph, ModelMetadata(
        model_uri=model_uri,
        canonical_model_uri=canonicalize_model_uri(model_uri),
        title=title,
        issued=issued,
        license=license_uri,
    )


def validate_ontology_turtle(dataset_dir: Path) -> Graph:
    """Validate that ontology.ttl exists and is parseable RDF/Turtle."""

    ontology_path = dataset_dir / "ontology.ttl"
    require_file(ontology_path, description="ontology.ttl")
    graph = parse_turtle(ontology_path, purpose="ontology.ttl")
    if len(graph) == 0:
        raise CatalogMetadataError(f"ontology.ttl is syntactically valid but empty: {ontology_path}")
    return graph


def read_existing_distribution_metadata(output_path: Path) -> tuple[Optional[URIRef], Optional[Literal]]:
    """Read reusable identifiers from an existing metadata-turtle.ttl file."""

    if not output_path.exists():
        return None, None

    graph = parse_turtle(output_path, purpose="existing metadata-turtle.ttl")
    distributions = [s for s in graph.subjects(RDF.type, DCAT.Distribution) if isinstance(s, URIRef)]
    if len(distributions) != 1:
        raise CatalogMetadataError(
            f"Expected exactly one dcat:Distribution in existing {output_path}, found {len(distributions)}"
        )
    distribution_uri = distributions[0]
    metadata_issued_values = list(graph.objects(distribution_uri, FDPO.metadataIssued))
    if len(metadata_issued_values) > 1:
        raise CatalogMetadataError(
            f"Expected at most one fdpo:metadataIssued in existing {output_path}, "
            f"found {len(metadata_issued_values)}"
        )
    metadata_issued = None
    if metadata_issued_values:
        value = metadata_issued_values[0]
        if not isinstance(value, Literal):
            raise CatalogMetadataError(
                f"Expected fdpo:metadataIssued in existing {output_path} to be a literal, found {value!r}"
            )
        validate_date_literal(value, field_name="fdpo:metadataIssued", source=distribution_uri)
        metadata_issued = value
    return distribution_uri, metadata_issued


def make_distribution_uri(model_metadata: ModelMetadata) -> URIRef:
    """Create a stable distribution URI for ontology.ttl metadata.

    Existing catalog files use UUID-based distribution URIs. For new generated
    files, UUIDv5 keeps that style while ensuring repeated generation gives the
    same URI for the same model.
    """

    generated_uuid = uuid.uuid5(
        DISTRIBUTION_UUID_NAMESPACE, f"{model_metadata.canonical_model_uri}|ontology.ttl"
    )
    return URIRef(f"{DISTRIBUTION_URI_BASE}{generated_uuid}/")


def repo_relative_ontology_path(dataset_dir: Path, repo_root: Path) -> tuple[str, list[str]]:
    """Return the repository-relative ontology.ttl path as POSIX text."""

    warnings: list[str] = []
    ontology_path = (dataset_dir / "ontology.ttl").resolve()
    repo_root = repo_root.resolve()
    try:
        relative_path = ontology_path.relative_to(repo_root)
    except ValueError:
        # Useful when testing or when a curator points directly to a copied model
        # folder outside the repository. The caller can override with --repo-root.
        relative_path = Path("models") / dataset_dir.name / "ontology.ttl"
        warnings.append(
            f"{ontology_path} is not under repo root {repo_root}; using fallback path {relative_path.as_posix()}"
        )
    return relative_path.as_posix(), warnings


def build_download_url(dataset_dir: Path, repo_root: Path, raw_base_url: str) -> tuple[URIRef, list[str]]:
    """Build the raw GitHub download URL for ontology.ttl."""

    relative_path, warnings = repo_relative_ontology_path(dataset_dir, repo_root)
    base = raw_base_url.rstrip("/")
    return URIRef(f"{base}/{relative_path}"), warnings


def build_distribution_graph(
    *,
    model_metadata: ModelMetadata,
    distribution_uri: URIRef,
    download_url: URIRef,
    metadata_issued: Literal,
    metadata_modified: Literal,
) -> Graph:
    """Build RDF metadata for the ontology.ttl distribution."""

    graph = Graph()
    bind_catalog_prefixes(graph)

    graph.add((distribution_uri, RDF.type, DCAT.Distribution))
    graph.add((distribution_uri, DCT.isPartOf, model_metadata.canonical_model_uri))
    graph.add((distribution_uri, DCT.issued, model_metadata.issued))
    graph.add((distribution_uri, DCAT.mediaType, IANA_TURTLE_MEDIA_TYPE))
    graph.add((distribution_uri, DCT.license, model_metadata.license))
    graph.add((
        distribution_uri,
        DCT.title,
        Literal(f"Turtle distribution of {str(model_metadata.title)}", lang="en"),
    ))
    graph.add((distribution_uri, DCAT.downloadURL, download_url))
    graph.add((distribution_uri, OCMV.isComplete, Literal(True, datatype=XSD.boolean)))
    graph.add((distribution_uri, FDPO.metadataIssued, metadata_issued))
    graph.add((distribution_uri, FDPO.metadataModified, metadata_modified))

    return graph


def ensure_model_metadata_distribution_link(
    metadata_graph: Graph,
    model_metadata: ModelMetadata,
    distribution_uri: URIRef,
) -> bool:
    """Add dcat:distribution link to model metadata graph when missing."""

    subjects_to_check = {model_metadata.model_uri, model_metadata.canonical_model_uri}
    for subject in subjects_to_check:
        if (subject, DCAT.distribution, distribution_uri) in metadata_graph:
            return False

    metadata_graph.add((model_metadata.canonical_model_uri, DCAT.distribution, distribution_uri))
    return True


def serialize_turtle(graph: Graph, output_path: Path) -> None:
    """Serialize a graph as Turtle, creating parent directories if needed."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(destination=output_path, format="turtle")


def generate_metadata_turtle(
    dataset_dir: Path,
    *,
    repo_root: Path,
    raw_base_url: str = DEFAULT_RAW_BASE_URL,
    output_name: str = "metadata-turtle.ttl",
    distribution_uri: Optional[str] = None,
    overwrite: bool = False,
    dry_run: bool = False,
    update_model_metadata: bool = False,
    reset_metadata_issued: bool = False,
) -> GenerationResult:
    """Generate metadata-turtle.ttl for one dataset folder."""

    dataset_dir = dataset_dir.resolve()
    if not dataset_dir.exists() or not dataset_dir.is_dir():
        raise CatalogMetadataError(f"Dataset folder does not exist or is not a directory: {dataset_dir}")

    # Parse ontology.ttl even though the metadata values come from metadata.ttl;
    # this catches missing or invalid Turtle distributions before generating
    # metadata that claims the distribution is available.
    validate_ontology_turtle(dataset_dir)
    model_graph, model_metadata = read_model_metadata(dataset_dir)

    output_path = dataset_dir / output_name
    if output_path.exists() and not overwrite and not dry_run:
        raise CatalogMetadataError(f"Output already exists. Use --overwrite to replace: {output_path}")

    existing_uri, existing_metadata_issued = read_existing_distribution_metadata(output_path)

    if distribution_uri is not None:
        dist_uri = URIRef(distribution_uri)
    elif existing_uri is not None:
        dist_uri = existing_uri
    else:
        dist_uri = make_distribution_uri(model_metadata)

    metadata_issued = now_utc_literal() if reset_metadata_issued else (existing_metadata_issued or now_utc_literal())
    metadata_modified = now_utc_literal()
    download_url, warnings = build_download_url(dataset_dir, repo_root, raw_base_url)

    graph = build_distribution_graph(
        model_metadata=model_metadata,
        distribution_uri=dist_uri,
        download_url=download_url,
        metadata_issued=metadata_issued,
        metadata_modified=metadata_modified,
    )

    # Basic self-validation for unresolved or inconsistent references.
    part_of_values = set(graph.objects(dist_uri, DCT.isPartOf))
    if model_metadata.canonical_model_uri not in part_of_values:
        raise CatalogMetadataError(
            f"Generated distribution {dist_uri} is not linked to model {model_metadata.canonical_model_uri}"
        )

    updated_model_metadata = False
    if update_model_metadata:
        updated_model_metadata = ensure_model_metadata_distribution_link(model_graph, model_metadata, dist_uri)
        bind_catalog_prefixes(model_graph)

    result = GenerationResult(
        dataset_dir=dataset_dir,
        output_path=output_path,
        distribution_uri=dist_uri,
        warnings=warnings,
        wrote_file=False,
        updated_model_metadata=updated_model_metadata,
    )

    if dry_run:
        return result

    serialize_turtle(graph, output_path)
    result.wrote_file = True

    if update_model_metadata and updated_model_metadata:
        serialize_turtle(model_graph, dataset_dir / "metadata.ttl")

    return result


def iter_dataset_dirs(paths: Iterable[Path], *, recursive: bool) -> Iterator[Path]:
    """Yield dataset folders from user-supplied files or directories."""

    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        candidates: list[Path] = []
        if resolved.is_file() and resolved.name == "ontology.ttl":
            candidates = [resolved.parent]
        elif resolved.is_dir() and (resolved / "ontology.ttl").is_file():
            candidates = [resolved]
        elif resolved.is_dir() and recursive:
            candidates = sorted({p.parent for p in resolved.rglob("ontology.ttl")})
        else:
            raise CatalogMetadataError(
                f"Path is not a dataset folder containing ontology.ttl. Use --recursive for parent folders: {path}"
            )

        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                yield candidate


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""

    parser = argparse.ArgumentParser(
        description="Generate metadata-turtle.ttl for OntoUML/UFO Catalog dataset folders."
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Dataset folder(s), ontology.ttl file(s), or parent folders when --recursive is used.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Search recursively for dataset folders containing ontology.ttl.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root used to compute raw GitHub download URLs. Defaults to the current directory.",
    )
    parser.add_argument(
        "--raw-base-url",
        default=DEFAULT_RAW_BASE_URL,
        help=f"Raw-file URL base. Default: {DEFAULT_RAW_BASE_URL}",
    )
    parser.add_argument(
        "--output-name",
        default="metadata-turtle.ttl",
        help="Output filename inside each dataset folder. Default: metadata-turtle.ttl",
    )
    parser.add_argument(
        "--distribution-uri",
        help="Explicit distribution URI. Only valid when processing exactly one dataset folder.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing metadata-turtle.ttl files. Existing distribution URI and metadataIssued are preserved.",
    )
    parser.add_argument(
        "--reset-metadata-issued",
        action="store_true",
        help="Reset fdpo:metadataIssued instead of preserving it from an existing output file.",
    )
    parser.add_argument(
        "--update-model-metadata",
        action="store_true",
        help="Also add the generated dcat:distribution link to metadata.ttl when it is missing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and report planned outputs without writing files.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Command-line entry point."""

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        dataset_dirs = list(iter_dataset_dirs(args.paths, recursive=args.recursive))
        if args.distribution_uri and len(dataset_dirs) != 1:
            raise CatalogMetadataError("--distribution-uri can only be used with exactly one dataset folder")

        results: list[GenerationResult] = []
        for dataset_dir in dataset_dirs:
            result = generate_metadata_turtle(
                dataset_dir,
                repo_root=args.repo_root,
                raw_base_url=args.raw_base_url,
                output_name=args.output_name,
                distribution_uri=args.distribution_uri,
                overwrite=args.overwrite,
                dry_run=args.dry_run,
                update_model_metadata=args.update_model_metadata,
                reset_metadata_issued=args.reset_metadata_issued,
            )
            if args.strict and result.warnings:
                raise CatalogMetadataError("; ".join(result.warnings))
            results.append(result)

    except CatalogMetadataError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for result in results:
        action = "would write" if args.dry_run else "wrote"
        print(f"{action}: {result.output_path}")
        print(f"  distribution: {result.distribution_uri}")
        if result.updated_model_metadata:
            print(f"  updated: {result.dataset_dir / 'metadata.ttl'}")
        for warning in result.warnings:
            print(f"  WARNING: {warning}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

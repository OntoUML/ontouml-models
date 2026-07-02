"""Generate an OntoUML/UFO Catalog release Turtle file.

This script reconstructs the historical release-generation behavior from
OntoUML/ontouml-models-tools: it aggregates catalog Turtle files into a single
release file named ``ontouml-models-YYYYMMDD.ttl``.

Run from the repository root, for example:

    python scripts/generate_release_file.py . --release-tag 20260702
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from rdflib import Graph


RELEASE_TAG_PATTERN = re.compile(r"^\d{8}$")


class ReleaseGenerationError(RuntimeError):
    """Raised when release generation should stop with a clear message."""


@dataclass(frozen=True)
class ReleaseConfig:
    """Configuration for release-file generation."""

    catalog_path: Path
    output_dir: Path
    release_tag: str
    list_files: bool = False


def default_release_tag() -> str:
    """Return the default release tag using the current UTC date."""

    return datetime.now(timezone.utc).strftime("%Y%m%d")


def validate_release_tag(release_tag: str) -> str:
    """Validate and return a release tag in the documented YYYYMMDD format."""

    normalized = release_tag.strip()
    if not RELEASE_TAG_PATTERN.fullmatch(normalized):
        raise ReleaseGenerationError(
            f"Release tag must use the documented YYYYMMDD format; got: {release_tag!r}"
        )
    try:
        datetime.strptime(normalized, "%Y%m%d")
    except ValueError as exc:
        raise ReleaseGenerationError(
            f"Release tag must be a valid calendar date in YYYYMMDD format; got: {release_tag!r}"
        ) from exc
    return normalized


def repository_relative_path(path: Path, root: Path) -> str:
    """Return a POSIX repository-relative path for display and sorting."""

    return path.resolve().relative_to(root.resolve()).as_posix()


def should_include_ttl_file(path: Path, catalog_path: Path) -> bool:
    """Return whether a Turtle file should be part of the catalog release.

    The historical tool included all catalog .ttl files except shape files and
    intended to exclude vocabulary.ttl. This implementation keeps that behavior
    while also excluding generated release outputs if a local results directory
    already exists.
    """

    relative = repository_relative_path(path, catalog_path)
    relative_parts = Path(relative).parts

    if any(part.startswith(".") for part in relative_parts):
        return False
    if relative.startswith("shapes/"):
        return False
    if path.name.endswith("-shape.ttl"):
        return False
    if path.name == "vocabulary.ttl":
        return False
    if relative.startswith("results/"):
        return False
    if path.name == "catalog-release.ttl":
        return False
    if path.name.startswith("ontouml-models-") and path.name.endswith(".ttl"):
        return False

    return True


def list_release_ttl_files(catalog_path: Path) -> list[Path]:
    """List Turtle files included in the release, sorted deterministically."""

    catalog_path = catalog_path.resolve()
    files = [
        path
        for path in catalog_path.rglob("*.ttl")
        if path.is_file() and should_include_ttl_file(path, catalog_path)
    ]
    return sorted(files, key=lambda path: repository_relative_path(path, catalog_path))


def bind_release_prefixes(graph: Graph) -> None:
    """Bind the prefixes used by the historical release-generation tool."""

    graph.bind("ontouml", "https://w3id.org/ontouml#")
    graph.bind("dcat", "http://www.w3.org/ns/dcat#")
    graph.bind("dct", "http://purl.org/dc/terms/")
    graph.bind("ocmv", "https://w3id.org/ontouml-models/vocabulary#")
    graph.bind("skos", "http://www.w3.org/2004/02/skos/core#")
    graph.bind("mod", "https://w3id.org/mod#")
    graph.bind("vcard", "http://www.w3.org/2006/vcard/ns#")
    graph.bind("vann", "http://purl.org/vocab/vann/")


def generate_release_file(config: ReleaseConfig) -> Path:
    """Generate and return the release Turtle file path."""

    catalog_path = config.catalog_path.resolve()
    if not catalog_path.exists():
        raise ReleaseGenerationError(f"Catalog path does not exist: {catalog_path}")
    if not catalog_path.is_dir():
        raise ReleaseGenerationError(f"Catalog path is not a directory: {catalog_path}")
    if not (catalog_path / "models").is_dir():
        raise ReleaseGenerationError(
            f"Catalog path must contain a models/ directory: {catalog_path}"
        )

    release_tag = validate_release_tag(config.release_tag)
    ttl_files = list_release_ttl_files(catalog_path)
    if not ttl_files:
        raise ReleaseGenerationError(
            f"No Turtle files found for release generation under: {catalog_path}"
        )

    if config.list_files:
        print("Included Turtle files:")
        for ttl_file in ttl_files:
            print(f"- {repository_relative_path(ttl_file, catalog_path)}")

    aggregated_graph = Graph()
    for ttl_file in ttl_files:
        try:
            aggregated_graph.parse(ttl_file, format="turtle")
        except Exception as exc:  # noqa: BLE001 - RDFLib raises several exception types
            relative = repository_relative_path(ttl_file, catalog_path)
            raise ReleaseGenerationError(
                f"Could not parse Turtle file {relative}: {exc}"
            ) from exc

    bind_release_prefixes(aggregated_graph)

    output_dir = config.output_dir
    if not output_dir.is_absolute():
        output_dir = catalog_path / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / f"ontouml-models-{release_tag}.ttl"
    try:
        aggregated_graph.serialize(destination=output_file, format="turtle")
    except OSError as exc:
        raise ReleaseGenerationError(
            f"Could not write release file {output_file}: {exc}"
        ) from exc

    print(f"Release file generated: {output_file}")
    print(f"Included Turtle files: {len(ttl_files)}")
    print(f"Aggregated triples: {len(aggregated_graph)}")

    return output_file


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""

    parser = argparse.ArgumentParser(
        description="Generate a single Turtle release file for the OntoUML/UFO Catalog."
    )
    parser.add_argument(
        "catalog_path",
        nargs="?",
        default=".",
        help="Path to the ontouml-models repository checkout. Default: current directory.",
    )
    parser.add_argument(
        "--release-tag",
        default=default_release_tag(),
        help="Release tag in YYYYMMDD format. Default: current UTC date.",
    )
    parser.add_argument(
        "--output-dir",
        default="results",
        help="Directory where the release file is written. Default: results.",
    )
    parser.add_argument(
        "--list-files",
        action="store_true",
        help="Print the Turtle files included in the release.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the release-file generator."""

    parser = build_parser()
    args = parser.parse_args(argv)

    config = ReleaseConfig(
        catalog_path=Path(args.catalog_path),
        output_dir=Path(args.output_dir),
        release_tag=args.release_tag,
        list_files=args.list_files,
    )

    try:
        generate_release_file(config)
    except ReleaseGenerationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

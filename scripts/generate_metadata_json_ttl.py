#!/usr/bin/env python3
"""Generate metadata-json.ttl files from mandatory metadata.yaml files.

Examples:
    # Generate for one dataset folder
    python scripts/generate_metadata_json_ttl.py models/amaral2019rot

    # Generate for every dataset folder under models/ that contains metadata.yaml
    python scripts/generate_metadata_json_ttl.py --models-dir models --all
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running this script directly from a repository checkout without installing
# the helper package first.
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if SRC_DIR.is_dir() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ontouml_models_automation.metadata_json import (  # noqa: E402
    MetadataJsonConfig,
    MetadataJsonError,
    find_dataset_folders,
    generate_metadata_json_ttl,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate OntoUML/UFO Catalog metadata-json.ttl files from metadata.yaml."
    )
    parser.add_argument(
        "dataset_folders",
        nargs="*",
        type=Path,
        help="Dataset/model folders containing metadata.yaml. Ignored when --all is used.",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=Path("models"),
        help="Models directory used with --all. Default: models",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process every direct child of --models-dir that contains metadata.yaml.",
    )
    parser.add_argument(
        "--repository",
        default="OntoUML/ontouml-models",
        help="Repository used to build default raw ontology.json download URLs. Default: OntoUML/ontouml-models",
    )
    parser.add_argument(
        "--branch",
        default="master",
        help="Branch used to build default raw ontology.json download URLs. Default: master",
    )
    parser.add_argument(
        "--metadata-timestamp",
        help="Timestamp for fdpo:metadataIssued and fdpo:metadataModified when absent in YAML. Use ISO 8601.",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Fail if metadata-json.ttl already exists.",
    )
    parser.add_argument(
        "--no-check-ontology-json",
        action="store_true",
        help="Do not require ontology.json to exist before generating metadata-json.ttl.",
    )
    parser.add_argument(
        "--generate-missing-distribution-id",
        action="store_true",
        help=(
            "Generate a deterministic UUID5 for distributions.json.id when it is missing. "
            "Use cautiously; explicit persistent distribution IDs are preferred."
        ),
    )
    return parser.parse_args(argv)


def parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise MetadataJsonError(
            f"Invalid --metadata-timestamp value {value!r}. Use ISO 8601, e.g., 2025-01-01T00:00:00Z."
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        if args.all:
            dataset_folders = find_dataset_folders(args.models_dir)
        else:
            dataset_folders = args.dataset_folders
    except MetadataJsonError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not dataset_folders:
        print(
            "No dataset folders provided. Pass one or more folders or use --all --models-dir models.",
            file=sys.stderr,
        )
        return 2

    try:
        metadata_timestamp = parse_timestamp(args.metadata_timestamp)
    except MetadataJsonError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    config = MetadataJsonConfig(
        repository=args.repository,
        branch=args.branch,
        metadata_timestamp=metadata_timestamp,
        overwrite=not args.no_overwrite,
        check_ontology_json=not args.no_check_ontology_json,
        generate_missing_distribution_id=args.generate_missing_distribution_id,
    )

    failures = 0
    for folder in dataset_folders:
        try:
            output = generate_metadata_json_ttl(folder, config)
            print(f"Generated {output}")
        except MetadataJsonError as exc:
            failures += 1
            print(f"ERROR: {folder}: {exc}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate mandatory file presence in OntoUML/UFO Catalog dataset folders.

This validator intentionally checks only file availability. It does not parse,
validate, or interpret ontology.vpp, ontology.json, metadata.yaml, or diagram
image contents.

Usage examples, from the repository root:

    python tools/validate_dataset_files.py models/example-model
    python tools/validate_dataset_files.py models/model-a models/model-b
    python tools/validate_dataset_files.py --models-dir models
    python tools/validate_dataset_files.py --models-dir models --format json

Exit codes:
    0: all checked dataset folders are valid
    1: at least one checked dataset folder is invalid
    2: command-line usage or input path error
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

REQUIRED_FILES: tuple[str, ...] = (
    "ontology.vpp",
    "ontology.json",
    "metadata.yaml",
)

DIAGRAM_DIRECTORIES: tuple[str, ...] = (
    "new-diagrams",
    "original-diagrams",
)

DIAGRAM_GLOB_REQUIREMENTS: tuple[str, ...] = tuple(
    f"{directory}/*.png" for directory in DIAGRAM_DIRECTORIES
)


@dataclass(frozen=True)
class DatasetValidationResult:
    """File-presence validation result for one dataset folder."""

    dataset_path: str
    valid: bool
    missing_files: list[str]
    missing_diagram_pngs: list[str]
    present_diagram_pngs: list[str]

    @property
    def missing_required_files(self) -> bool:
        """Return whether any mandatory non-diagram file is missing."""
        return bool(self.missing_files)

    @property
    def missing_required_diagrams(self) -> bool:
        """Return whether the mandatory diagram availability rule failed."""
        return bool(self.missing_diagram_pngs)


def _relative_to_dataset(path: Path, dataset_path: Path) -> str:
    """Return a stable, POSIX-style path relative to the dataset folder."""
    return path.relative_to(dataset_path).as_posix()


def find_diagram_pngs(dataset_path: Path) -> list[str]:
    """Find direct child .png files under the allowed diagram directories.

    The check is intentionally limited to lower-case ``.png`` files directly
    contained in ``new-diagrams/`` or ``original-diagrams/``. It does not scan
    recursively and does not treat ``.PNG`` as equivalent to ``.png``.
    """
    pngs: list[str] = []

    for directory_name in DIAGRAM_DIRECTORIES:
        directory = dataset_path / directory_name
        if not directory.is_dir():
            continue

        for child in sorted(directory.iterdir()):
            if child.is_file() and child.name.endswith(".png"):
                pngs.append(_relative_to_dataset(child, dataset_path))

    return pngs


def validate_dataset_folder(dataset_path: Path | str) -> DatasetValidationResult:
    """Validate one dataset folder for mandatory file presence.

    Parameters
    ----------
    dataset_path:
        Path to a dataset/model folder, normally a direct child of ``models/``.

    Returns
    -------
    DatasetValidationResult
        The result contains separate fields for missing mandatory files and for
        missing diagram PNG availability.
    """
    path = Path(dataset_path)

    missing_files = [
        filename for filename in REQUIRED_FILES if not (path / filename).is_file()
    ]

    present_diagram_pngs = find_diagram_pngs(path)
    missing_diagram_pngs = [] if present_diagram_pngs else list(DIAGRAM_GLOB_REQUIREMENTS)

    return DatasetValidationResult(
        dataset_path=path.as_posix(),
        valid=not missing_files and not missing_diagram_pngs,
        missing_files=missing_files,
        missing_diagram_pngs=missing_diagram_pngs,
        present_diagram_pngs=present_diagram_pngs,
    )


def validate_dataset_folders(
    dataset_paths: Iterable[Path | str],
) -> list[DatasetValidationResult]:
    """Validate multiple dataset folders."""
    return [validate_dataset_folder(path) for path in dataset_paths]


def discover_dataset_folders(models_dir: Path | str) -> list[Path]:
    """Return direct child directories of a models directory, sorted by name."""
    path = Path(models_dir)
    return sorted(child for child in path.iterdir() if child.is_dir())


def build_summary(results: Sequence[DatasetValidationResult]) -> dict[str, object]:
    """Build a machine-readable validation summary."""
    invalid_count = sum(1 for result in results if not result.valid)
    return {
        "valid": invalid_count == 0,
        "total": len(results),
        "valid_count": len(results) - invalid_count,
        "invalid_count": invalid_count,
        "required_files": list(REQUIRED_FILES),
        "required_diagram_pngs": list(DIAGRAM_GLOB_REQUIREMENTS),
        "results": [asdict(result) for result in results],
    }


def format_text_report(results: Sequence[DatasetValidationResult]) -> str:
    """Render validation results as a human-readable text report."""
    summary = build_summary(results)
    lines: list[str] = [
        "Dataset mandatory file validation",
        "=================================",
        f"Datasets checked: {summary['total']}",
        f"Valid datasets:    {summary['valid_count']}",
        f"Invalid datasets:  {summary['invalid_count']}",
        "",
        "Required files:",
    ]

    lines.extend(f"  - {filename}" for filename in REQUIRED_FILES)
    lines.append("Required diagram availability:")
    lines.append("  - at least one .png file in new-diagrams/ or original-diagrams/")
    lines.append("")

    for result in results:
        status = "VALID" if result.valid else "INVALID"
        lines.append(f"[{status}] {result.dataset_path}")

        if result.missing_files:
            lines.append("  Missing required files:")
            lines.extend(f"    - {filename}" for filename in result.missing_files)
        else:
            lines.append("  Missing required files: none")

        if result.missing_diagram_pngs:
            lines.append("  Missing diagram PNG availability:")
            lines.extend(f"    - {pattern}" for pattern in result.missing_diagram_pngs)
        else:
            lines.append("  Missing diagram PNG availability: none")
            lines.append("  Diagram PNGs found:")
            lines.extend(f"    - {filename}" for filename in result.present_diagram_pngs)

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Check mandatory file presence in OntoUML/UFO Catalog dataset "
            "folders. This validates file availability only, not file content."
        )
    )
    parser.add_argument(
        "dataset_paths",
        nargs="*",
        type=Path,
        help="One or more dataset/model folders to validate.",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        help=(
            "Validate all direct child directories of this models directory. "
            "Common value: models"
        ),
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format. Default: text.",
    )
    return parser.parse_args(argv)


def collect_targets(args: argparse.Namespace) -> tuple[list[Path], list[str]]:
    """Collect dataset folders from positional paths and/or --models-dir."""
    targets: list[Path] = []
    errors: list[str] = []

    if args.models_dir is not None:
        if not args.models_dir.exists():
            errors.append(f"models directory does not exist: {args.models_dir}")
        elif not args.models_dir.is_dir():
            errors.append(f"models path is not a directory: {args.models_dir}")
        else:
            targets.extend(discover_dataset_folders(args.models_dir))

    targets.extend(args.dataset_paths)

    if not targets and args.models_dir is None:
        default_models_dir = Path("models")
        if default_models_dir.is_dir():
            targets.extend(discover_dataset_folders(default_models_dir))
        else:
            errors.append(
                "no dataset folders provided and default models/ directory was not found"
            )

    # De-duplicate while preserving order.
    unique_targets: list[Path] = []
    seen: set[str] = set()
    for target in targets:
        key = target.resolve().as_posix() if target.exists() else target.as_posix()
        if key not in seen:
            unique_targets.append(target)
            seen.add(key)

    for target in unique_targets:
        if not target.exists():
            errors.append(f"dataset folder does not exist: {target}")
        elif not target.is_dir():
            errors.append(f"dataset path is not a directory: {target}")

    return unique_targets, errors


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line validator."""
    args = parse_args(argv)
    targets, errors = collect_targets(args)

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 2

    results = validate_dataset_folders(targets)

    if args.format == "json":
        print(json.dumps(build_summary(results), indent=2, sort_keys=True))
    else:
        print(format_text_report(results), end="")

    return 0 if all(result.valid for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Process a new OntoUML/UFO Catalog model submission.

This script orchestrates the repository's existing metadata, bibliography, and
generation tools for a single model folder. It intentionally delegates metadata
and BibTeX/BibLaTeX semantics to those tools and only adds workflow-level
safeguards:

- source-file preflight checks for a new model submission;
- same-repository pull request model-folder detection;
- deterministic command ordering, including optional references.bib validation;
- final Turtle/RDF parse validation;
- narrow, model-folder-scoped processing.

Run from the repository root, for example:

    python scripts/process_new_model_submission.py models/example \
      --metadata-timestamp 2026-06-24T12:00:00Z

Use ``--dry-run`` to validate inputs and exercise the existing generators without
writing generated metadata files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

try:
    from rdflib import Graph
except ImportError as exc:  # pragma: no cover - dependency failure only
    raise SystemExit(
        "RDFLib is required. Install it with: python -m pip install -r scripts/requirements.txt"
    ) from exc


REQUIRED_SOURCE_FILES = (
    "metadata.yaml",
    "ontology.json",
    "ontology.ttl",
    "ontology.vpp",
)
OPTIONAL_SOURCE_FILES = ("references.bib",)
ACCEPTED_IMAGE_FOLDERS = ("original-diagrams", "new-diagrams")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class SubmissionProcessingError(RuntimeError):
    """Raised when submission processing should stop with a clear message."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class CommandStep:
    """A named subprocess command to execute from the repository root."""

    name: str
    command: tuple[str, ...]


def repository_root(start: Optional[Path] = None) -> Path:
    """Return the repository root inferred from ``start`` or the current directory."""

    current = (start or Path.cwd()).resolve()
    candidates = (current, *current.parents)
    for candidate in candidates:
        if (candidate / "scripts").is_dir() and (candidate / "models").is_dir():
            return candidate
    raise SubmissionProcessingError(
        "Could not determine the repository root. Run this command from inside the repository.",
        exit_code=2,
    )


def path_for_display(path: Path, root: Path) -> str:
    """Return a readable repository-relative path when possible."""

    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def resolve_model_folder(raw_path: str, root: Path, models_dir: str = "models") -> Path:
    """Resolve and validate the target model folder.

    Catalog model folders are expected to be direct children of ``models/``. This
    keeps the workflow narrowly scoped and prevents accidental processing outside
    the catalog dataset tree.
    """

    if not raw_path or not raw_path.strip():
        raise SubmissionProcessingError("A model folder path is required.", exit_code=2)

    raw = Path(raw_path.strip())
    candidate = raw if raw.is_absolute() else root / raw
    model_folder = candidate.resolve()
    models_root = (root / models_dir).resolve()

    try:
        relative = model_folder.relative_to(models_root)
    except ValueError as exc:
        raise SubmissionProcessingError(
            f"Model folder must be inside {models_root}: {model_folder}",
            exit_code=2,
        ) from exc

    if len(relative.parts) != 1:
        raise SubmissionProcessingError(
            "Model folder must be a direct child of the models directory, "
            f"for example models/example-model; got {path_for_display(model_folder, root)}.",
            exit_code=2,
        )

    if not model_folder.exists():
        raise SubmissionProcessingError(
            f"Model folder does not exist: {path_for_display(model_folder, root)}",
            exit_code=2,
        )
    if not model_folder.is_dir():
        raise SubmissionProcessingError(
            f"Model path is not a directory: {path_for_display(model_folder, root)}",
            exit_code=2,
        )

    return model_folder


def require_regular_file(path: Path, label: str, root: Path) -> None:
    """Require ``path`` to exist as a regular file."""

    if not path.exists():
        raise SubmissionProcessingError(
            f"Missing required {label}: {path_for_display(path, root)}"
        )
    if not path.is_file():
        raise SubmissionProcessingError(
            f"{label} path is not a file: {path_for_display(path, root)}"
        )


def validate_ontology_json(path: Path, root: Path) -> None:
    """Parse ontology.json as UTF-8 JSON and require a top-level object."""

    require_regular_file(path, "ontology.json", root)
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
    except UnicodeDecodeError as exc:
        raise SubmissionProcessingError(
            f"ontology.json is not valid UTF-8 JSON text: {path_for_display(path, root)}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise SubmissionProcessingError(
            f"ontology.json is not valid JSON: {path_for_display(path, root)}: {exc}"
        ) from exc
    except OSError as exc:
        raise SubmissionProcessingError(
            f"Could not read ontology.json: {path_for_display(path, root)}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise SubmissionProcessingError(
            f"ontology.json must contain a JSON object at the top level: {path_for_display(path, root)}"
        )


def validate_turtle_file(path: Path, root: Path, label: str) -> None:
    """Parse a Turtle file with RDFLib."""

    require_regular_file(path, label, root)
    graph = Graph()
    try:
        graph.parse(path, format="turtle")
    except Exception as exc:  # noqa: BLE001 - RDFLib raises several exception types
        raise SubmissionProcessingError(
            f"{label} is not valid Turtle/RDF: {path_for_display(path, root)}: {exc}"
        ) from exc


def validate_vpp_source(path: Path, root: Path) -> None:
    """Validate the required Visual Paradigm project source at file level."""

    require_regular_file(path, "ontology.vpp", root)
    if CONTROL_CHARS.search(path.name):
        raise SubmissionProcessingError(
            f"ontology.vpp filename contains control characters: {path_for_display(path, root)}"
        )
    try:
        if path.stat().st_size <= 0:
            raise SubmissionProcessingError(
                f"ontology.vpp is empty: {path_for_display(path, root)}"
            )
    except OSError as exc:
        raise SubmissionProcessingError(
            f"Could not inspect ontology.vpp: {path_for_display(path, root)}: {exc}"
        ) from exc


def discover_png_diagrams(model_folder: Path) -> list[Path]:
    """Return PNG diagrams found directly in the accepted image folders."""

    diagrams: list[Path] = []
    for folder_name in ACCEPTED_IMAGE_FOLDERS:
        folder = model_folder / folder_name
        if folder.is_dir():
            diagrams.extend(
                sorted(path for path in folder.glob("*.png") if path.is_file())
            )
    return sorted(diagrams)


def validate_png_file(path: Path, root: Path) -> None:
    """Perform a lightweight PNG signature and IHDR preflight check."""

    if CONTROL_CHARS.search(path.name):
        raise SubmissionProcessingError(
            f"PNG filename contains control characters: {path_for_display(path, root)}"
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise SubmissionProcessingError(
            f"Could not read PNG diagram: {path_for_display(path, root)}: {exc}"
        ) from exc

    if not data.startswith(PNG_SIGNATURE):
        raise SubmissionProcessingError(
            f"Diagram is not a PNG file: {path_for_display(path, root)}"
        )
    if len(data) < 24 or data[12:16] != b"IHDR":
        raise SubmissionProcessingError(
            f"PNG diagram is missing a valid IHDR header: {path_for_display(path, root)}"
        )


def validate_optional_references_bib_path(path: Path, root: Path) -> None:
    """Validate only the optional references.bib path shape before orchestration.

    Full basic BibTeX/BibLaTeX validation is delegated to
    scripts/validate_references_bib.py in the command sequence. This keeps this
    helper as an orchestrator instead of duplicating bibliography-validation
    logic.
    """

    if path.exists() and not path.is_file():
        raise SubmissionProcessingError(
            f"references.bib path is not a file: {path_for_display(path, root)}"
        )


def validate_required_sources(model_folder: Path, root: Path) -> list[Path]:
    """Validate source files expected from a new model submission."""

    for file_name in REQUIRED_SOURCE_FILES:
        require_regular_file(model_folder / file_name, file_name, root)

    validate_ontology_json(model_folder / "ontology.json", root)
    validate_turtle_file(model_folder / "ontology.ttl", root, "ontology.ttl")
    validate_vpp_source(model_folder / "ontology.vpp", root)

    diagrams = discover_png_diagrams(model_folder)
    if not diagrams:
        folders = ", ".join(ACCEPTED_IMAGE_FOLDERS)
        raise SubmissionProcessingError(
            f"At least one .png diagram is required in one of: {folders}."
        )
    for diagram in diagrams:
        validate_png_file(diagram, root)

    validate_optional_references_bib_path(model_folder / "references.bib", root)
    return diagrams


def expected_png_metadata_paths(
    diagrams: Iterable[Path], model_folder: Path
) -> list[Path]:
    """Return the metadata-png-*.ttl paths expected for the discovered diagrams."""

    paths: list[Path] = []
    for diagram in diagrams:
        source_folder = diagram.parent.name
        if source_folder == "original-diagrams":
            prefix = "o"
        elif source_folder == "new-diagrams":
            prefix = "n"
        else:  # pragma: no cover - discover_png_diagrams limits this
            continue
        paths.append(model_folder / f"metadata-png-{prefix}-{diagram.stem}.ttl")
    return sorted(paths)


def expected_generated_metadata_paths(
    model_folder: Path, diagrams: Iterable[Path]
) -> list[Path]:
    """Return metadata files expected after a successful non-dry-run execution."""

    paths = [
        model_folder / "metadata-json.ttl",
        model_folder / "metadata-turtle.ttl",
        model_folder / "metadata-vpp.ttl",
        model_folder / "metadata.ttl",
    ]
    paths.extend(expected_png_metadata_paths(diagrams, model_folder))
    return sorted(paths)


def ensure_expected_outputs_exist(paths: Iterable[Path], root: Path) -> None:
    """Fail when an expected generated metadata file is absent."""

    missing = [path for path in paths if not path.exists()]
    if missing:
        joined = "\n".join(f"- {path_for_display(path, root)}" for path in missing)
        raise SubmissionProcessingError(
            "Expected generated metadata file(s) were not created:\n" + joined
        )


def validate_all_turtle_files(model_folder: Path, root: Path) -> None:
    """Parse every Turtle file in the model folder after generation."""

    ttl_paths = sorted(model_folder.glob("*.ttl"))
    if not ttl_paths:
        raise SubmissionProcessingError(
            f"No Turtle files were found in {path_for_display(model_folder, root)} after generation."
        )

    for ttl_path in ttl_paths:
        validate_turtle_file(ttl_path, root, ttl_path.name)


def add_common_generation_flags(
    command: list[str],
    *,
    repository: str,
    branch: str,
    models_dir_name: str,
    metadata_timestamp: str,
    allow_missing_license: bool,
    dry_run: bool,
) -> list[str]:
    """Add CLI flags common to distribution metadata generators."""

    command.extend(
        [
            "--repository",
            repository,
            "--branch",
            branch,
            "--models-dir-name",
            models_dir_name,
            "--metadata-timestamp",
            metadata_timestamp,
        ]
    )
    if allow_missing_license:
        command.append("--allow-missing-license")
    if dry_run:
        command.append("--dry-run")
    return command


def build_steps(
    args: argparse.Namespace, root: Path, model_folder: Path
) -> list[CommandStep]:
    """Build the ordered command sequence for existing repository tools."""

    python = sys.executable
    model_arg = model_folder.relative_to(root).as_posix()
    models_dir_arg = Path(args.models_dir).as_posix().strip("/") or "models"
    steps: list[CommandStep] = []

    validate_command = [
        python,
        "scripts/validate_metadata_yaml.py",
        model_arg,
    ]
    if not args.no_fix_metadata_yaml:
        validate_command.append("--fix")
        if args.dry_run:
            validate_command.append("--dry-run")
    if args.allow_missing_license:
        validate_command.append("--allow-missing-license")
    steps.append(CommandStep("Validate/fix metadata.yaml", tuple(validate_command)))

    steps.append(
        CommandStep(
            "Validate optional references.bib",
            (
                python,
                "scripts/validate_references_bib.py",
                model_arg,
            ),
        )
    )

    common = {
        "repository": args.repository,
        "branch": args.branch,
        "models_dir_name": models_dir_arg,
        "metadata_timestamp": args.metadata_timestamp,
        "allow_missing_license": args.allow_missing_license,
        "dry_run": args.dry_run,
    }

    steps.append(
        CommandStep(
            "Generate PNG distribution metadata",
            tuple(
                add_common_generation_flags(
                    [python, "scripts/generate_png_metadata.py", model_arg],
                    **common,
                )
            ),
        )
    )

    json_command = add_common_generation_flags(
        [python, "scripts/generate_json_metadata.py", model_arg],
        **common,
    )
    if not args.no_validate_ontology_json:
        json_command.append("--validate-ontology-json")
    steps.append(
        CommandStep("Generate JSON distribution metadata", tuple(json_command))
    )

    steps.append(
        CommandStep(
            "Generate Turtle distribution metadata",
            tuple(
                add_common_generation_flags(
                    [python, "scripts/generate_turtle_metadata.py", model_arg],
                    **common,
                )
            ),
        )
    )

    steps.append(
        CommandStep(
            "Generate VPP distribution metadata",
            tuple(
                add_common_generation_flags(
                    [python, "scripts/generate_vpp_metadata.py", model_arg],
                    **common,
                )
            ),
        )
    )

    model_metadata_command = [
        python,
        "scripts/metadata_yaml_to_ttl.py",
        model_arg,
        "--repository",
        args.repository,
        "--branch",
        args.branch,
        "--models-dir",
        models_dir_arg,
        "--metadata-timestamp",
        args.metadata_timestamp,
    ]
    if args.allow_missing_license:
        model_metadata_command.append("--allow-missing-license")
    if args.dry_run:
        model_metadata_command.append("--dry-run")
    steps.append(
        CommandStep("Generate model-level metadata.ttl", tuple(model_metadata_command))
    )

    return steps


def github_group_start(name: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::group::{name}")


def github_group_end() -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print("::endgroup::")


def run_step(step: CommandStep, root: Path) -> None:
    """Run one command step and surface readable failure information."""

    print(f"\n==> {step.name}")
    print("+ " + " ".join(step.command))
    github_group_start(step.name)
    try:
        completed = subprocess.run(step.command, cwd=root, check=False)
    finally:
        github_group_end()

    if completed.returncode != 0:
        raise SubmissionProcessingError(
            f"Step failed with exit code {completed.returncode}: {step.name}"
        )


def normalize_changed_path(path_text: str) -> str:
    """Normalize a Git path for repository-relative checks."""

    return path_text.strip().replace("\\", "/").strip("/")


def detect_model_folder_from_changed_files(
    changed_files: Iterable[str], *, models_dir: str = "models"
) -> str:
    """Return the unique model folder affected by a model-submission PR.

    The first automatic phase intentionally supports only one model folder and no
    files outside that folder. Generated metadata files inside the same folder are
    allowed because the workflow may commit them back to the PR branch.
    """

    normalized_files = [
        normalize_changed_path(path)
        for path in changed_files
        if normalize_changed_path(path)
    ]
    if not normalized_files:
        raise SubmissionProcessingError("No changed files were detected.", exit_code=2)

    models_prefix = models_dir.strip("/") + "/"
    model_folders: set[str] = set()
    outside_files: list[str] = []
    invalid_model_paths: list[str] = []

    for path in normalized_files:
        if not path.startswith(models_prefix):
            outside_files.append(path)
            continue
        parts = path.split("/")
        if len(parts) < 3:
            invalid_model_paths.append(path)
            continue
        model_folders.add("/".join(parts[:2]))

    if outside_files:
        joined = "\n".join(f"- {path}" for path in outside_files)
        raise SubmissionProcessingError(
            "Model-submission PRs must not change files outside the target model folder.\n"
            + joined
        )
    if invalid_model_paths:
        joined = "\n".join(f"- {path}" for path in invalid_model_paths)
        raise SubmissionProcessingError(
            "Changed model paths must be inside a direct model folder, such as models/example-model/.\n"
            + joined
        )
    if len(model_folders) != 1:
        joined = ", ".join(sorted(model_folders)) or "none"
        raise SubmissionProcessingError(
            "Exactly one model folder must be changed by this workflow; detected: "
            + joined
        )

    return next(iter(model_folders))


def changed_files_between_refs(base_ref: str, head_ref: str, root: Path) -> list[str]:
    """Return files changed between two Git refs."""

    if not base_ref or not head_ref:
        raise SubmissionProcessingError(
            "Both base and head refs are required for changed-file detection.",
            exit_code=2,
        )
    completed = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...{head_ref}"],
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise SubmissionProcessingError(
            "Could not detect changed files with git diff: " + completed.stderr.strip(),
            exit_code=2,
        )
    return [line for line in completed.stdout.splitlines() if line.strip()]


def detect_model_folder_from_git(base_ref: str, head_ref: str, models_dir: str) -> str:
    """Detect the unique changed model folder from a Git diff."""

    root = repository_root()
    changed_files = changed_files_between_refs(base_ref, head_ref, root)
    return detect_model_folder_from_changed_files(changed_files, models_dir=models_dir)


def process_submission(args: argparse.Namespace) -> int:
    """Run the complete submission processing pipeline."""

    root = repository_root()
    model_folder = resolve_model_folder(args.model_folder, root, args.models_dir)
    print(f"Repository root: {root}")
    print(f"Target model folder: {path_for_display(model_folder, root)}")

    steps = build_steps(args, root, model_folder)
    metadata_yaml_step = steps[0]
    if metadata_yaml_step.name != "Validate/fix metadata.yaml":
        raise SubmissionProcessingError(
            "Internal workflow ordering error: metadata.yaml validation must be the first step.",
            exit_code=2,
        )
    run_step(metadata_yaml_step, root)

    print("\n==> Validate required source files")
    diagrams = validate_required_sources(model_folder, root)
    print(f"Found {len(diagrams)} PNG diagram(s).")

    for step in steps[1:]:
        run_step(step, root)

    if args.dry_run:
        print("\nDry run completed. Generated metadata files were not written.")
        return 0

    print("\n==> Validate generated output files")
    expected_outputs = expected_generated_metadata_paths(model_folder, diagrams)
    ensure_expected_outputs_exist(expected_outputs, root)
    validate_all_turtle_files(model_folder, root)

    print("\nSubmission processing completed successfully.")
    print("Generated/validated metadata files:")
    for path in expected_outputs:
        print(f"- {path_for_display(path, root)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Process a single new OntoUML/UFO Catalog model submission by running "
            "the existing metadata validation and generation scripts."
        )
    )
    parser.add_argument(
        "model_folder",
        nargs="?",
        help="Repository-relative model folder to process, for example models/example-model.",
    )
    parser.add_argument(
        "--detect-model-folder",
        nargs=2,
        metavar=("BASE_REF", "HEAD_REF"),
        help=(
            "Print the unique changed model folder between BASE_REF and HEAD_REF, "
            "then exit. Intended for same-repository pull request workflows."
        ),
    )
    parser.add_argument(
        "--models-dir",
        default="models",
        help="Repository-relative models directory. Default: models.",
    )
    parser.add_argument(
        "--metadata-timestamp",
        default="now",
        help=(
            "xsd:dateTime value passed to metadata generators, or 'now'. "
            "Use a fixed value for deterministic local tests. Default: now."
        ),
    )
    parser.add_argument(
        "--repository",
        default="OntoUML/ontouml-models",
        help=(
            "Repository used in generated storage/download URLs. "
            "Default: OntoUML/ontouml-models."
        ),
    )
    parser.add_argument(
        "--branch",
        default="master",
        help="Branch used in generated storage/download URLs. Default: master.",
    )
    parser.add_argument(
        "--allow-missing-license",
        action="store_true",
        help=(
            "Allow missing license metadata. Intended only for legacy datasets; "
            "new submissions should normally provide a license."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and run generators in dry-run mode without writing metadata files.",
    )
    parser.add_argument(
        "--no-fix-metadata-yaml",
        action="store_true",
        help="Do not pass --fix to scripts/validate_metadata_yaml.py.",
    )
    parser.add_argument(
        "--no-validate-ontology-json",
        action="store_true",
        help=(
            "Do not pass --validate-ontology-json to the JSON metadata generator. "
            "Not recommended for new submissions."
        ),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.detect_model_folder:
            base_ref, head_ref = args.detect_model_folder
            print(detect_model_folder_from_git(base_ref, head_ref, args.models_dir))
            return 0
        if not args.model_folder:
            parser.error(
                "model_folder is required unless --detect-model-folder is used."
            )
        return process_submission(args)
    except SubmissionProcessingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

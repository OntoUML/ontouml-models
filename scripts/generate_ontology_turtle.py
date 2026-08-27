"""Generate catalog ontology.ttl files from canonical ontology.json sources.

The wrapper invokes the pinned OntoUML JSON2Graph CLI for one or more catalog
datasets, validates the candidate graph, and installs it atomically. Normal
generation preserves an existing Turtle file when its graph is isomorphic to
the candidate. ``--force-materialization`` instead installs every byte-different
validated candidate and is reserved for the catalog-wide migration.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

try:
    import yaml
except ImportError as exc:  # pragma: no cover - dependency failure only
    raise SystemExit(
        "PyYAML is required. Install it with: "
        "python -m pip install -r scripts/requirements.txt"
    ) from exc

try:
    from rdflib import Graph, Literal, Namespace, URIRef
    from rdflib.compare import isomorphic
    from rdflib.namespace import RDF
except ImportError as exc:  # pragma: no cover - dependency failure only
    raise SystemExit(
        "RDFLib is required. Install it with: "
        "python -m pip install -r scripts/requirements.txt"
    ) from exc


CONVERTER_DISTRIBUTION = "ontouml-json2graph"
REQUIRED_CONVERTER_VERSION = "2.0.1"
DEFAULT_MODELS_DIR = "models"
MODEL_BASE_IRI = "https://w3id.org/ontouml-models/model"
ONTOLOGY_JSON = "ontology.json"
ONTOLOGY_TURTLE = "ontology.ttl"
METADATA_YAML = "metadata.yaml"

ONTOUML = Namespace("https://w3id.org/ontouml#")
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class GeneratorSetupError(RuntimeError):
    """Raised when command setup prevents generation from starting."""


class DatasetGenerationError(RuntimeError):
    """Raised when a dataset cannot be generated safely."""

    def __init__(
        self,
        dataset: Path,
        stage: str,
        category: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.dataset = dataset
        self.stage = stage
        self.category = category


@dataclass(frozen=True)
class Config:
    """Execution policy for ontology generation."""

    check: bool = False
    dry_run: bool = False
    force_materialization: bool = False
    report_format: str = "text"
    quiet: bool = False


@dataclass(frozen=True)
class GenerationResult:
    """Result of converting one catalog dataset."""

    dataset: Path
    slug: str
    source_path: Path
    output_path: Path
    base_uri: str
    declared_languages: tuple[str, ...]
    language: Optional[str]
    converter_version: str
    existing_triples: Optional[int]
    candidate_triples: int
    isomorphic: Optional[bool]
    existed: bool
    changed: bool
    written: bool
    diagnostics: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_uri": self.base_uri,
            "candidate_triples": self.candidate_triples,
            "changed": self.changed,
            "converter_version": self.converter_version,
            "dataset": str(self.dataset),
            "declared_languages": list(self.declared_languages),
            "diagnostics": list(self.diagnostics),
            "existed": self.existed,
            "existing_triples": self.existing_triples,
            "isomorphic": self.isomorphic,
            "language": self.language,
            "output_path": str(self.output_path),
            "slug": self.slug,
            "source_path": str(self.source_path),
            "written": self.written,
        }


class MetadataYamlLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_mapping_no_duplicates(
    loader: MetadataYamlLoader,
    node: yaml.MappingNode,
    deep: bool = False,
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


MetadataYamlLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping_no_duplicates,
)


def installed_converter_version() -> str:
    """Return the installed converter version or raise a setup error."""

    try:
        installed = version(CONVERTER_DISTRIBUTION)
    except PackageNotFoundError as exc:
        raise GeneratorSetupError(
            f"{CONVERTER_DISTRIBUTION} is not installed. Install "
            "scripts/requirements.txt before running this command."
        ) from exc
    if installed != REQUIRED_CONVERTER_VERSION:
        raise GeneratorSetupError(
            f"Expected {CONVERTER_DISTRIBUTION} "
            f"{REQUIRED_CONVERTER_VERSION}, found {installed}."
        )
    return installed


def validate_dataset_folder(dataset_folder: Path) -> Path:
    """Validate a dataset path and return its normalized absolute path."""

    original = Path(dataset_folder)
    if ".." in original.parts:
        raise DatasetGenerationError(
            original,
            "input-validation",
            "path-traversal",
            f"Dataset path must not contain '..': {original}",
        )

    dataset = original.resolve()
    if not dataset.exists():
        raise DatasetGenerationError(
            dataset,
            "input-validation",
            "missing-dataset",
            f"Dataset folder does not exist: {dataset}",
        )
    if not dataset.is_dir():
        raise DatasetGenerationError(
            dataset,
            "input-validation",
            "invalid-dataset-path",
            f"Dataset path is not a directory: {dataset}",
        )

    slug = dataset.name
    if (
        not slug
        or slug in {".", ".."}
        or CONTROL_CHARS.search(slug)
        or not SLUG_RE.fullmatch(slug)
    ):
        raise DatasetGenerationError(
            dataset,
            "input-validation",
            "invalid-slug",
            "Dataset slug must start with an ASCII letter or digit and contain "
            f"only ASCII letters, digits, '.', '_', or '-': {slug!r}",
        )

    for filename in (METADATA_YAML, ONTOLOGY_JSON):
        required_path = dataset / filename
        if not required_path.exists():
            raise DatasetGenerationError(
                dataset,
                "input-validation",
                "missing-source",
                f"Missing required source file: {required_path}",
            )
        if not required_path.is_file():
            raise DatasetGenerationError(
                dataset,
                "input-validation",
                "invalid-source-path",
                f"Required source path is not a file: {required_path}",
            )
    return dataset


def canonical_key(value: object) -> str:
    """Normalize a metadata key for catalog-compatible matching."""

    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def load_declared_languages(dataset: Path) -> tuple[str, ...]:
    """Load and normalize the dataset's declared metadata languages."""

    metadata_path = dataset / METADATA_YAML
    try:
        data = yaml.load(
            metadata_path.read_text(encoding="utf-8"),
            Loader=MetadataYamlLoader,
        )
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise DatasetGenerationError(
            dataset,
            "metadata",
            "invalid-metadata",
            f"Could not read or parse {metadata_path}: {exc}",
        ) from exc

    if not isinstance(data, Mapping):
        raise DatasetGenerationError(
            dataset,
            "metadata",
            "invalid-metadata-root",
            f"Canonical metadata file must contain a YAML mapping: {metadata_path}",
        )

    language_fields = [
        value for key, value in data.items() if canonical_key(key) == "language"
    ]
    if len(language_fields) != 1:
        detail = "missing" if not language_fields else "ambiguous"
        raise DatasetGenerationError(
            dataset,
            "metadata",
            f"{detail}-language",
            f"Expected exactly one language field in {metadata_path}.",
        )

    raw_value = language_fields[0]
    raw_items = raw_value if isinstance(raw_value, list) else [raw_value]
    languages: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        parts = item.split(",") if isinstance(item, str) else [item]
        for part in parts:
            if not isinstance(part, str) or not LANGUAGE_RE.fullmatch(part.strip()):
                raise DatasetGenerationError(
                    dataset,
                    "metadata",
                    "invalid-language",
                    "Metadata language values must be BCP 47/IANA-like tags "
                    f"such as 'en' or 'pt-BR'; received {part!r} in {metadata_path}.",
                )
            language = part.strip()
            normalized = language.casefold()
            if normalized not in seen:
                seen.add(normalized)
                languages.append(language)

    if not languages:
        raise DatasetGenerationError(
            dataset,
            "metadata",
            "missing-language",
            f"Expected at least one language tag in {metadata_path}.",
        )
    return tuple(languages)


def load_project_id(dataset: Path) -> str:
    """Load the exact top-level project ID from ontology.json."""

    source_path = dataset / ONTOLOGY_JSON
    try:
        data = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DatasetGenerationError(
            dataset,
            "input-validation",
            "invalid-json",
            f"Could not read or parse {source_path}: {exc}",
        ) from exc

    if not isinstance(data, Mapping):
        raise DatasetGenerationError(
            dataset,
            "input-validation",
            "invalid-json-root",
            f"Canonical ontology JSON must contain an object: {source_path}",
        )

    project_id = data.get("id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise DatasetGenerationError(
            dataset,
            "input-validation",
            "missing-project-id",
            f"Canonical ontology JSON must declare a non-empty top-level project ID: {source_path}",
        )
    return project_id


def base_uri_for_slug(slug: str) -> str:
    """Return the canonical catalog hash namespace for a dataset slug."""

    return f"{MODEL_BASE_IRI}/{slug}#"


def build_json2graph_command(
    dataset: Path,
    output_directory: Path,
    language: Optional[str],
    *,
    python_executable: str = sys.executable,
) -> list[str]:
    """Build the exact pinned JSON2Graph CLI command for one dataset."""

    command = [
        python_executable,
        "-m",
        "json2graph.decode",
        "-i",
        str(dataset / ONTOLOGY_JSON),
        "-o",
        str(output_directory),
        "-f",
        "ttl",
        "--base-uri",
        base_uri_for_slug(dataset.name),
    ]
    if language is not None:
        command.extend(["--language", language])
    command.extend(
        [
            "--invalid-cardinality-policy",
            "preserve",
            "--invalid-stereotype-policy",
            "preserve",
            "--unresolved-model-element-policy",
            "omit",
            "--path-order-policy",
            "warn",
            "--property-assignment-policy",
            "warn",
            "--transformation-metadata",
            "none",
            "--silent",
        ]
    )
    return command


def diagnostic_lines(completed: subprocess.CompletedProcess[str]) -> tuple[str, ...]:
    """Return non-empty converter warning/diagnostic lines."""

    return tuple(line for line in completed.stderr.splitlines() if line.strip())


def process_failure_summary(completed: subprocess.CompletedProcess[str]) -> str:
    """Return a bounded summary for a failed converter process."""

    lines = [
        line
        for stream in (completed.stderr, completed.stdout)
        for line in stream.splitlines()
        if line.strip()
    ]
    if not lines:
        return "no diagnostic output"
    summary = " | ".join(lines[-12:])
    return summary if len(summary) <= 3000 else summary[-3000:]


def run_json2graph(
    dataset: Path,
    output_directory: Path,
    language: Optional[str],
) -> tuple[Path, tuple[str, ...]]:
    """Run JSON2Graph and return its expected candidate and diagnostics."""

    command = build_json2graph_command(dataset, output_directory, language)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise DatasetGenerationError(
            dataset,
            "conversion",
            "converter-execution",
            f"Could not execute JSON2Graph: {exc}",
        ) from exc

    if completed.returncode != 0:
        raise DatasetGenerationError(
            dataset,
            "conversion",
            "converter-nonzero-exit",
            f"JSON2Graph exited with code {completed.returncode}: "
            f"{process_failure_summary(completed)}",
        )

    candidate = output_directory / ONTOLOGY_TURTLE
    if not candidate.exists() or not candidate.is_file():
        raise DatasetGenerationError(
            dataset,
            "conversion",
            "missing-output",
            f"JSON2Graph did not create the expected output: {candidate}",
        )
    return candidate, diagnostic_lines(completed)


def parse_turtle(path: Path, dataset: Path, *, candidate: bool) -> Graph:
    """Parse a Turtle graph or raise a categorized dataset error."""

    graph = Graph()
    try:
        graph.parse(path, format="turtle")
    except Exception as exc:  # noqa: BLE001 - RDFLib exposes parser-specific errors
        kind = "candidate" if candidate else "existing"
        raise DatasetGenerationError(
            dataset,
            f"{kind}-validation",
            f"invalid-{kind}-turtle",
            f"Could not parse {kind} Turtle file {path}: {exc}",
        ) from exc
    if candidate and len(graph) == 0:
        raise DatasetGenerationError(
            dataset,
            "candidate-validation",
            "empty-candidate",
            f"JSON2Graph produced an empty Turtle graph: {path}",
        )
    return graph


def validate_candidate_namespace(
    graph: Graph,
    dataset: Path,
    base_uri: str,
    project_id: str,
) -> None:
    """Require generated subjects and the exact JSON project IRI below the hash base."""

    foreign_subjects = sorted(
        {
            str(subject)
            for subject in graph.subjects()
            if isinstance(subject, URIRef) and not str(subject).startswith(base_uri)
        }
    )
    if foreign_subjects:
        preview = ", ".join(foreign_subjects[:3])
        raise DatasetGenerationError(
            dataset,
            "candidate-validation",
            "wrong-namespace",
            f"Generated subjects do not use the expected namespace {base_uri}: "
            f"{preview}",
        )

    projects = {
        subject
        for subject in graph.subjects(RDF.type, ONTOUML.Project)
        if isinstance(subject, URIRef)
    }
    if len(projects) != 1:
        raise DatasetGenerationError(
            dataset,
            "candidate-validation",
            "invalid-project-count",
            "Expected exactly one generated ontouml:Project resource, found "
            f"{len(projects)}.",
        )
    project = next(iter(projects))
    expected_project = URIRef(base_uri + project_id)
    if project != expected_project:
        raise DatasetGenerationError(
            dataset,
            "candidate-validation",
            "wrong-project-identity",
            f"Generated project must be {expected_project}, derived from the "
            f"top-level JSON project ID; found {project}.",
        )


def validate_candidate_languages(
    graph: Graph,
    dataset: Path,
    language: Optional[str],
) -> None:
    """Verify that generated ontouml:name literals follow metadata policy."""

    for value in graph.objects(None, ONTOUML.name):
        if not isinstance(value, Literal):
            raise DatasetGenerationError(
                dataset,
                "candidate-validation",
                "invalid-name-value",
                f"Generated ontouml:name value is not a literal: {value}",
            )
        if language is None and value.language is not None:
            raise DatasetGenerationError(
                dataset,
                "candidate-validation",
                "unexpected-language-tag",
                "Multilingual metadata requires untagged ontouml:name literals, "
                f"but found {value.n3()}.",
            )
        if language is not None and (
            value.language is None or value.language.casefold() != language.casefold()
        ):
            raise DatasetGenerationError(
                dataset,
                "candidate-validation",
                "wrong-language-tag",
                f"Metadata declares only {language!r}, but generated ontouml:name "
                f"value does not use that tag: {value.n3()}.",
            )


def atomic_install_candidate(
    candidate: Path,
    target: Path,
    dataset: Path,
) -> None:
    """Atomically replace target with the validated candidate bytes."""

    mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o644
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as destination, candidate.open(
            "rb"
        ) as source:
            while chunk := source.read(1024 * 1024):
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, target)
    except OSError as exc:
        raise DatasetGenerationError(
            dataset,
            "write",
            "atomic-replacement-failed",
            f"Could not atomically install {target}: {exc}",
        ) from exc
    finally:
        if temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass


def process_dataset(
    dataset_folder: Path,
    config: Config,
    converter_version: str,
) -> GenerationResult:
    """Generate, validate, compare, and optionally install one ontology.ttl."""

    dataset = validate_dataset_folder(dataset_folder)
    slug = dataset.name
    languages = load_declared_languages(dataset)
    project_id = load_project_id(dataset)
    language = languages[0] if len(languages) == 1 else None
    source_path = dataset / ONTOLOGY_JSON
    output_path = dataset / ONTOLOGY_TURTLE
    base_uri = base_uri_for_slug(slug)

    with tempfile.TemporaryDirectory(
        prefix=f"ontouml-json2graph-{slug}-"
    ) as temporary_directory:
        candidate_path, diagnostics = run_json2graph(
            dataset,
            Path(temporary_directory),
            language,
        )
        candidate_graph = parse_turtle(candidate_path, dataset, candidate=True)
        validate_candidate_namespace(candidate_graph, dataset, base_uri, project_id)
        validate_candidate_languages(candidate_graph, dataset, language)

        existed = output_path.exists()
        existing_graph: Optional[Graph] = None
        existing_bytes: Optional[bytes] = None
        graphs_are_isomorphic: Optional[bool] = None
        if existed:
            if not output_path.is_file():
                raise DatasetGenerationError(
                    dataset,
                    "existing-validation",
                    "invalid-existing-path",
                    f"Existing output path is not a file: {output_path}",
                )
            existing_graph = parse_turtle(output_path, dataset, candidate=False)
            try:
                existing_bytes = output_path.read_bytes()
            except OSError as exc:
                raise DatasetGenerationError(
                    dataset,
                    "existing-validation",
                    "unreadable-existing-output",
                    f"Could not read existing output {output_path}: {exc}",
                ) from exc
            graphs_are_isomorphic = isomorphic(existing_graph, candidate_graph)

        try:
            candidate_bytes = candidate_path.read_bytes()
        except OSError as exc:
            raise DatasetGenerationError(
                dataset,
                "candidate-validation",
                "unreadable-candidate",
                f"Could not read generated candidate {candidate_path}: {exc}",
            ) from exc

        if not existed:
            changed = True
        elif config.force_materialization:
            changed = existing_bytes != candidate_bytes
        else:
            changed = not bool(graphs_are_isomorphic)

        written = changed and not config.check and not config.dry_run
        if written:
            atomic_install_candidate(candidate_path, output_path, dataset)

        return GenerationResult(
            dataset=dataset,
            slug=slug,
            source_path=source_path,
            output_path=output_path,
            base_uri=base_uri,
            declared_languages=languages,
            language=language,
            converter_version=converter_version,
            existing_triples=len(existing_graph) if existing_graph is not None else None,
            candidate_triples=len(candidate_graph),
            isomorphic=graphs_are_isomorphic,
            existed=existed,
            changed=changed,
            written=written,
            diagnostics=diagnostics,
        )


def discover_datasets(models_dir: Path) -> list[Path]:
    """Discover dataset folders by metadata.yaml presence in sorted order."""

    models = models_dir.resolve()
    if not models.exists():
        raise GeneratorSetupError(f"Models directory does not exist: {models}")
    if not models.is_dir():
        raise GeneratorSetupError(f"Models path is not a directory: {models}")
    return sorted(
        (
            path
            for path in models.iterdir()
            if path.is_dir() and (path / METADATA_YAML).exists()
        ),
        key=lambda path: (path.name.casefold(), path.name),
    )


def resolve_targets(args: argparse.Namespace) -> list[Path]:
    """Resolve command-line targets without processing repository content."""

    if args.all:
        if args.datasets:
            raise GeneratorSetupError(
                "Use either --all or explicit dataset folders, not both."
            )
        targets = discover_datasets(args.models_dir)
    elif args.datasets:
        targets = [Path(path) for path in args.datasets]
    else:
        cwd = Path.cwd()
        if (cwd / METADATA_YAML).exists():
            targets = [cwd]
        else:
            raise GeneratorSetupError(
                "No dataset folder provided. Pass one or more model folders, "
                "use --all, or run from a dataset folder."
            )

    unique = {str(path.resolve()): path for path in targets}
    ordered = sorted(
        unique.values(),
        key=lambda path: (path.name.casefold(), path.name, str(path.resolve())),
    )
    if not ordered:
        raise GeneratorSetupError("No dataset folders with metadata.yaml were found.")
    return ordered


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Generate catalog ontology.ttl files with OntoUML JSON2Graph.",
    )
    parser.add_argument(
        "datasets",
        nargs="*",
        type=Path,
        help=(
            "Dataset folder(s) to process. If omitted, the current directory is "
            "used when it contains metadata.yaml."
        ),
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
        "--check",
        action="store_true",
        help="Do not write files; exit 1 if any ontology.ttl needs an update.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report candidate changes without writing files.",
    )
    parser.add_argument(
        "--force-materialization",
        action="store_true",
        help=(
            "Install byte-different validated candidates even when their graphs "
            "are isomorphic. Reserved for the one-time catalog migration."
        ),
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
        help=(
            "Suppress progress and the final text summary. Converter policy "
            "warnings and errors remain visible."
        ),
    )
    args = parser.parse_args(argv)
    if args.check and args.dry_run:
        parser.error("--check and --dry-run cannot be used together.")
    return args


def action_label(result: GenerationResult, config: Config) -> str:
    """Return the user-facing action label for one result."""

    if not result.changed:
        return "up to date" if config.check else "unchanged"
    if config.check:
        return "needs update"
    if config.dry_run:
        return "would create" if not result.existed else "would update"
    return "created" if not result.existed else "updated"


def print_progress(result: GenerationResult, config: Config) -> None:
    """Print one concise text progress record."""

    language = result.language or "untagged"
    comparison = "force-materialization" if config.force_materialization else "semantic"
    print(
        f"{action_label(result, config)}: {result.output_path} <- "
        f"{result.source_path} (language={language}, comparison={comparison})"
    )


def print_summary(
    results: Sequence[GenerationResult],
    errors: Sequence[Mapping[str, str]],
    config: Config,
) -> None:
    """Print the final text summary."""

    changed = sum(1 for result in results if result.changed)
    written = sum(1 for result in results if result.written)
    mode = "force-materialization" if config.force_materialization else "semantic"
    print(
        f"Summary: {len(results) + len(errors)} dataset(s), "
        f"{len(results)} succeeded, {len(errors)} error(s), {changed} changed, "
        f"{written} written; comparison={mode}."
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run catalog generation and return its process exit code."""

    args = parse_args(argv)
    config = Config(
        check=args.check,
        dry_run=args.dry_run,
        force_materialization=args.force_materialization,
        report_format=args.format,
        quiet=args.quiet,
    )

    try:
        converter_version = installed_converter_version()
        targets = resolve_targets(args)
    except GeneratorSetupError as exc:
        print(f"ERROR [setup]: {exc}", file=sys.stderr)
        return 2

    results: list[GenerationResult] = []
    errors: list[dict[str, str]] = []
    for target in targets:
        try:
            result = process_dataset(target, config, converter_version)
            results.append(result)
            for diagnostic in result.diagnostics:
                print(f"JSON2Graph warning [{result.slug}]: {diagnostic}", file=sys.stderr)
            if config.report_format == "text" and not config.quiet:
                print_progress(result, config)
        except DatasetGenerationError as exc:
            record = {
                "category": exc.category,
                "converter_version": converter_version,
                "dataset": str(exc.dataset),
                "error": str(exc),
                "stage": exc.stage,
            }
            errors.append(record)
            print(
                f"ERROR {exc.dataset} [{exc.stage}/{exc.category}] "
                f"(JSON2Graph {converter_version}): {exc}",
                file=sys.stderr,
            )

    check_drift = config.check and any(result.changed for result in results)
    ok = not errors and not check_drift
    if config.report_format == "json":
        print(
            json.dumps(
                {
                    "converter_version": converter_version,
                    "errors": errors,
                    "force_materialization": config.force_materialization,
                    "ok": ok,
                    "results": [result.to_dict() for result in results],
                },
                indent=2,
                sort_keys=True,
            )
        )
    elif not config.quiet:
        print_summary(results, errors, config)

    if errors or check_drift:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

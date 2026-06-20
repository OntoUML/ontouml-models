#!/usr/bin/env python3
"""Validate OntoUML/UFO Catalog dataset metadata.yaml files.

Usage examples:
  python tools/validation/metadata_yaml_validator.py models/amaral2019rot
  python tools/validation/metadata_yaml_validator.py models --recursive
  python tools/validation/metadata_yaml_validator.py models --recursive --format json

Exit codes:
  0  all checked metadata.yaml files are valid
  1  at least one validation error was found
  2  command-line, file-system, or YAML loading problem prevented validation

The validator intentionally does not use RDFLib because it validates the YAML
authoring format directly. RDF/SHACL validation should be applied to generated
metadata.ttl files in a separate validation stage.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Literal
from urllib.parse import urlparse

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised only without dependency
    raise SystemExit(
        "PyYAML is required. Install it with: python -m pip install PyYAML"
    ) from exc

Severity = Literal["error", "warning"]
UnknownPolicy = Literal["error", "warning", "ignore"]


@dataclass(frozen=True)
class Issue:
    severity: Severity
    code: str
    field_path: str
    message: str


@dataclass
class ValidationResult:
    dataset_path: str
    metadata_path: str | None
    valid: bool
    errors: list[Issue]
    warnings: list[Issue]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_path": self.dataset_path,
            "metadata_path": self.metadata_path,
            "valid": self.valid,
            "errors": [asdict(i) for i in self.errors],
            "warnings": [asdict(i) for i in self.warnings],
        }


class DuplicateKeyLoader(yaml.SafeLoader):
    """YAML loader that rejects duplicate mapping keys."""


def _construct_mapping_no_duplicates(loader: DuplicateKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
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


DuplicateKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping_no_duplicates,
)


# Expected top-level YAML keys. The repository examples use these keys as the
# metadata.yaml template for one model/dataset directory.
EXPECTED_FIELDS: tuple[str, ...] = (
    "title",
    "acronym",
    "issued",
    "modified",
    "contributor",
    "keyword",
    "theme",
    "editorialNote",
    "ontologyType",
    "language",
    "designedForTask",
    "context",
    "source",
    "representationStyle",
    "landingPage",
    "license",
)

# Keys that must have a non-null/non-empty value for a semantically usable model
# metadata record. Other expected keys are still required as keys, but may be null
# when no information is available.
REQUIRED_VALUE_FIELDS: tuple[str, ...] = (
    "title",
    "issued",
    "keyword",
    "theme",
    "ontologyType",
    "language",
    "designedForTask",
    "context",
    "representationStyle",
)

ONTOLOGY_TYPES = {"core", "domain", "application"}
DESIGNED_FOR_TASKS = {
    "conceptual clarification",
    "data publication",
    "decision support system",
    "example",
    "information retrieval",
    "interoperability",
    "language engineering",
    "learning",
    "ontological analysis",
    "software engineering",
}
CONTEXTS = {"research", "industry", "classroom"}
REPRESENTATION_STYLES = {"ontouml", "ufo"}
REPRESENTATION_STYLE_ALIASES = {
    "ontoumlstyle": "ontouml",
    "ontouml-style": "ontouml",
    "ocmv:ontoumlstyle": "ontouml",
    "ufo-style": "ufo",
    "ufostyle": "ufo",
    "ocmv:ufostyle": "ufo",
}

LCC_CLASSES: dict[str, str] = {
    "A": "General Works",
    "B": "Philosophy, Psychology, Religion",
    "C": "Auxiliary Sciences of History",
    "D": "World History and History of Europe, Asia, Africa, Australia, New Zealand, etc.",
    "E": "History of the Americas",
    "F": "History of the Americas",
    "G": "Geography, Anthropology, and Recreation",
    "H": "Social Sciences",
    "J": "Political Science",
    "K": "Law",
    "L": "Education",
    "M": "Music",
    "N": "Fine Arts",
    "P": "Language and Literature",
    "Q": "Science",
    "R": "Medicine",
    "S": "Agriculture",
    "T": "Technology",
    "U": "Military Science",
    "V": "Naval Science",
    "Z": "Bibliography, Library Science, and General Information Resources",
}

LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
YEAR_RE = re.compile(r"^[0-9]{4}$")
YEARMONTH_RE = re.compile(r"^[0-9]{4}-[0-9]{2}$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
DATETIME_START_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}")
LCC_URI_RE = re.compile(r"^https?://id\.loc\.gov/authorities/classification/[^\s]+/?$")
LCC_LABEL_RE = re.compile(r"^Class\s+([A-Z])\s+-\s+(.+)$")
ORCID_RE = re.compile(r"^https?://orcid\.org/[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9X]{4}$", re.I)
DBLP_RE = re.compile(r"^https?://dblp\.org/(pid|rec)/.+", re.I)
DOI_URL_RE = re.compile(r"^https?://doi\.org/10\..+", re.I)


def _is_null(value: Any) -> bool:
    return value is None


def _is_empty_string(value: Any) -> bool:
    return isinstance(value, str) and not value.strip()


def _is_empty_sequence(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 0


def _is_missing_value(value: Any) -> bool:
    return _is_null(value) or _is_empty_string(value) or _is_empty_sequence(value)


def _scalar_to_text(value: Any) -> str:
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    return str(value).strip()


def _normalize_token(value: Any) -> str:
    return _scalar_to_text(value).strip().lower()


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return [value]


def _is_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_valid_date_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 1000 <= value <= 9999
    if isinstance(value, (_dt.date, _dt.datetime)):
        return True
    if not isinstance(value, str):
        return False
    text = value.strip()
    if YEAR_RE.match(text):
        return True
    if YEARMONTH_RE.match(text):
        try:
            year, month = map(int, text.split("-"))
            return 1 <= month <= 12 and 1000 <= year <= 9999
        except ValueError:
            return False
    if DATE_RE.match(text):
        try:
            _dt.date.fromisoformat(text)
            return True
        except ValueError:
            return False
    if DATETIME_START_RE.match(text):
        normalized = text.replace("Z", "+00:00")
        try:
            _dt.datetime.fromisoformat(normalized)
            return True
        except ValueError:
            return False
    return False


def _validate_language_tag(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return bool(LANGUAGE_RE.match(value.strip()))


def _validate_theme(value: Any) -> tuple[bool, str | None]:
    """Return (is_error_free, warning_message)."""
    if not isinstance(value, str):
        return False, None
    text = value.strip()
    if LCC_URI_RE.match(text):
        return True, None
    match = LCC_LABEL_RE.match(text)
    if not match:
        return False, None
    code = match.group(1)
    label = match.group(2).strip()
    if code not in LCC_CLASSES:
        return False, None
    canonical = LCC_CLASSES[code]
    if label.casefold() != canonical.casefold():
        return True, f"LCC class code {code!r} is valid, but the label differs from canonical label {canonical!r}."
    return True, None


class MetadataYamlValidator:
    def __init__(self, *, unknown_fields: UnknownPolicy = "error", strict: bool = False) -> None:
        self.unknown_fields = unknown_fields
        self.strict = strict

    def validate_dataset_path(self, dataset_path: Path) -> ValidationResult:
        metadata_path = dataset_path if dataset_path.name == "metadata.yaml" else dataset_path / "metadata.yaml"
        result = ValidationResult(
            dataset_path=str(dataset_path),
            metadata_path=str(metadata_path),
            valid=False,
            errors=[],
            warnings=[],
        )

        if not metadata_path.exists():
            result.errors.append(
                Issue("error", "missing_file", "$", "metadata.yaml was not found for this dataset path.")
            )
            return self._finalize(result)
        if not metadata_path.is_file():
            result.errors.append(
                Issue("error", "not_a_file", "$", "metadata.yaml path exists but is not a file.")
            )
            return self._finalize(result)

        try:
            with metadata_path.open("r", encoding="utf-8") as file:
                data = yaml.load(file, Loader=DuplicateKeyLoader)
        except yaml.YAMLError as exc:
            result.errors.append(
                Issue("error", "invalid_yaml", "$", f"metadata.yaml is not valid YAML: {exc}")
            )
            return self._finalize(result)
        except OSError as exc:
            result.errors.append(
                Issue("error", "read_error", "$", f"Could not read metadata.yaml: {exc}")
            )
            return self._finalize(result)

        self._validate_mapping(data, result)
        return self._finalize(result)

    def _add(self, result: ValidationResult, severity: Severity, code: str, field_path: str, message: str) -> None:
        issue = Issue(severity, code, field_path, message)
        if severity == "error":
            result.errors.append(issue)
        else:
            result.warnings.append(issue)

    def _warn_or_error(self, result: ValidationResult, code: str, field_path: str, message: str) -> None:
        self._add(result, "error" if self.strict else "warning", code, field_path, message)

    def _validate_mapping(self, data: Any, result: ValidationResult) -> None:
        if not isinstance(data, dict):
            self._add(result, "error", "root_not_mapping", "$", "metadata.yaml must contain a YAML mapping/object at the root.")
            return

        for key in data.keys():
            if not isinstance(key, str):
                self._add(result, "error", "non_string_key", "$", f"Top-level key {key!r} must be a string.")
                continue
            if key not in EXPECTED_FIELDS:
                if self.unknown_fields == "error":
                    self._add(result, "error", "unexpected_field", f"$.{key}", "Unexpected top-level field.")
                elif self.unknown_fields == "warning":
                    self._add(result, "warning", "unexpected_field", f"$.{key}", "Unexpected top-level field.")

        for field in EXPECTED_FIELDS:
            if field not in data:
                self._add(result, "error", "missing_field", f"$.{field}", "Required metadata.yaml key is missing.")

        for field in REQUIRED_VALUE_FIELDS:
            if field in data and _is_missing_value(data[field]):
                self._add(result, "error", "missing_value", f"$.{field}", "Field must have a non-empty value.")

        if "title" in data:
            self._validate_optional_string(data["title"], result, "title", required_value=True)
        if "acronym" in data:
            self._validate_optional_string(data["acronym"], result, "acronym")
        if "issued" in data:
            self._validate_date_field(data["issued"], result, "issued", required_value=True)
        if "modified" in data:
            self._validate_date_field(data["modified"], result, "modified", required_value=False)
        if "contributor" in data:
            self._validate_url_list(data["contributor"], result, "contributor", required_value=False, contributor=True)
        if "keyword" in data:
            self._validate_keyword(data["keyword"], result)
        if "theme" in data:
            self._validate_theme_field(data["theme"], result)
        if "editorialNote" in data:
            self._validate_scalar_or_list_of_strings(data["editorialNote"], result, "editorialNote", required_value=False)
        if "ontologyType" in data:
            self._validate_enum_list(data["ontologyType"], result, "ontologyType", ONTOLOGY_TYPES, required_value=True)
        if "language" in data:
            self._validate_language(data["language"], result)
        if "designedForTask" in data:
            self._validate_enum_list(data["designedForTask"], result, "designedForTask", DESIGNED_FOR_TASKS, required_value=True)
        if "context" in data:
            self._validate_enum_list(data["context"], result, "context", CONTEXTS, required_value=True)
        if "source" in data:
            self._validate_url_list(data["source"], result, "source", required_value=False, source=True)
        if "representationStyle" in data:
            self._validate_representation_style(data["representationStyle"], result)
        if "landingPage" in data:
            self._validate_url_or_url_list(data["landingPage"], result, "landingPage", required_value=False)
        if "license" in data:
            self._validate_license(data["license"], result)

    def _validate_optional_string(self, value: Any, result: ValidationResult, field: str, *, required_value: bool = False) -> None:
        if _is_null(value):
            if required_value:
                self._add(result, "error", "null_not_allowed", f"$.{field}", "Field must not be null.")
            return
        if not isinstance(value, str):
            self._add(result, "error", "invalid_type", f"$.{field}", "Expected a string or null.")
            return
        if required_value and not value.strip():
            self._add(result, "error", "empty_string", f"$.{field}", "Expected a non-empty string.")

    def _validate_date_field(self, value: Any, result: ValidationResult, field: str, *, required_value: bool) -> None:
        if _is_null(value):
            if required_value:
                self._add(result, "error", "null_not_allowed", f"$.{field}", "Field must not be null.")
            return
        if not _is_valid_date_like(value):
            self._add(
                result,
                "error",
                "invalid_date",
                f"$.{field}",
                "Expected a date-like value: YYYY, YYYY-MM, YYYY-MM-DD, or ISO date-time.",
            )

    def _validate_keyword(self, value: Any, result: ValidationResult) -> None:
        field = "keyword"
        if not isinstance(value, list):
            self._add(result, "error", "invalid_type", f"$.{field}", "Expected a list of non-empty strings.")
            return
        if not value:
            self._add(result, "error", "empty_list", f"$.{field}", "Expected at least one keyword.")
            return
        seen: set[str] = set()
        for index, item in enumerate(value):
            path = f"$.{field}[{index}]"
            if not isinstance(item, str) or not item.strip():
                self._add(result, "error", "invalid_keyword", path, "Expected a non-empty string keyword.")
                continue
            norm = item.strip().casefold()
            if norm in seen:
                self._add(result, "warning", "duplicate_keyword", path, "Duplicate keyword after case normalization.")
            seen.add(norm)

    def _validate_theme_field(self, value: Any, result: ValidationResult) -> None:
        if _is_null(value) or _is_empty_string(value):
            self._add(result, "error", "missing_value", "$.theme", "Expected one LCC class label or URI.")
            return
        ok, warning = _validate_theme(value)
        if not ok:
            self._add(
                result,
                "error",
                "invalid_theme",
                "$.theme",
                "Expected an LCC class label such as 'Class H - Social Sciences' or an id.loc.gov LCC URI.",
            )
            return
        if warning:
            self._add(result, "warning", "non_canonical_theme_label", "$.theme", warning)

    def _validate_scalar_or_list_of_strings(self, value: Any, result: ValidationResult, field: str, *, required_value: bool) -> None:
        if _is_null(value):
            if required_value:
                self._add(result, "error", "null_not_allowed", f"$.{field}", "Field must not be null.")
            return
        if isinstance(value, list):
            if required_value and not value:
                self._add(result, "error", "empty_list", f"$.{field}", "Expected at least one value.")
                return
            for index, item in enumerate(value):
                if not isinstance(item, str) or not item.strip():
                    self._add(result, "error", "invalid_type", f"$.{field}[{index}]", "Expected a non-empty string.")
            return
        if not isinstance(value, str):
            self._add(result, "error", "invalid_type", f"$.{field}", "Expected a string, list of strings, or null.")
            return
        if required_value and not value.strip():
            self._add(result, "error", "empty_string", f"$.{field}", "Expected a non-empty string.")

    def _validate_enum_list(self, value: Any, result: ValidationResult, field: str, allowed: set[str], *, required_value: bool) -> None:
        if not isinstance(value, list):
            self._add(result, "error", "invalid_type", f"$.{field}", "Expected a list.")
            return
        if required_value and not value:
            self._add(result, "error", "empty_list", f"$.{field}", "Expected at least one value.")
            return
        seen: set[str] = set()
        for index, item in enumerate(value):
            path = f"$.{field}[{index}]"
            if not isinstance(item, str) or not item.strip():
                self._add(result, "error", "invalid_type", path, "Expected a non-empty string enumeration value.")
                continue
            token = _normalize_token(item)
            if token not in allowed:
                self._add(result, "error", "invalid_enum", path, f"Unexpected value {item!r}. Allowed values: {', '.join(sorted(allowed))}.")
            if token in seen:
                self._add(result, "warning", "duplicate_value", path, "Duplicate controlled value.")
            seen.add(token)

    def _validate_language(self, value: Any, result: ValidationResult) -> None:
        field = "language"
        if _is_missing_value(value):
            self._add(result, "error", "missing_value", f"$.{field}", "Expected at least one BCP 47/IANA language tag.")
            return
        values = _as_list(value) if isinstance(value, list) else [value]
        for index, item in enumerate(values):
            path = f"$.{field}[{index}]" if isinstance(value, list) else f"$.{field}"
            if not _validate_language_tag(item):
                self._add(result, "error", "invalid_language", path, "Expected a BCP 47/IANA language tag such as 'en', 'pt-br', or 'en-gb'.")

    def _validate_url_list(
        self,
        value: Any,
        result: ValidationResult,
        field: str,
        *,
        required_value: bool,
        contributor: bool = False,
        source: bool = False,
    ) -> None:
        if _is_null(value):
            if required_value:
                self._add(result, "error", "null_not_allowed", f"$.{field}", "Expected a non-empty list of URLs.")
            return
        if not isinstance(value, list):
            self._add(result, "error", "invalid_type", f"$.{field}", "Expected a list of HTTP(S) URLs or null.")
            return
        if required_value and not value:
            self._add(result, "error", "empty_list", f"$.{field}", "Expected at least one URL.")
            return
        seen: set[str] = set()
        for index, item in enumerate(value):
            path = f"$.{field}[{index}]"
            if not isinstance(item, str) or not item.strip():
                self._add(result, "error", "invalid_type", path, "Expected a non-empty URL string.")
                continue
            text = item.strip()
            if not _is_http_url(text):
                self._add(result, "error", "invalid_url", path, "Expected an HTTP(S) URL.")
                continue
            if text in seen:
                self._add(result, "warning", "duplicate_url", path, "Duplicate URL.")
            seen.add(text)
            if contributor and not (ORCID_RE.match(text) or DBLP_RE.match(text)):
                self._add(
                    result,
                    "warning",
                    "non_pid_contributor_url",
                    path,
                    "Contributor URL is valid, but DBLP or ORCID identifiers are preferred when available.",
                )
            if source and not (DOI_URL_RE.match(text) or DBLP_RE.match(text)):
                self._add(result, "warning", "non_persistent_source", path, "DOI or DBLP identifiers are preferred for bibliographic sources.")

    def _validate_url_or_url_list(self, value: Any, result: ValidationResult, field: str, *, required_value: bool) -> None:
        if _is_null(value):
            if required_value:
                self._add(result, "error", "null_not_allowed", f"$.{field}", "Expected one URL or a list of URLs.")
            return
        values = value if isinstance(value, list) else [value]
        if required_value and not values:
            self._add(result, "error", "empty_list", f"$.{field}", "Expected at least one URL.")
            return
        for index, item in enumerate(values):
            path = f"$.{field}[{index}]" if isinstance(value, list) else f"$.{field}"
            if not isinstance(item, str) or not item.strip():
                self._add(result, "error", "invalid_type", path, "Expected a non-empty URL string.")
                continue
            if not _is_http_url(item):
                self._add(result, "error", "invalid_url", path, "Expected an HTTP(S) URL.")

    def _validate_license(self, value: Any, result: ValidationResult) -> None:
        if _is_null(value) or _is_empty_string(value) or _is_empty_sequence(value):
            self._warn_or_error(
                result,
                "missing_license",
                "$.license",
                "License is empty. Existing catalog policy treats models without explicit licensing information as restrictive/private; explicit license URL is recommended.",
            )
            return
        self._validate_url_or_url_list(value, result, "license", required_value=False)

    def _validate_representation_style(self, value: Any, result: ValidationResult) -> None:
        field = "representationStyle"
        if not isinstance(value, list):
            self._add(result, "error", "invalid_type", f"$.{field}", "Expected a list.")
            return
        if not value:
            self._add(result, "error", "empty_list", f"$.{field}", "Expected at least one representation style.")
            return
        seen: set[str] = set()
        for index, item in enumerate(value):
            path = f"$.{field}[{index}]"
            if not isinstance(item, str) or not item.strip():
                self._add(result, "error", "invalid_type", path, "Expected a non-empty string enumeration value.")
                continue
            token = _normalize_token(item)
            token = REPRESENTATION_STYLE_ALIASES.get(token, token)
            if token not in REPRESENTATION_STYLES:
                self._add(result, "error", "invalid_enum", path, "Allowed values: ontouml, ufo.")
            if token in seen:
                self._add(result, "warning", "duplicate_value", path, "Duplicate representation style.")
            seen.add(token)

    def _finalize(self, result: ValidationResult) -> ValidationResult:
        result.valid = not result.errors
        return result


def discover_metadata_targets(paths: Iterable[Path], *, recursive: bool) -> tuple[list[Path], list[str]]:
    targets: list[Path] = []
    problems: list[str] = []
    for input_path in paths:
        path = input_path.resolve()
        if path.name == "metadata.yaml":
            targets.append(path)
            continue
        if not path.exists():
            problems.append(f"Path does not exist: {input_path}")
            continue
        if path.is_file():
            problems.append(f"Expected metadata.yaml or a dataset directory, got file: {input_path}")
            continue
        if recursive:
            targets.extend(sorted(p for p in path.rglob("metadata.yaml") if p.is_file()))
        else:
            targets.append(path / "metadata.yaml")
    # Preserve order while removing duplicates.
    unique: list[Path] = []
    seen: set[Path] = set()
    for target in targets:
        if target not in seen:
            unique.append(target)
            seen.add(target)
    return unique, problems


def _dataset_path_for_metadata_path(metadata_path: Path) -> Path:
    return metadata_path.parent if metadata_path.name == "metadata.yaml" else metadata_path


def format_text(results: list[ValidationResult]) -> str:
    lines: list[str] = []
    for result in results:
        status = "VALID" if result.valid else "INVALID"
        lines.append(f"{status}: {result.dataset_path}")
        if result.metadata_path:
            lines.append(f"  metadata: {result.metadata_path}")
        for issue in result.errors:
            lines.append(f"  ERROR   {issue.field_path} [{issue.code}] {issue.message}")
        for issue in result.warnings:
            lines.append(f"  WARNING {issue.field_path} [{issue.code}] {issue.message}")
    total = len(results)
    invalid = sum(1 for r in results if not r.valid)
    warnings = sum(len(r.warnings) for r in results)
    lines.append(f"Summary: {total} checked, {invalid} invalid, {warnings} warning(s).")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate OntoUML/UFO Catalog dataset metadata.yaml files.",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Dataset directory, metadata.yaml file, or root directory when --recursive is used.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively validate every metadata.yaml below each provided directory.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format. Default: text.",
    )
    parser.add_argument(
        "--unknown-fields",
        choices=("error", "warning", "ignore"),
        default="error",
        help="How to handle unexpected top-level YAML fields. Default: error.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Promote selected policy warnings, such as empty license, to errors.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    targets, discovery_problems = discover_metadata_targets(args.paths, recursive=args.recursive)
    if discovery_problems:
        for problem in discovery_problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        return 2
    if not targets:
        print("ERROR: No metadata.yaml files found.", file=sys.stderr)
        return 2

    validator = MetadataYamlValidator(unknown_fields=args.unknown_fields, strict=args.strict)
    results: list[ValidationResult] = []
    for metadata_path in targets:
        dataset_path = _dataset_path_for_metadata_path(metadata_path)
        results.append(validator.validate_dataset_path(dataset_path))

    if args.format == "json":
        print(json.dumps([r.to_dict() for r in results], indent=2, ensure_ascii=False))
    else:
        print(format_text(results))

    return 1 if any(not result.valid for result in results) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

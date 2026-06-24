"""Validate optional references.bib files for OntoUML/UFO Catalog datasets.

The validator is intentionally lightweight and dependency-free. It performs a
basic BibTeX/BibLaTeX syntax check suitable for repository maintenance and
CI/workflow preflight checks. It does not try to replace a full BibTeX processor.

Typical usage from the repository root:

    python scripts/validate_references_bib.py models/amaral2019rot
    python scripts/validate_references_bib.py models/a models/b
    python scripts/validate_references_bib.py --all --models-dir models
    python scripts/validate_references_bib.py models/example/references.bib
    python scripts/validate_references_bib.py --all --format json

Exit codes:

    0  no validation errors were found
    1  validation errors were found
    2  command-line or discovery problem prevented normal execution

Missing references.bib files are accepted by default because references.bib is an
optional catalog input file. Use --require to report missing files as errors.
Warnings do not affect the exit code unless --fail-on-warning or --strict is used.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional, Sequence


Severity = Literal["error", "warning"]


class ReferencesBibError(RuntimeError):
    """Raised when validation cannot continue because of a tool/setup problem."""


@dataclass(frozen=True)
class Issue:
    """One validation or lint issue."""

    severity: Severity
    code: str
    dataset_path: str
    references_path: Optional[str]
    entry_key: Optional[str]
    message: str
    suggestion: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationResult:
    """Validation result for one dataset folder or references.bib file."""

    dataset_path: Path
    references_path: Path
    present: bool
    issues: list[Issue] = field(default_factory=list)
    entries_checked: int = 0

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_path": str(self.dataset_path),
            "references_path": str(self.references_path),
            "present": self.present,
            "valid": self.valid,
            "entries_checked": self.entries_checked,
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
        }


@dataclass(frozen=True)
class Config:
    """Runtime configuration."""

    require: bool = False
    strict: bool = False
    fail_on_warning: bool = False


@dataclass(frozen=True)
class ParsedEntry:
    """A single parsed BibTeX entry."""

    entry_type: str
    body: str
    start_index: int
    start_line: int
    start_column: int
    body_start_index: int
    body_start_line: int
    body_start_column: int
    key: Optional[str] = None


# Standard BibTeX plus common BibLaTeX entry types. Unknown types are warnings by
# default, not errors, so the validator remains compatible with future or local
# entry-type extensions.
KNOWN_ENTRY_TYPES: set[str] = {
    "article",
    "artwork",
    "audio",
    "bibnote",
    "book",
    "bookinbook",
    "booklet",
    "collection",
    "conference",
    "dataset",
    "electronic",
    "image",
    "inbook",
    "incollection",
    "inproceedings",
    "inreference",
    "manual",
    "bachelorsthesis",
    "mastersthesis",
    "masterthesis",
    "misc",
    "movie",
    "music",
    "mvbook",
    "mvcollection",
    "mvproceedings",
    "mvreference",
    "online",
    "patent",
    "periodical",
    "phdthesis",
    "proceedings",
    "reference",
    "report",
    "set",
    "software",
    "suppbook",
    "suppcollection",
    "suppperiodical",
    "techreport",
    "thesis",
    "unpublished",
    "video",
    "www",
    "xdata",
}

SPECIAL_ENTRY_TYPES: set[str] = {"comment", "preamble", "string"}

ENTRY_TYPE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
FIELD_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
CITATION_KEY_RE = re.compile(r"^[^,\s{}()=\"]+$")


def line_col(text: str, index: int) -> tuple[int, int]:
    """Return one-based line and column for a zero-based text index."""

    line = text.count("\n", 0, index) + 1
    line_start = text.rfind("\n", 0, index) + 1
    return line, index - line_start + 1


def line_col_in_entry_body(entry: ParsedEntry, body_index: int) -> tuple[int, int]:
    """Return one-based file line/column for an offset in an entry body."""

    bounded_index = max(0, min(body_index, len(entry.body)))
    relative_line, relative_column = line_col(entry.body, bounded_index)
    if relative_line == 1:
        return entry.body_start_line, entry.body_start_column + relative_column - 1
    return entry.body_start_line + relative_line - 1, relative_column


def remove_top_level_line_comments(text: str) -> tuple[str, list[int]]:
    """Remove top-level BibTeX comments while preserving an offset map.

    The validator accepts comments between fields, e.g. after a comma. It does
    not strip percent signs inside braced or quoted values, where they may be
    intentional content such as ``title = {100\\% coverage}``.

    Backslash-escaped braces are treated as brace-like LaTeX content for
    balancing purposes. This accepts common constructs such as ``{\\{a}}`` in
    exported BibTeX while still preserving original offsets.
    """

    output: list[str] = []
    original_offsets: list[int] = []
    depth_brace = 0
    depth_paren = 0
    in_quote = False
    escaped = False
    index = 0

    while index < len(text):
        char = text[index]

        if escaped:
            output.append(char)
            original_offsets.append(index)
            escaped = False
            index += 1
            continue

        if char == "\\":
            output.append(char)
            original_offsets.append(index)
            next_char = text[index + 1] if index + 1 < len(text) else ""
            if not in_quote and next_char in "{}":
                output.append(next_char)
                original_offsets.append(index + 1)
                if next_char == "{":
                    depth_brace += 1
                elif next_char == "}" and depth_brace > 0:
                    depth_brace -= 1
                index += 2
                continue
            escaped = True
            index += 1
            continue

        if not in_quote and depth_brace == 0 and depth_paren == 0 and char == "%":
            while index < len(text) and text[index] != "\n":
                index += 1
            continue

        if char == '"' and depth_brace == 0 and depth_paren == 0:
            in_quote = not in_quote
        elif not in_quote:
            if char == "{":
                depth_brace += 1
            elif char == "}" and depth_brace > 0:
                depth_brace -= 1
            elif char == "(":
                depth_paren += 1
            elif char == ")" and depth_paren > 0:
                depth_paren -= 1

        output.append(char)
        original_offsets.append(index)
        index += 1

    return "".join(output), original_offsets


def original_offset_from_cleaned(
    cleaned_offset: int, original_offsets: list[int]
) -> int:
    """Map an offset in comment-stripped text back to the original body."""

    if not original_offsets:
        return 0
    if cleaned_offset >= len(original_offsets):
        return original_offsets[-1] + 1
    return original_offsets[cleaned_offset]


def is_outside_segment_ignorable(segment: str) -> bool:
    """Return whether text outside entries is whitespace or full-line comments."""

    for line in segment.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("%"):
            return False
    return True


def is_at_in_full_line_comment(text: str, at_index: int) -> bool:
    """Return whether an @ marker occurs inside an outside full-line comment."""

    line_start = text.rfind("\n", 0, at_index) + 1
    prefix = text[line_start:at_index].lstrip()
    return prefix.startswith("%")


def find_next_entry_marker(text: str, start: int) -> int:
    """Return the next @ marker that is not inside a full-line comment."""

    index = start
    while True:
        at_index = text.find("@", index)
        if at_index == -1:
            return -1
        if not is_at_in_full_line_comment(text, at_index):
            return at_index
        index = at_index + 1


def split_top_level(text: str, separator: str = ",") -> list[tuple[str, int]]:
    """Split text on top-level separators, preserving segment start offsets.

    In BibTeX, quoted strings and braced values are both valid value forms. A
    double quote inside a braced value is literal text, not the start of a quoted
    string. Therefore, quote tracking is only activated at top level. This avoids
    false positives for long abstracts containing ordinary quotation marks.

    Backslash-escaped braces are treated as brace-like LaTeX content so values
    such as ``{\\{a}}`` remain balanced during top-level splitting.
    """

    parts: list[tuple[str, int]] = []
    depth_brace = 0
    depth_paren = 0
    in_quote = False
    escaped = False
    start = 0
    index = 0

    while index < len(text):
        char = text[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\":
            next_char = text[index + 1] if index + 1 < len(text) else ""
            if not in_quote and next_char in "{}":
                if next_char == "{":
                    depth_brace += 1
                elif next_char == "}" and depth_brace > 0:
                    depth_brace -= 1
                index += 2
                continue
            escaped = True
            index += 1
            continue
        if char == '"' and depth_brace == 0 and depth_paren == 0:
            in_quote = not in_quote
            index += 1
            continue
        if in_quote:
            index += 1
            continue
        if char == "{":
            depth_brace += 1
        elif char == "}" and depth_brace > 0:
            depth_brace -= 1
        elif char == "(":
            depth_paren += 1
        elif char == ")" and depth_paren > 0:
            depth_paren -= 1
        elif (
            char == separator and depth_brace == 0 and depth_paren == 0 and not in_quote
        ):
            parts.append((text[start:index], start))
            start = index + 1
        index += 1

    parts.append((text[start:], start))
    return parts


def find_matching_delimiter(
    text: str, opener_index: int, opener: str, closer: str
) -> int:
    """Return the index of the closing delimiter for a BibTeX entry body.

    Quote tracking is only activated at the first nesting level of the entry.
    Literal quotation marks inside braced field values must not hide the closing
    brace of that field or of the entry.

    Backslash-escaped braces are treated as brace-like LaTeX content for
    balancing purposes. This avoids prematurely closing entries that contain
    exported fragments such as ``{\\{o}}`` in a braced title.
    """

    depth = 1
    in_quote = False
    escaped = False
    index = opener_index + 1

    while index < len(text):
        char = text[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\":
            next_char = text[index + 1] if index + 1 < len(text) else ""
            if not in_quote and next_char in "{}":
                if next_char == opener:
                    depth += 1
                elif next_char == closer:
                    depth -= 1
                    if depth == 0:
                        return index + 1
                index += 2
                continue
            escaped = True
            index += 1
            continue
        if char == '"' and depth == 1:
            in_quote = not in_quote
            index += 1
            continue
        if in_quote:
            index += 1
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
        index += 1

    raise ValueError("Unclosed BibTeX entry.")


def braced_value_has_valid_shape(token: str) -> bool:
    """Return whether a braced BibTeX value is balanced and fully enclosed.

    Quotation marks inside a braced value are literal text. Backslash-escaped
    braces are treated as brace-like LaTeX content for balancing purposes, so
    exported constructs such as ``{\\{a}}`` do not prematurely close the value.
    """

    if not (token.startswith("{") and token.endswith("}") and len(token) >= 2):
        return False

    depth = 0
    escaped = False
    index = 0
    while index < len(token):
        char = token[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\":
            next_char = token[index + 1] if index + 1 < len(token) else ""
            if next_char in "{}":
                if next_char == "{":
                    depth += 1
                elif next_char == "}":
                    depth -= 1
                    if depth == 0 and index + 1 != len(token) - 1:
                        return False
                    if depth < 0:
                        return False
                index += 2
                continue
            escaped = True
            index += 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and index != len(token) - 1:
                return False
            if depth < 0:
                return False
        index += 1
    return depth == 0 and not escaped


class ReferencesBibValidator:
    """Validate references.bib files using a lightweight BibTeX parser."""

    def __init__(self, config: Config) -> None:
        self.config = config

    def validate_target(self, target: Path) -> ValidationResult:
        dataset_path, references_path = self.references_path_for_target(target)
        result = ValidationResult(
            dataset_path=dataset_path,
            references_path=references_path,
            present=references_path.exists(),
        )

        if not references_path.exists():
            if self.config.require:
                self.add_issue(
                    result,
                    "error",
                    "missing_references_bib",
                    None,
                    "Missing required references.bib file.",
                    "Create references.bib or run without --require when bibliography data is optional.",
                )
            return result

        if not references_path.is_file():
            self.add_issue(
                result,
                "error",
                "not_a_file",
                None,
                "references.bib path exists but is not a file.",
                "Replace it with a UTF-8 BibTeX file.",
            )
            return result

        try:
            text = references_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            self.add_issue(
                result,
                "error",
                "invalid_utf8",
                None,
                f"references.bib is not valid UTF-8 text: {exc}.",
                "Save the file as UTF-8.",
            )
            return result
        except OSError as exc:
            raise ReferencesBibError(
                f"Could not read {references_path}: {exc}"
            ) from exc

        self.validate_text(text, result)
        return result

    def references_path_for_target(self, target: Path) -> tuple[Path, Path]:
        if target.is_dir():
            return target, target / "references.bib"

        if target.name == "references.bib":
            return target.parent, target

        if target.exists():
            raise ReferencesBibError(
                f"Expected a dataset folder or references.bib file, got: {target}"
            )

        # If the path does not exist and looks like a file path, report it through
        # the normal missing-file path; otherwise treat it as a dataset folder.
        if target.suffix:
            return target.parent, target
        return target, target / "references.bib"

    def validate_text(self, text: str, result: ValidationResult) -> None:
        if not text.strip():
            self.add_issue(
                result,
                "error",
                "empty_file",
                None,
                "references.bib is empty.",
                "Remove the optional file or add at least one bibliographic entry.",
            )
            return

        try:
            entries = self.parse_entries(text, result)
        except ValueError as exc:
            line, column = line_col(text, len(text))
            self.add_issue(
                result,
                "error",
                "unclosed_entry",
                None,
                str(exc),
                "Check that every @entry{...} or @entry(...) has a matching closing delimiter.",
                line=line,
                column=column,
            )
            return

        seen_keys: dict[str, ParsedEntry] = {}
        regular_entries = 0

        for entry in entries:
            if entry.entry_type in SPECIAL_ENTRY_TYPES:
                self.validate_special_entry(entry, result)
                continue

            regular_entries += 1
            self.validate_regular_entry(entry, result)

            if entry.key:
                lowered_key = entry.key.lower()
                previous = seen_keys.get(lowered_key)
                if previous is not None:
                    self.add_issue(
                        result,
                        "error",
                        "duplicate_key",
                        entry.key,
                        f"Duplicate BibTeX citation key {entry.key!r}.",
                        "Use unique citation keys within references.bib.",
                        line=entry.start_line,
                        column=entry.start_column,
                    )
                else:
                    seen_keys[lowered_key] = entry

        result.entries_checked = regular_entries

        if regular_entries == 0:
            self.add_issue(
                result,
                "error",
                "no_bibliographic_entries",
                None,
                "references.bib does not contain any bibliographic entry.",
                "Add at least one regular entry such as @article, @book, @inproceedings, or @misc.",
            )

    def parse_entries(self, text: str, result: ValidationResult) -> list[ParsedEntry]:
        entries: list[ParsedEntry] = []
        index = 0

        while True:
            at_index = find_next_entry_marker(text, index)
            if at_index == -1:
                trailing = text[index:]
                if not is_outside_segment_ignorable(trailing):
                    line, column = line_col(text, index)
                    self.add_issue(
                        result,
                        "error",
                        "unexpected_text",
                        None,
                        "Unexpected text outside a BibTeX entry.",
                        "Keep only whitespace or full-line comments outside @entry blocks.",
                        line=line,
                        column=column,
                    )
                break

            leading = text[index:at_index]
            if not is_outside_segment_ignorable(leading):
                line, column = line_col(text, index)
                self.add_issue(
                    result,
                    "error",
                    "unexpected_text",
                    None,
                    "Unexpected text outside a BibTeX entry.",
                    "Keep only whitespace or full-line comments outside @entry blocks.",
                    line=line,
                    column=column,
                )

            type_start = at_index + 1
            match = ENTRY_TYPE_RE.match(text, type_start)
            if match is None:
                line, column = line_col(text, at_index)
                self.add_issue(
                    result,
                    "error",
                    "missing_entry_type",
                    None,
                    "Expected an entry type after '@'.",
                    "Use syntax such as @article{key, ...}.",
                    line=line,
                    column=column,
                )
                index = at_index + 1
                continue

            entry_type = match.group(0).lower()
            cursor = match.end()
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1

            if cursor >= len(text) or text[cursor] not in "{(":
                line, column = line_col(text, cursor)
                self.add_issue(
                    result,
                    "error",
                    "missing_entry_body",
                    None,
                    f"Expected '{{' or '(' after @{entry_type}.",
                    "Use syntax such as @article{key, ...}.",
                    line=line,
                    column=column,
                )
                index = cursor + 1
                continue

            opener = text[cursor]
            closer = "}" if opener == "{" else ")"
            try:
                closing_index = find_matching_delimiter(text, cursor, opener, closer)
            except ValueError:
                raise ValueError(
                    f"Unclosed @{entry_type} entry starting at line {line_col(text, at_index)[0]}."
                )

            body = text[cursor + 1 : closing_index]
            line, column = line_col(text, at_index)
            body_line, body_column = line_col(text, cursor + 1)
            entry = ParsedEntry(
                entry_type=entry_type,
                body=body,
                start_index=at_index,
                start_line=line,
                start_column=column,
                body_start_index=cursor + 1,
                body_start_line=body_line,
                body_start_column=body_column,
            )
            entries.append(entry)
            index = closing_index + 1

        return entries

    def validate_special_entry(
        self, entry: ParsedEntry, result: ValidationResult
    ) -> None:
        body = entry.body.strip()
        if not body:
            self.add_issue(
                result,
                "warning",
                "empty_special_entry",
                None,
                f"@{entry.entry_type} entry is empty.",
                "Remove the empty entry or provide content.",
                line=entry.start_line,
                column=entry.start_column,
            )
            return

        if entry.entry_type == "string":
            if "=" not in body:
                self.add_issue(
                    result,
                    "error",
                    "invalid_string_entry",
                    None,
                    "@string must contain a macro assignment.",
                    'Use syntax such as @string{JWS = "Journal of Web Semantics"}.',
                    line=entry.start_line,
                    column=entry.start_column,
                )
                return
            name = body.split("=", 1)[0].strip()
            if FIELD_NAME_RE.fullmatch(name) is None:
                self.add_issue(
                    result,
                    "error",
                    "invalid_string_macro",
                    None,
                    f"Invalid @string macro name {name!r}.",
                    "Use a macro name starting with a letter.",
                    line=entry.start_line,
                    column=entry.start_column,
                )
            value = body.split("=", 1)[1].strip()
            if value and not self.value_has_valid_shape(value):
                self.add_issue(
                    result,
                    "error",
                    "invalid_string_value",
                    None,
                    f"@string macro {name!r} has a malformed value {value!r}.",
                    "Use a braced value, quoted value, number, or BibTeX macro.",
                    line=entry.start_line,
                    column=entry.start_column,
                )

    def validate_regular_entry(
        self, entry: ParsedEntry, result: ValidationResult
    ) -> None:
        if entry.entry_type not in KNOWN_ENTRY_TYPES:
            self.add_issue(
                result,
                "warning",
                "unknown_entry_type",
                None,
                f"Unknown BibTeX/BibLaTeX entry type @{entry.entry_type}.",
                "Check for typos or extend the validator if this entry type is intentionally supported.",
                line=entry.start_line,
                column=entry.start_column,
            )

        cleaned_body, original_offsets = remove_top_level_line_comments(entry.body)
        cleaned_parts = split_top_level(cleaned_body, ",")
        body_parts = [
            (part, original_offset_from_cleaned(offset, original_offsets))
            for part, offset in cleaned_parts
        ]
        key = body_parts[0][0].strip() if body_parts else ""
        object.__setattr__(entry, "key", key)

        if not key:
            self.add_issue(
                result,
                "error",
                "missing_citation_key",
                None,
                f"@{entry.entry_type} entry is missing a citation key.",
                "Use syntax such as @article{citation-key, field = value}.",
                line=entry.start_line,
                column=entry.start_column,
            )
        elif CITATION_KEY_RE.fullmatch(key) is None:
            self.add_issue(
                result,
                "error",
                "invalid_citation_key",
                key,
                f"Invalid citation key {key!r}.",
                "Use a non-empty key without spaces, commas, braces, parentheses, quotes, or '='.",
                line=entry.start_line,
                column=entry.start_column,
            )

        fields = body_parts[1:]
        non_empty_fields = [(part, offset) for part, offset in fields if part.strip()]
        if not non_empty_fields:
            self.add_issue(
                result,
                "error",
                "missing_fields",
                key or None,
                f"@{entry.entry_type} entry {key!r} has no fields.",
                "Add at least one field such as title, author, year, doi, or url.",
                line=entry.start_line,
                column=entry.start_column,
            )
            return

        seen_fields: set[str] = set()
        for raw_field, offset in non_empty_fields:
            self.validate_field(
                raw_field, offset, entry, result, key or None, seen_fields
            )

    def validate_field(
        self,
        raw_field: str,
        offset: int,
        entry: ParsedEntry,
        result: ValidationResult,
        key: Optional[str],
        seen_fields: set[str],
    ) -> None:
        field_text = raw_field.strip()
        leading_whitespace = len(raw_field) - len(raw_field.lstrip())
        field_line, field_column = line_col_in_entry_body(
            entry, offset + leading_whitespace
        )

        if "=" not in field_text:
            self.add_issue(
                result,
                "error",
                "missing_field_assignment",
                key,
                f"Invalid field fragment {field_text!r}; expected name = value.",
                "Separate fields with top-level commas and assign each field with '='.",
                line=field_line,
                column=field_column,
            )
            return

        name, value = field_text.split("=", 1)
        name = name.strip()
        value = value.strip()

        if FIELD_NAME_RE.fullmatch(name) is None:
            name_offset = raw_field.find(name) if name else leading_whitespace
            line, column = line_col_in_entry_body(entry, offset + max(0, name_offset))
            self.add_issue(
                result,
                "error",
                "invalid_field_name",
                key,
                f"Invalid field name {name!r}.",
                "Use a field name starting with a letter and containing only letters, digits, underscores, or hyphens.",
                line=line,
                column=column,
            )
            return

        normalized_name = name.lower()
        if normalized_name in seen_fields:
            self.add_issue(
                result,
                "warning",
                "duplicate_field",
                key,
                f"Duplicate field {name!r} in entry {key!r}.",
                "Keep one value per field.",
                line=field_line,
                column=field_column,
            )
        seen_fields.add(normalized_name)

        if not value:
            self.add_issue(
                result,
                "error",
                "empty_field_value",
                key,
                f"Field {name!r} has an empty value.",
                "Provide a value or remove the field.",
                line=field_line,
                column=field_column,
            )
            return

        if not self.value_has_valid_shape(value):
            self.add_issue(
                result,
                "error",
                "invalid_field_value",
                key,
                f"Field {name!r} has a malformed value {value!r}.",
                "Use a braced value, quoted value, number, or BibTeX macro.",
                line=field_line,
                column=field_column,
            )

    def value_has_valid_shape(self, value: str) -> bool:
        """Check the basic lexical form of a BibTeX field value."""

        # Values may be concatenated with #, e.g. month = jan # " " # feb.
        for part, _offset in split_top_level(value, "#"):
            token = part.strip()
            if not token:
                return False
            if token.startswith("{"):
                if not braced_value_has_valid_shape(token):
                    return False
                continue
            if token.startswith('"'):
                if not self.quoted_value_has_valid_shape(token):
                    return False
                continue
            if token.isdigit():
                continue
            if FIELD_NAME_RE.fullmatch(token):
                continue
            return False
        return True

    def quoted_value_has_valid_shape(self, token: str) -> bool:
        """Return whether a quoted BibTeX value has a balanced quote shape."""

        if not (token.startswith('"') and token.endswith('"') and len(token) >= 2):
            return False

        escaped = False
        for char in token[1:-1]:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                return False
        return not escaped

    def add_issue(
        self,
        result: ValidationResult,
        severity: Severity,
        code: str,
        entry_key: Optional[str],
        message: str,
        suggestion: Optional[str] = None,
        *,
        line: Optional[int] = None,
        column: Optional[int] = None,
    ) -> None:
        if severity == "warning" and self.config.strict:
            severity = "error"
        result.issues.append(
            Issue(
                severity=severity,
                code=code,
                dataset_path=str(result.dataset_path),
                references_path=str(result.references_path) if result.present else None,
                entry_key=entry_key,
                message=message,
                suggestion=suggestion,
                line=line,
                column=column,
            )
        )


def discover_datasets(models_dir: Path) -> list[Path]:
    models_dir = models_dir.resolve()
    if not models_dir.exists():
        raise ReferencesBibError(f"Models directory does not exist: {models_dir}")
    if not models_dir.is_dir():
        raise ReferencesBibError(f"Models path is not a directory: {models_dir}")
    return sorted(path for path in models_dir.iterdir() if path.is_dir())


def resolve_targets(args: argparse.Namespace) -> list[Path]:
    if args.all:
        if args.targets:
            raise ReferencesBibError(
                "Use either --all or explicit dataset folders/files, not both."
            )
        return discover_datasets(args.models_dir)

    if args.targets:
        targets = [Path(path) for path in args.targets]
        missing = [path for path in targets if not path.exists()]
        if missing:
            joined = ", ".join(str(path) for path in missing)
            raise ReferencesBibError(f"Input path does not exist: {joined}")
        return targets

    cwd = Path.cwd()
    if (cwd / "references.bib").exists():
        return [cwd / "references.bib"]
    if (cwd / "metadata.yaml").exists():
        return [cwd]

    raise ReferencesBibError(
        "No target provided. Pass one or more dataset folders/references.bib files, use --all, or run from a dataset folder."
    )


def format_text(results: Sequence[ValidationResult]) -> str:
    lines: list[str] = []
    for result in results:
        if not result.present and result.valid:
            status = "SKIPPED"
        else:
            status = "VALID" if result.valid else "INVALID"
        lines.append(f"{status}: {result.dataset_path}")
        lines.append(f"  references: {result.references_path}")
        if result.present:
            lines.append(f"  entries checked: {result.entries_checked}")
        else:
            lines.append("  optional file not present")
        for issue in result.errors:
            location = format_location(issue)
            lines.append(f"  ERROR   {location}{issue.code}: {issue.message}")
            if issue.suggestion:
                lines.append(f"          fix: {issue.suggestion}")
        for issue in result.warnings:
            location = format_location(issue)
            lines.append(f"  WARNING {location}{issue.code}: {issue.message}")
            if issue.suggestion:
                lines.append(f"          fix: {issue.suggestion}")

    total = len(results)
    present = sum(1 for result in results if result.present)
    errors = sum(len(result.errors) for result in results)
    warnings = sum(len(result.warnings) for result in results)
    entries = sum(result.entries_checked for result in results)
    lines.append(
        f"Summary: {total} checked, {present} file(s) present, {entries} bibliographic entries, {errors} error(s), {warnings} warning(s)."
    )
    return "\n".join(lines)


def format_location(issue: Issue) -> str:
    parts: list[str] = []
    if issue.entry_key:
        parts.append(f"{issue.entry_key}")
    if issue.line is not None:
        location = f"line {issue.line}"
        if issue.column is not None:
            location += f", column {issue.column}"
        parts.append(location)
    return f"{' @ '.join(parts)} [{issue.code}] " if parts else f"[{issue.code}] "


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate optional references.bib files for OntoUML/UFO Catalog datasets.",
    )
    parser.add_argument(
        "targets",
        nargs="*",
        type=Path,
        help="Dataset folder(s) or references.bib file(s) to validate. If omitted, the current directory is used when it contains references.bib or metadata.yaml.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Validate references.bib files for all direct dataset folders below --models-dir.",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=Path("models"),
        help="Models directory used with --all. Default: models.",
    )
    parser.add_argument(
        "--require",
        action="store_true",
        help="Report missing references.bib files as errors. By default, missing references.bib files are accepted because the file is optional.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format. Default: text.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Promote warnings to errors.",
    )
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Return exit code 1 when warnings are present, without changing their reported severity.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        targets = resolve_targets(args)
        config = Config(
            require=args.require,
            strict=args.strict,
            fail_on_warning=args.fail_on_warning,
        )
        validator = ReferencesBibValidator(config)
        results = [validator.validate_target(target) for target in targets]
    except ReferencesBibError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(
            json.dumps(
                [result.to_dict() for result in results],
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(format_text(results))

    has_errors = any(result.errors for result in results)
    has_warnings = any(result.warnings for result in results)
    if has_errors or (args.fail_on_warning and has_warnings):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

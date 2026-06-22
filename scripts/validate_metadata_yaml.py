"""Validate, lint, and safely fix OntoUML/UFO Catalog metadata.yaml files.

The validator is intended for repository maintenance and later CI/workflow use. It
checks one or more dataset folders, or all direct dataset folders below models/,
without requiring network access.

Typical usage from the repository root:

    python scripts/validate_metadata_yaml.py models/amaral2019rot
    python scripts/validate_metadata_yaml.py models/a models/b
    python scripts/validate_metadata_yaml.py --all --models-dir models
    python scripts/validate_metadata_yaml.py models/example --fix
    python scripts/validate_metadata_yaml.py --all --format json

Exit codes:

    0  no validation errors were found
    1  validation errors were found
    2  command-line, discovery, or write problem prevented normal execution

Warnings do not affect the exit code unless --fail-on-warning or --strict is used.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Optional, Sequence
from urllib.parse import urlparse

try:
    import yaml
except (
    ImportError
) as exc:  # pragma: no cover - exercised only when dependency is missing
    raise SystemExit(
        "PyYAML is required. Install it with: python -m pip install -r scripts/requirements.txt"
    ) from exc

Severity = Literal["error", "warning"]
UnknownPolicy = Literal["error", "warning", "ignore"]
OutputFormat = Literal["text", "json"]


class MetadataYamlError(RuntimeError):
    """Raised when validation cannot continue because of a tool/setup problem."""


@dataclass(frozen=True)
class Issue:
    """One validation or lint issue."""

    severity: Severity
    code: str
    dataset_path: str
    metadata_path: Optional[str]
    field: Optional[str]
    message: str
    suggestion: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Fix:
    """One deterministic fix planned or applied by the tool."""

    code: str
    dataset_path: str
    metadata_path: str
    field: Optional[str]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationResult:
    """Validation result for one dataset folder."""

    dataset_path: Path
    metadata_path: Path
    issues: list[Issue] = field(default_factory=list)
    fixes: list[Fix] = field(default_factory=list)
    changed: bool = False

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
            "metadata_path": str(self.metadata_path),
            "valid": self.valid,
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "fixes": [fix.to_dict() for fix in self.fixes],
            "changed": self.changed,
        }


@dataclass(frozen=True)
class Config:
    """Runtime configuration."""

    fix: bool = False
    dry_run: bool = False
    strict: bool = False
    fail_on_warning: bool = False
    unknown_fields: UnknownPolicy = "error"
    missing_expected_fields: UnknownPolicy = "warning"


class MetadataYamlLoader(yaml.SafeLoader):
    """Safe YAML loader that preserves date lexical values and rejects duplicate keys."""


# Preserve timestamp/date scalars as strings. This mirrors metadata_yaml_to_ttl.py
# and avoids rewriting date lexical forms such as nanosecond timestamps.
MetadataYamlLoader.yaml_implicit_resolvers = {
    key: [
        resolver
        for resolver in resolvers
        if resolver[0] != "tag:yaml.org,2002:timestamp"
    ]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _construct_mapping_no_duplicates(
    loader: MetadataYamlLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
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


MetadataYamlLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping_no_duplicates,
)


# The current catalog examples still use these field names. The converter also
# accepts snake_case aliases, but this script preserves the repository-facing
# metadata.yaml template unless the source already uses a supported alias.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "iri": ("iri", "uri", "model_iri", "modelIri", "identifier", "id"),
    "title": ("title", "dct:title"),
    "alternative": (
        "alternative",
        "alternative_title",
        "alternativeTitle",
        "dct:alternative",
    ),
    "description": ("description", "dct:description"),
    "issued": ("issued", "dct:issued"),
    "modified": ("modified", "dct:modified"),
    "license": ("license", "dct:license"),
    "access_rights": ("access_rights", "accessRights", "dct:accessRights"),
    "editorial_note": ("editorialNote", "editorial_note", "skos:editorialNote"),
    "creator": ("creator", "creators", "dct:creator"),
    "contributor": ("contributor", "contributors", "dct:contributor"),
    "publisher": ("publisher", "dct:publisher"),
    "metadata_issued": ("metadata_issued", "metadataIssued", "fdpo:metadataIssued"),
    "metadata_modified": (
        "metadata_modified",
        "metadataModified",
        "fdpo:metadataModified",
    ),
    "landing_page": ("landingPage", "landing_page", "dcat:landingPage"),
    "bibliographic_citation": (
        "bibliographic_citation",
        "bibliographicCitation",
        "dct:bibliographicCitation",
    ),
    "storage_url": ("storage_url", "storageUrl", "ocmv:storageUrl"),
    "contact_points": ("contact_points", "contactPoints", "dcat:contactPoint"),
    "keyword": ("keyword", "keywords", "dcat:keyword"),
    "acronym": ("acronym", "mod:acronym"),
    "source": ("source", "sources", "dct:source"),
    "language": ("language", "languages", "dct:language"),
    "theme": ("theme", "dcat:theme"),
    "designed_for_task": (
        "designedForTask",
        "designed_for_task",
        "mod:designedForTask",
    ),
    "context": ("context", "ocmv:context"),
    "representation_style": (
        "representationStyle",
        "representation_style",
        "ocmv:representationStyle",
    ),
    "ontology_type": ("ontologyType", "ontology_type", "ocmv:ontologyType"),
    "is_part_of": ("is_part_of", "isPartOf", "dct:isPartOf"),
    "distribution": ("distribution", "distributions", "dcat:distribution"),
}

PREFERRED_FIELD_NAME: dict[str, str] = {
    canonical: aliases[0] for canonical, aliases in FIELD_ALIASES.items()
}

# Fields expected by the repository's model-level metadata template. Required
# fields are errors when missing; other expected fields are warnings by default.
EXPECTED_TEMPLATE_FIELDS: tuple[str, ...] = (
    "title",
    "acronym",
    "issued",
    "modified",
    "contributor",
    "keyword",
    "theme",
    "editorial_note",
    "ontology_type",
    "language",
    "designed_for_task",
    "context",
    "source",
    "representation_style",
    "landing_page",
    "license",
)

# Minimum mandatory fields aligned with scripts/metadata_yaml_to_ttl.py and the
# metadata YAML documentation.
REQUIRED_VALUE_FIELDS: tuple[str, ...] = (
    "title",
    "issued",
    "license",
    "theme",
    "keyword",
)

LIST_FIELDS: set[str] = {
    "contributor",
    "creator",
    "source",
    "keyword",
    "designed_for_task",
    "context",
    "representation_style",
    "ontology_type",
    "distribution",
}

SINGLE_URI_FIELDS: set[str] = {
    "iri",
    "license",
    "publisher",
    "landing_page",
    "storage_url",
    "is_part_of",
}

LITERAL_FIELDS: set[str] = {
    "title",
    "alternative",
    "description",
    "editorial_note",
    "bibliographic_citation",
    "keyword",
    "acronym",
}

DATE_FIELDS: set[str] = {"issued", "modified", "metadata_issued", "metadata_modified"}

URL_LIST_FIELDS: set[str] = {"contributor", "creator", "source"}

DESIGNED_FOR_TASKS: dict[str, str] = {
    "conceptualclarification": "conceptual clarification",
    "datapublication": "data publication",
    "decisionsupportsystem": "decision support system",
    "example": "example",
    "informationretrieval": "information retrieval",
    "interoperability": "interoperability",
    "languageengineering": "language engineering",
    "learning": "learning",
    "ontologicalanalysis": "ontological analysis",
    "softwareengineering": "software engineering",
}
CONTEXTS: dict[str, str] = {
    "research": "research",
    "industry": "industry",
    "classroom": "classroom",
}
REPRESENTATION_STYLES: dict[str, str] = {
    "ontouml": "ontouml",
    "ontoumlstyle": "ontouml",
    "ufo": "ufo",
    "ufostyle": "ufo",
}
ONTOLOGY_TYPES: dict[str, str] = {
    "core": "core",
    "domain": "domain",
    "application": "application",
}
CONTROLLED_VALUES: dict[str, dict[str, str]] = {
    "designed_for_task": DESIGNED_FOR_TASKS,
    "context": CONTEXTS,
    "representation_style": REPRESENTATION_STYLES,
    "ontology_type": ONTOLOGY_TYPES,
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

ALIAS_TO_CANONICAL: dict[str, str] = {
    alias: canonical
    for canonical, aliases in FIELD_ALIASES.items()
    for alias in aliases
}
KNOWN_KEYS: set[str] = set(ALIAS_TO_CANONICAL)

DATE_YEAR_RE = re.compile(r"^\d{4}$")
DATE_YEAR_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
DATE_TIME_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T"
    r"(\d{2}):(\d{2}):(\d{2})"
    r"(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2})?$"
)
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
ORCID_RE = re.compile(r"^https?://orcid\.org/\d{4}-\d{4}-\d{4}-[\dX]{4}$", re.I)
DBLP_RE = re.compile(r"^https?://dblp\.org/(pid|rec)/.+", re.I)
DOI_URL_RE = re.compile(r"^https?://doi\.org/10\..+", re.I)
LCC_URI_RE = re.compile(
    r"^https?://id\.loc\.gov/authorities/classification/([A-Z][A-Z0-9.-]*)/?$", re.I
)
LCC_LABEL_RE = re.compile(r"^Class\s+([A-Z])\s+-\s+(.+)$", re.I)
OCMV_BASE_URI = "https://w3id.org/ontouml-models/vocabulary#"

LICENSE_ALIASES: dict[str, str] = {
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


def canonical_token(value: Any) -> str:
    """Normalize a token for lenient comparison with controlled values."""

    if isinstance(value, str):
        text = value.strip()
        if text.startswith("ocmv:"):
            text = text.split(":", 1)[1]
        elif text.startswith(OCMV_BASE_URI):
            text = text[len(OCMV_BASE_URI) :]
        value = text
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return len(value) == 0
    return False


def scalar_text(value: Any) -> str:
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    return str(value).strip()


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def is_http_uri(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def valid_date_like(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    text = scalar_text(value)
    if DATE_YEAR_RE.fullmatch(text):
        year = int(text)
        return 1000 <= year <= 9999
    year_month = DATE_YEAR_MONTH_RE.fullmatch(text)
    if year_month:
        try:
            _dt.date(int(year_month.group(1)), int(year_month.group(2)), 1)
            return True
        except ValueError:
            return False
    date_match = DATE_RE.fullmatch(text)
    if date_match:
        try:
            _dt.date.fromisoformat(text)
            return True
        except ValueError:
            return False
    date_time = DATE_TIME_RE.fullmatch(text)
    if date_time:
        try:
            date_part = date_time.group(1)
            _dt.date.fromisoformat(date_part)
            hour, minute, second = map(int, date_time.group(2, 3, 4))
            _dt.time(hour, minute, second)
            return True
        except ValueError:
            return False
    return False


def lcc_label_for_code(code: str) -> Optional[str]:
    """Return the repository-style LCC class label for a compact class code."""

    compact = code.strip().strip("/").upper()
    if not compact:
        return None
    class_code = compact[0]
    label = LCC_CLASSES.get(class_code)
    if label is None:
        return None
    return f"Class {class_code} - {label}"


def normalize_theme_value(
    value: Any,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return normalized theme, warning, error.

    The normalized value follows the original repository's metadata.yaml style,
    e.g. ``Class H - Social Sciences``. Compact values such as ``H`` or
    ``lcc:H`` and id.loc.gov URIs are accepted, but ``--fix`` expands them to
    the full class label used in existing catalog metadata files.
    """

    if not isinstance(value, str):
        return None, None, "Expected a single Library of Congress Classification value."
    text = value.strip()
    if not text:
        return (
            None,
            None,
            "Expected a non-empty Library of Congress Classification value.",
        )

    uri_match = LCC_URI_RE.fullmatch(text)
    if uri_match:
        label = lcc_label_for_code(uri_match.group(1))
        if label is None:
            return (
                None,
                None,
                f"Unsupported Library of Congress Classification code {uri_match.group(1)!r}.",
            )
        return (
            label,
            "Use the full LCC class label used by the catalog metadata.yaml files.",
            None,
        )

    label_match = LCC_LABEL_RE.fullmatch(text)
    if label_match:
        code = label_match.group(1).upper()
        label = label_match.group(2).strip()
        canonical_label = LCC_CLASSES.get(code)
        if canonical_label is None:
            return (
                None,
                None,
                f"Unsupported Library of Congress Classification code {code!r}.",
            )
        normalized = f"Class {code} - {canonical_label}"
        if label.casefold() != canonical_label.casefold():
            return (
                normalized,
                f"The LCC label differs from the canonical label {canonical_label!r}.",
                None,
            )
        if text != normalized:
            return (
                normalized,
                "Use the canonical capitalization of the full LCC class label.",
                None,
            )
        return normalized, None, None

    if text.lower().startswith("lcc:"):
        text = text.split(":", 1)[1]
    code = text.strip("/").upper()
    if re.fullmatch(r"[A-Z][A-Z0-9.-]*", code):
        label = lcc_label_for_code(code)
        if label is not None:
            return (
                label,
                "Use the full LCC class label used by the catalog metadata.yaml files.",
                None,
            )
    return (
        None,
        None,
        "Expected an LCC code such as 'H', 'lcc:H', an id.loc.gov LCC URI, or an existing catalog label such as 'Class H - Social Sciences'.",
    )


def literal_has_value(value: Any) -> bool:
    """Return whether a literal-compatible value contains at least one text value."""

    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        if "value" in value:
            return literal_has_value(value.get("value"))
        return any(literal_has_value(v) for v in value.values())
    if isinstance(value, list):
        return any(literal_has_value(item) for item in value)
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float))


def literal_type_issues(value: Any, field_name: str) -> list[tuple[str, str]]:
    """Return (field_path, message) pairs for unsupported literal syntax."""

    issues: list[tuple[str, str]] = []

    def visit(item: Any, path: str) -> None:
        if item is None:
            return
        if isinstance(item, bool):
            issues.append(
                (path, "Expected a string or language-tagged literal, not a boolean.")
            )
            return
        if isinstance(item, (str, int, float)):
            return
        if isinstance(item, list):
            for index, nested in enumerate(item):
                visit(nested, f"{path}[{index}]")
            return
        if isinstance(item, Mapping):
            if "value" in item:
                value_item = item.get("value")
                if isinstance(value_item, bool) or not isinstance(
                    value_item, (str, int, float)
                ):
                    issues.append(
                        (
                            f"{path}.value",
                            "Literal mapping field 'value' must be a string or scalar literal value.",
                        )
                    )
                lang = item.get("lang") or item.get("language")
                datatype = item.get("datatype")
                if lang and datatype:
                    issues.append(
                        (
                            path,
                            "Literal mappings must not define both 'lang' and 'datatype'.",
                        )
                    )
                return
            for key, nested in item.items():
                if not isinstance(key, str) or not LANGUAGE_RE.fullmatch(key.strip()):
                    issues.append(
                        (
                            f"{path}.{key}",
                            "Language-map keys must be language tags such as 'en' or 'pt-BR'.",
                        )
                    )
                if isinstance(nested, bool) or not isinstance(
                    nested, (str, int, float)
                ):
                    issues.append(
                        (
                            f"{path}.{key}",
                            "Language-map values must be string or scalar literal values.",
                        )
                    )
            return
        issues.append((path, f"Unsupported literal value type: {type(item).__name__}."))

    visit(value, field_name)
    return issues


def title_language_buckets(value: Any) -> list[Optional[str]]:
    """Return language buckets for title values to detect duplicates."""

    buckets: list[Optional[str]] = []
    for item in as_list(value):
        if isinstance(item, Mapping):
            if "value" in item:
                lang = item.get("lang") or item.get("language")
                buckets.append(str(lang) if lang else None)
            else:
                for lang in item.keys():
                    buckets.append(str(lang))
        else:
            buckets.append(None)
    return buckets


class MetadataYamlValidator:
    """Validator/fixer for one or more metadata.yaml files."""

    def __init__(self, config: Config) -> None:
        self.config = config

    def validate_dataset(self, dataset_path: Path) -> ValidationResult:
        dataset_path = dataset_path.resolve()
        metadata_path = (
            dataset_path
            if dataset_path.name == "metadata.yaml"
            else dataset_path / "metadata.yaml"
        )
        result = ValidationResult(
            dataset_path=_dataset_for_metadata_path(metadata_path),
            metadata_path=metadata_path,
        )

        if not metadata_path.exists():
            self.add_issue(
                result,
                "error",
                "missing_file",
                None,
                "metadata.yaml is missing for this dataset.",
                "Create metadata.yaml using the catalog template before generating metadata.ttl.",
            )
            return result
        if not metadata_path.is_file():
            self.add_issue(
                result,
                "error",
                "not_a_file",
                None,
                "metadata.yaml exists but is not a regular file.",
                "Replace it with a regular YAML file.",
            )
            return result

        try:
            data = self.read_yaml(metadata_path)
        except yaml.YAMLError as exc:
            self.add_issue(
                result,
                "error",
                "invalid_yaml",
                None,
                f"metadata.yaml is not valid YAML: {exc}",
                "Fix YAML syntax before running validation again.",
            )
            return result
        except OSError as exc:
            self.add_issue(
                result,
                "error",
                "read_error",
                None,
                f"Could not read metadata.yaml: {exc}",
                "Check file permissions and encoding.",
            )
            return result

        if not isinstance(data, dict):
            self.add_issue(
                result,
                "error",
                "root_not_mapping",
                None,
                "metadata.yaml must contain a YAML mapping/object at the root.",
                "Use top-level key-value pairs such as title, issued, keyword, theme, and license.",
            )
            return result

        changed_data = self.validate_mapping(data, result)
        if self.config.fix and result.changed and not self.config.dry_run:
            try:
                write_yaml(metadata_path, changed_data)
            except OSError as exc:
                raise MetadataYamlError(
                    f"Could not write fixed metadata.yaml {metadata_path}: {exc}"
                ) from exc

        return result

    def read_yaml(self, metadata_path: Path) -> Any:
        with metadata_path.open("r", encoding="utf-8-sig") as stream:
            return yaml.load(stream, Loader=MetadataYamlLoader)

    def validate_mapping(
        self, data: dict[Any, Any], result: ValidationResult
    ) -> OrderedDict[str, Any]:
        output: OrderedDict[str, Any] = OrderedDict()
        canonical_to_original: dict[str, str] = {}
        canonical_values: dict[str, Any] = {}
        unknown_items: list[tuple[Any, Any]] = []

        for original_key, value in data.items():
            if not isinstance(original_key, str):
                self.add_issue(
                    result,
                    "error",
                    "non_string_key",
                    None,
                    f"Top-level key {original_key!r} must be a string.",
                    "Rename the key to a string field name.",
                )
                continue

            canonical = ALIAS_TO_CANONICAL.get(original_key)
            if canonical is None:
                unknown_items.append((original_key, value))
                self.handle_unknown_field(result, original_key)
                output[original_key] = value
                continue

            preferred = PREFERRED_FIELD_NAME[canonical]
            if canonical in canonical_to_original:
                previous = canonical_to_original[canonical]
                self.add_issue(
                    result,
                    "error",
                    "duplicate_alias_field",
                    preferred,
                    f"Both {previous!r} and {original_key!r} refer to the same metadata field.",
                    "Keep only one spelling of the field before fixing or converting metadata.",
                )
                output[original_key] = value
                continue

            canonical_to_original[canonical] = original_key
            canonical_values[canonical] = value
            output_key = preferred if self.config.fix else original_key
            if self.config.fix and output_key != original_key:
                self.add_fix(
                    result,
                    "rename_field",
                    preferred,
                    f"Renamed field {original_key!r} to repository-preferred field {preferred!r}.",
                )
            output[output_key] = value

        # Missing expected fields are inserted in template order only in fix mode.
        for canonical in EXPECTED_TEMPLATE_FIELDS:
            if canonical not in canonical_values:
                if (
                    canonical not in REQUIRED_VALUE_FIELDS
                    and self.config.missing_expected_fields == "ignore"
                ):
                    continue
                severity = self.missing_expected_severity(canonical)
                self.add_issue(
                    result,
                    severity,
                    "missing_field",
                    PREFERRED_FIELD_NAME[canonical],
                    f"Expected metadata field {PREFERRED_FIELD_NAME[canonical]!r} is missing.",
                    "Add the field. Use null only when the information is genuinely unavailable."
                    if canonical not in REQUIRED_VALUE_FIELDS
                    else "Add a non-empty value for this mandatory field.",
                )
                if self.config.fix and canonical not in REQUIRED_VALUE_FIELDS:
                    self.insert_missing_expected_field(output, canonical, result)

        # Validate and possibly normalize present values.
        for canonical, value in list(canonical_values.items()):
            preferred = PREFERRED_FIELD_NAME[canonical]
            self.validate_field(canonical, value, result)
            if (
                self.config.fix
                and canonical in canonical_values
                and preferred in output
            ):
                fixed, changed, message = self.safe_fix_value(
                    canonical, output[preferred]
                )
                if changed:
                    output[preferred] = fixed
                    self.add_fix(result, "normalize_value", preferred, message)

        if self.config.fix:
            # Reorder template fields first to reduce churn and keep deterministic output.
            output = self.reorder_output(output)

        return output

    def handle_unknown_field(self, result: ValidationResult, key: str) -> None:
        if self.config.unknown_fields == "ignore":
            return
        self.add_issue(
            result,
            "error" if self.config.unknown_fields == "error" else "warning",
            "unexpected_field",
            key,
            f"Unexpected top-level field {key!r}.",
            "Check for typos or add the field to the validator if the schema was intentionally extended.",
        )

    def missing_expected_severity(self, canonical: str) -> Severity:
        if canonical in REQUIRED_VALUE_FIELDS:
            return "error"
        if self.config.strict or self.config.missing_expected_fields == "error":
            return "error"
        return "warning"

    def insert_missing_expected_field(
        self, output: OrderedDict[str, Any], canonical: str, result: ValidationResult
    ) -> None:
        preferred = PREFERRED_FIELD_NAME[canonical]
        if preferred not in output:
            output[preferred] = None
            self.add_fix(
                result,
                "add_missing_optional_field",
                preferred,
                f"Added missing expected optional field {preferred!r} with null value.",
            )

    def validate_field(
        self, canonical: str, value: Any, result: ValidationResult
    ) -> None:
        preferred = PREFERRED_FIELD_NAME[canonical]

        if canonical in REQUIRED_VALUE_FIELDS and is_missing_value(value):
            self.add_issue(
                result,
                "error",
                "missing_value",
                preferred,
                f"Mandatory field {preferred!r} must have a non-empty value.",
                "Provide a value; the tool does not guess mandatory metadata.",
            )
            return

        if value is None:
            return

        if canonical in LITERAL_FIELDS:
            self.validate_literal_field(canonical, value, result)
        if canonical in DATE_FIELDS:
            self.validate_date_field(preferred, value, result)
        if canonical in SINGLE_URI_FIELDS:
            self.validate_single_uri_field(canonical, value, result)
        if canonical in URL_LIST_FIELDS:
            self.validate_url_list_field(canonical, value, result)
        if canonical in CONTROLLED_VALUES:
            self.validate_controlled_list_field(canonical, value, result)
        if canonical == "theme":
            self.validate_theme_field(value, result)
        if canonical == "language":
            self.validate_language_field(value, result)
        if canonical == "contact_points":
            self.validate_contact_points(value, result)
        if canonical == "publisher" and isinstance(value, list) and len(value) > 1:
            self.add_issue(
                result,
                "error",
                "too_many_values",
                preferred,
                "Publisher must have at most one URI.",
            )

    def validate_literal_field(
        self, canonical: str, value: Any, result: ValidationResult
    ) -> None:
        preferred = PREFERRED_FIELD_NAME[canonical]
        if canonical == "keyword" and not isinstance(value, list):
            self.add_issue(
                result,
                "warning",
                "scalar_should_be_list",
                preferred,
                "keyword is expected as a list, even when there is only one keyword.",
                "Use a YAML list. The --fix option can wrap the scalar in a list.",
            )
        for field_path, message in literal_type_issues(value, preferred):
            self.add_issue(result, "error", "invalid_literal_type", field_path, message)
        if not literal_has_value(value):
            severity = "error" if canonical in REQUIRED_VALUE_FIELDS else "warning"
            self.add_issue(
                result,
                severity,
                "empty_literal",
                preferred,
                "Expected at least one non-empty literal value.",
                "Provide a non-empty string or language-tagged literal.",
            )
        if canonical == "title":
            seen: set[Optional[str]] = set()
            for bucket in title_language_buckets(value):
                if bucket in seen:
                    label = bucket or "no language tag"
                    self.add_issue(
                        result,
                        "error",
                        "duplicate_title_language",
                        preferred,
                        f"Title has more than one value for language bucket {label!r}.",
                        "Keep at most one title per language.",
                    )
                    break
                seen.add(bucket)

    def validate_date_field(
        self, field_name: str, value: Any, result: ValidationResult
    ) -> None:
        if not valid_date_like(value):
            self.add_issue(
                result,
                "error",
                "invalid_date",
                field_name,
                "Expected YYYY, YYYY-MM, YYYY-MM-DD, or an xsd:dateTime-like value.",
                "Use a valid calendar date or year, preserving existing FDP timestamp lexical forms where needed.",
            )

    def validate_single_uri_field(
        self, canonical: str, value: Any, result: ValidationResult
    ) -> None:
        preferred = PREFERRED_FIELD_NAME[canonical]
        if isinstance(value, list):
            if len(value) == 1:
                if self.config.fix:
                    value = value[0]
                else:
                    self.add_issue(
                        result,
                        "error",
                        "single_uri_as_list",
                        preferred,
                        f"{preferred!r} must be a single HTTP(S) URI, not a one-item list.",
                        "Use a scalar URI value. The --fix option can unwrap a one-item list safely.",
                    )
                    return
            else:
                self.add_issue(
                    result,
                    "error",
                    "invalid_type",
                    preferred,
                    f"{preferred!r} must be a single HTTP(S) URI, not a list with {len(value)} values.",
                    "Keep exactly one URI value; this cannot be fixed automatically because choosing one value would be unsafe.",
                )
                return
        if canonical == "theme":
            return
        if not isinstance(value, str) or not value.strip():
            self.add_issue(
                result,
                "error",
                "invalid_type",
                preferred,
                "Expected a non-empty URI string.",
            )
            return
        if canonical == "license":
            alias = LICENSE_ALIASES.get(canonical_token(value))
            if alias:
                self.add_issue(
                    result,
                    "warning",
                    "license_alias",
                    preferred,
                    f"License alias {value!r} is accepted only as a fixable shorthand.",
                    f"Use the license URI {alias}.",
                )
                return
        if canonical == "iri":
            text = value.strip()
            if is_http_uri(text):
                return
            if ":" in text or not re.fullmatch(r"[A-Za-z0-9._/-]+", text):
                self.add_issue(
                    result,
                    "error",
                    "invalid_uri_or_slug",
                    preferred,
                    "Expected an absolute HTTP(S) URI or a local slug without a URI prefix.",
                    "Use a persistent HTTP(S) model IRI when available, or a simple dataset slug.",
                )
            return
        if not is_http_uri(value):
            self.add_issue(
                result,
                "error",
                "invalid_uri",
                preferred,
                "Expected an absolute HTTP(S) URI.",
                "Use a persistent HTTP(S) identifier where possible.",
            )

    def validate_url_list_field(
        self, canonical: str, value: Any, result: ValidationResult
    ) -> None:
        preferred = PREFERRED_FIELD_NAME[canonical]
        if not isinstance(value, list):
            self.add_issue(
                result,
                "warning",
                "scalar_should_be_list",
                preferred,
                f"{preferred!r} is expected as a list, even when there is only one value.",
                "Use a YAML list. The --fix option can wrap the scalar in a list.",
            )
        seen: set[str] = set()
        for index, item in enumerate(as_list(value)):
            field = f"{preferred}[{index}]" if isinstance(value, list) else preferred
            if not isinstance(item, str) or not item.strip():
                self.add_issue(
                    result,
                    "error",
                    "invalid_type",
                    field,
                    "Expected a non-empty URI string.",
                )
                continue
            text = item.strip()
            if not is_http_uri(text):
                self.add_issue(
                    result,
                    "error",
                    "invalid_uri",
                    field,
                    "Expected an absolute HTTP(S) URI.",
                )
                continue
            if text in seen:
                self.add_issue(
                    result, "warning", "duplicate_uri", field, "Duplicate URI value."
                )
            seen.add(text)
            if canonical in {"creator", "contributor"} and not (
                ORCID_RE.match(text) or DBLP_RE.match(text)
            ):
                self.add_issue(
                    result,
                    "warning",
                    "non_pid_agent_uri",
                    field,
                    "Agent URI is valid, but DBLP or ORCID identifiers are preferred when available.",
                )
            if canonical == "source" and not (
                DOI_URL_RE.match(text) or DBLP_RE.match(text)
            ):
                self.add_issue(
                    result,
                    "warning",
                    "non_persistent_source_uri",
                    field,
                    "Source URI is valid, but DOI or DBLP identifiers are preferred for bibliographic sources.",
                )

    def validate_controlled_list_field(
        self, canonical: str, value: Any, result: ValidationResult
    ) -> None:
        preferred = PREFERRED_FIELD_NAME[canonical]
        allowed = CONTROLLED_VALUES[canonical]
        if not isinstance(value, list):
            self.add_issue(
                result,
                "warning",
                "scalar_should_be_list",
                preferred,
                f"{preferred!r} is expected as a list, even when there is only one value.",
                "Use a YAML list. The --fix option can wrap the scalar in a list.",
            )
        values = as_list(value)
        if not values and canonical in REQUIRED_VALUE_FIELDS:
            self.add_issue(
                result,
                "error",
                "empty_list",
                preferred,
                "Expected at least one controlled value.",
            )
            return
        seen: set[str] = set()
        for index, item in enumerate(values):
            field = f"{preferred}[{index}]" if isinstance(value, list) else preferred
            if not isinstance(item, str) or not item.strip():
                self.add_issue(
                    result,
                    "error",
                    "invalid_type",
                    field,
                    "Expected a non-empty controlled-value string.",
                )
                continue
            token = canonical_token(item)
            if token not in allowed:
                self.add_issue(
                    result,
                    "error",
                    "invalid_controlled_value",
                    field,
                    f"Unexpected value {item!r}.",
                    "Allowed values: " + ", ".join(sorted(set(allowed.values()))),
                )
            if token in seen:
                self.add_issue(
                    result,
                    "warning",
                    "duplicate_controlled_value",
                    field,
                    "Duplicate controlled value.",
                )
            seen.add(token)

    def validate_theme_field(self, value: Any, result: ValidationResult) -> None:
        preferred = PREFERRED_FIELD_NAME["theme"]
        if isinstance(value, list):
            self.add_issue(
                result,
                "error",
                "invalid_type",
                preferred,
                "theme must contain exactly one scalar LCC value, not a list.",
                "Use a single compact LCC code such as H.",
            )
            return
        normalized, warning, error = normalize_theme_value(value)
        if error:
            self.add_issue(result, "error", "invalid_theme", preferred, error)
        elif warning:
            self.add_issue(
                result,
                "warning",
                "non_canonical_theme",
                preferred,
                warning,
                f"Use theme: {normalized}.",
            )

    def validate_language_field(self, value: Any, result: ValidationResult) -> None:
        preferred = PREFERRED_FIELD_NAME["language"]
        values = value if isinstance(value, list) else [value]
        if not values:
            self.add_issue(
                result,
                "error",
                "missing_value",
                preferred,
                "Expected at least one language tag.",
            )
            return
        for index, item in enumerate(values):
            field = f"{preferred}[{index}]" if isinstance(value, list) else preferred
            if not isinstance(item, str) or not LANGUAGE_RE.fullmatch(item.strip()):
                self.add_issue(
                    result,
                    "error",
                    "invalid_language",
                    field,
                    "Expected a BCP 47/IANA-like language tag such as 'en', 'pt-BR', or 'en-GB'.",
                )

    def validate_contact_points(self, value: Any, result: ValidationResult) -> None:
        preferred = PREFERRED_FIELD_NAME["contact_points"]
        for index, item in enumerate(as_list(value)):
            field = f"{preferred}[{index}]"
            if not isinstance(item, Mapping):
                self.add_issue(
                    result,
                    "error",
                    "invalid_type",
                    field,
                    "Each contact point must be a mapping.",
                )
                continue
            email = (
                item.get("email") or item.get("hasEmail") or item.get("vcard:hasEmail")
            )
            if not isinstance(email, str) or not email.strip():
                self.add_issue(
                    result,
                    "error",
                    "missing_email",
                    field,
                    "Contact point is missing a non-empty email value.",
                )

    def safe_fix_value(self, canonical: str, value: Any) -> tuple[Any, bool, str]:
        preferred = PREFERRED_FIELD_NAME[canonical]
        changed = False
        fixed = value

        if (
            canonical in SINGLE_URI_FIELDS
            and isinstance(fixed, list)
            and len(fixed) == 1
        ):
            fixed = fixed[0]
            changed = True
            message = f"Unwrapped one-item YAML list for scalar field {preferred!r}."
        elif (
            canonical in LIST_FIELDS
            and fixed is not None
            and not isinstance(fixed, list)
        ):
            fixed = [fixed]
            changed = True
            message = f"Wrapped scalar value of {preferred!r} in a YAML list."
        else:
            message = f"Normalized value of {preferred!r}."

        if canonical in CONTROLLED_VALUES:
            values = fixed if isinstance(fixed, list) else [fixed]
            normalized_values: list[Any] = []
            value_changed = False
            for item in values:
                token = canonical_token(item)
                canonical_value = CONTROLLED_VALUES[canonical].get(token)
                if canonical_value:
                    normalized_values.append(canonical_value)
                    if item != canonical_value:
                        value_changed = True
                else:
                    normalized_values.append(item)
            if isinstance(fixed, list):
                fixed = normalized_values
            elif normalized_values:
                fixed = normalized_values[0]
            changed = changed or value_changed
            if value_changed:
                message = f"Normalized controlled value(s) of {preferred!r}."

        if canonical == "theme":
            normalized, _warning, error = normalize_theme_value(fixed)
            if normalized and not error and fixed != normalized:
                fixed = normalized
                changed = True
                message = "Normalized theme to the full Library of Congress Classification class label."

        if canonical == "license" and isinstance(fixed, str):
            alias = LICENSE_ALIASES.get(canonical_token(fixed))
            if alias:
                fixed = alias
                changed = True
                message = "Replaced license shorthand with its canonical URI."

        if isinstance(fixed, str):
            stripped = fixed.strip()
            if stripped != fixed:
                fixed = stripped
                changed = True
                message = f"Trimmed whitespace in {preferred!r}."

        return fixed, changed, message

    def reorder_output(self, output: OrderedDict[str, Any]) -> OrderedDict[str, Any]:
        ordered: OrderedDict[str, Any] = OrderedDict()
        preferred_order = [
            PREFERRED_FIELD_NAME[field] for field in EXPECTED_TEMPLATE_FIELDS
        ]
        for key in preferred_order:
            if key in output:
                ordered[key] = output.pop(key)
        for key, value in output.items():
            ordered[key] = value
        return ordered

    def add_issue(
        self,
        result: ValidationResult,
        severity: Severity,
        code: str,
        field_name: Optional[str],
        message: str,
        suggestion: Optional[str] = None,
    ) -> None:
        if severity == "warning" and (
            self.config.strict or self.config.fail_on_warning
        ):
            severity = "error"
        result.issues.append(
            Issue(
                severity=severity,
                code=code,
                dataset_path=str(result.dataset_path),
                metadata_path=str(result.metadata_path),
                field=field_name,
                message=message,
                suggestion=suggestion,
            )
        )

    def add_fix(
        self,
        result: ValidationResult,
        code: str,
        field_name: Optional[str],
        message: str,
    ) -> None:
        result.changed = True
        result.fixes.append(
            Fix(
                code=code,
                dataset_path=str(result.dataset_path),
                metadata_path=str(result.metadata_path),
                field=field_name,
                message=message,
            )
        )


def _dataset_for_metadata_path(path: Path) -> Path:
    return path.parent if path.name == "metadata.yaml" else path


class CatalogYamlDumper(yaml.SafeDumper):
    """YAML dumper configured to minimize style churn in catalog metadata files."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> Any:
        # Force block sequences to be indented under their parent key. PyYAML uses
        # two spaces; write_yaml post-processes this to the one-space style already
        # used throughout the original catalog metadata.yaml files.
        return super().increase_indent(flow, False)


def _represent_empty_null(
    dumper: CatalogYamlDumper, value: None
) -> yaml.nodes.ScalarNode:
    """Represent null as an empty YAML value, e.g. ``acronym:`` not ``acronym: null``."""

    return dumper.represent_scalar("tag:yaml.org,2002:null", "")


CatalogYamlDumper.add_representer(type(None), _represent_empty_null)


def _restore_catalog_sequence_indent(text: str) -> str:
    """Convert PyYAML's two-space top-level sequence indent to catalog style."""

    lines = []
    for line in text.splitlines():
        if line.startswith("  - ") or line == "  -":
            lines.append(" " + line[2:])
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


def write_yaml(path: Path, data: Mapping[str, Any]) -> None:
    text = yaml.dump(
        dict(data),
        Dumper=CatalogYamlDumper,
        sort_keys=False,
        allow_unicode=True,
        width=4096,
        default_flow_style=False,
    )
    text = _restore_catalog_sequence_indent(text)
    path.write_text(text, encoding="utf-8")


def discover_datasets(models_dir: Path) -> list[Path]:
    models_dir = models_dir.resolve()
    if not models_dir.exists():
        raise MetadataYamlError(f"Models directory does not exist: {models_dir}")
    if not models_dir.is_dir():
        raise MetadataYamlError(f"Models path is not a directory: {models_dir}")
    return sorted(path for path in models_dir.iterdir() if path.is_dir())


def resolve_targets(args: argparse.Namespace) -> list[Path]:
    if args.all:
        if args.datasets:
            raise MetadataYamlError(
                "Use either --all or explicit dataset folders, not both."
            )
        return discover_datasets(args.models_dir)

    if args.datasets:
        targets = [Path(path) for path in args.datasets]
        missing = [path for path in targets if not path.exists()]
        if missing:
            joined = ", ".join(str(path) for path in missing)
            raise MetadataYamlError(f"Input path does not exist: {joined}")
        return targets

    cwd = Path.cwd()
    if (cwd / "metadata.yaml").exists():
        return [cwd]

    raise MetadataYamlError(
        "No dataset folder provided. Pass one or more model folders, use --all, or run from a dataset folder."
    )


def format_text(results: Sequence[ValidationResult], *, dry_run: bool) -> str:
    lines: list[str] = []
    for result in results:
        status = "VALID" if result.valid else "INVALID"
        lines.append(f"{status}: {result.dataset_path}")
        lines.append(f"  metadata: {result.metadata_path}")
        for issue in result.errors:
            field = issue.field or "$"
            lines.append(f"  ERROR   {field} [{issue.code}] {issue.message}")
            if issue.suggestion:
                lines.append(f"          fix: {issue.suggestion}")
        for issue in result.warnings:
            field = issue.field or "$"
            lines.append(f"  WARNING {field} [{issue.code}] {issue.message}")
            if issue.suggestion:
                lines.append(f"          fix: {issue.suggestion}")
        for fix in result.fixes:
            action = "would fix" if dry_run else "fixed"
            field = f" {fix.field}" if fix.field else ""
            lines.append(f"  {action}: [{fix.code}]{field} {fix.message}")
    total = len(results)
    errors = sum(len(result.errors) for result in results)
    warnings = sum(len(result.warnings) for result in results)
    changed = sum(1 for result in results if result.changed)
    action = "would change" if dry_run else "changed"
    lines.append(
        f"Summary: {total} checked, {errors} error(s), {warnings} warning(s), {changed} file(s) {action}."
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate, lint, and safely fix OntoUML/UFO Catalog metadata.yaml files.",
    )
    parser.add_argument(
        "datasets",
        nargs="*",
        type=Path,
        help="Dataset folder(s) or metadata.yaml file(s) to validate. If omitted, the current directory is used when it contains metadata.yaml.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Validate all direct dataset folders below --models-dir.",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=Path("models"),
        help="Models directory used with --all. Default: models.",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply safe deterministic fixes. Mandatory missing values and ambiguous problems are reported but not guessed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned fixes without writing files. Mainly useful together with --fix.",
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
        "--missing-expected-fields",
        choices=("error", "warning", "ignore"),
        default="warning",
        help="How to handle expected but non-mandatory template fields that are absent. Default: warning.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Promote warnings to errors. Useful for CI after the catalog has been normalized.",
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
            fix=args.fix,
            dry_run=args.dry_run,
            strict=args.strict,
            fail_on_warning=False,  # keep reported severity stable; exit handling uses args.fail_on_warning
            unknown_fields=args.unknown_fields,
            missing_expected_fields=args.missing_expected_fields,
        )
        validator = MetadataYamlValidator(config)
        results = [validator.validate_dataset(target) for target in targets]
    except MetadataYamlError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(
            json.dumps(
                [result.to_dict() for result in results], indent=2, ensure_ascii=False
            )
        )
    else:
        print(format_text(results, dry_run=args.dry_run))

    has_errors = any(result.errors for result in results)
    has_warnings = any(result.warnings for result in results)
    if has_errors or (args.fail_on_warning and has_warnings):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

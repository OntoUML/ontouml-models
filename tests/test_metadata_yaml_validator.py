from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools" / "validation" / "metadata_yaml_validator.py"


def write_metadata(dataset: Path, text: str) -> Path:
    dataset.mkdir(parents=True, exist_ok=True)
    path = dataset / "metadata.yaml"
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


VALID_METADATA = """
title: Reference Ontology of Trust
acronym: ROT
issued: 2019
modified: 2022
contributor:
  - https://dblp.org/pid/81/4277
keyword:
  - trust
theme: Class H - Social Sciences
editorialNote: Imported from source repository.
ontologyType:
  - domain
language: en
designedForTask:
  - conceptual clarification
context:
  - research
source:
  - https://doi.org/10.1007/978-3-030-33246-4_1
representationStyle:
  - ontouml
landingPage: https://github.com/unibz-core/trust-ontology
license: https://creativecommons.org/licenses/by/4.0/
"""


def run_validator(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_valid_metadata_returns_zero(tmp_path: Path) -> None:
    dataset = tmp_path / "models" / "amaral2019rot"
    write_metadata(dataset, VALID_METADATA)

    result = run_validator(str(dataset))

    assert result.returncode == 0
    assert "VALID:" in result.stdout


def test_missing_required_field_returns_validation_error(tmp_path: Path) -> None:
    dataset = tmp_path / "models" / "missing-title"
    write_metadata(dataset, VALID_METADATA.replace("title: Reference Ontology of Trust\n", ""))

    result = run_validator(str(dataset), "--format", "json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload[0]["valid"] is False
    assert any(issue["code"] == "missing_field" and issue["field_path"] == "$.title" for issue in payload[0]["errors"])


def test_invalid_controlled_value_returns_validation_error(tmp_path: Path) -> None:
    dataset = tmp_path / "models" / "bad-enum"
    write_metadata(dataset, VALID_METADATA.replace("  - domain", "  - foundational"))

    result = run_validator(str(dataset), "--format", "json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any(issue["code"] == "invalid_enum" and issue["field_path"] == "$.ontologyType[0]" for issue in payload[0]["errors"])


def test_empty_license_is_warning_by_default(tmp_path: Path) -> None:
    dataset = tmp_path / "models" / "empty-license"
    write_metadata(dataset, VALID_METADATA.replace("license: https://creativecommons.org/licenses/by/4.0/", "license:"))

    result = run_validator(str(dataset), "--format", "json")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload[0]["valid"] is True
    assert any(issue["code"] == "missing_license" for issue in payload[0]["warnings"])


def test_empty_license_is_error_in_strict_mode(tmp_path: Path) -> None:
    dataset = tmp_path / "models" / "empty-license-strict"
    write_metadata(dataset, VALID_METADATA.replace("license: https://creativecommons.org/licenses/by/4.0/", "license:"))

    result = run_validator(str(dataset), "--strict", "--format", "json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any(issue["code"] == "missing_license" for issue in payload[0]["errors"])


def test_duplicate_yaml_key_is_invalid(tmp_path: Path) -> None:
    dataset = tmp_path / "models" / "duplicate-key"
    write_metadata(dataset, VALID_METADATA + "\ntitle: Duplicate\n")

    result = run_validator(str(dataset), "--format", "json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any(issue["code"] == "invalid_yaml" for issue in payload[0]["errors"])


def test_recursive_validation_finds_metadata_files(tmp_path: Path) -> None:
    root = tmp_path / "models"
    write_metadata(root / "a", VALID_METADATA)
    write_metadata(root / "b", VALID_METADATA.replace("theme: Class H - Social Sciences", "theme: Class T - Technology"))

    result = run_validator(str(root), "--recursive", "--format", "json")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert len(payload) == 2


def test_lcc_uri_theme_is_accepted(tmp_path: Path) -> None:
    dataset = tmp_path / "models" / "theme-uri"
    write_metadata(dataset, VALID_METADATA.replace("theme: Class H - Social Sciences", "theme: http://id.loc.gov/authorities/classification/H"))

    result = run_validator(str(dataset), "--format", "json")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload[0]["valid"] is True


def test_non_doi_source_is_warning_not_error(tmp_path: Path) -> None:
    dataset = tmp_path / "models" / "source-warning"
    write_metadata(dataset, VALID_METADATA.replace("https://doi.org/10.1007/978-3-030-33246-4_1", "https://example.org/paper.pdf"))

    result = run_validator(str(dataset), "--format", "json")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload[0]["valid"] is True
    assert any(issue["code"] == "non_persistent_source" for issue in payload[0]["warnings"])

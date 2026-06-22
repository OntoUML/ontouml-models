from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "validate_metadata_yaml.py"


def load_module():
    spec = importlib.util.spec_from_file_location("validate_metadata_yaml", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = load_module()


def write_metadata(folder: Path, text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "metadata.yaml"
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
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
editorialNote: Curated for the catalog.
ontologyType:
  - domain
language: en
designedForTask:
  - conceptual clarification
context:
  - research
source:
  - https://doi.org/10.1000/example
representationStyle:
  - ontouml
landingPage: https://example.org/model
license: https://creativecommons.org/licenses/by/4.0/
"""


def test_valid_current_catalog_style_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "example"
    write_metadata(dataset, VALID_METADATA)

    exit_code = validator.main([str(dataset)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "VALID:" in captured.out
    assert "0 error(s)" in captured.out


def test_missing_metadata_file_is_validation_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "missing"
    dataset.mkdir(parents=True)

    exit_code = validator.main([str(dataset)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "missing_file" in captured.out
    assert "metadata.yaml is missing" in captured.out


def test_invalid_yaml_duplicate_key_is_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "dup"
    write_metadata(
        dataset,
        """
        title: A
        title: B
        issued: 2024
        license: https://creativecommons.org/licenses/by/4.0/
        theme: Class H - Social Sciences
        keyword:
          - test
        """,
    )

    exit_code = validator.main([str(dataset)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "invalid_yaml" in captured.out
    assert "duplicate key" in captured.out


def test_missing_required_field_is_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "bad"
    write_metadata(
        dataset,
        """
        title: Missing license
        issued: 2024
        theme: Class H - Social Sciences
        keyword:
          - test
        """,
    )

    exit_code = validator.main([str(dataset), "--missing-expected-fields", "ignore"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "license" in captured.out
    assert "missing_field" in captured.out


def test_fix_normalizes_safe_scalar_and_theme_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "fixable"
    metadata_path = write_metadata(
        dataset,
        """
        title: Fixable model
        acronym: FM
        issued: 2024
        modified: 2024
        contributor: https://dblp.org/pid/81/4277
        keyword: trust
        theme: H
        editorialNote: note
        ontologyType: Domain
        language: en
        designedForTask: ConceptualClarification
        context: Research
        source: https://doi.org/10.1000/example
        representationStyle: OntoumlStyle
        landingPage: https://example.org/model
        license: CC-BY-4.0
        """,
    )

    exit_code = validator.main([str(dataset), "--fix"])

    captured = capsys.readouterr()
    fixed = metadata_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "fixed:" in captured.out
    assert "theme: Class H - Social Sciences" in fixed
    assert "license: https://creativecommons.org/licenses/by/4.0/" in fixed
    assert "contributor:\n - https://dblp.org/pid/81/4277" in fixed
    assert "keyword:\n - trust" in fixed
    assert "ontologyType:\n - domain" in fixed
    assert "designedForTask:\n - conceptual clarification" in fixed
    assert "representationStyle:\n - ontouml" in fixed


def test_fix_preserves_catalog_empty_value_style(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "empty-style"
    metadata_path = write_metadata(
        dataset,
        """
        title: Empty style
        acronym:
        issued: 2024
        modified: 2024
        contributor: https://dblp.org/pid/81/4277
        keyword: trust
        theme: H
        editorialNote:
        ontologyType: Domain
        language: en
        designedForTask: ConceptualClarification
        context: Research
        source: https://doi.org/10.1000/example
        representationStyle: OntoumlStyle
        landingPage: https://example.org/model
        license: CC-BY-4.0
        """,
    )

    exit_code = validator.main([str(dataset), "--fix"])

    capsys.readouterr()
    fixed = metadata_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "acronym:\n" in fixed
    assert "editorialNote:\n" in fixed
    assert "acronym: null" not in fixed
    assert "editorialNote: null" not in fixed


def test_fix_dry_run_does_not_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "dry"
    metadata_path = write_metadata(
        dataset,
        VALID_METADATA.replace("theme: Class H - Social Sciences", "theme: H"),
    )
    before = metadata_path.read_text(encoding="utf-8")

    exit_code = validator.main([str(dataset), "--fix", "--dry-run"])

    captured = capsys.readouterr()
    after = metadata_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "would fix:" in captured.out
    assert before == after


def test_all_discovers_direct_dataset_folders_and_reports_missing_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    models_dir = tmp_path / "models"
    write_metadata(models_dir / "valid", VALID_METADATA)
    (models_dir / "missing").mkdir(parents=True)

    exit_code = validator.main(["--all", "--models-dir", str(models_dir)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "VALID:" in captured.out
    assert "INVALID:" in captured.out
    assert "missing_file" in captured.out


def test_json_output_contains_structured_issues(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "json"
    write_metadata(
        dataset,
        """
        title: JSON test
        issued: 2024
        theme: invalid theme
        keyword:
          - test
        license: https://creativecommons.org/licenses/by/4.0/
        """,
    )

    exit_code = validator.main(
        [str(dataset), "--format", "json", "--missing-expected-fields", "ignore"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload[0]["valid"] is False
    assert payload[0]["errors"][0]["code"] in {"invalid_theme", "missing_field"}


def test_iri_slug_and_full_ocmv_uri_are_accepted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "aliases"
    write_metadata(
        dataset,
        VALID_METADATA.replace(
            "title: Reference Ontology of Trust",
            "iri: local-slug\ntitle: Reference Ontology of Trust",
        ).replace(
            "  - domain", "  - https://w3id.org/ontouml-models/vocabulary#Domain"
        ),
    )

    exit_code = validator.main([str(dataset)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "INVALID" not in captured.out


def test_boolean_literal_is_invalid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "boolean-title"
    write_metadata(
        dataset,
        VALID_METADATA.replace("title: Reference Ontology of Trust", "title: false"),
    )

    exit_code = validator.main([str(dataset)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "invalid_literal_type" in captured.out


def test_nonexistent_explicit_path_is_setup_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "models" / "does-not-exist"

    exit_code = validator.main([str(missing)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Input path does not exist" in captured.err


def test_fix_unwraps_single_item_license_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "license-list"
    metadata_path = write_metadata(
        dataset,
        VALID_METADATA.replace(
            "license: https://creativecommons.org/licenses/by/4.0/",
            "license:\n  - https://creativecommons.org/licenses/by/4.0/",
        ),
    )

    exit_code = validator.main([str(dataset), "--fix"])

    captured = capsys.readouterr()
    fixed = metadata_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "fixed:" in captured.out
    assert "license: https://creativecommons.org/licenses/by/4.0/" in fixed
    assert "license:\n - https://creativecommons.org/licenses/by/4.0/" not in fixed


def test_single_item_license_list_requires_fix_without_fix_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "license-list-no-fix"
    write_metadata(
        dataset,
        VALID_METADATA.replace(
            "license: https://creativecommons.org/licenses/by/4.0/",
            "license:\n  - https://creativecommons.org/licenses/by/4.0/",
        ),
    )

    exit_code = validator.main([str(dataset)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "single_uri_as_list" in captured.out
    assert "--fix option can unwrap" in captured.out

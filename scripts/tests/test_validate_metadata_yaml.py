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


def test_full_ocmv_uri_controlled_value_is_accepted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "controlled-uri"
    write_metadata(
        dataset,
        VALID_METADATA.replace(
            "  - domain", "  - https://w3id.org/ontouml-models/vocabulary#Domain"
        ),
    )

    exit_code = validator.main([str(dataset)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "INVALID" not in captured.out


def test_converter_only_fields_are_unexpected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "converter-only"
    write_metadata(
        dataset,
        VALID_METADATA.replace(
            "title: Reference Ontology of Trust",
            "iri: local-slug\neditorial_note: Alias note\ntitle: Reference Ontology of Trust",
        ),
    )

    exit_code = validator.main([str(dataset)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "unexpected_field" in captured.out
    assert "iri" in captured.out
    assert "editorial_note" in captured.out


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


def test_modified_before_issued_is_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "date-order"
    write_metadata(
        dataset,
        VALID_METADATA.replace("issued: 2019", "issued: 2024").replace(
            "modified: 2022", "modified: 2023"
        ),
    )

    exit_code = validator.main([str(dataset)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "modified_before_issued" in captured.out
    assert "modified date must be greater than or equal" in captured.out


def test_modified_same_year_as_more_precise_issued_is_accepted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "date-precision"
    write_metadata(
        dataset,
        VALID_METADATA.replace("issued: 2019", "issued: 2024-05-10").replace(
            "modified: 2022", "modified: 2024"
        ),
    )

    exit_code = validator.main([str(dataset)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "modified_before_issued" not in captured.out


def test_fix_preserves_multiline_editorial_note_as_block_scalar(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "multiline-note"
    metadata_path = write_metadata(
        dataset,
        """
        title: Multiline note
        acronym:
        issued: 2024
        modified: 2024
        contributor:
         - https://dblp.org/pid/81/4277
        keyword:
         - test
        theme: H
        editorialNote: |
         The ontology was developed in the context of a master thesis which isn't yet published.
         The category's "restrictedTo" was set to "relator".
        ontologyType:
         - Domain
        language: en
        designedForTask:
         - conceptual clarification
        context:
         - research
        source:
        representationStyle:
         - OntoumlStyle
        landingPage:
        license: https://creativecommons.org/licenses/by/4.0/
        """,
    )

    exit_code = validator.main([str(dataset), "--fix"])

    capsys.readouterr()
    fixed = metadata_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "editorialNote: |" in fixed
    assert "isn''t" not in fixed
    assert "category''s" not in fixed
    assert " The ontology was developed" in fixed
    loaded = validator.yaml.load(fixed, Loader=validator.MetadataYamlLoader)
    assert "isn't yet published" in loaded["editorialNote"]
    assert 'category\'s "restrictedTo"' in loaded["editorialNote"]


def test_landing_page_allows_multiple_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "landing-page-list"
    metadata_path = write_metadata(
        dataset,
        VALID_METADATA.replace(
            "landingPage: https://example.org/model",
            "landingPage:\n  - https://example.org/model\n  - https://example.org/extra",
        ),
    )

    exit_code = validator.main([str(dataset), "--fix"])

    captured = capsys.readouterr()
    fixed = metadata_path.read_text(encoding="utf-8")
    loaded = validator.yaml.load(fixed, Loader=validator.MetadataYamlLoader)
    assert exit_code == 0
    assert "invalid_type" not in captured.out
    assert loaded["landingPage"] == [
        "https://example.org/model",
        "https://example.org/extra",
    ]


def test_comma_separated_language_tags_are_accepted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "multi-language"
    write_metadata(
        dataset,
        VALID_METADATA.replace("language: en", "language: en, pt-br"),
    )

    exit_code = validator.main([str(dataset)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "invalid_language" not in captured.out


def test_fix_converts_comma_separated_language_tags_to_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "fix-language"
    metadata_path = write_metadata(
        dataset,
        VALID_METADATA.replace("language: en", "language: en, pt-br"),
    )

    exit_code = validator.main([str(dataset), "--fix"])

    captured = capsys.readouterr()
    fixed = metadata_path.read_text(encoding="utf-8")
    loaded = validator.yaml.load(fixed, Loader=validator.MetadataYamlLoader)
    assert exit_code == 0
    assert "fixed:" in captured.out
    assert "language:\n - en\n - pt-br" in fixed
    assert loaded["language"] == ["en", "pt-br"]


def test_fix_does_not_convert_invalid_comma_separated_language_tags(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "invalid-language"
    metadata_path = write_metadata(
        dataset,
        VALID_METADATA.replace("language: en", "language: en, not a tag"),
    )
    before = metadata_path.read_text(encoding="utf-8")

    exit_code = validator.main([str(dataset), "--fix"])

    captured = capsys.readouterr()
    after = metadata_path.read_text(encoding="utf-8")
    assert exit_code == 1
    assert "invalid_language" in captured.out
    assert before == after


def test_language_list_is_accepted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "language-list"
    write_metadata(
        dataset,
        VALID_METADATA.replace("language: en", "language:\n  - en\n  - pt-br"),
    )

    exit_code = validator.main([str(dataset), "--fix"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "invalid_language" not in captured.out


def test_invalid_theme_message_names_repository_style(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "invalid-theme"
    write_metadata(
        dataset,
        VALID_METADATA.replace(
            "theme: Class H - Social Sciences", "theme: Social Sciences"
        ),
    )

    exit_code = validator.main([str(dataset)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Expected the repository-style LCC class label" in captured.out
    assert "accepted only as fixable input" in captured.out


def test_allow_missing_license_relaxes_absent_license(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "legacy-no-license"
    write_metadata(
        dataset,
        """
        title: Legacy model
        issued: 2020
        theme: Class H - Social Sciences
        keyword:
          - legacy
        """,
    )

    exit_code = validator.main(
        [
            str(dataset),
            "--allow-missing-license",
            "--missing-expected-fields",
            "ignore",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "WARNING license [missing_field]" in captured.out
    assert "ERROR   license" not in captured.out


def test_allow_missing_license_relaxes_empty_license_even_in_strict_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "legacy-empty-license"
    write_metadata(
        dataset,
        VALID_METADATA.replace(
            "license: https://creativecommons.org/licenses/by/4.0/", "license:"
        ),
    )

    exit_code = validator.main([str(dataset), "--allow-missing-license", "--strict"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "WARNING license [missing_value]" in captured.out
    assert "ERROR   license" not in captured.out


def test_missing_license_remains_error_without_relaxing_argument(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "strict-no-license"
    write_metadata(
        dataset,
        VALID_METADATA.replace(
            "license: https://creativecommons.org/licenses/by/4.0/", "license:"
        ),
    )

    exit_code = validator.main([str(dataset)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ERROR   license [missing_value]" in captured.out


def test_contact_points_is_not_supported_metadata_yaml_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "contact-points"
    write_metadata(
        dataset,
        VALID_METADATA
        + "contactPoints:\n"
        + " - name: Pedro Paulo Favato Barcelos\n"
        + "   email: pedro@example.org\n",
    )

    exit_code = validator.main([str(dataset)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "unexpected_field" in captured.out
    assert "contactPoints" in captured.out


def test_rdf_predicate_and_converter_alias_fields_are_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "models" / "unsupported-fields"
    unsupported_fields = """
    dct:title: Wrong title field
    dcat:keyword:
     - wrong keyword field
    landing_page: https://example.org/alias
    storage_url: https://example.org/storage
    distribution: https://example.org/distribution
    dcat:contactPoint: https://example.org/contact
    """
    write_metadata(dataset, VALID_METADATA + textwrap.dedent(unsupported_fields))

    exit_code = validator.main([str(dataset)])

    captured = capsys.readouterr()
    assert exit_code == 1
    for field in (
        "dct:title",
        "dcat:keyword",
        "landing_page",
        "storage_url",
        "distribution",
        "dcat:contactPoint",
    ):
        assert field in captured.out
    assert captured.out.count("unexpected_field") >= 6

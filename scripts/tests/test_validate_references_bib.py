from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def load_module():
    script = None
    for parent in Path(__file__).resolve().parents:
        for candidate in (
            parent / "validate_references_bib.py",
            parent / "scripts" / "validate_references_bib.py",
        ):
            if candidate.exists():
                script = candidate
                break
        if script is not None:
            break
    assert script is not None
    spec = importlib.util.spec_from_file_location("validate_references_bib", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


VALID_BIB = """% Dataset references
@article{sales2023catalog,
  author = {Sales, Tiago Prince and Barcelos, Pedro Paulo F.},
  title = {A FAIR catalog of ontology-driven conceptual models},
  journal = {Data & Knowledge Engineering},
  year = {2023},
  doi = {10.1016/j.datak.2023.102210}
}

@inproceedings{guizzardi2022example,
  title = "Example title",
  booktitle = {Proceedings of an Example Conference},
  year = 2022,
  month = jan # " " # feb
}
"""


def make_dataset(tmp_path: Path, bib_text: str | None = VALID_BIB) -> Path:
    dataset = tmp_path / "models" / "example-model"
    dataset.mkdir(parents=True)
    (dataset / "metadata.yaml").write_text("title: Example\n", encoding="utf-8")
    if bib_text is not None:
        (dataset / "references.bib").write_text(bib_text, encoding="utf-8")
    return dataset


def test_valid_references_bib_is_accepted(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path)
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert result.valid
    assert result.entries_checked == 2
    assert result.errors == []


def test_missing_references_bib_is_skipped_by_default(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, bib_text=None)
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert result.valid
    assert not result.present
    assert result.errors == []


def test_missing_references_bib_can_be_required(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, bib_text=None)
    validator = module.ReferencesBibValidator(module.Config(require=True))

    result = validator.validate_target(dataset)

    assert not result.valid
    assert result.errors[0].code == "missing_references_bib"


def test_empty_references_bib_is_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, bib_text=" \n\t\n")
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert result.errors[0].code == "empty_file"


def test_unclosed_entry_is_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@article{broken,
  title = {Missing closing brace}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert result.errors[0].code == "unclosed_entry"


def test_entry_without_at_sign_is_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""article{broken,
  title = {Wrong start}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(issue.code == "unexpected_text" for issue in result.errors)


def test_missing_citation_key_is_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@article{,
  title = {Missing key}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(issue.code == "missing_citation_key" for issue in result.errors)


def test_invalid_field_assignment_is_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@article{broken,
  title {Missing equals},
  year = {2024}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(issue.code == "missing_field_assignment" for issue in result.errors)


def test_duplicate_citation_key_is_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@article{same,
  title = {First}
}
@book{same,
  title = {Second}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(issue.code == "duplicate_key" for issue in result.errors)


def test_unknown_entry_type_is_warning_by_default(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@customtype{key,
  title = {Unknown type but syntactically valid}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert result.valid
    assert any(issue.code == "unknown_entry_type" for issue in result.warnings)


def test_strict_promotes_unknown_entry_type_warning_to_error(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@customtype{key,
  title = {Unknown type but syntactically valid}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config(strict=True))

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(issue.code == "unknown_entry_type" for issue in result.errors)


def test_string_preamble_and_comment_entries_are_accepted_with_regular_entry(
    tmp_path: Path,
):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@string{JWS = "Journal of Web Semantics"}
@preamble{"Generated bibliography"}
@comment{This comment is allowed}
@article{key,
  title = {Uses macro},
  journal = JWS,
  year = 2024
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert result.valid
    assert result.entries_checked == 1


def test_file_target_is_supported(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path)
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset / "references.bib")

    assert result.valid
    assert result.dataset_path == dataset


def test_top_level_comments_between_fields_are_accepted(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@article{key,
  title = {Commented entry}, % comment after field
  % full-line comment between fields
  year = {2024},
  note = {100\\% coverage}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert result.valid
    assert result.entries_checked == 1


def test_unescaped_quote_inside_quoted_value_is_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@article{broken,
  title = "A "broken" quoted value",
  year = {2024}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(issue.code == "invalid_field_value" for issue in result.errors)


def test_cli_returns_two_for_missing_explicit_target(tmp_path: Path, capsys):
    module = load_module()
    missing = tmp_path / "models" / "missing-model"

    exit_code = module.main([str(missing)])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "Input path does not exist" in captured.err


def test_json_output_shape_from_main(tmp_path: Path, capsys):
    module = load_module()
    dataset = make_dataset(tmp_path)

    exit_code = module.main([str(dataset), "--format", "json"])
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload[0]["valid"] is True
    assert payload[0]["entries_checked"] == 2


def test_cli_returns_one_for_invalid_file(tmp_path: Path, capsys):
    module = load_module()
    dataset = make_dataset(tmp_path, bib_text="@article{broken")

    exit_code = module.main([str(dataset)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "INVALID" in captured.out


def test_parenthesized_entries_are_supported(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@book(smith2024,
  title = {Parenthesized Entry},
  publisher = {Example Press},
  year = {2024}
)
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert result.valid
    assert result.entries_checked == 1


def test_nested_braces_and_escaped_quotes_are_accepted(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text=r"""@article{latex2024,
  title = {A {Nested} Title with {\LaTeX} and "quotes"},
  note = "A \"quoted\" note",
  year = {2024}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert result.valid
    assert result.entries_checked == 1


def test_at_signs_inside_values_are_accepted(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@online{web2024,
  title = {Project page @ GitHub},
  url = {https://example.org/contact?a=b&c=d},
  note = "email@example.org",
  year = {2024}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert result.valid
    assert result.entries_checked == 1


def test_only_special_entries_is_rejected_as_no_bibliographic_entries(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@string{JWS = "Journal of Web Semantics"}
@comment{No regular bibliographic entry here}
@preamble{"Preamble only"}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(issue.code == "no_bibliographic_entries" for issue in result.errors)
    assert result.entries_checked == 0


def test_comment_only_file_is_rejected_as_no_bibliographic_entries(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""% comment one
% comment two
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(issue.code == "no_bibliographic_entries" for issue in result.errors)


def test_invalid_utf8_file_is_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, bib_text=None)
    (dataset / "references.bib").write_bytes(b"\xff\xfe\x00")
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert result.errors[0].code == "invalid_utf8"


def test_references_bib_directory_is_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, bib_text=None)
    (dataset / "references.bib").mkdir()
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert result.errors[0].code == "not_a_file"


def test_missing_entry_type_after_at_is_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@{broken,
  title = {Missing entry type}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(issue.code == "missing_entry_type" for issue in result.errors)


def test_missing_entry_body_is_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@article broken,
  title = {Missing braces}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(issue.code == "missing_entry_body" for issue in result.errors)


def test_invalid_citation_key_is_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@article{bad key,
  title = {Invalid key}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(issue.code == "invalid_citation_key" for issue in result.errors)


def test_invalid_field_name_is_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@article{key,
  1title = {Invalid field name},
  year = {2024}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(issue.code == "invalid_field_name" for issue in result.errors)


def test_empty_field_value_is_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@article{key,
  title = ,
  year = {2024}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(issue.code == "empty_field_value" for issue in result.errors)


def test_unclosed_braced_field_value_is_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@article{key,
  title = {Unclosed value,
  year = {2024}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(
        issue.code in {"unclosed_entry", "invalid_field_value"}
        for issue in result.errors
    )


def test_empty_concatenation_part_is_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@article{key,
  title = {First} # ,
  year = {2024}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(issue.code == "invalid_field_value" for issue in result.errors)


def test_duplicate_field_warns_by_default(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@article{key,
  title = {First},
  title = {Second},
  year = {2024}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert result.valid
    assert any(issue.code == "duplicate_field" for issue in result.warnings)


def test_strict_promotes_duplicate_field_warning_to_error(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@article{key,
  title = {First},
  title = {Second},
  year = {2024}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config(strict=True))

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(issue.code == "duplicate_field" for issue in result.errors)


def test_empty_special_entry_warns_by_default(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@comment{}
@article{key,
  title = {Valid},
  year = {2024}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert result.valid
    assert any(issue.code == "empty_special_entry" for issue in result.warnings)


def test_string_entry_without_equals_is_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@string{Journal of Web Semantics}
@article{key,
  title = {Valid},
  year = {2024}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(issue.code == "invalid_string_entry" for issue in result.errors)


def test_invalid_string_macro_name_is_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@string{1JWS = "Journal of Web Semantics"}
@article{key,
  title = {Valid},
  year = {2024}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(issue.code == "invalid_string_macro" for issue in result.errors)


def test_invalid_string_value_is_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@string{JWS = [Journal of Web Semantics]}
@article{key,
  title = {Valid},
  year = {2024}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(issue.code == "invalid_string_value" for issue in result.errors)


def test_fail_on_warning_returns_one_without_promoting_warning(tmp_path: Path, capsys):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@customtype{key,
  title = {Unknown type but syntactically valid}
}
""",
    )

    exit_code = module.main([str(dataset), "--fail-on-warning"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "WARNING" in captured.out
    assert "ERROR" not in captured.out


def test_all_discovers_direct_dataset_folders(tmp_path: Path, capsys):
    module = load_module()
    dataset_a = make_dataset(tmp_path, VALID_BIB)
    dataset_b = tmp_path / "models" / "without-bib"
    dataset_b.mkdir(parents=True)
    (dataset_b / "metadata.yaml").write_text("title: Without Bib\n", encoding="utf-8")

    exit_code = module.main(["--all", "--models-dir", str(tmp_path / "models")])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "example-model" in captured.out
    assert "without-bib" in captured.out
    assert "SKIPPED" in captured.out
    assert dataset_a.name in captured.out


def test_all_and_explicit_targets_are_mutually_exclusive(tmp_path: Path, capsys):
    module = load_module()
    dataset = make_dataset(tmp_path)

    exit_code = module.main(
        [str(dataset), "--all", "--models-dir", str(tmp_path / "models")]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "Use either --all or explicit" in captured.err


def test_json_output_reports_warnings_separately(tmp_path: Path, capsys):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@customtype{key,
  title = {Unknown type but syntactically valid}
}
""",
    )

    exit_code = module.main([str(dataset), "--format", "json"])
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload[0]["errors"] == []
    assert payload[0]["warnings"][0]["code"] == "unknown_entry_type"


def test_issue_locations_are_reported_for_field_errors(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@article{key,
  title {Missing equals},
  year = {2024}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)
    issue = next(
        issue for issue in result.errors if issue.code == "missing_field_assignment"
    )

    assert issue.line is not None and issue.line >= 2
    assert issue.column is not None and issue.column >= 1


def test_current_directory_dataset_is_used_when_no_target_is_given(
    tmp_path: Path, monkeypatch, capsys
):
    module = load_module()
    dataset = make_dataset(tmp_path)
    monkeypatch.chdir(dataset)

    exit_code = module.main([])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "VALID" in captured.out
    assert "references.bib" in captured.out


def test_current_directory_without_target_is_reported_as_usage_error(
    tmp_path: Path, monkeypatch, capsys
):
    module = load_module()
    monkeypatch.chdir(tmp_path)

    exit_code = module.main([])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "No target provided" in captured.err


def test_bachelorsthesis_and_masterthesis_are_known_entry_types(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@bachelorsthesis{bsc2024,
  author = {Example, Alice},
  title = {Bachelor thesis example},
  school = {Example University},
  year = {2024}
}

@masterthesis{msc2024,
  author = {Example, Bob},
  title = {Master thesis example},
  school = {Example University},
  year = {2024}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert result.valid
    assert result.entries_checked == 2
    assert not any(issue.code == "unknown_entry_type" for issue in result.warnings)


def test_braced_value_accepts_literal_quotes_and_latex_macros(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text=r"""@phdthesis{moreira2019semiotics,
  title = {SEMIoTICS: Semantic Model-driven Development for IoT Interoperability of Emergency Services},
  author = {Moreira, {Jo{\~a}o Luiz}},
  year = {2019},
  abstract = {This abstract contains "quoted text", drivers{\textquoteright} vital signs, JSON-LD examples, and contributions:{\textbullet{} Improved IoT Semantic Interoperability;\textbullet{} Improved Situation Identification}.},
  language = {English}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert result.valid
    assert result.entries_checked == 1
    assert result.errors == []


def test_braced_value_accepts_repository_style_long_abstract_regression(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text=r"""@phdthesis{moreira2019semiotics,
  title        = {SEMIoTICS: Semantic Model-driven Development for IoT Interoperability of Emergency Services: Improving the Semantic Interoperability of IoT Early Warning Systems},
  author       = {Moreira, {Jo{\~a}o Luiz}},
  year         = 2019,
  abstract     = {Disaster Risk Reduction (DRR) is a systematic approach to analyze potential disasters and reduce their occurrence rate and possible impact. The main DRR component is an Early Warning System (EWS), which is a distributed information system that is able to monitor the physical world and issue warnings if abnormal situations occur. In this case study, accident risks are assessed by monitoring two types of data, namely (1) the drivers{\textquoteright} vital signs with electrocardiogram (ECG), and (2) the trucks{\textquoteright} position, speed and acceleration. The most important contributions of this thesis are:\textbullet{} Improved IoT Semantic Interoperability;\textbullet{} Improved Situation Identification;\textbullet{} Interoperability reference for disaster services.},
  language     = {English}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert result.valid
    assert result.entries_checked == 1
    assert result.errors == []


def test_extra_closing_brace_in_field_value_is_still_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text=r"""@inproceedings{andrade2023integracao,
  title = {Integra\c{c}\~{a}o de Dados de Publica\c{c}\~{o}es Cient\'{\i}ficas usando uma Abordagem baseada em Ontologias}},
  author = {Example, Alice},
  year = 2023
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert any(
        issue.code in {"unexpected_text", "invalid_field_value"}
        for issue in result.errors
    )


def test_trailing_dot_in_field_name_is_still_rejected(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@article{silva2012architecture,
  title = {IT architecture from the service continuity perspective},
  author. = {Example, Alice},
  journal. = {Journal of Information Security Research},
  year. = 2012
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert not result.valid
    assert sum(issue.code == "invalid_field_name" for issue in result.errors) == 3


def test_at_sign_inside_full_line_comment_is_ignored(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""% See also @not_an_entry in this comment.
@article{commentcase,
  title = {A valid title},
  author = {Example, Alice},
  year = 2024
}
% Another comment mentioning @misc{ignored}.
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert result.valid
    assert result.entries_checked == 1
    assert result.errors == []


def test_literal_unpaired_double_quote_inside_braced_value_before_comment_is_valid(
    tmp_path: Path,
):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text="""@article{quotedbrace,
  title = {A title with a literal " character}, % top-level field comment
  author = {Example, Alice},
  year = 2024
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert result.valid
    assert result.entries_checked == 1
    assert result.errors == []


def test_escaped_literal_braces_inside_braced_value_are_accepted(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text=r"""@masterthesis{ferreira2013ontologia,
  title = {{Ontologia de Emerg{\^{e}}ncia no Apoio {\`{a}} Gera{\c{c}}{\{a}}o de Solu{\c{c}}{\{o}}es de Variabilidade de Planos de Emerg{\^{e}}ncia}},
  author = {Ferreira, Maria In{\^{e}}s Garcia Bosc{\'{a}}},
  year = 2013,
  school = {Universidade Federal do Rio De Janeiro}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert result.valid
    assert result.entries_checked == 1
    assert result.errors == []


def test_repository_ferreira_regression_with_escaped_literal_braces_is_valid(
    tmp_path: Path,
):
    module = load_module()
    dataset = make_dataset(
        tmp_path,
        bib_text=r"""@inproceedings{ferreira2015ontoemergeplan,
  title        = {OntoEmergePlan: variability of emergency plans supported by a domain ontology},
  author       = {Maria I. G. B. Ferreira and Jo{\~{a}}o L. R. Moreira and Maria Luiza Machado Campos and Bernardo F. B. Braga and Tiago Prince Sales and others},
  year         = 2015,
  booktitle    = {12th Proceedings of the International Conference on Information Systems for Crisis Response and Management, Krystiansand, Norway, May 24-27, 2015},
  publisher    = {{ISCRAM} Association},
  url          = {http://idl.iscram.org/files/mariaigbferreira/2015/1184\%5FMariaI.G.B.Ferreira\%5Fetal2015.pdf},
  editor       = {Leysia Palen and Monika B{\"{u}}scher and Tina Comes and Amanda Lee Hughes},
  timestamp    = {Thu, 12 Mar 2020 11:29:43 +0100},
  biburl       = {https://dblp.org/rec/conf/iscram/FerreiraMCBSCB15.bib},
  bibsource    = {dblp computer science bibliography, https://dblp.org}
}
@masterthesis{ferreira2013ontologia,
  title        = {{Ontologia de Emerg{\^{e}}ncia no Apoio {\`{a}} Gera{\c{c}}{\{a}}o de Solu{\c{c}}{\{o}}es de Variabilidade de Planos de Emerg{\^{e}}ncia}},
  author       = {Ferreira, Maria In{\^{e}}s Garcia Bosc{\'{a}}},
  year         = 2013,
  pages        = 175,
  url          = {http://objdig.ufrj.br/15/teses/867022.pdf},
  institution  = {Universidade Federal do Rio De Janeiro},
  type         = {M.Sc. Dissertation}
}
""",
    )
    validator = module.ReferencesBibValidator(module.Config())

    result = validator.validate_target(dataset)

    assert result.valid
    assert result.entries_checked == 2
    assert result.errors == []

from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path

import pytest


def load_module():
    script = None
    for parent in Path(__file__).resolve().parents:
        for candidate in (
            parent / "process_new_model_submission.py",
            parent / "scripts" / "process_new_model_submission.py",
        ):
            if candidate.exists():
                script = candidate
                break
        if script is not None:
            break
    assert script is not None
    spec = importlib.util.spec_from_file_location(
        "process_new_model_submission", script
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "models").mkdir()
    return root


def make_model(root: Path, name: str = "example-model") -> Path:
    model = root / "models" / name
    model.mkdir()
    (model / "metadata.yaml").write_text(
        "\n".join(
            [
                "title: Example Model",
                "issued: 2026",
                "license: https://creativecommons.org/licenses/by/4.0/",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (model / "ontology.json").write_text(
        json.dumps({"id": "project_1", "type": "Project"}),
        encoding="utf-8",
    )
    (model / "ontology.ttl").write_text(
        "@prefix ex: <https://example.org/> .\nex:model ex:predicate ex:object .\n",
        encoding="utf-8",
    )
    (model / "ontology.vpp").write_bytes(b"vpp-placeholder")
    (model / "new-diagrams").mkdir()
    (model / "new-diagrams" / "main.png").write_bytes(PNG_1X1)
    return model


def parsed_args(module, *extra: str):
    parser = module.build_parser()
    return parser.parse_args(
        [
            "models/example-model",
            "--metadata-timestamp",
            "2026-06-24T12:00:00Z",
            *extra,
        ]
    )


def command_by_name(steps, name: str) -> tuple[str, ...]:
    for step in steps:
        if step.name == name:
            return step.command
    raise AssertionError(f"Step not found: {name}")


def test_resolve_model_folder_accepts_direct_child(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)

    resolved = module.resolve_model_folder("models/example-model", root)

    assert resolved == model.resolve()


def test_resolve_model_folder_rejects_nested_model_path(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    nested = root / "models" / "group" / "example-model"
    nested.mkdir(parents=True)

    with pytest.raises(module.SubmissionProcessingError, match="direct child"):
        module.resolve_model_folder("models/group/example-model", root)


def test_resolve_model_folder_rejects_path_outside_models(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    outside = root / "example-model"
    outside.mkdir()

    with pytest.raises(module.SubmissionProcessingError, match="inside"):
        module.resolve_model_folder("example-model", root)


def test_validate_required_sources_accepts_complete_submission_without_references(
    tmp_path: Path,
):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)

    diagrams = module.validate_required_sources(model, root)

    assert [path.name for path in diagrams] == ["main.png"]


def test_validate_required_sources_rejects_missing_required_file(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    (model / "ontology.vpp").unlink()

    with pytest.raises(module.SubmissionProcessingError, match="ontology.vpp"):
        module.validate_required_sources(model, root)


def test_validate_required_sources_rejects_missing_png_diagram(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    (model / "new-diagrams" / "main.png").unlink()

    with pytest.raises(module.SubmissionProcessingError, match="At least one .png"):
        module.validate_required_sources(model, root)


def test_validate_required_sources_rejects_invalid_ontology_json(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    (model / "ontology.json").write_text("not-json", encoding="utf-8")

    with pytest.raises(module.SubmissionProcessingError, match="not valid JSON"):
        module.validate_required_sources(model, root)


def test_validate_required_sources_rejects_non_object_ontology_json(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    (model / "ontology.json").write_text("[]", encoding="utf-8")

    with pytest.raises(module.SubmissionProcessingError, match="top level"):
        module.validate_required_sources(model, root)


def test_validate_required_sources_rejects_invalid_ontology_ttl(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    (model / "ontology.ttl").write_text("this is not turtle", encoding="utf-8")

    with pytest.raises(module.SubmissionProcessingError, match="ontology.ttl"):
        module.validate_required_sources(model, root)


def test_validate_required_sources_rejects_empty_vpp(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    (model / "ontology.vpp").write_bytes(b"")

    with pytest.raises(module.SubmissionProcessingError, match="ontology.vpp is empty"):
        module.validate_required_sources(model, root)


def test_validate_required_sources_rejects_invalid_png_signature(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    (model / "new-diagrams" / "main.png").write_bytes(b"not-a-png")

    with pytest.raises(module.SubmissionProcessingError, match="not a PNG"):
        module.validate_required_sources(model, root)


def test_references_bib_is_delegated_to_external_validator(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    # The helper only checks that the optional path is a file. Syntax and UTF-8
    # validation are delegated to scripts/validate_references_bib.py.
    (model / "references.bib").write_bytes(b"\xff\xfe\x00")

    diagrams = module.validate_required_sources(model, root)

    assert [path.name for path in diagrams] == ["main.png"]


def test_references_bib_directory_is_rejected_during_preflight(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    (model / "references.bib").mkdir()

    with pytest.raises(module.SubmissionProcessingError, match="references.bib path"):
        module.validate_required_sources(model, root)


def test_expected_generated_metadata_paths_include_png_metadata(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    diagrams = module.discover_png_diagrams(model)

    expected = {
        path.name for path in module.expected_generated_metadata_paths(model, diagrams)
    }

    assert {
        "metadata-json.ttl",
        "metadata-turtle.ttl",
        "metadata-vpp.ttl",
        "metadata.ttl",
        "metadata-png-n-main.ttl",
    } <= expected


def test_expected_generated_metadata_paths_include_original_and_new_diagrams(
    tmp_path: Path,
):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    (model / "original-diagrams").mkdir()
    (model / "original-diagrams" / "source.png").write_bytes(PNG_1X1)
    diagrams = module.discover_png_diagrams(model)

    expected = {
        path.name for path in module.expected_generated_metadata_paths(model, diagrams)
    }

    assert "metadata-png-n-main.ttl" in expected
    assert "metadata-png-o-source.ttl" in expected


def test_build_steps_uses_existing_repository_scripts(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    args = parsed_args(module)

    steps = module.build_steps(args, root, model)
    commands = [" ".join(step.command) for step in steps]

    assert any("scripts/validate_metadata_yaml.py" in command for command in commands)
    assert any("scripts/validate_references_bib.py" in command for command in commands)
    assert any("scripts/generate_png_metadata.py" in command for command in commands)
    assert any("scripts/generate_json_metadata.py" in command for command in commands)
    assert any("scripts/generate_turtle_metadata.py" in command for command in commands)
    assert any("scripts/generate_vpp_metadata.py" in command for command in commands)
    assert any("scripts/metadata_yaml_to_ttl.py" in command for command in commands)


def test_build_steps_validates_references_before_metadata_generation(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    args = parsed_args(module)

    step_names = [step.name for step in module.build_steps(args, root, model)]

    assert step_names.index("Validate/fix metadata.yaml") < step_names.index(
        "Validate optional references.bib"
    )
    assert step_names.index("Validate optional references.bib") < step_names.index(
        "Generate PNG distribution metadata"
    )


def test_references_validator_runs_without_require_strict_or_dry_run_flags(
    tmp_path: Path,
):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    args = parsed_args(module, "--allow-missing-license", "--dry-run")

    command = command_by_name(
        module.build_steps(args, root, model), "Validate optional references.bib"
    )

    assert command[0] == sys.executable
    assert command[1] == "scripts/validate_references_bib.py"
    assert "--require" not in command
    assert "--strict" not in command
    assert "--fail-on-warning" not in command
    assert "--dry-run" not in command


def test_dry_run_passes_dry_run_to_metadata_yaml_validator(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    args = parsed_args(module, "--dry-run")

    command = command_by_name(
        module.build_steps(args, root, model), "Validate/fix metadata.yaml"
    )

    assert "--fix" in command
    assert "--dry-run" in command


def test_no_fix_metadata_yaml_dry_run_does_not_pass_validator_dry_run(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    args = parsed_args(module, "--dry-run", "--no-fix-metadata-yaml")

    command = command_by_name(
        module.build_steps(args, root, model), "Validate/fix metadata.yaml"
    )

    assert "--fix" not in command
    assert "--dry-run" not in command


def test_no_fix_metadata_yaml_removes_fix_flag(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    args = parsed_args(module, "--no-fix-metadata-yaml")

    command = command_by_name(
        module.build_steps(args, root, model), "Validate/fix metadata.yaml"
    )

    assert "--fix" not in command


def test_no_validate_ontology_json_removes_generator_validation_flag(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    args = parsed_args(module, "--no-validate-ontology-json")

    command = command_by_name(
        module.build_steps(args, root, model), "Generate JSON distribution metadata"
    )

    assert "--validate-ontology-json" not in command


def test_ensure_expected_outputs_exist_reports_missing_files(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    missing = root / "models" / "example-model" / "metadata.ttl"

    with pytest.raises(module.SubmissionProcessingError, match="metadata.ttl"):
        module.ensure_expected_outputs_exist([missing], root)


def test_validate_all_turtle_files_rejects_invalid_generated_turtle(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    (model / "metadata-json.ttl").write_text("not turtle", encoding="utf-8")

    with pytest.raises(module.SubmissionProcessingError, match="metadata-json.ttl"):
        module.validate_all_turtle_files(model, root)


def test_detect_model_folder_from_changed_files_accepts_single_model_folder():
    module = load_module()

    detected = module.detect_model_folder_from_changed_files(
        [
            "models/example-model/metadata.yaml",
            "models/example-model/ontology.json",
            "models/example-model/metadata.ttl",
        ]
    )

    assert detected == "models/example-model"


def test_detect_model_folder_from_changed_files_rejects_outside_file():
    module = load_module()

    with pytest.raises(module.SubmissionProcessingError, match="outside the target"):
        module.detect_model_folder_from_changed_files(
            ["models/example-model/metadata.yaml", "README.md"]
        )


def test_detect_model_folder_from_changed_files_rejects_multiple_model_folders():
    module = load_module()

    with pytest.raises(
        module.SubmissionProcessingError, match="Exactly one model folder"
    ):
        module.detect_model_folder_from_changed_files(
            [
                "models/example-a/metadata.yaml",
                "models/example-b/ontology.json",
            ]
        )


def test_detect_model_folder_from_changed_files_rejects_direct_models_file():
    module = load_module()

    with pytest.raises(module.SubmissionProcessingError, match="direct model folder"):
        module.detect_model_folder_from_changed_files(["models/metadata.yaml"])

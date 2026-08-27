from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml


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
VALID_TURTLE = (
    "@prefix ex: <https://example.org/> .\n"
    "ex:model ex:predicate ex:object .\n"
)


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "models").mkdir()
    return root


def make_model(
    root: Path,
    name: str = "example-model",
    *,
    include_ontology_turtle: bool = True,
) -> Path:
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
    if include_ontology_turtle:
        (model / "ontology.ttl").write_text(VALID_TURTLE, encoding="utf-8")
    (model / "ontology.vpp").write_bytes(b"vpp-placeholder")
    (model / "new-diagrams").mkdir()
    (model / "new-diagrams" / "main.png").write_bytes(PNG_1X1)
    return model


def write_expected_metadata_outputs(module, model: Path) -> None:
    diagrams = module.discover_png_diagrams(model)
    for path in module.expected_generated_metadata_paths(model, diagrams):
        if path.name == "ontology.ttl":
            continue
        path.write_text(VALID_TURTLE, encoding="utf-8")


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


def load_submission_workflow() -> dict:
    for parent in Path(__file__).resolve().parents:
        workflow = parent / ".github" / "workflows" / "process-new-model-submission.yml"
        if workflow.is_file():
            return yaml.load(
                workflow.read_text(encoding="utf-8"), Loader=yaml.BaseLoader
            )
    raise AssertionError("Could not locate process-new-model-submission.yml.")


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


def test_validate_required_sources_accepts_submission_without_turtle_or_references(
    tmp_path: Path,
):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root, include_ontology_turtle=False)

    diagrams = module.validate_required_sources(model, root)

    assert [path.name for path in diagrams] == ["main.png"]
    assert not (model / "ontology.ttl").exists()


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
        "ontology.ttl",
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
    assert any("scripts/generate_ontology_turtle.py" in command for command in commands)
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


def test_build_steps_generates_ontology_before_turtle_metadata(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root, include_ontology_turtle=False)
    args = parsed_args(module)

    steps = module.build_steps(args, root, model)
    step_names = [step.name for step in steps]
    command = command_by_name(steps, "Generate ontology.ttl")

    assert step_names[1] == "Generate ontology.ttl"
    assert step_names.index("Generate ontology.ttl") < step_names.index(
        "Generate Turtle distribution metadata"
    )
    assert command == (
        sys.executable,
        "scripts/generate_ontology_turtle.py",
        "models/example-model",
    )


def test_dry_run_passes_dry_run_to_ontology_generator(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root, include_ontology_turtle=False)
    args = parsed_args(module, "--dry-run")

    command = command_by_name(
        module.build_steps(args, root, model), "Generate ontology.ttl"
    )

    assert command[-1] == "--dry-run"


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


def test_process_submission_without_turtle_generates_and_validates_it(
    tmp_path: Path, monkeypatch
):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root, include_ontology_turtle=False)
    executed = []

    def fake_run_step(step, command_root):
        assert command_root == root
        executed.append(step)
        if step.name == "Generate ontology.ttl":
            assert "--dry-run" not in step.command
            (model / "ontology.ttl").write_text(VALID_TURTLE, encoding="utf-8")
        elif step.name == "Generate Turtle distribution metadata":
            assert (model / "ontology.ttl").is_file()
        elif step.name == "Generate model-level metadata.ttl":
            write_expected_metadata_outputs(module, model)

    monkeypatch.setattr(module, "repository_root", lambda: root)
    monkeypatch.setattr(module, "run_step", fake_run_step)

    result = module.process_submission(parsed_args(module))
    names = [step.name for step in executed]

    assert result == 0
    assert (model / "ontology.ttl").read_text(encoding="utf-8") == VALID_TURTLE
    assert names.index("Generate ontology.ttl") < names.index(
        "Generate Turtle distribution metadata"
    )
    module.validate_all_turtle_files(model, root)


def test_malformed_json_prevents_ontology_and_metadata_generation(
    tmp_path: Path, monkeypatch
):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root, include_ontology_turtle=False)
    (model / "ontology.json").write_text("not-json", encoding="utf-8")
    executed = []

    monkeypatch.setattr(module, "repository_root", lambda: root)
    monkeypatch.setattr(
        module, "run_step", lambda step, unused_root: executed.append(step)
    )

    with pytest.raises(module.SubmissionProcessingError, match="not valid JSON"):
        module.process_submission(parsed_args(module))

    assert [step.name for step in executed] == ["Validate/fix metadata.yaml"]
    assert not (model / "ontology.ttl").exists()


def test_ontology_generator_failure_prevents_downstream_generation(
    tmp_path: Path, monkeypatch
):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root, include_ontology_turtle=False)
    executed = []

    def fake_run_step(step, unused_root):
        executed.append(step)
        if step.name == "Generate ontology.ttl":
            raise module.SubmissionProcessingError("JSON2Graph failed")

    monkeypatch.setattr(module, "repository_root", lambda: root)
    monkeypatch.setattr(module, "run_step", fake_run_step)

    with pytest.raises(module.SubmissionProcessingError, match="JSON2Graph failed"):
        module.process_submission(parsed_args(module))

    assert [step.name for step in executed] == [
        "Validate/fix metadata.yaml",
        "Generate ontology.ttl",
    ]
    assert not (model / "ontology.ttl").exists()


def test_missing_turtle_dry_run_materializes_then_removes_temporary_output(
    tmp_path: Path, monkeypatch
):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root, include_ontology_turtle=False)
    executed = []

    def fake_run_step(step, unused_root):
        executed.append(step)
        if step.name == "Generate ontology.ttl":
            assert "--dry-run" not in step.command
            (model / "ontology.ttl").write_text(VALID_TURTLE, encoding="utf-8")
        elif step.name == "Generate Turtle distribution metadata":
            assert "--dry-run" in step.command
            assert (model / "ontology.ttl").is_file()

    monkeypatch.setattr(module, "repository_root", lambda: root)
    monkeypatch.setattr(module, "run_step", fake_run_step)

    result = module.process_submission(parsed_args(module, "--dry-run"))

    assert result == 0
    assert not (model / "ontology.ttl").exists()
    assert any(
        step.name == "Generate Turtle distribution metadata" for step in executed
    )


def test_missing_turtle_dry_run_cleans_up_after_downstream_failure(
    tmp_path: Path, monkeypatch
):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root, include_ontology_turtle=False)

    def fake_run_step(step, unused_root):
        if step.name == "Generate ontology.ttl":
            (model / "ontology.ttl").write_text(VALID_TURTLE, encoding="utf-8")
        elif step.name == "Validate optional references.bib":
            raise module.SubmissionProcessingError("references validation failed")

    monkeypatch.setattr(module, "repository_root", lambda: root)
    monkeypatch.setattr(module, "run_step", fake_run_step)

    with pytest.raises(
        module.SubmissionProcessingError, match="references validation failed"
    ):
        module.process_submission(parsed_args(module, "--dry-run"))

    assert not (model / "ontology.ttl").exists()


def test_process_submission_rerun_preserves_generated_turtle(
    tmp_path: Path, monkeypatch
):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root, include_ontology_turtle=False)
    ontology_calls = 0
    ontology_writes = 0

    def fake_run_step(step, unused_root):
        nonlocal ontology_calls, ontology_writes
        if step.name == "Generate ontology.ttl":
            ontology_calls += 1
            if not (model / "ontology.ttl").exists():
                (model / "ontology.ttl").write_text(
                    VALID_TURTLE, encoding="utf-8"
                )
                ontology_writes += 1
        elif step.name == "Generate model-level metadata.ttl":
            write_expected_metadata_outputs(module, model)

    monkeypatch.setattr(module, "repository_root", lambda: root)
    monkeypatch.setattr(module, "run_step", fake_run_step)

    assert module.process_submission(parsed_args(module)) == 0
    first_bytes = (model / "ontology.ttl").read_bytes()
    assert module.process_submission(parsed_args(module)) == 0

    assert ontology_calls == 2
    assert ontology_writes == 1
    assert (model / "ontology.ttl").read_bytes() == first_bytes


def test_process_submission_replaces_drifted_turtle_before_final_validation(
    tmp_path: Path, monkeypatch
):
    module = load_module()
    root = make_repo(tmp_path)
    model = make_model(root)
    (model / "ontology.ttl").write_text("not turtle", encoding="utf-8")

    def fake_run_step(step, unused_root):
        if step.name == "Generate ontology.ttl":
            (model / "ontology.ttl").write_text(VALID_TURTLE, encoding="utf-8")
        elif step.name == "Generate model-level metadata.ttl":
            write_expected_metadata_outputs(module, model)

    monkeypatch.setattr(module, "repository_root", lambda: root)
    monkeypatch.setattr(module, "run_step", fake_run_step)

    assert module.process_submission(parsed_args(module)) == 0
    assert (model / "ontology.ttl").read_text(encoding="utf-8") == VALID_TURTLE


def test_run_step_preserves_converter_warnings_in_job_output(tmp_path: Path, capfd):
    module = load_module()
    root = make_repo(tmp_path)
    step = module.CommandStep(
        "Generate ontology.ttl",
        (
            sys.executable,
            "-c",
            "import sys; print('JSON2Graph warning: reviewed', file=sys.stderr)",
        ),
    )

    module.run_step(step, root)

    captured = capfd.readouterr()
    assert "JSON2Graph warning: reviewed" in captured.err


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
        module.SubmissionProcessingError, match="generated-artifact maintenance"
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


def test_classify_changed_files_selects_normal_mode_for_one_model():
    module = load_module()

    result = module.classify_changed_files(
        [
            "models/example-model/metadata.yaml",
            "models/example-model/ontology.json",
            "models/example-model/metadata.ttl",
            "catalog.ttl",
        ]
    )

    assert result.mode == module.NORMAL_SUBMISSION_MODE
    assert result.model_folder == "models/example-model"
    assert result.model_folders == ("models/example-model",)


def test_classify_changed_files_selects_bulk_mode_for_generated_artifacts():
    module = load_module()

    result = module.classify_changed_files(
        [
            "models/model-b/metadata-turtle.ttl",
            "models/model-a/ontology.ttl",
            "models/model-a/metadata.ttl",
            "catalog.ttl",
        ]
    )

    assert result.mode == module.BULK_GENERATED_MODE
    assert result.model_folder is None
    assert result.model_folders == ("models/model-a", "models/model-b")


@pytest.mark.parametrize(
    "source_path",
    [
        "models/model-b/metadata.yaml",
        "models/model-b/ontology.json",
        "models/model-b/ontology.vpp",
        "models/model-b/references.bib",
        "models/model-b/new-diagrams/diagram.png",
    ],
)
def test_classify_changed_files_rejects_sources_in_multi_model_pr(source_path: str):
    module = load_module()

    with pytest.raises(
        module.SubmissionProcessingError, match="generated-artifact maintenance"
    ):
        module.classify_changed_files(
            ["models/model-a/ontology.ttl", source_path]
        )


@pytest.mark.parametrize(
    "unexpected_path",
    [
        "models/model-b/metadata-json.ttl",
        "models/model-b/metadata-vpp.ttl",
        "models/model-b/metadata-png-o-diagram.ttl",
        "models/model-b/metadata-custom.ttl",
        "models/model-b/generated/ontology.ttl",
    ],
)
def test_classify_changed_files_rejects_unrecognized_bulk_artifacts(
    unexpected_path: str,
):
    module = load_module()

    with pytest.raises(
        module.SubmissionProcessingError, match="unrecognized paths"
    ):
        module.classify_changed_files(
            ["models/model-a/ontology.ttl", unexpected_path]
        )


def test_classify_changed_files_rejects_catalog_without_model_folder():
    module = load_module()

    with pytest.raises(module.SubmissionProcessingError, match="no model folders"):
        module.classify_changed_files(["catalog.ttl"])


def test_bulk_workflow_mode_is_read_only_and_normal_mode_retains_write_scope():
    workflow = load_submission_workflow()
    jobs = workflow["jobs"]
    classify_job = jobs["classify"]
    normal_job = jobs["process"]
    bulk_job = jobs["validate-bulk-generated-maintenance"]

    assert workflow["permissions"]["contents"] == "read"
    assert classify_job["permissions"]["contents"] == "read"
    assert classify_job["steps"][0]["with"]["persist-credentials"] == "false"
    classify_command = classify_job["steps"][1]["run"]
    assert '"metadata-json.ttl"' not in classify_command
    assert '"metadata-vpp.ttl"' not in classify_command
    assert "metadata-png-" not in classify_command
    assert normal_job["permissions"]["contents"] == "write"
    assert "mode == 'normal'" in normal_job["if"]
    assert bulk_job["permissions"]["contents"] == "read"
    assert "mode == 'bulk-generated'" in bulk_job["if"]
    assert bulk_job["steps"][0]["with"]["persist-credentials"] == "false"

    bulk_commands = "\n".join(
        step.get("run", "") for step in bulk_job["steps"]
    )
    assert "generate_ontology_turtle.py --all --models-dir models --check" in (
        bulk_commands
    )
    assert "generate_turtle_metadata.py --all" in bulk_commands
    assert "metadata_yaml_to_ttl.py --all" in bulk_commands
    assert "generate_catalog_file.py . --check" in bulk_commands
    assert "git diff --exit-code -- ." in bulk_commands
    assert "git push" not in bulk_commands


def test_normal_pr_checkout_is_pinned_to_classified_head_sha():
    workflow = load_submission_workflow()
    classify_job = workflow["jobs"]["classify"]
    normal_job = workflow["jobs"]["process"]

    assert classify_job["outputs"]["head_sha"] == "${{ steps.changes.outputs.head_sha }}"
    checkout_ref = normal_job["steps"][0]["with"]["ref"]
    assert "needs.classify.outputs.head_sha" in checkout_ref


def test_normal_workflow_generates_then_stages_turtle_with_noop_guard():
    workflow = load_submission_workflow()
    normal_job = workflow["jobs"]["process"]
    steps = normal_job["steps"]
    step_names = [step["name"] for step in steps]

    process_step = next(
        step for step in steps if step["name"] == "Process model submission"
    )
    commit_step = next(
        step for step in steps if step["name"] == "Commit generated files"
    )

    assert step_names.index("Process model submission") < step_names.index(
        "Synchronize catalog metadata"
    )
    assert step_names.index("Synchronize catalog metadata") < step_names.index(
        "Commit generated files"
    )
    assert "scripts/process_new_model_submission.py" in process_step["run"]
    assert "ontology.ttl" not in process_step["run"]
    assert "success()" in commit_step["if"]
    assert 'git add -- "$MODEL_PATH" catalog.ttl' in commit_step["run"]
    assert "git diff --cached --quiet" in commit_step["run"]
    assert "No generated changes to commit." in commit_step["run"]
    assert "git push" in commit_step["run"]


def test_fork_rejection_never_receives_write_permissions():
    workflow = load_submission_workflow()
    reject_job = workflow["jobs"]["reject-fork-pr"]
    classify_job = workflow["jobs"]["classify"]

    assert workflow["permissions"]["contents"] == "read"
    assert reject_job.get("permissions", {}).get("contents", "read") != "write"
    assert "head.repo.full_name != github.repository" in reject_job["if"]
    assert "head.repo.full_name == github.repository" in classify_job["if"]

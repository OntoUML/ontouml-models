from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "json2graph"


def load_module():
    script = None
    for parent in Path(__file__).resolve().parents:
        for candidate in (
            parent / "generate_ontology_turtle.py",
            parent / "scripts" / "generate_ontology_turtle.py",
        ):
            if candidate.exists():
                script = candidate
                break
        if script is not None:
            break
    assert script is not None
    spec = importlib.util.spec_from_file_location(
        "generate_ontology_turtle", script
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def repository_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "scripts").is_dir() and (parent / "models").is_dir():
            return parent
    raise AssertionError("Could not locate the repository root.")


def copy_fixture(tmp_path: Path, fixture_name: str) -> Path:
    dataset = tmp_path / "models" / fixture_name
    shutil.copytree(FIXTURES / fixture_name, dataset)
    return dataset


def write_dataset(
    tmp_path: Path,
    *,
    slug: str = "example-model",
    languages: tuple[str, ...] = ("en",),
    project_id: str = "project-1",
) -> Path:
    dataset = tmp_path / "models" / slug
    dataset.mkdir(parents=True)
    if len(languages) == 1:
        language_yaml = f"language: {languages[0]}\n"
    else:
        language_yaml = "language:\n" + "".join(
            f"  - {language}\n" for language in languages
        )
    (dataset / "metadata.yaml").write_text(
        "title: Example model\n" + language_yaml,
        encoding="utf-8",
    )
    (dataset / "ontology.json").write_text(
        json.dumps(
            {
                "id": project_id,
                "type": "Project",
                "name": "Example project",
                "model": {
                    "id": "package-1",
                    "type": "Package",
                    "name": "Example model",
                    "contents": [],
                },
            }
        ),
        encoding="utf-8",
    )
    return dataset


def candidate_text(
    module,
    dataset: Path,
    *,
    project_id: str = "project-1",
    language: str | None = "en",
    description: str | None = None,
    base_uri: str | None = None,
) -> str:
    base = base_uri or module.base_uri_for_slug(dataset.name)
    project = URIRef(base + project_id)
    graph = Graph()
    graph.add((project, RDF.type, module.ONTOUML.Project))
    graph.add((project, module.ONTOUML.name, Literal("Example project", lang=language)))
    if description is not None:
        graph.add((project, module.ONTOUML.description, Literal(description)))
    return graph.serialize(format="turtle")


def install_fake_converter(
    module,
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: str | None = None,
    diagnostics: tuple[str, ...] = (),
):
    temporary_directories: list[Path] = []

    def fake_run(dataset: Path, output_directory: Path, language: str | None):
        temporary_directories.append(output_directory)
        output = output_directory / module.ONTOLOGY_TURTLE
        output.write_text(
            text
            if text is not None
            else candidate_text(module, dataset, language=language),
            encoding="utf-8",
        )
        return output, diagnostics

    monkeypatch.setattr(module, "run_json2graph", fake_run)
    return temporary_directories


def test_installed_converter_version_is_exactly_201() -> None:
    module = load_module()

    assert module.installed_converter_version() == "2.0.1"


def test_converter_version_mismatch_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module()
    monkeypatch.setattr(module, "version", lambda _name: "2.0.0")

    with pytest.raises(module.GeneratorSetupError, match="Expected.*2.0.1.*2.0.0"):
        module.installed_converter_version()


def test_missing_converter_package_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module()

    def missing(_name: str):
        raise module.PackageNotFoundError

    monkeypatch.setattr(module, "version", missing)

    with pytest.raises(module.GeneratorSetupError, match="is not installed"):
        module.installed_converter_version()


def test_base_uri_and_single_language_command_are_exact(tmp_path: Path) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)
    output = tmp_path / "output"

    command = module.build_json2graph_command(
        dataset,
        output,
        "en",
        python_executable="test-python",
    )

    assert module.base_uri_for_slug("example-model") == (
        "https://w3id.org/ontouml-models/model/example-model#"
    )
    assert command == [
        "test-python",
        "-m",
        "json2graph.decode",
        "-i",
        str(dataset / "ontology.json"),
        "-o",
        str(output),
        "-f",
        "ttl",
        "--base-uri",
        "https://w3id.org/ontouml-models/model/example-model#",
        "--language",
        "en",
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


def test_multilingual_command_omits_language_and_unselected_options(
    tmp_path: Path,
) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path, languages=("en", "pt-br"))

    command = module.build_json2graph_command(dataset, tmp_path / "output", None)

    assert "--language" not in command
    assert "--correct" not in command
    assert "--model_only" not in command
    assert "--decode_all" not in command


def test_dataset_path_traversal_is_rejected(tmp_path: Path) -> None:
    module = load_module()
    escaped = tmp_path / "models" / ".." / "outside"
    escaped.mkdir(parents=True)

    with pytest.raises(module.DatasetGenerationError) as error:
        module.validate_dataset_folder(escaped)

    assert error.value.category == "path-traversal"


@pytest.mark.parametrize("slug", ["bad slug", "bad#slug", "bad@slug"])
def test_invalid_dataset_slug_is_rejected(tmp_path: Path, slug: str) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path, slug=slug)

    with pytest.raises(module.DatasetGenerationError) as error:
        module.validate_dataset_folder(dataset)

    assert error.value.category == "invalid-slug"


def test_missing_dataset_source_is_rejected(tmp_path: Path) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)
    (dataset / "ontology.json").unlink()

    with pytest.raises(module.DatasetGenerationError) as error:
        module.validate_dataset_folder(dataset)

    assert error.value.category == "missing-source"


@pytest.mark.parametrize(
    ("yaml_text", "expected"),
    [
        ("language: en\n", ("en",)),
        ("language: [en]\n", ("en",)),
        ("language: en, pt-br\n", ("en", "pt-br")),
        ("language:\n  - en\n  - nl\n", ("en", "nl")),
        ("language:\n  - pt-BR\n  - pt-br\n", ("pt-BR",)),
    ],
)
def test_metadata_language_forms_are_normalized(
    tmp_path: Path,
    yaml_text: str,
    expected: tuple[str, ...],
) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)
    (dataset / "metadata.yaml").write_text(yaml_text, encoding="utf-8")

    assert module.load_declared_languages(dataset) == expected


@pytest.mark.parametrize(
    ("yaml_text", "category"),
    [
        ("title: Missing language\n", "missing-language"),
        ("language: english\n", "invalid-language"),
        ("language: en\nLanguage: pt-br\n", "ambiguous-language"),
        ("language: en\nlanguage: pt-br\n", "invalid-metadata"),
    ],
)
def test_invalid_metadata_language_is_rejected(
    tmp_path: Path,
    yaml_text: str,
    category: str,
) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)
    (dataset / "metadata.yaml").write_text(yaml_text, encoding="utf-8")

    with pytest.raises(module.DatasetGenerationError) as error:
        module.load_declared_languages(dataset)

    assert error.value.category == category


@pytest.mark.parametrize(
    ("content", "category"),
    [
        ('{"id":', "invalid-json"),
        ("[]", "invalid-json-root"),
        ('{"type": "Project"}', "missing-project-id"),
    ],
)
def test_invalid_project_identity_source_is_rejected(
    tmp_path: Path,
    content: str,
    category: str,
) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)
    (dataset / "ontology.json").write_text(content, encoding="utf-8")

    with pytest.raises(module.DatasetGenerationError) as error:
        module.load_project_id(dataset)

    assert error.value.category == category


def test_candidate_requires_canonical_namespace_and_exact_project_id(
    tmp_path: Path,
) -> None:
    module = load_module()
    dataset = tmp_path / "models" / "example-model"
    base = module.base_uri_for_slug(dataset.name)
    valid = Graph()
    valid.add((URIRef(base + "project-1"), RDF.type, module.ONTOUML.Project))

    module.validate_candidate_namespace(valid, dataset, base, "project-1")

    wrong_project = Graph()
    wrong_project.add((URIRef(base + "wrong"), RDF.type, module.ONTOUML.Project))
    with pytest.raises(module.DatasetGenerationError) as project_error:
        module.validate_candidate_namespace(
            wrong_project, dataset, base, "project-1"
        )
    assert project_error.value.category == "wrong-project-identity"

    foreign = Graph()
    foreign.add(
        (
            URIRef("https://example.org/project-1"),
            RDF.type,
            module.ONTOUML.Project,
        )
    )
    with pytest.raises(module.DatasetGenerationError) as namespace_error:
        module.validate_candidate_namespace(foreign, dataset, base, "project-1")
    assert namespace_error.value.category == "wrong-namespace"


def test_candidate_language_validation_enforces_selected_policy(tmp_path: Path) -> None:
    module = load_module()
    dataset = tmp_path / "models" / "example-model"
    subject = URIRef("https://example.org/subject")

    tagged = Graph()
    tagged.add((subject, module.ONTOUML.name, Literal("Name", lang="en")))
    module.validate_candidate_languages(tagged, dataset, "en")
    with pytest.raises(module.DatasetGenerationError) as tagged_error:
        module.validate_candidate_languages(tagged, dataset, None)
    assert tagged_error.value.category == "unexpected-language-tag"

    untagged = Graph()
    untagged.add((subject, module.ONTOUML.name, Literal("Name")))
    module.validate_candidate_languages(untagged, dataset, None)
    with pytest.raises(module.DatasetGenerationError) as untagged_error:
        module.validate_candidate_languages(untagged, dataset, "en")
    assert untagged_error.value.category == "wrong-language-tag"


def test_converter_execution_error_is_categorized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)

    def fail(*_args, **_kwargs):
        raise OSError("executable missing")

    monkeypatch.setattr(module.subprocess, "run", fail)

    with pytest.raises(module.DatasetGenerationError) as error:
        module.run_json2graph(dataset, tmp_path / "output", "en")

    assert error.value.category == "converter-execution"


def test_converter_nonzero_exit_is_categorized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)
    completed = subprocess.CompletedProcess(
        args=["json2graph"], returncode=7, stdout="", stderr="conversion failed"
    )
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: completed)

    with pytest.raises(module.DatasetGenerationError) as error:
        module.run_json2graph(dataset, tmp_path / "output", "en")

    assert error.value.category == "converter-nonzero-exit"
    assert "code 7" in str(error.value)
    assert "conversion failed" in str(error.value)


def test_converter_missing_output_is_categorized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    completed = subprocess.CompletedProcess(
        args=["json2graph"], returncode=0, stdout="", stderr=""
    )
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: completed)

    with pytest.raises(module.DatasetGenerationError) as error:
        module.run_json2graph(dataset, output, "en")

    assert error.value.category == "missing-output"


def test_invalid_candidate_never_overwrites_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)
    target = dataset / "ontology.ttl"
    original = b"<https://example.org/old> <https://example.org/p> <https://example.org/o> .\n"
    target.write_bytes(original)
    install_fake_converter(module, monkeypatch, text="not valid Turtle")

    with pytest.raises(module.DatasetGenerationError) as error:
        module.process_dataset(dataset, module.Config(), "2.0.1")

    assert error.value.category == "invalid-candidate-turtle"
    assert target.read_bytes() == original


def test_wrong_namespace_never_overwrites_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)
    target = dataset / "ontology.ttl"
    original = b"<https://example.org/old> <https://example.org/p> <https://example.org/o> .\n"
    target.write_bytes(original)
    wrong = candidate_text(
        module,
        dataset,
        base_uri="https://example.org/foreign#",
    )
    install_fake_converter(module, monkeypatch, text=wrong)

    with pytest.raises(module.DatasetGenerationError) as error:
        module.process_dataset(dataset, module.Config(), "2.0.1")

    assert error.value.category == "wrong-namespace"
    assert target.read_bytes() == original


def test_new_output_is_created_after_validation_and_temp_output_is_cleaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)
    temporary_directories = install_fake_converter(module, monkeypatch)

    result = module.process_dataset(dataset, module.Config(), "2.0.1")

    assert result.existed is False
    assert result.changed is True
    assert result.written is True
    assert (dataset / "ontology.ttl").is_file()
    assert temporary_directories
    assert all(not path.exists() for path in temporary_directories)


def test_normal_mode_preserves_isomorphic_existing_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)
    generated = candidate_text(module, dataset)
    target = dataset / "ontology.ttl"
    historical = ("# historical serialization\n" + generated).encode("utf-8")
    target.write_bytes(historical)
    install_fake_converter(module, monkeypatch, text=generated)

    result = module.process_dataset(dataset, module.Config(), "2.0.1")

    assert result.isomorphic is True
    assert result.changed is False
    assert result.written is False
    assert target.read_bytes() == historical


def test_normal_mode_replaces_semantically_different_existing_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)
    old = candidate_text(module, dataset, description="old")
    new = candidate_text(module, dataset, description="new")
    target = dataset / "ontology.ttl"
    target.write_text(old, encoding="utf-8")
    install_fake_converter(module, monkeypatch, text=new)

    result = module.process_dataset(dataset, module.Config(), "2.0.1")

    assert result.isomorphic is False
    assert result.changed is True
    assert result.written is True
    assert Graph().parse(target).isomorphic(Graph().parse(data=new, format="turtle"))


def test_force_materialization_installs_isomorphic_byte_different_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)
    generated = candidate_text(module, dataset)
    target = dataset / "ontology.ttl"
    target.write_text("# historical serialization\n" + generated, encoding="utf-8")
    install_fake_converter(module, monkeypatch, text=generated)

    result = module.process_dataset(
        dataset,
        module.Config(force_materialization=True),
        "2.0.1",
    )

    assert result.isomorphic is True
    assert result.changed is True
    assert result.written is True
    assert target.read_text(encoding="utf-8") == generated


def test_atomic_replacement_failure_preserves_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)
    target = dataset / "ontology.ttl"
    original = candidate_text(module, dataset, description="old").encode("utf-8")
    target.write_bytes(original)
    install_fake_converter(
        module,
        monkeypatch,
        text=candidate_text(module, dataset, description="new"),
    )

    def fail_replace(_source: Path, _target: Path):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(module.os, "replace", fail_replace)

    with pytest.raises(module.DatasetGenerationError) as error:
        module.process_dataset(dataset, module.Config(), "2.0.1")

    assert error.value.category == "atomic-replacement-failed"
    assert target.read_bytes() == original
    assert list(dataset.glob(".ontology.ttl.*.tmp")) == []


def test_dataset_discovery_is_sorted_and_ignores_non_datasets(tmp_path: Path) -> None:
    module = load_module()
    models = tmp_path / "models"
    for name in ("z-model", "A-model", "m-model"):
        write_dataset(tmp_path, slug=name)
    (models / "not-a-dataset").mkdir()

    discovered = module.discover_datasets(models)

    assert [path.name for path in discovered] == ["A-model", "m-model", "z-model"]


def test_explicit_targets_are_deduplicated_and_sorted(tmp_path: Path) -> None:
    module = load_module()
    first = write_dataset(tmp_path, slug="z-model")
    second = write_dataset(tmp_path, slug="a-model")
    args = argparse.Namespace(
        all=False,
        datasets=[first, second, first],
        models_dir=tmp_path / "models",
    )

    targets = module.resolve_targets(args)

    assert [path.name for path in targets] == ["a-model", "z-model"]


def test_check_mode_reports_drift_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)
    install_fake_converter(module, monkeypatch)

    exit_code = module.main([str(dataset), "--check"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "needs update" in captured.out
    assert not (dataset / "ontology.ttl").exists()


def test_check_mode_accepts_isomorphic_existing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)
    generated = candidate_text(module, dataset)
    target = dataset / "ontology.ttl"
    historical = "# historical serialization\n" + generated
    target.write_text(historical, encoding="utf-8")
    install_fake_converter(module, monkeypatch, text=generated)

    exit_code = module.main([str(dataset), "--check", "--quiet"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == ""
    assert target.read_text(encoding="utf-8") == historical


def test_dry_run_reports_change_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)
    install_fake_converter(module, monkeypatch)

    exit_code = module.main([str(dataset), "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "would create" in captured.out
    assert not (dataset / "ontology.ttl").exists()


def test_quiet_mode_suppresses_text_but_preserves_converter_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)
    install_fake_converter(
        module,
        monkeypatch,
        diagnostics=("ExamplePolicyWarning: expected diagnostic",),
    )

    exit_code = module.main([str(dataset), "--dry-run", "--quiet"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == ""
    assert "ExamplePolicyWarning" in captured.err


def test_json_reporting_is_machine_readable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_module()
    dataset = write_dataset(tmp_path)
    install_fake_converter(module, monkeypatch)

    exit_code = module.main([str(dataset), "--dry-run", "--format", "json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["converter_version"] == "2.0.1"
    assert payload["errors"] == []
    assert payload["results"][0]["slug"] == "example-model"
    assert payload["results"][0]["language"] == "en"
    assert payload["results"][0]["written"] is False


def test_setup_error_uses_exit_code_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_module()
    monkeypatch.setattr(
        module,
        "installed_converter_version",
        lambda: (_ for _ in ()).throw(module.GeneratorSetupError("bad setup")),
    )

    assert module.main([str(tmp_path / "missing")]) == 2
    assert "ERROR [setup]: bad setup" in capsys.readouterr().err


def test_check_and_dry_run_are_mutually_exclusive() -> None:
    module = load_module()

    with pytest.raises(SystemExit) as error:
        module.parse_args(["--check", "--dry-run"])

    assert error.value.code == 2


def test_real_minimal_single_language_generation_and_noop_rerun(
    tmp_path: Path,
) -> None:
    module = load_module()
    dataset = copy_fixture(tmp_path, "minimal-single-language")

    first = module.process_dataset(dataset, module.Config(), "2.0.1")
    first_bytes = (dataset / "ontology.ttl").read_bytes()
    second = module.process_dataset(dataset, module.Config(), "2.0.1")
    graph = Graph().parse(dataset / "ontology.ttl")
    names = list(graph.objects(None, module.ONTOUML.name))

    assert first.written is True
    assert second.isomorphic is True
    assert second.changed is False
    assert second.written is False
    assert (dataset / "ontology.ttl").read_bytes() == first_bytes
    assert names
    assert all(isinstance(name, Literal) and name.language == "en" for name in names)
    assert (
        URIRef(module.base_uri_for_slug(dataset.name) + "project-1"),
        RDF.type,
        module.ONTOUML.Project,
    ) in graph
    assert list(dataset.glob("*.provenance.ttl")) == []


def test_real_minimal_multilingual_generation_uses_untagged_names(
    tmp_path: Path,
) -> None:
    module = load_module()
    dataset = copy_fixture(tmp_path, "minimal-multilingual")

    result = module.process_dataset(dataset, module.Config(), "2.0.1")
    graph = Graph().parse(dataset / "ontology.ttl")
    names = list(graph.objects(None, module.ONTOUML.name))

    assert result.declared_languages == ("en", "pt-br")
    assert result.language is None
    assert names
    assert all(isinstance(name, Literal) and name.language is None for name in names)


def test_real_policy_fixture_emits_and_applies_all_selected_policies(
    tmp_path: Path,
) -> None:
    module = load_module()
    dataset = copy_fixture(tmp_path, "policy-warnings")

    result = module.process_dataset(dataset, module.Config(), "2.0.1")
    diagnostics = "\n".join(result.diagnostics)
    graph = Graph().parse(dataset / "ontology.ttl")
    base = module.base_uri_for_slug(dataset.name)
    class_uri = URIRef(base + "policy-class")
    cardinality_uri = URIRef(base + "policy-property_cardinality")
    view_uri = URIRef(base + "unresolved-view")
    missing_uri = URIRef(base + "missing-relation")
    path_uri = URIRef(base + "unresolved-view_path")

    for warning_name in (
        "InvalidCardinalityWarning",
        "InvalidStereotypeWarning",
        "UnresolvedModelElementWarning",
        "PathPointOrderWarning",
        "PropertyAssignmentWarning",
    ):
        assert warning_name in diagnostics
    assert (
        class_uri,
        module.ONTOUML.stereotype,
        module.ONTOUML.abstractIndividual,
    ) in graph
    assert (
        cardinality_uri,
        module.ONTOUML.cardinalityValue,
        Literal("-1"),
    ) in graph
    assert list(graph.objects(cardinality_uri, module.ONTOUML.lowerBound)) == []
    assert list(graph.objects(cardinality_uri, module.ONTOUML.upperBound)) == []
    assert list(graph.objects(view_uri, module.ONTOUML.isViewOf)) == []
    assert list(graph.triples((missing_uri, None, None))) == []
    assert list(graph.triples((None, None, missing_uri))) == []
    assert len(set(graph.objects(path_uri, module.ONTOUML.point))) == 3
    assert list(graph.objects(class_uri, RDFS.comment)) == []


@pytest.mark.parametrize(
    ("fixture_name", "category"),
    [
        ("malformed-json", "invalid-json"),
        ("non-object-json", "invalid-json-root"),
    ],
)
def test_invalid_json_fixtures_fail_without_creating_output(
    tmp_path: Path,
    fixture_name: str,
    category: str,
) -> None:
    module = load_module()
    dataset = copy_fixture(tmp_path, fixture_name)

    with pytest.raises(module.DatasetGenerationError) as error:
        module.process_dataset(dataset, module.Config(), "2.0.1")

    assert error.value.category == category
    assert not (dataset / "ontology.ttl").exists()


@pytest.mark.parametrize("slug", ["amaral2019rot", "alpinebits2022"])
def test_representative_catalog_dataset_converts_without_writing(slug: str) -> None:
    module = load_module()
    dataset = repository_root() / "models" / slug
    before = (dataset / "ontology.ttl").read_bytes()

    result = module.process_dataset(
        dataset,
        module.Config(dry_run=True),
        "2.0.1",
    )

    assert result.candidate_triples > 0
    assert result.base_uri == module.base_uri_for_slug(slug)
    assert result.written is False
    assert (dataset / "ontology.ttl").read_bytes() == before

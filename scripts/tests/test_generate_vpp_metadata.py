from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path

import pytest


def load_module():
    script = None
    for parent in Path(__file__).resolve().parents:
        for candidate in (
            parent / "generate_vpp_metadata.py",
            parent / "scripts" / "generate_vpp_metadata.py",
        ):
            if candidate.exists():
                script = candidate
                break
        if script is not None:
            break
    assert script is not None
    spec = importlib.util.spec_from_file_location("generate_vpp_metadata", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_metadata_yaml(
    dataset: Path,
    *,
    slug: str = "example",
    title: str = "Petroleum System Model",
    issued: str = "2015",
    license_value: str | None = "https://creativecommons.org/licenses/by/4.0/",
    model_uri: str | None = None,
) -> None:
    license_line = f"license: {license_value}\n" if license_value is not None else ""
    uri_line = f"uri: {model_uri}\n" if model_uri is not None else ""
    (dataset / "metadata.yaml").write_text(
        f"""
id: {slug}
title: {title}
issued: {issued}
{uri_line}{license_line}""".strip()
        + "\n",
        encoding="utf-8",
    )


def deterministic_model_uri(slug: str) -> str:
    model_uuid = uuid.uuid5(
        uuid.NAMESPACE_URL, f"https://w3id.org/ontouml-models/model|{slug}"
    )
    return f"https://w3id.org/ontouml-models/model/{model_uuid}"


def write_dataset(tmp_path: Path) -> Path:
    dataset = tmp_path / "models" / "example-model"
    dataset.mkdir(parents=True)
    (dataset / "ontology.vpp").write_bytes(b"VPP test bytes")
    write_metadata_yaml(dataset)
    return dataset


def write_existing_vpp_metadata(
    dataset: Path,
    *,
    model_uri: str = "https://w3id.org/ontouml-models/model/0647761f-976f-41c4-94c0-a907ae1ed577",
    title: str = "Existing VPP title",
    license_line: str = "    dct:license <https://creativecommons.org/licenses/by-sa/4.0/>;\n",
    download_url: str = "https://raw.githubusercontent.com/OntoUML/ontouml-models/master/models/example-model/ontology.vpp",
    editorial_note_line: str = '    skos:editorialNote "Existing VPP editorial note."@en;\n',
) -> None:
    (dataset / "metadata-vpp.ttl").write_text(
        f"""
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
@prefix ocmv: <https://w3id.org/ontouml-models/vocabulary#>.
@prefix skos: <http://www.w3.org/2004/02/skos/core#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

<https://w3id.org/ontouml-models/distribution/existing-vpp> a dcat:Distribution;
    dct:isPartOf <{model_uri}>;
    dct:issued "2015"^^xsd:gYear;
{license_line}    dcat:mediaType <https://www.iana.org/assignments/media-types/application/octet-stream>;
    dct:format <https://www.file-extension.info/format/vpp>;
    dct:title "{title}"@en;
    dcat:downloadURL <{download_url}>;
    ocmv:isComplete "true"^^xsd:boolean;
{editorial_note_line}    fdpo:metadataIssued "2023-04-14T17:33:24.802284319Z"^^xsd:dateTime;
    fdpo:metadataModified "2023-04-14T17:33:25.802284319Z"^^xsd:dateTime .
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_vpp_metadata_generation_uses_metadata_yaml_when_metadata_ttl_is_absent(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_dataset(tmp_path)

    assert not (dataset / "metadata.ttl").exists()
    generated = module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    assert len(generated) == 1
    text = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")
    assert "metadata.ttl" not in text
    assert (
        "dcat:mediaType <https://www.iana.org/assignments/media-types/application/octet-stream>"
        in text
    )
    assert "dct:format <https://www.file-extension.info/format/vpp>" in text
    assert "ocmv:isComplete true" in text
    assert (
        'dct:title "Visual Paradigm distribution of Petroleum System Model"@en' in text
    )
    assert "https://creativecommons.org/licenses/by/4.0/" in text
    assert (
        "https://raw.githubusercontent.com/OntoUML/ontouml-models/master/models/example-model/ontology.vpp"
        in text
    )


def test_existing_vpp_metadata_preserves_distribution_and_curated_values(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_dataset(tmp_path)
    write_existing_vpp_metadata(dataset)

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    text = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")
    assert "https://w3id.org/ontouml-models/distribution/existing-vpp" in text
    assert (
        "dct:isPartOf <https://w3id.org/ontouml-models/model/0647761f-976f-41c4-94c0-a907ae1ed577>"
        in text
    )
    assert "Existing VPP title" in text
    assert "Existing VPP editorial note." in text
    assert "https://creativecommons.org/licenses/by-sa/4.0/" in text
    assert "2023-04-14T17:33:24.802284319Z" in text
    assert "2023-04-14T17:33:25.802284319Z" not in text
    assert "2024-01-02T03:04:05Z" in text


def test_other_distribution_is_part_of_is_used_when_vpp_metadata_is_absent(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_dataset(tmp_path)
    (dataset / "metadata-json.ttl").write_text(
        """
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.

<https://w3id.org/ontouml-models/distribution/json-existing> a dcat:Distribution;
    dct:isPartOf <https://w3id.org/ontouml-models/model/from-json> .
""".strip()
        + "\n",
        encoding="utf-8",
    )

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    text = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")
    assert "dct:isPartOf <https://w3id.org/ontouml-models/model/from-json>" in text


def test_conflicting_other_distribution_model_iris_fail(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)
    (dataset / "metadata-json.ttl").write_text(
        "@prefix dct: <http://purl.org/dc/terms/>.\n"
        "<https://example.org/d1> dct:isPartOf <https://w3id.org/ontouml-models/model/a> .\n",
        encoding="utf-8",
    )
    (dataset / "metadata-turtle.ttl").write_text(
        "@prefix dct: <http://purl.org/dc/terms/>.\n"
        "<https://example.org/d2> dct:isPartOf <https://w3id.org/ontouml-models/model/b> .\n",
        encoding="utf-8",
    )

    with pytest.raises(module.MetadataGenerationError, match="Conflicting model URIs"):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )

    assert not (dataset / "metadata-vpp.ttl").exists()


def test_existing_vpp_model_uri_conflict_with_other_distribution_fails(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)
    write_existing_vpp_metadata(
        dataset,
        model_uri="https://w3id.org/ontouml-models/model/from-vpp",
    )
    (dataset / "metadata-json.ttl").write_text(
        "@prefix dcat: <http://www.w3.org/ns/dcat#>.\n"
        "@prefix dct: <http://purl.org/dc/terms/>.\n"
        "<https://w3id.org/ontouml-models/distribution/json-existing> "
        "a dcat:Distribution; "
        "dct:isPartOf <https://w3id.org/ontouml-models/model/from-json> .\n",
        encoding="utf-8",
    )

    with pytest.raises(module.MetadataGenerationError, match="Conflicting model URIs"):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )

    text = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")
    assert "from-vpp" in text
    assert "from-json" not in text


def test_new_dataset_uses_converter_compatible_deterministic_model_uri(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "new-deterministic-model"
    dataset.mkdir(parents=True)
    (dataset / "ontology.vpp").write_bytes(b"VPP test bytes")
    write_metadata_yaml(
        dataset,
        slug="ignored-yaml-id",
        title="New Deterministic Model",
        issued="2024",
    )

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    text = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")
    assert (
        f"dct:isPartOf <{deterministic_model_uri('new-deterministic-model')}>" in text
    )
    assert "ignored-yaml-id" not in text


def test_explicit_yaml_model_uri_is_used_for_new_dataset(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)
    (dataset / "metadata.yaml").unlink()
    write_metadata_yaml(
        dataset,
        title="Explicit URI Model",
        issued="2024",
        model_uri="https://w3id.org/ontouml-models/model/explicit-yaml-model",
    )

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    text = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")
    assert (
        "dct:isPartOf <https://w3id.org/ontouml-models/model/explicit-yaml-model>"
        in text
    )


def test_existing_catalog_dataset_without_distribution_model_iri_fails(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)
    (dataset / "metadata.ttl").write_text(
        "@prefix dcat: <http://www.w3.org/ns/dcat#>.\n"
        "<https://w3id.org/ontouml-models/model/existing> a dcat:Dataset .\n",
        encoding="utf-8",
    )

    with pytest.raises(
        module.MetadataGenerationError, match="stable catalog model IRI"
    ):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )

    assert not (dataset / "metadata-vpp.ttl").exists()


def test_existing_vpp_metadata_without_is_part_of_fails(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)
    (dataset / "metadata-vpp.ttl").write_text(
        """
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

<https://w3id.org/ontouml-models/distribution/existing-vpp> a dcat:Distribution;
    fdpo:metadataIssued "2023-04-14T17:33:24.802284319Z"^^xsd:dateTime;
    fdpo:metadataModified "2023-04-14T17:33:25.802284319Z"^^xsd:dateTime .
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(module.MetadataGenerationError, match="no dct:isPartOf"):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )


def test_missing_license_fails_without_allow_missing_license(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)
    write_metadata_yaml(
        dataset,
        title="Missing License Model",
        issued="2024",
        license_value=None,
    )

    with pytest.raises(module.MetadataGenerationError, match="license"):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )

    assert not (dataset / "metadata-vpp.ttl").exists()


def test_missing_license_is_allowed_with_allow_missing_license(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)
    write_metadata_yaml(
        dataset,
        title="Missing License Model",
        issued="2024",
        license_value=None,
    )

    module.process_dataset(
        dataset,
        module.Config(
            metadata_timestamp="2024-01-02T03:04:05Z",
            allow_missing_license=True,
        ),
    )

    text = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")
    assert "dct:license" not in text
    assert "Missing License Model" in text


def test_available_license_is_emitted_when_allow_missing_license_is_used(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_dataset(tmp_path)

    module.process_dataset(
        dataset,
        module.Config(
            metadata_timestamp="2024-01-02T03:04:05Z",
            allow_missing_license=True,
        ),
    )

    text = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")
    assert "dct:license <https://creativecommons.org/licenses/by/4.0/>" in text


def test_existing_distribution_license_is_preserved_with_missing_license_relaxation(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_dataset(tmp_path)
    write_metadata_yaml(dataset, title="Legacy", issued="2024", license_value=None)
    write_existing_vpp_metadata(dataset)

    module.process_dataset(
        dataset,
        module.Config(
            metadata_timestamp="2024-01-02T03:04:05Z",
            allow_missing_license=True,
        ),
    )

    text = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")
    assert "dct:license <https://creativecommons.org/licenses/by-sa/4.0/>" in text


def test_missing_metadata_timestamp_for_new_vpp_metadata_fails(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)

    with pytest.raises(module.MetadataGenerationError, match="metadata-timestamp"):
        module.process_dataset(dataset, module.Config())

    assert not (dataset / "metadata-vpp.ttl").exists()


def test_timestamp_initialization_for_new_file(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    text = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")
    assert text.count("2024-01-02T03:04:05Z") == 2


def test_metadata_modified_is_preserved_when_existing_file_is_unchanged(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)
    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )
    first = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")

    generated = module.process_dataset(dataset, module.Config())

    second = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")
    assert generated[0].changed is False
    assert first == second
    assert "2024-01-02T03:04:05Z" in second


def test_missing_metadata_timestamp_for_changed_existing_file_fails(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)
    write_existing_vpp_metadata(dataset, title="Outdated title")
    write_metadata_yaml(dataset, title="Current title", issued="2024")

    with pytest.raises(module.MetadataGenerationError, match="metadata-timestamp"):
        module.process_dataset(dataset, module.Config())

    text = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")
    assert "Outdated title" in text


def test_check_mode_reports_change_without_writing(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)

    result = module.main(
        [
            str(dataset),
            "--check",
            "--metadata-timestamp",
            "2024-01-02T03:04:05Z",
            "--quiet",
        ]
    )

    assert result == 1
    assert not (dataset / "metadata-vpp.ttl").exists()


def test_dry_run_does_not_write(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)

    generated = module.process_dataset(
        dataset,
        module.Config(
            metadata_timestamp="2024-01-02T03:04:05Z",
            dry_run=True,
        ),
    )

    assert generated[0].changed is True
    assert generated[0].written is False
    assert not (dataset / "metadata-vpp.ttl").exists()


def test_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    module = load_module()
    dataset = write_dataset(tmp_path)

    result = module.main(
        [
            str(dataset),
            "--format",
            "json",
            "--metadata-timestamp",
            "2024-01-02T03:04:05Z",
        ]
    )

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["errors"] == []
    assert output["results"][0]["metadata_path"].endswith("metadata-vpp.ttl")


def test_no_partial_write_when_source_file_is_missing(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)
    (dataset / "ontology.vpp").unlink()

    with pytest.raises(
        module.MetadataGenerationError, match="Missing required VPP source file"
    ):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )

    assert not (dataset / "metadata-vpp.ttl").exists()


def test_generated_identifiers_and_urls_use_repository_relative_paths(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "deep" / "repo" / "models" / "relative-model"
    dataset.mkdir(parents=True)
    (dataset / "ontology.vpp").write_bytes(b"VPP test bytes")
    write_metadata_yaml(dataset, title="Relative Model", issued="2024")

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    text = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")
    assert str(tmp_path) not in text
    assert "models/relative-model/ontology.vpp" in text


def test_model_uri_trailing_slash_normalization_avoids_false_conflict(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_dataset(tmp_path)
    write_existing_vpp_metadata(
        dataset,
        model_uri="https://w3id.org/ontouml-models/model/same-model/",
    )
    (dataset / "metadata-json.ttl").write_text(
        "@prefix dcat: <http://www.w3.org/ns/dcat#>.\n"
        "@prefix dct: <http://purl.org/dc/terms/>.\n"
        "<https://w3id.org/ontouml-models/distribution/json-existing> "
        "a dcat:Distribution; "
        "dct:isPartOf <https://w3id.org/ontouml-models/model/same-model> .\n",
        encoding="utf-8",
    )

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    text = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")
    assert "dct:isPartOf <https://w3id.org/ontouml-models/model/same-model>" in text


def test_full_is_part_of_uri_in_other_distribution_is_used(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)
    (dataset / "metadata-json.ttl").write_text(
        "<https://w3id.org/ontouml-models/distribution/json-existing> "
        "<http://purl.org/dc/terms/isPartOf> "
        "<https://w3id.org/ontouml-models/model/full-predicate-model> .\n",
        encoding="utf-8",
    )

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    text = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")
    assert (
        "dct:isPartOf <https://w3id.org/ontouml-models/model/full-predicate-model>"
        in text
    )


def test_new_distribution_uri_is_deterministic_and_source_based(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "stable-vpp-id"
    dataset.mkdir(parents=True)
    (dataset / "ontology.vpp").write_bytes(b"VPP test bytes")
    write_metadata_yaml(dataset, title="Stable VPP ID", issued="2024")

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    model_uri = deterministic_model_uri("stable-vpp-id")
    expected_distribution_uri = (
        "https://w3id.org/ontouml-models/distribution/"
        f"{uuid.uuid5(uuid.NAMESPACE_URL, f'{model_uri}|ontology.vpp')}/"
    )
    text = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")
    assert expected_distribution_uri in text

    first = text
    (dataset / "metadata-vpp.ttl").unlink()
    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )
    second = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")
    assert expected_distribution_uri in second
    assert first == second


def test_no_overwrite_fails_without_changing_existing_metadata(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)
    write_existing_vpp_metadata(dataset)
    before = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")

    with pytest.raises(module.MetadataGenerationError, match="overwrite is disabled"):
        module.process_dataset(dataset, module.Config(overwrite=False))

    after = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")
    assert after == before


def test_all_mode_processes_multiple_datasets(tmp_path: Path):
    module = load_module()
    models_dir = tmp_path / "models"
    dataset_a = models_dir / "dataset-a"
    dataset_b = models_dir / "dataset-b"
    dataset_a.mkdir(parents=True)
    dataset_b.mkdir()
    (dataset_a / "ontology.vpp").write_bytes(b"VPP A")
    (dataset_b / "ontology.vpp").write_bytes(b"VPP B")
    write_metadata_yaml(dataset_a, title="Dataset A", issued="2024")
    write_metadata_yaml(dataset_b, title="Dataset B", issued="2024")

    result = module.main(
        [
            "--all",
            "--models-dir",
            str(models_dir),
            "--metadata-timestamp",
            "2024-01-02T03:04:05Z",
            "--quiet",
        ]
    )

    assert result == 0
    assert (dataset_a / "metadata-vpp.ttl").exists()
    assert (dataset_b / "metadata-vpp.ttl").exists()


def test_invalid_metadata_timestamp_fails_without_writing(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)

    with pytest.raises(module.MetadataGenerationError, match="metadata-timestamp"):
        module.process_dataset(dataset, module.Config(metadata_timestamp="not-a-date"))

    assert not (dataset / "metadata-vpp.ttl").exists()


def test_malformed_existing_vpp_metadata_fails_without_writing(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)
    malformed = "@prefix dcat: <http://www.w3.org/ns/dcat#>.\n<this is not turtle"
    (dataset / "metadata-vpp.ttl").write_text(malformed, encoding="utf-8")

    with pytest.raises(module.MetadataGenerationError, match="Could not parse"):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )

    assert (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8") == malformed


def test_repository_branch_and_models_dir_name_options_in_download_url(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_dataset(tmp_path)

    module.process_dataset(
        dataset,
        module.Config(
            repository="pedropaulofb/ontouml-models-dev",
            branch="metadata regeneration",
            models_dir_name="catalog models",
            metadata_timestamp="2024-01-02T03:04:05Z",
        ),
    )

    text = (dataset / "metadata-vpp.ttl").read_text(encoding="utf-8")
    assert (
        "https://raw.githubusercontent.com/pedropaulofb/ontouml-models-dev/"
        "metadata%20regeneration/catalog%20models/example-model/ontology.vpp"
    ) in text

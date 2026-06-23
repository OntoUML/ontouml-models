from __future__ import annotations

import importlib.util
import io
import json
import sys
import uuid
from contextlib import redirect_stdout
from pathlib import Path

import pytest


def load_module():
    script = None
    for parent in Path(__file__).resolve().parents:
        for candidate in (
            parent / "generate_turtle_metadata.py",
            parent / "scripts" / "generate_turtle_metadata.py",
        ):
            if candidate.exists():
                script = candidate
                break
        if script is not None:
            break
    assert script is not None
    spec = importlib.util.spec_from_file_location("generate_turtle_metadata", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_metadata_yaml(
    dataset: Path,
    *,
    title: str = "Aviation Safety Ontology",
    issued: str = "2018",
    license_value: str | None = "https://creativecommons.org/licenses/by/4.0/",
    uri: str | None = None,
) -> None:
    lines = [f"title: {title}", f"issued: {issued}"]
    if license_value is not None:
        lines.append(f"license: {license_value}")
    if uri is not None:
        lines.append(f"uri: {uri}")
    (dataset / "metadata.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_ontology(dataset: Path, *, valid: bool = True) -> None:
    if valid:
        text = "@prefix ex: <https://example.org/> .\nex:s ex:p ex:o .\n"
    else:
        text = "@prefix ex: <https://example.org/> .\nex:s ex:p .\n"
    (dataset / "ontology.ttl").write_text(text, encoding="utf-8")


def make_dataset(tmp_path: Path, name: str = "example-model") -> Path:
    dataset = tmp_path / "models" / name
    dataset.mkdir(parents=True)
    write_metadata_yaml(dataset)
    write_ontology(dataset)
    return dataset


def deterministic_model_uri(slug: str) -> str:
    model_uuid = uuid.uuid5(
        uuid.NAMESPACE_URL, f"https://w3id.org/ontouml-models/model|{slug}"
    )
    return f"https://w3id.org/ontouml-models/model/{model_uuid}"


def existing_turtle_metadata(
    *,
    distribution_uri: str = "https://w3id.org/ontouml-models/distribution/existing-turtle/",
    model_uri: str | None = "https://w3id.org/ontouml-models/model/existing-model",
    title: str = "Existing Turtle title",
    license_uri: str = "https://example.org/existing-license",
    download_url: str = "https://example.org/existing/ontology.ttl",
    issued_ts: str = "2023-04-14T17:34:20.99131566Z",
    modified_ts: str = "2023-04-14T17:34:21.99131566Z",
    editorial_note: str | None = "Existing Turtle editorial note.",
) -> str:
    is_part_of = f"    dct:isPartOf <{model_uri}>;\n" if model_uri else ""
    editorial = (
        f'    skos:editorialNote "{editorial_note}"@en;\n'
        if editorial_note is not None
        else ""
    )
    return (
        f"""
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
@prefix skos: <http://www.w3.org/2004/02/skos/core#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

<{distribution_uri}> a dcat:Distribution;
{is_part_of}    dct:title "{title}"@en;
    dct:license <{license_uri}>;
    dcat:downloadURL <{download_url}>;
{editorial}    fdpo:metadataIssued "{issued_ts}"^^xsd:dateTime;
    fdpo:metadataModified "{modified_ts}"^^xsd:dateTime .
""".strip()
        + "\n"
    )


def existing_other_distribution(model_uri: str) -> str:
    return (
        f"""
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.

<https://w3id.org/ontouml-models/distribution/json-existing/> a dcat:Distribution;
    dct:isPartOf <{model_uri}> .
""".strip()
        + "\n"
    )


def test_turtle_metadata_generation_uses_metadata_yaml_when_metadata_ttl_is_absent(
    tmp_path: Path,
):
    module = load_module()
    dataset = make_dataset(tmp_path, "new-turtle-model")

    assert not (dataset / "metadata.ttl").exists()
    generated = module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    assert len(generated) == 1
    output = (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8")
    assert "https://www.iana.org/assignments/media-types/text/turtle" in output
    assert "ocmv:isComplete true" in output
    assert f"dct:isPartOf <{deterministic_model_uri('new-turtle-model')}>" in output
    assert 'dct:issued "2018"^^xsd:gYear' in output
    assert "https://creativecommons.org/licenses/by/4.0/" in output
    assert "Turtle distribution of Aviation Safety Ontology" in output
    assert "models/new-turtle-model/ontology.ttl" in output


def test_generator_has_no_hard_dependency_on_model_level_metadata_ttl(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "no-metadata-ttl")

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    assert (dataset / "metadata-turtle.ttl").exists()
    assert not (dataset / "metadata.ttl").exists()


def test_existing_turtle_is_part_of_is_preserved(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "existing-target")
    (dataset / "metadata-turtle.ttl").write_text(
        existing_turtle_metadata(
            model_uri="https://w3id.org/ontouml-models/model/preserved-target"
        ),
        encoding="utf-8",
    )

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    output = (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8")
    assert "https://w3id.org/ontouml-models/model/preserved-target" in output
    assert deterministic_model_uri("existing-target") not in output


def test_other_distribution_is_part_of_is_used_when_target_metadata_is_absent(
    tmp_path: Path,
):
    module = load_module()
    dataset = make_dataset(tmp_path, "fallback-other")
    (dataset / "metadata-json.ttl").write_text(
        existing_other_distribution("https://w3id.org/ontouml-models/model/from-json"),
        encoding="utf-8",
    )

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    output = (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8")
    assert "dct:isPartOf <https://w3id.org/ontouml-models/model/from-json>" in output


def test_conflicting_other_distribution_model_iris_fail(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "conflict")
    (dataset / "metadata-json.ttl").write_text(
        existing_other_distribution("https://w3id.org/ontouml-models/model/a"),
        encoding="utf-8",
    )
    (dataset / "metadata-vpp.ttl").write_text(
        existing_other_distribution("https://w3id.org/ontouml-models/model/b"),
        encoding="utf-8",
    )

    with pytest.raises(module.MetadataGenerationError, match="Conflicting model URIs"):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )

    assert not (dataset / "metadata-turtle.ttl").exists()


def test_conflict_between_target_and_other_distribution_model_iri_fails(
    tmp_path: Path,
):
    module = load_module()
    dataset = make_dataset(tmp_path, "target-other-conflict")
    (dataset / "metadata-turtle.ttl").write_text(
        existing_turtle_metadata(
            model_uri="https://w3id.org/ontouml-models/model/from-turtle"
        ),
        encoding="utf-8",
    )
    (dataset / "metadata-json.ttl").write_text(
        existing_other_distribution("https://w3id.org/ontouml-models/model/from-json"),
        encoding="utf-8",
    )
    original_target = (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8")

    with pytest.raises(module.MetadataGenerationError, match="Conflicting model URIs"):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )

    assert (dataset / "metadata-turtle.ttl").read_text(
        encoding="utf-8"
    ) == original_target


def test_existing_target_without_model_iri_fails_without_explicit_or_preserved_source(
    tmp_path: Path,
):
    module = load_module()
    dataset = make_dataset(tmp_path, "target-no-model-uri")
    (dataset / "metadata-turtle.ttl").write_text(
        existing_turtle_metadata(model_uri=None),
        encoding="utf-8",
    )
    original_target = (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8")

    with pytest.raises(module.MetadataGenerationError, match="metadata-turtle.ttl"):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )

    assert (dataset / "metadata-turtle.ttl").read_text(
        encoding="utf-8"
    ) == original_target


def test_new_dataset_uses_converter_compatible_deterministic_model_uri(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "new-deterministic-model")

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    output = (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8")
    assert (
        f"dct:isPartOf <{deterministic_model_uri('new-deterministic-model')}>" in output
    )


def test_existing_catalog_dataset_without_distribution_model_iri_fails(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "existing-catalog")
    (dataset / "metadata.ttl").write_text(
        "@prefix dcat: <http://www.w3.org/ns/dcat#>.\n"
        "<https://w3id.org/ontouml-models/model/legacy> a dcat:Dataset .\n",
        encoding="utf-8",
    )

    with pytest.raises(
        module.MetadataGenerationError,
        match="appears to be an existing catalog dataset",
    ):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )

    assert not (dataset / "metadata-turtle.ttl").exists()


def test_existing_distribution_iri_and_curated_values_are_preserved(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "curated")
    (dataset / "metadata-turtle.ttl").write_text(
        existing_turtle_metadata(),
        encoding="utf-8",
    )

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    output = (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8")
    assert "https://w3id.org/ontouml-models/distribution/existing-turtle/" in output
    assert "Existing Turtle title" in output
    assert "Existing Turtle editorial note." in output
    assert "https://example.org/existing/ontology.ttl" in output
    assert "https://example.org/existing-license" in output
    assert "2023-04-14T17:34:20.99131566Z" in output
    assert "2023-04-14T17:34:21.99131566Z" not in output
    assert "2024-01-02T03:04:05Z" in output


def test_missing_license_fails_without_allow_missing_license(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "missing-license")
    write_metadata_yaml(dataset, license_value=None)

    with pytest.raises(module.MetadataGenerationError, match="license"):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )

    assert not (dataset / "metadata-turtle.ttl").exists()


def test_missing_license_is_allowed_with_allow_missing_license(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "missing-license-allowed")
    write_metadata_yaml(dataset, license_value=None)

    module.process_dataset(
        dataset,
        module.Config(
            metadata_timestamp="2024-01-02T03:04:05Z",
            allow_missing_license=True,
        ),
    )

    output = (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8")
    assert "dct:license" not in output
    assert "Turtle distribution of Aviation Safety Ontology" in output


def test_available_license_is_emitted_when_allow_missing_license_is_used(
    tmp_path: Path,
):
    module = load_module()
    dataset = make_dataset(tmp_path, "available-license")

    module.process_dataset(
        dataset,
        module.Config(
            metadata_timestamp="2024-01-02T03:04:05Z",
            allow_missing_license=True,
        ),
    )

    output = (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8")
    assert "dct:license <https://creativecommons.org/licenses/by/4.0/>" in output


def test_missing_metadata_timestamp_for_new_file_fails(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "timestamp-required")

    with pytest.raises(module.MetadataGenerationError, match="No run timestamp"):
        module.process_dataset(dataset, module.Config())

    assert not (dataset / "metadata-turtle.ttl").exists()


def test_metadata_modified_is_preserved_when_generated_file_is_unchanged(
    tmp_path: Path,
):
    module = load_module()
    dataset = make_dataset(tmp_path, "unchanged")
    first = module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )
    assert first[0].changed is True
    original_text = (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8")

    second = module.process_dataset(dataset, module.Config())
    second_text = (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8")

    assert second[0].changed is False
    assert second[0].written is False
    assert second_text == original_text
    assert "2024-01-02T03:04:05Z" in second_text


def test_check_detects_required_update_without_writing(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "check-mode")

    result = module.process_dataset(
        dataset,
        module.Config(
            metadata_timestamp="2024-01-02T03:04:05Z",
            check=True,
        ),
    )

    assert result[0].changed is True
    assert result[0].written is False
    assert not (dataset / "metadata-turtle.ttl").exists()


def test_dry_run_detects_generation_without_writing(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "dry-run")

    result = module.process_dataset(
        dataset,
        module.Config(
            metadata_timestamp="2024-01-02T03:04:05Z",
            dry_run=True,
        ),
    )

    assert result[0].changed is True
    assert result[0].written is False
    assert not (dataset / "metadata-turtle.ttl").exists()


def test_json_output_from_cli(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "json-cli")

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        code = module.main(
            [
                str(dataset),
                "--format",
                "json",
                "--metadata-timestamp",
                "2024-01-02T03:04:05Z",
            ]
        )

    assert code == 0
    data = json.loads(stdout.getvalue())
    assert data["ok"] is True
    assert data["errors"] == []
    assert data["results"][0]["metadata_path"].endswith("metadata-turtle.ttl")


def test_no_partial_write_when_source_turtle_is_invalid(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "invalid-source")
    write_ontology(dataset, valid=False)

    with pytest.raises(
        module.MetadataGenerationError, match="Could not parse Turtle source"
    ):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )

    assert not (dataset / "metadata-turtle.ttl").exists()


def test_generated_download_url_uses_repository_relative_source_path(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "path-model")

    module.process_dataset(
        dataset,
        module.Config(
            repository="pedropaulofb/ontouml-models-dev",
            branch="feature-branch",
            models_dir_name="models",
            metadata_timestamp="2024-01-02T03:04:05Z",
        ),
    )

    output = (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8")
    assert (
        "https://raw.githubusercontent.com/pedropaulofb/ontouml-models-dev/feature-branch/models/path-model/ontology.ttl"
        in output
    )
    assert str(tmp_path) not in output


def write_ahmad_catalog_like_dataset(tmp_path: Path) -> Path:
    dataset = tmp_path / "models" / "ahmad2018aviation"
    dataset.mkdir(parents=True)
    (dataset / "metadata.yaml").write_text(
        """
title: Aviation Safety Ontology
acronym:
issued: 2018
modified:
contributor:
 - https://dblp.org/pid/185/3559
 - https://dblp.org/pid/77/5702
 - https://dblp.org/pid/166/2116
keyword:
 - safety
 - aviation
theme: Class T - Technology
editorialNote:
ontologyType:
 - domain
language: en
designedForTask:
 - information retrieval
context:
 - research
source:
 - https://doi.org/10.1007/978-3-030-02671-4_22
representationStyle:
 - ufo
landingPage:
license:
""".lstrip(),
        encoding="utf-8",
    )
    write_ontology(dataset)
    (dataset / "metadata-turtle.ttl").write_text(
        """
@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
@prefix ocmv: <https://w3id.org/ontouml-models/vocabulary#>.
@prefix owl: <http://www.w3.org/2002/07/owl#>.
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
@prefix skos: <http://www.w3.org/2004/02/skos/core#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

<https://w3id.org/ontouml-models/distribution/69cd521b-671c-49f2-a176-e31910dec404/> a dcat:Distribution;
    dct:isPartOf <https://w3id.org/ontouml-models/model/660ad6c4-dbc1-43e7-b582-d7eb9ec43739>;
    dct:issued "2018"^^xsd:gYear;
    dct:license <https://creativecommons.org/licenses/by/4.0/>;    dcat:mediaType <https://www.iana.org/assignments/media-types/text/turtle>;
    dct:title "Turtle distribution of Aviation Safety Ontology"@en;
    dcat:downloadURL <https://raw.githubusercontent.com/OntoUML/ontouml-models/master/models/ahmad2018aviation/ontology.ttl>;
    ocmv:isComplete "true"^^xsd:boolean;
    fdpo:metadataIssued "2023-04-14T17:34:20.99131566Z"^^xsd:dateTime;
    fdpo:metadataModified "2023-04-14T17:34:20.99131566Z"^^xsd:dateTime .
""".lstrip(),
        encoding="utf-8",
    )
    return dataset


def write_qam_catalog_like_dataset(tmp_path: Path) -> Path:
    dataset = tmp_path / "models" / "qam"
    dataset.mkdir(parents=True)
    (dataset / "metadata.yaml").write_text(
        """
title: Quality Assurance Model
acronym:
issued: 2013
modified:
contributor:
keyword:
 - quality assurance process
theme: Class H - Social Sciences
editorialNote: Ontology build in classroom for learning purposes. The author is anonymous.
ontologyType:
 - application
language: en
designedForTask:
 - learning
context:
 - classroom
source:
representationStyle:
 - ontouml
landingPage:
license: https://creativecommons.org/licenses/by/4.0
""".lstrip(),
        encoding="utf-8",
    )
    write_ontology(dataset)
    (dataset / "metadata-turtle.ttl").write_text(
        """
@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
@prefix ocmv: <https://w3id.org/ontouml-models/vocabulary#>.
@prefix owl: <http://www.w3.org/2002/07/owl#>.
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
@prefix skos: <http://www.w3.org/2004/02/skos/core#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

<https://w3id.org/ontouml-models/distribution/f39081f9-416d-4d2f-832f-1b82d4a7d4cf/> a dcat:Distribution;
    dct:isPartOf <https://w3id.org/ontouml-models/model/0b6d6128-81e6-4985-8f0e-bd5af9a295f3>;
    dct:issued "2013"^^xsd:gYear;
    dcat:mediaType <https://www.iana.org/assignments/media-types/text/turtle>;
    dct:license <https://creativecommons.org/licenses/by/4.0>;
    dct:title "Turtle distribution of Quality Assurance Model"@en;
    dcat:downloadURL <https://raw.githubusercontent.com/OntoUML/ontouml-models/master/models/qam/ontology.ttl>;
    ocmv:isComplete "true"^^xsd:boolean;
    fdpo:metadataIssued "2023-04-14T18:10:47.674011631Z"^^xsd:dateTime;
    fdpo:metadataModified "2023-04-14T18:10:47.674011631Z"^^xsd:dateTime .
""".lstrip(),
        encoding="utf-8",
    )
    return dataset


def test_catalog_like_ahmad_regeneration_preserves_existing_catalog_identifiers(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_ahmad_catalog_like_dataset(tmp_path)

    assert not (dataset / "metadata.ttl").exists()
    module.process_dataset(
        dataset,
        module.Config(
            allow_missing_license=True,
            metadata_timestamp="2024-01-02T03:04:05Z",
        ),
    )

    output = (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8")
    assert (
        "https://w3id.org/ontouml-models/distribution/69cd521b-671c-49f2-a176-e31910dec404/"
        in output
    )
    assert (
        "dct:isPartOf <https://w3id.org/ontouml-models/model/660ad6c4-dbc1-43e7-b582-d7eb9ec43739>"
        in output
    )
    assert deterministic_model_uri("ahmad2018aviation") not in output
    assert "Turtle distribution of Aviation Safety Ontology" in output
    assert "https://creativecommons.org/licenses/by/4.0/" in output
    assert "models/ahmad2018aviation/ontology.ttl" in output


def test_catalog_like_qam_regeneration_preserves_existing_turtle_distribution(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_qam_catalog_like_dataset(tmp_path)

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    output = (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8")
    assert (
        "https://w3id.org/ontouml-models/distribution/f39081f9-416d-4d2f-832f-1b82d4a7d4cf/"
        in output
    )
    assert (
        "dct:isPartOf <https://w3id.org/ontouml-models/model/0b6d6128-81e6-4985-8f0e-bd5af9a295f3>"
        in output
    )
    assert "https://creativecommons.org/licenses/by/4.0" in output
    assert "Turtle distribution of Quality Assurance Model" in output


def test_explicit_yaml_model_uri_is_used_for_new_dataset(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "explicit-yaml-uri")
    explicit_uri = "https://w3id.org/ontouml-models/model/explicit-from-yaml"
    write_metadata_yaml(dataset, uri=explicit_uri)

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    output = (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8")
    assert f"dct:isPartOf <{explicit_uri}>" in output
    assert deterministic_model_uri("explicit-yaml-uri") not in output


def test_existing_target_without_is_part_of_can_use_explicit_yaml_model_uri(
    tmp_path: Path,
):
    module = load_module()
    dataset = make_dataset(tmp_path, "target-explicit-yaml-uri")
    explicit_uri = "https://w3id.org/ontouml-models/model/explicit-existing-target"
    write_metadata_yaml(dataset, uri=explicit_uri)
    (dataset / "metadata-turtle.ttl").write_text(
        existing_turtle_metadata(model_uri=None),
        encoding="utf-8",
    )

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    output = (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8")
    assert f"dct:isPartOf <{explicit_uri}>" in output
    assert "https://w3id.org/ontouml-models/distribution/existing-turtle/" in output


def test_full_uri_is_part_of_predicate_in_other_distribution_is_supported(
    tmp_path: Path,
):
    module = load_module()
    dataset = make_dataset(tmp_path, "full-predicate")
    model_uri = "https://w3id.org/ontouml-models/model/from-full-predicate"
    (dataset / "metadata-json.ttl").write_text(
        f"""
@prefix dcat: <http://www.w3.org/ns/dcat#>.

<https://w3id.org/ontouml-models/distribution/json-existing/> a dcat:Distribution;
    <http://purl.org/dc/terms/isPartOf> <{model_uri}> .
""".lstrip(),
        encoding="utf-8",
    )

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    output = (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8")
    assert f"dct:isPartOf <{model_uri}>" in output


def test_malformed_existing_target_metadata_fails_without_overwriting(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "malformed-existing-target")
    bad_text = (
        "@prefix dcat: <http://www.w3.org/ns/dcat#>.\n<broken> a dcat:Distribution ;\n"
    )
    (dataset / "metadata-turtle.ttl").write_text(bad_text, encoding="utf-8")

    with pytest.raises(
        module.MetadataGenerationError,
        match="Could not parse existing distribution metadata",
    ):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )

    assert (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8") == bad_text


def test_missing_source_turtle_fails_without_writing(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "missing-source")
    (dataset / "ontology.ttl").unlink()

    with pytest.raises(
        module.MetadataGenerationError, match="Missing required Turtle source file"
    ):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )

    assert not (dataset / "metadata-turtle.ttl").exists()


def test_no_overwrite_fails_for_existing_target_without_modifying_it(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "no-overwrite")
    original = existing_turtle_metadata()
    (dataset / "metadata-turtle.ttl").write_text(original, encoding="utf-8")

    with pytest.raises(module.MetadataGenerationError, match="overwrite is disabled"):
        module.process_dataset(
            dataset,
            module.Config(
                overwrite=False,
                metadata_timestamp="2024-01-02T03:04:05Z",
            ),
        )

    assert (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8") == original


def test_main_check_returns_one_and_json_marks_not_ok_when_update_is_needed(
    tmp_path: Path,
):
    module = load_module()
    dataset = make_dataset(tmp_path, "check-cli-json")

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        code = module.main(
            [
                str(dataset),
                "--check",
                "--format",
                "json",
                "--metadata-timestamp",
                "2024-01-02T03:04:05Z",
            ]
        )

    assert code == 1
    data = json.loads(stdout.getvalue())
    assert data["ok"] is False
    assert data["results"][0]["changed"] is True
    assert not (dataset / "metadata-turtle.ttl").exists()


def test_all_discovers_dataset_folders_below_models_dir(tmp_path: Path):
    module = load_module()
    models_dir = tmp_path / "models"
    first = make_dataset(tmp_path, "all-first")
    second = make_dataset(tmp_path, "all-second")
    (models_dir / "not-a-dataset").mkdir()

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        code = module.main(
            [
                "--all",
                "--models-dir",
                str(models_dir),
                "--format",
                "json",
                "--metadata-timestamp",
                "2024-01-02T03:04:05Z",
            ]
        )

    assert code == 0
    data = json.loads(stdout.getvalue())
    assert len(data["results"]) == 2
    assert (first / "metadata-turtle.ttl").exists()
    assert (second / "metadata-turtle.ttl").exists()
    assert not (models_dir / "not-a-dataset" / "metadata-turtle.ttl").exists()


def test_invalid_metadata_timestamp_fails_without_writing(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "invalid-timestamp")

    with pytest.raises(module.MetadataGenerationError, match="--metadata-timestamp"):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02 03:04:05")
        )

    assert not (dataset / "metadata-turtle.ttl").exists()


def test_generated_metadata_parses_and_has_one_distribution_subject(tmp_path: Path):
    module = load_module()
    dataset = make_dataset(tmp_path, "parse-generated")

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    graph = module.Graph()
    graph.parse(dataset / "metadata-turtle.ttl", format="turtle")
    subjects = list(graph.subjects(module.RDF.type, module.DCAT.Distribution))
    assert len(subjects) == 1
    assert (subjects[0], module.DCAT.mediaType, module.TURTLE_MEDIA_TYPE) in graph
    assert (
        subjects[0],
        module.OCMV.isComplete,
        module.Literal(True, datatype=module.XSD.boolean),
    ) in graph


def test_owned_distribution_semantics_are_regenerated_from_script_defaults(
    tmp_path: Path,
):
    module = load_module()
    dataset = make_dataset(tmp_path, "wrong-owned-values")
    (dataset / "metadata-turtle.ttl").write_text(
        """
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
@prefix ocmv: <https://w3id.org/ontouml-models/vocabulary#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

<https://w3id.org/ontouml-models/distribution/wrong-owned-values/> a dcat:Distribution;
    dct:isPartOf <https://w3id.org/ontouml-models/model/wrong-owned-values>;
    dcat:mediaType <https://www.iana.org/assignments/media-types/application/json>;
    ocmv:isComplete "false"^^xsd:boolean;
    fdpo:metadataIssued "2023-04-14T17:34:20Z"^^xsd:dateTime;
    fdpo:metadataModified "2023-04-14T17:34:20Z"^^xsd:dateTime .
""".lstrip(),
        encoding="utf-8",
    )

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    output = (dataset / "metadata-turtle.ttl").read_text(encoding="utf-8")
    assert "https://www.iana.org/assignments/media-types/text/turtle" in output
    assert "https://www.iana.org/assignments/media-types/application/json" not in output
    assert "ocmv:isComplete true" in output
    assert "ocmv:isComplete false" not in output

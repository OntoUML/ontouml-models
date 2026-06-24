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
            parent / "generate_json_metadata.py",
            parent / "scripts" / "generate_json_metadata.py",
        ):
            if candidate.exists():
                script = candidate
                break
        if script is not None:
            break
    assert script is not None
    spec = importlib.util.spec_from_file_location("generate_json_metadata", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_ontology_json(dataset: Path, content: object | None = None) -> None:
    payload = content if content is not None else {"id": "project_1", "type": "Project"}
    (dataset / "ontology.json").write_text(json.dumps(payload), encoding="utf-8")


def write_metadata_yaml(
    dataset: Path,
    *,
    title: str = "Reference Ontology of Trust",
    issued: str = "2019",
    license_value: str | None = "https://creativecommons.org/licenses/by/4.0/",
    extra: str = "",
) -> None:
    license_line = f"license: {license_value}\n" if license_value is not None else ""
    (dataset / "metadata.yaml").write_text(
        f"""
title: {title}
issued: {issued}
{license_line}{extra}""".strip()
        + "\n",
        encoding="utf-8",
    )


def write_dataset(tmp_path: Path, *, name: str = "example-model") -> Path:
    dataset = tmp_path / "models" / name
    dataset.mkdir(parents=True)
    write_ontology_json(dataset)
    write_metadata_yaml(dataset)
    return dataset


def deterministic_model_uri(slug: str) -> str:
    model_uuid = uuid.uuid5(
        uuid.NAMESPACE_URL, f"https://w3id.org/ontouml-models/model|{slug}"
    )
    return f"https://w3id.org/ontouml-models/model/{model_uuid}"


def write_existing_json_metadata(
    dataset: Path,
    *,
    distribution_uri: str = "https://w3id.org/ontouml-models/distribution/existing-json/",
    model_uri: str = "https://w3id.org/ontouml-models/model/existing-model",
    title: str = "Curated JSON title",
    download_url: str = "https://example.org/curated/ontology.json",
    license_uri: str | None = "https://example.org/existing-license",
    editorial_note: str | None = "Curated JSON editorial note.",
    metadata_issued: str = "2023-04-14T17:35:29.862157131Z",
    metadata_modified: str = "2023-04-14T17:35:30.862157131Z",
) -> None:
    license_line = f"    dct:license <{license_uri}>;\n" if license_uri else ""
    editorial_line = (
        f'    skos:editorialNote "{editorial_note}"@en;\n' if editorial_note else ""
    )
    (dataset / "metadata-json.ttl").write_text(
        f"""
@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
@prefix ocmv: <https://w3id.org/ontouml-models/vocabulary#>.
@prefix skos: <http://www.w3.org/2004/02/skos/core#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

<{distribution_uri}> a dcat:Distribution;
    dct:isPartOf <{model_uri}>;
    dct:issued "2019"^^xsd:gYear;
    dcat:mediaType <https://www.iana.org/assignments/media-types/application/json>;
{license_line}    ocmv:conformsToSchema <https://w3id.org/ontouml/schema>;
    dct:title "{title}"@en;
    dcat:downloadURL <{download_url}>;
    ocmv:isComplete "true"^^xsd:boolean;
{editorial_line}    fdpo:metadataIssued "{metadata_issued}"^^xsd:dateTime;
    fdpo:metadataModified "{metadata_modified}"^^xsd:dateTime .
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_json_metadata_generation_uses_metadata_yaml_when_metadata_ttl_is_absent(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_dataset(tmp_path, name="new-json-model")

    assert not (dataset / "metadata.ttl").exists()
    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    generated = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")
    assert 'dct:issued "2019"^^xsd:gYear' in generated
    assert "JSON distribution of Reference Ontology of Trust" in generated
    assert "https://creativecommons.org/licenses/by/4.0/" in generated
    assert (
        "dcat:mediaType <https://www.iana.org/assignments/media-types/application/json>"
        in generated
    )
    assert "ocmv:conformsToSchema <https://w3id.org/ontouml/schema>" in generated
    assert 'ocmv:isComplete "true"^^xsd:boolean' in generated
    assert "metadata.ttl" not in generated


def test_metadata_ttl_is_not_used_when_distribution_metadata_provides_model_uri(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_dataset(tmp_path, name="ignore-metadata-ttl")
    (dataset / "metadata.ttl").write_text(
        "<https://w3id.org/ontouml-models/model/from-metadata-ttl/> a <http://www.w3.org/ns/dcat#Dataset> .\n",
        encoding="utf-8",
    )
    (dataset / "metadata-png-o-diagram.ttl").write_text(
        """
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
<https://w3id.org/ontouml-models/distribution/png-existing> a dcat:Distribution;
    dct:isPartOf <https://w3id.org/ontouml-models/model/from-distribution-metadata> .
""".strip()
        + "\n",
        encoding="utf-8",
    )

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    generated = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")
    assert "from-distribution-metadata" in generated
    assert "from-metadata-ttl" not in generated


def test_existing_json_is_part_of_is_preserved(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path, name="existing-json-is-part-of")
    write_existing_json_metadata(
        dataset,
        model_uri="https://w3id.org/ontouml-models/model/preserved-json-model",
    )

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    generated = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")
    assert (
        "dct:isPartOf <https://w3id.org/ontouml-models/model/preserved-json-model>"
        in generated
    )


def test_other_distribution_is_part_of_is_used_when_json_metadata_is_absent(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_dataset(tmp_path, name="other-distribution-uri")
    (dataset / "metadata-vpp.ttl").write_text(
        """
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
<https://w3id.org/ontouml-models/distribution/vpp-existing> a dcat:Distribution;
    dct:isPartOf <https://w3id.org/ontouml-models/model/from-existing-vpp> .
""".strip()
        + "\n",
        encoding="utf-8",
    )

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    generated = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")
    assert (
        "dct:isPartOf <https://w3id.org/ontouml-models/model/from-existing-vpp>"
        in generated
    )


def test_conflicting_existing_distribution_model_uris_fail(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path, name="conflicting-model-uris")
    write_existing_json_metadata(
        dataset,
        model_uri="https://w3id.org/ontouml-models/model/from-json",
    )
    (dataset / "metadata-vpp.ttl").write_text(
        """
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
<https://w3id.org/ontouml-models/distribution/vpp-existing> a dcat:Distribution;
    dct:isPartOf <https://w3id.org/ontouml-models/model/from-vpp> .
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(module.MetadataGenerationError, match="Conflicting model URIs"):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )


def test_new_dataset_uses_converter_compatible_deterministic_model_uri(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path, name="new-deterministic-json-model")

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    generated = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")
    assert (
        f"dct:isPartOf <{deterministic_model_uri('new-deterministic-json-model')}>"
        in generated
    )


def test_existing_catalog_dataset_without_preservable_model_uri_fails(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path, name="existing-without-model-uri")
    (dataset / "metadata.ttl").write_text("legacy model metadata\n", encoding="utf-8")

    with pytest.raises(
        module.MetadataGenerationError, match="No stable catalog model IRI"
    ):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )

    assert not (dataset / "metadata-json.ttl").exists()


def test_existing_distribution_iri_and_curated_values_are_preserved(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path, name="curated-json-values")
    write_existing_json_metadata(dataset)

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    generated = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")
    assert "https://w3id.org/ontouml-models/distribution/existing-json/" in generated
    assert "Curated JSON title" in generated
    assert "Curated JSON editorial note." in generated
    assert "https://example.org/curated/ontology.json" in generated
    assert "2023-04-14T17:35:29.862157131Z" in generated


def test_missing_license_fails_without_allow_missing_license(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path, name="missing-license-json")
    write_metadata_yaml(
        dataset, title="Missing License JSON", issued="2024", license_value=None
    )

    with pytest.raises(module.MetadataGenerationError, match="license"):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )

    assert not (dataset / "metadata-json.ttl").exists()


def test_missing_license_is_allowed_with_allow_missing_license(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path, name="allow-missing-license-json")
    write_metadata_yaml(
        dataset, title="Missing License JSON", issued="2024", license_value=None
    )

    module.process_dataset(
        dataset,
        module.Config(
            metadata_timestamp="2024-01-02T03:04:05Z",
            allow_missing_license=True,
        ),
    )

    generated = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")
    assert "dct:license" not in generated
    assert "Missing License JSON" in generated


def test_existing_distribution_license_is_preserved_when_missing_license_is_allowed(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_dataset(tmp_path, name="preserve-existing-license-json")
    write_metadata_yaml(
        dataset, title="Existing License JSON", issued="2024", license_value=None
    )
    write_existing_json_metadata(
        dataset, license_uri="https://example.org/existing-json-license"
    )

    module.process_dataset(
        dataset,
        module.Config(
            metadata_timestamp="2024-01-02T03:04:05Z",
            allow_missing_license=True,
        ),
    )

    generated = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")
    assert "https://example.org/existing-json-license" in generated


def test_yaml_license_is_emitted_even_with_allow_missing_license(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path, name="allow-with-yaml-license-json")

    module.process_dataset(
        dataset,
        module.Config(
            metadata_timestamp="2024-01-02T03:04:05Z",
            allow_missing_license=True,
        ),
    )

    generated = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")
    assert "https://creativecommons.org/licenses/by/4.0/" in generated


def test_new_file_timestamps_are_initialized_from_metadata_timestamp(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path, name="new-timestamp-json")

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    generated = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")
    assert 'fdpo:metadataIssued "2024-01-02T03:04:05Z"^^xsd:dateTime' in generated
    assert 'fdpo:metadataModified "2024-01-02T03:04:05Z"^^xsd:dateTime' in generated


def test_existing_metadata_issued_is_preserved_and_modified_updates_when_changed(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_dataset(tmp_path, name="changed-timestamp-json")
    write_existing_json_metadata(dataset, title="Old Curated Title")
    write_metadata_yaml(dataset, title="Changed Model Title", issued="2020")

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    generated = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")
    assert "2023-04-14T17:35:29.862157131Z" in generated
    assert "2023-04-14T17:35:30.862157131Z" not in generated
    assert "2024-01-02T03:04:05Z" in generated


def test_unchanged_existing_metadata_modified_is_preserved_without_new_timestamp(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_dataset(tmp_path, name="unchanged-json")

    first_results = module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )
    assert first_results[0].written
    first_text = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")

    second_results = module.process_dataset(dataset, module.Config())
    second_text = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")

    assert not second_results[0].changed
    assert first_text == second_text
    assert "2024-01-02T03:04:05Z" in second_text


def test_missing_metadata_timestamp_for_new_file_fails(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path, name="missing-new-timestamp-json")

    with pytest.raises(module.MetadataGenerationError, match="No run timestamp"):
        module.process_dataset(dataset, module.Config())

    assert not (dataset / "metadata-json.ttl").exists()


def test_changed_existing_file_requires_metadata_timestamp(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path, name="changed-existing-requires-timestamp")
    write_existing_json_metadata(dataset)
    write_metadata_yaml(dataset, title="Changed JSON Title", issued="2022")

    with pytest.raises(module.MetadataGenerationError, match="metadataModified"):
        module.process_dataset(dataset, module.Config())

    generated = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")
    assert "2023-04-14T17:35:30.862157131Z" in generated


def test_cli_check_returns_one_and_does_not_write(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path, name="check-json")

    exit_code = module.main(
        [str(dataset), "--check", "--metadata-timestamp", "2024-01-02T03:04:05Z"]
    )

    assert exit_code == 1
    assert not (dataset / "metadata-json.ttl").exists()


def test_cli_dry_run_does_not_write(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    module = load_module()
    dataset = write_dataset(tmp_path, name="dry-run-json")

    exit_code = module.main(
        [str(dataset), "--dry-run", "--metadata-timestamp", "2024-01-02T03:04:05Z"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "would generate:" in captured.out
    assert not (dataset / "metadata-json.ttl").exists()


def test_cli_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    module = load_module()
    dataset = write_dataset(tmp_path, name="json-output")

    exit_code = module.main(
        [
            str(dataset),
            "--format",
            "json",
            "--metadata-timestamp",
            "2024-01-02T03:04:05Z",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["errors"] == []
    assert payload["results"][0]["metadata_path"].endswith("metadata-json.ttl")


def test_invalid_ontology_json_content_is_ignored_by_default(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path, name="invalid-source-json")
    (dataset / "ontology.json").write_text("not valid json", encoding="utf-8")

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    assert (dataset / "metadata-json.ttl").exists()


def test_invalid_ontology_json_fails_when_content_validation_is_enabled(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_dataset(tmp_path, name="invalid-source-json")
    (dataset / "ontology.json").write_text("not valid json", encoding="utf-8")

    with pytest.raises(module.MetadataGenerationError, match="Invalid ontology JSON"):
        module.process_dataset(
            dataset,
            module.Config(
                metadata_timestamp="2024-01-02T03:04:05Z",
                validate_source_json=True,
            ),
        )

    assert not (dataset / "metadata-json.ttl").exists()


def test_non_utf8_ontology_json_fails_as_generation_error_when_validation_is_enabled(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_dataset(tmp_path, name="non-utf8-source-json")
    (dataset / "ontology.json").write_bytes(b'{"name": "caf\xed"}')

    with pytest.raises(module.MetadataGenerationError, match="not valid UTF-8"):
        module.process_dataset(
            dataset,
            module.Config(
                metadata_timestamp="2024-01-02T03:04:05Z",
                validate_source_json=True,
            ),
        )

    assert not (dataset / "metadata-json.ttl").exists()


def test_download_url_uses_repository_relative_path_not_local_absolute_path(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_dataset(tmp_path, name="path-json")

    module.process_dataset(
        dataset,
        module.Config(
            metadata_timestamp="2024-01-02T03:04:05Z",
            repository="Example/repo",
            branch="feature-branch",
            models_dir_name="models",
        ),
    )

    generated = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")
    assert (
        "https://raw.githubusercontent.com/Example/repo/feature-branch/models/path-json/ontology.json"
        in generated
    )
    assert str(tmp_path) not in generated


def test_explicit_yaml_model_uri_is_used_for_new_dataset_when_present(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "explicit-yaml-uri-json"
    dataset.mkdir(parents=True)
    write_ontology_json(dataset)
    write_metadata_yaml(
        dataset,
        title="Explicit YAML URI",
        issued="2024",
        extra="model:\n  uri: https://w3id.org/ontouml-models/model/explicit-yaml-uri/\n",
    )

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    generated = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")
    assert (
        "dct:isPartOf <https://w3id.org/ontouml-models/model/explicit-yaml-uri>"
        in generated
    )


def write_catalog_fixture(
    tmp_path: Path,
    *,
    folder_name: str,
    metadata_yaml: str,
    metadata_json_ttl: str,
) -> Path:
    """Create a minimal local copy of an existing catalog dataset fixture."""

    dataset = tmp_path / "models" / folder_name
    dataset.mkdir(parents=True)
    (dataset / "metadata.yaml").write_text(
        metadata_yaml.strip() + "\n", encoding="utf-8"
    )
    (dataset / "metadata-json.ttl").write_text(
        metadata_json_ttl.strip() + "\n", encoding="utf-8"
    )
    write_ontology_json(dataset)
    return dataset


AMARAL2019ROT_METADATA_YAML = """
title: Reference Ontology of Trust
acronym: ROT
issued: 2019
modified: 2022
contributor:
 - https://dblp.org/pid/81/4277
 - https://dblp.org/pid/134/4947
 - https://dblp.org/pid/11/78
 - https://dblp.org/pid/33/8219
 - https://dblp.org/pid/91/3408
 - https://dblp.org/pid/75/5043
 - https://dblp.org/pid/m/JohnMylopoulos
keyword:
 - trust
theme: Class H - Social Sciences
editorialNote: "The files listed here were imported from ROT's github repository (https://github.com/unibz-core/trust-ontology) on March 23, 2022. Therefore, the ontology is much larger than that described in the paper identified as the main source here."
ontologyType:
 - domain
language: en
designedForTask:
 - conceptual clarification
context:
 - research
source:
 - https://doi.org/10.1007/978-3-030-33246-4_1
 - https://dblp.org/rec/conf/vmbo/AmaralSGP21
 - https://doi.org/10.1007/978-3-030-63479-7_6
 - https://doi.org/10.1007/978-3-030-62522-1_25
representationStyle:
 - ontouml
landingPage: https://github.com/unibz-core/trust-ontology
license: https://creativecommons.org/licenses/by/4.0/
"""


AMARAL2019ROT_METADATA_JSON = """
@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
@prefix ocmv: <https://w3id.org/ontouml-models/vocabulary#>.
@prefix owl: <http://www.w3.org/2002/07/owl#>.
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
@prefix skos: <http://www.w3.org/2004/02/skos/core#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

<https://w3id.org/ontouml-models/distribution/7c83f03b-c170-49d2-9dd9-0a600be6cc96/> a dcat:Distribution;
    dct:isPartOf <https://w3id.org/ontouml-models/model/d88fe48c-d574-43b4-85d6-a6e1aeaa6726>;
    dct:issued "2019"^^xsd:gYear;
    dcat:mediaType <https://www.iana.org/assignments/media-types/application/json>;
    dct:license <https://creativecommons.org/licenses/by/4.0/>;
    ocmv:conformsToSchema <https://w3id.org/ontouml/schema>;
    dct:title "JSON distribution of Reference Ontology of Trust"@en;
    dcat:downloadURL <https://raw.githubusercontent.com/OntoUML/ontouml-models/master/models/amaral2019rot/ontology.json>;
    ocmv:isComplete "true"^^xsd:boolean;
    fdpo:metadataIssued "2023-04-14T17:35:29.862157131Z"^^xsd:dateTime;
    fdpo:metadataModified "2023-04-14T17:35:29.862157131Z"^^xsd:dateTime .
"""


ALPINEBITS2022_METADATA_YAML = """
title: AlpineBits DestinationData Ontology
acronym:
issued: 2020
modified: 2022
contributor:
 - https://dblp.org/pid/134/4947
 - https://dblp.org/pid/169/2246
keyword:
 - tourism
 - alpine tourism
theme: Class G - Geography, Anthropology, and Recreation
editorialNote: This version of the ontology is yet to be officially published. The expected release is scheduled to April 2022.
ontologyType:
 - domain
language: en
designedForTask:
 - software engineering
 - interoperability
context:
 - industry
source:
 - https://www.alpinebits.org/wp-content/uploads/2020/08/AlpineBits_2020-04.pdf
representationStyle:
 - ontouml
landingPage: https://www.alpinebits.org/destinationdata/
license: https://creativecommons.org/licenses/by-sa/3.0/
"""


ALPINEBITS2022_METADATA_JSON = """
@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
@prefix ocmv: <https://w3id.org/ontouml-models/vocabulary#>.
@prefix owl: <http://www.w3.org/2002/07/owl#>.
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
@prefix skos: <http://www.w3.org/2004/02/skos/core#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

<https://w3id.org/ontouml-models/distribution/b329a4b1-7b57-4aa4-a284-787a4c7abcf2/> a dcat:Distribution;
    dct:isPartOf <https://w3id.org/ontouml-models/model/ad142d17-1fcd-4189-b050-faed17165bc7>;
    dct:issued "2020"^^xsd:gYear;
    dcat:mediaType <https://www.iana.org/assignments/media-types/application/json>;
    dct:license <https://creativecommons.org/licenses/by-sa/3.0/>;
    ocmv:conformsToSchema <https://w3id.org/ontouml/schema>;
    dct:title "JSON distribution of AlpineBits DestinationData Ontology"@en;
    dcat:downloadURL <https://raw.githubusercontent.com/OntoUML/ontouml-models/master/models/alpinebits2022/ontology.json>;
    ocmv:isComplete "true"^^xsd:boolean;
    fdpo:metadataIssued "2023-04-14T17:35:07.332997226Z"^^xsd:dateTime;
    fdpo:metadataModified "2023-04-14T17:35:07.332997226Z"^^xsd:dateTime .
"""


ONTOBIO_METADATA_YAML_WITH_EMPTY_LICENSE = """
title: OntoBio
acronym:
issued: 2011
modified: 2016
contributor:
 - https://dblp.org/pid/135/0761
 - https://dblp.org/pid/88/711
 - https://dblp.org/pid/61/2142
 - https://orcid.org/0000-0002-1904-3751
 - https://dblp.org/pid/200/9519
keyword:
 - biology
theme: Class Q - Science
editorialNote: in the reference papers we do not have reference diagrams. However, we have a GitHub page were to get some visual information. Still, the quality of the images is very low. Some images are unreadable which led to them not being included in this model
ontologyType:
 - domain
language: en
designedForTask:
 - software engineering
 - interoperability
context:
 - research
source:
 - https://doi.org/10.1109/HICSS.2015.453
 - https://tede.ufam.edu.br/handle/tede/2887
 - https://dblp.org/rec/conf/ontobras/AlbuquerqueSJ16
 - https://www.researchgate.net/profile/Marcos-De-Sousa-2/publication/284186226_Novas_Contribuicoes_e_Implementacoes_a_um_Modelo_Formal_de_Ontologia_de_Dominio_para_Biodiversidade/links/564f233708aeafc2aab39cca/Novas-Contribuicoes-e-Implementacoes-a-um-Modelo-Formal-de-Ontologia-de-Dominio-para-Biodiversidade.pdf
representationStyle:
 - ontouml
landingPage: https://github.com/unibz-core/OntoBio_Ontology
license:
"""


ONTOBIO_METADATA_JSON_WITH_EXISTING_LICENSE = """
@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
@prefix ocmv: <https://w3id.org/ontouml-models/vocabulary#>.
@prefix owl: <http://www.w3.org/2002/07/owl#>.
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
@prefix skos: <http://www.w3.org/2004/02/skos/core#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

<https://w3id.org/ontouml-models/distribution/faf6213a-d88b-4399-a12b-e6ea29a4ad01/> a dcat:Distribution;
    dct:isPartOf <https://w3id.org/ontouml-models/model/f3d40402-e30d-4bbc-8792-5566bc8c30e9>;
    dct:issued "2011"^^xsd:gYear;
    dct:license <https://creativecommons.org/licenses/by/4.0/>;    dcat:mediaType <https://www.iana.org/assignments/media-types/application/json>;
    ocmv:conformsToSchema <https://w3id.org/ontouml/schema>;
    dct:title "JSON distribution of OntoBio"@en;
    dcat:downloadURL <https://raw.githubusercontent.com/OntoUML/ontouml-models/master/models/albuquerque2011ontobio/ontology.json>;
    ocmv:isComplete "true"^^xsd:boolean;
    fdpo:metadataIssued "2023-04-14T17:34:38.539952272Z"^^xsd:dateTime;
    fdpo:metadataModified "2023-04-14T17:34:38.539952272Z"^^xsd:dateTime .
"""


@pytest.mark.parametrize(
    ("folder_name", "metadata_yaml", "metadata_json_ttl"),
    [
        (
            "amaral2019rot",
            AMARAL2019ROT_METADATA_YAML,
            AMARAL2019ROT_METADATA_JSON,
        ),
        (
            "alpinebits2022",
            ALPINEBITS2022_METADATA_YAML,
            ALPINEBITS2022_METADATA_JSON,
        ),
    ],
)
def test_existing_catalog_fixtures_regenerate_unchanged_without_metadata_ttl(
    tmp_path: Path,
    folder_name: str,
    metadata_yaml: str,
    metadata_json_ttl: str,
):
    module = load_module()
    dataset = write_catalog_fixture(
        tmp_path,
        folder_name=folder_name,
        metadata_yaml=metadata_yaml,
        metadata_json_ttl=metadata_json_ttl,
    )
    original = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")

    results = module.process_dataset(dataset, module.Config())
    regenerated = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")

    assert not (dataset / "metadata.ttl").exists()
    assert results[0].changed is False
    assert regenerated == original


def test_existing_catalog_fixture_with_empty_yaml_license_preserves_distribution_license(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_catalog_fixture(
        tmp_path,
        folder_name="albuquerque2011ontobio",
        metadata_yaml=ONTOBIO_METADATA_YAML_WITH_EMPTY_LICENSE,
        metadata_json_ttl=ONTOBIO_METADATA_JSON_WITH_EXISTING_LICENSE,
    )

    with pytest.raises(module.MetadataGenerationError, match="license"):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )

    results = module.process_dataset(
        dataset,
        module.Config(
            allow_missing_license=True,
            metadata_timestamp="2024-01-02T03:04:05Z",
        ),
    )
    regenerated = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")

    assert results[0].changed is True
    assert "https://creativecommons.org/licenses/by/4.0/" in regenerated
    assert "2023-04-14T17:34:38.539952272Z" in regenerated
    assert "2024-01-02T03:04:05Z" in regenerated


def test_no_overwrite_rejects_existing_metadata_json(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path, name="no-overwrite-json")
    write_existing_json_metadata(dataset)

    with pytest.raises(module.MetadataGenerationError, match="overwrite is disabled"):
        module.process_dataset(
            dataset,
            module.Config(
                metadata_timestamp="2024-01-02T03:04:05Z",
                overwrite=False,
            ),
        )


@pytest.mark.parametrize(
    ("issued", "expected"),
    [
        ("2024-06", 'dct:issued "2024-06"^^xsd:gYearMonth'),
        ("2024-06-23", 'dct:issued "2024-06-23"^^xsd:date'),
        (
            "2024-06-23T12:34:56Z",
            'dct:issued "2024-06-23T12:34:56Z"^^xsd:dateTime',
        ),
    ],
)
def test_supported_issued_date_lexical_forms_are_emitted(
    tmp_path: Path, issued: str, expected: str
):
    module = load_module()
    dataset = write_dataset(tmp_path, name=f"issued-{issued.replace(':', '-')}")
    write_metadata_yaml(dataset, title="Issued Date Model", issued=issued)

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )

    generated = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")
    assert expected in generated


def test_duplicate_yaml_keys_fail_before_writing(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "duplicate-yaml-keys"
    dataset.mkdir(parents=True)
    write_ontology_json(dataset)
    (dataset / "metadata.yaml").write_text(
        """
title: First title
title: Second title
issued: 2024
license: https://creativecommons.org/licenses/by/4.0/
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(module.MetadataGenerationError, match="duplicate key"):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )
    assert not (dataset / "metadata-json.ttl").exists()


def test_invalid_existing_metadata_json_fails_before_rewriting(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path, name="invalid-existing-metadata")
    (dataset / "metadata-json.ttl").write_text("not turtle", encoding="utf-8")

    with pytest.raises(
        module.MetadataGenerationError, match="Could not parse existing JSON metadata"
    ):
        module.process_dataset(
            dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
        )
    assert (dataset / "metadata-json.ttl").read_text(encoding="utf-8") == "not turtle"


def test_json_array_source_is_allowed_by_default_but_fails_when_validation_is_enabled(
    tmp_path: Path,
):
    module = load_module()
    dataset = write_dataset(tmp_path, name="array-source-json")
    write_ontology_json(dataset, content=[])

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )
    assert (dataset / "metadata-json.ttl").exists()

    (dataset / "metadata-json.ttl").unlink()
    with pytest.raises(module.MetadataGenerationError, match="JSON object"):
        module.process_dataset(
            dataset,
            module.Config(
                metadata_timestamp="2024-01-02T03:04:05Z",
                validate_source_json=True,
            ),
        )
    assert not (dataset / "metadata-json.ttl").exists()


def test_custom_existing_schema_uri_is_preserved(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path, name="custom-schema-json")
    write_existing_json_metadata(dataset)
    existing = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")
    (dataset / "metadata-json.ttl").write_text(
        existing.replace(
            "https://w3id.org/ontouml/schema",
            "https://example.org/custom-json-schema",
        ),
        encoding="utf-8",
    )

    module.process_dataset(
        dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z")
    )
    generated = (dataset / "metadata-json.ttl").read_text(encoding="utf-8")

    assert "https://example.org/custom-json-schema" in generated


def test_cli_quiet_suppresses_text_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    module = load_module()
    dataset = write_dataset(tmp_path, name="quiet-json")

    exit_code = module.main(
        [
            str(dataset),
            "--quiet",
            "--metadata-timestamp",
            "2024-01-02T03:04:05Z",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""


def test_cli_setup_error_returns_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    module = load_module()

    exit_code = module.main(["--all", "--models-dir", str(tmp_path / "missing")])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Models directory does not exist" in captured.err

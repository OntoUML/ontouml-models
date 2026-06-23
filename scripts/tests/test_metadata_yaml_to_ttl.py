from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from rdflib import Graph


def load_module():
    script = None
    for parent in Path(__file__).resolve().parents:
        for candidate in (
            parent / "metadata_yaml_to_ttl.py",
            parent / "scripts" / "metadata_yaml_to_ttl.py",
        ):
            if candidate.exists():
                script = candidate
                break
        if script is not None:
            break
    assert script is not None
    spec = importlib.util.spec_from_file_location("metadata_yaml_to_ttl", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_metadata_yaml(
    dataset: Path,
    *,
    license_line: str | None = "license: https://creativecommons.org/licenses/by/4.0/",
) -> None:
    dataset.mkdir(parents=True, exist_ok=True)
    license_text = f"{license_line}\n" if license_line is not None else ""
    (dataset / "metadata.yaml").write_text(
        f"""
title: Reference Ontology of Trust
acronym: ROT
issued: 2019
modified: 2022
contributor:
 - https://dblp.org/pid/81/4277
 - https://dblp.org/pid/134/4947
keyword:
 - trust
theme: Class H - Social Sciences
editorialNote: Existing editorial note.
ontologyType:
 - domain
language: en
designedForTask:
 - conceptual clarification
context:
 - research
source:
 - https://doi.org/10.1007/example
representationStyle:
 - ontouml
landingPage: https://github.com/unibz-core/trust-ontology
{license_text}""".strip()
        + "\n",
        encoding="utf-8",
    )


def write_existing_metadata_ttl(dataset: Path) -> None:
    (dataset / "metadata.ttl").write_text(
        """
@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
@prefix lcc: <http://id.loc.gov/authorities/classification/>.
@prefix mod: <https://w3id.org/mod#>.
@prefix ocmv: <https://w3id.org/ontouml-models/vocabulary#>.
@prefix skos: <http://www.w3.org/2004/02/skos/core#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

<https://w3id.org/ontouml-models/model/d88fe48c-d574-43b4-85d6-a6e1aeaa6726/> a dcat:Dataset, mod:SemanticArtefact, dcat:Resource;
    dct:isPartOf <https://w3id.org/ontouml-models/catalog/b663ca18-8085-44a7-bcfe-2c2b5ba1faa8>;
    dct:title "Old title";
    ocmv:storageUrl "https://github.com/OntoUML/ontouml-models/tree/master/models/amaral2019rot"^^xsd:anyURI ;
    fdpo:metadataIssued "2023-04-14T17:35:28.608937306Z"^^xsd:dateTime;
    fdpo:metadataModified "2023-04-14T17:35:28.608937306Z"^^xsd:dateTime .

<https://w3id.org/ontouml-models/model/d88fe48c-d574-43b4-85d6-a6e1aeaa6726> dcat:distribution <https://w3id.org/ontouml-models/distribution/one/>, <https://w3id.org/ontouml-models/distribution/two/> .
""".strip()
        + "\n",
        encoding="utf-8",
    )


def assert_parseable_turtle(path: Path) -> None:
    Graph().parse(path, format="turtle")


def test_regeneration_preserves_existing_catalog_managed_values(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "amaral2019rot"
    write_metadata_yaml(dataset)
    write_existing_metadata_ttl(dataset)

    result = module.convert_dataset(dataset, module.Config())

    generated = (dataset / "metadata.ttl").read_text(encoding="utf-8")
    assert result.written is True
    assert "Reference Ontology of Trust" in generated
    assert "Old title" not in generated
    assert "@prefix owl:" not in generated
    assert (
        "https://w3id.org/ontouml-models/model/d88fe48c-d574-43b4-85d6-a6e1aeaa6726/"
        in generated
    )
    assert (
        "https://w3id.org/ontouml-models/model/d88fe48c-d574-43b4-85d6-a6e1aeaa6726> dcat:distribution"
        in generated
    )
    assert "https://w3id.org/ontouml-models/distribution/one/" in generated
    assert "2023-04-14T17:35:28.608937306Z" in generated
    assert (
        "https://github.com/OntoUML/ontouml-models/tree/master/models/amaral2019rot"
        in generated
    )
    assert_parseable_turtle(dataset / "metadata.ttl")


def test_new_dataset_uses_deterministic_model_iri_and_explicit_timestamp(
    tmp_path: Path,
):
    module = load_module()
    dataset = tmp_path / "models" / "new-model"
    write_metadata_yaml(dataset)

    first = module.convert_dataset(
        dataset,
        module.Config(metadata_timestamp="2026-01-31T12:00:00Z"),
    )
    first_text = (dataset / "metadata.ttl").read_text(encoding="utf-8")
    second = module.convert_dataset(
        dataset,
        module.Config(metadata_timestamp="2026-01-31T12:00:00Z"),
    )
    second_text = (dataset / "metadata.ttl").read_text(encoding="utf-8")

    assert first.written is True
    assert second.written is False
    assert first_text == second_text
    assert "metadata-turtle.ttl" not in first_text
    assert "@prefix owl:" not in first_text
    assert "2026-01-31T12:00:00Z" in first_text
    assert "models/new-model" in first_text
    assert_parseable_turtle(dataset / "metadata.ttl")


def test_new_dataset_requires_explicit_metadata_timestamp_when_missing_in_yaml(
    tmp_path: Path,
):
    module = load_module()
    dataset = tmp_path / "models" / "new-model"
    write_metadata_yaml(dataset)

    with pytest.raises(module.MetadataConversionError, match="metadataIssued"):
        module.convert_dataset(dataset, module.Config())


def test_metadata_timestamp_fields_are_rejected_by_strict_yaml_schema(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "new-model"
    write_metadata_yaml(dataset)
    with (dataset / "metadata.yaml").open("a", encoding="utf-8") as stream:
        stream.write("metadata_issued: 2026-02-01T00:00:00Z\n")
        stream.write("metadata_modified: 2026-02-02T00:00:00Z\n")

    with pytest.raises(
        module.MetadataConversionError, match="Unsupported metadata.yaml field"
    ):
        module.convert_dataset(dataset, module.Config())

    assert not (dataset / "metadata.ttl").exists()


def test_missing_license_fails_by_default(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "missing-license"
    write_metadata_yaml(dataset, license_line=None)

    with pytest.raises(module.MetadataConversionError, match="license"):
        module.convert_dataset(
            dataset,
            module.Config(metadata_timestamp="2026-01-31T12:00:00Z"),
        )


def test_allow_missing_license_does_not_suppress_yaml_license(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "has-license"
    write_metadata_yaml(
        dataset, license_line="license: https://creativecommons.org/licenses/by-sa/4.0/"
    )

    module.convert_dataset(
        dataset,
        module.Config(
            allow_missing_license=True,
            metadata_timestamp="2026-01-31T12:00:00Z",
        ),
    )

    generated = (dataset / "metadata.ttl").read_text(encoding="utf-8")
    assert "dct:license <https://creativecommons.org/licenses/by-sa/4.0/>" in generated
    assert_parseable_turtle(dataset / "metadata.ttl")


def test_allow_missing_license_preserves_existing_license_when_yaml_license_missing(
    tmp_path: Path,
):
    module = load_module()
    dataset = tmp_path / "models" / "legacy-license"
    write_metadata_yaml(dataset, license_line=None)
    write_existing_metadata_ttl(dataset)
    ttl_path = dataset / "metadata.ttl"
    ttl_path.write_text(
        ttl_path.read_text(encoding="utf-8").replace(
            '    dct:title "Old title";',
            '    dct:title "Old title";\n    dct:license <https://creativecommons.org/licenses/by-sa/4.0/>;',
        ),
        encoding="utf-8",
    )

    result = module.convert_dataset(
        dataset,
        module.Config(
            allow_missing_license=True,
            metadata_timestamp="2026-01-31T12:00:00Z",
        ),
    )

    generated = ttl_path.read_text(encoding="utf-8")
    assert "dct:license <https://creativecommons.org/licenses/by-sa/4.0/>" in generated
    assert any(
        "preserved from existing metadata.ttl" in warning for warning in result.warnings
    )
    assert_parseable_turtle(ttl_path)


def test_missing_yaml_license_still_fails_without_allow_even_when_existing_ttl_has_license(
    tmp_path: Path,
):
    module = load_module()
    dataset = tmp_path / "models" / "legacy-license"
    write_metadata_yaml(dataset, license_line=None)
    write_existing_metadata_ttl(dataset)
    ttl_path = dataset / "metadata.ttl"
    ttl_path.write_text(
        ttl_path.read_text(encoding="utf-8").replace(
            '    dct:title "Old title";',
            '    dct:title "Old title";\n    dct:license <https://creativecommons.org/licenses/by-sa/4.0/>;',
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.MetadataConversionError, match="license"):
        module.convert_dataset(
            dataset,
            module.Config(metadata_timestamp="2026-01-31T12:00:00Z"),
        )


def test_allow_missing_license_omits_license_triple_for_legacy_dataset(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "missing-license"
    write_metadata_yaml(dataset, license_line=None)

    result = module.convert_dataset(
        dataset,
        module.Config(
            allow_missing_license=True,
            metadata_timestamp="2026-01-31T12:00:00Z",
        ),
    )

    generated = (dataset / "metadata.ttl").read_text(encoding="utf-8")
    assert "dct:license" not in generated
    assert "License metadata omitted" in result.warnings[0]
    assert_parseable_turtle(dataset / "metadata.ttl")


def test_check_mode_reports_needed_update_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    module = load_module()
    dataset = tmp_path / "models" / "check-model"
    write_metadata_yaml(dataset)
    write_existing_metadata_ttl(dataset)
    before = (dataset / "metadata.ttl").read_text(encoding="utf-8")

    exit_code = module.main([str(dataset), "--check"])
    after = (dataset / "metadata.ttl").read_text(encoding="utf-8")
    captured = capsys.readouterr()

    assert exit_code == 1
    assert before == after
    assert "needs update" in captured.out
    assert "---" in captured.out


def test_cli_all_processes_only_direct_dataset_folders(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    module = load_module()
    models = tmp_path / "models"
    first = models / "first"
    second = models / "second"
    unrelated = models / "without-yaml"
    write_metadata_yaml(first)
    write_metadata_yaml(second)
    unrelated.mkdir(parents=True)

    exit_code = module.main(
        [
            "--all",
            "--models-dir",
            str(models),
            "--metadata-timestamp",
            "2026-01-31T12:00:00Z",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert (first / "metadata.ttl").exists()
    assert (second / "metadata.ttl").exists()
    assert not (unrelated / "metadata.ttl").exists()
    assert "generated:" in captured.out


def test_quiet_suppresses_success_progress_and_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    module = load_module()
    dataset = tmp_path / "models" / "quiet-model"
    write_metadata_yaml(dataset)

    exit_code = module.main(
        [
            str(dataset),
            "--metadata-timestamp",
            "2026-01-31T12:00:00Z",
            "--quiet",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""
    assert (dataset / "metadata.ttl").exists()


def test_json_summary_reports_results(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    module = load_module()
    dataset = tmp_path / "models" / "json-model"
    write_metadata_yaml(dataset)

    exit_code = module.main(
        [
            str(dataset),
            "--metadata-timestamp",
            "2026-01-31T12:00:00Z",
            "--format",
            "json",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert '"ok": true' in captured.out
    assert '"written": true' in captured.out


def test_converter_does_not_create_metadata_turtle_ttl(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "no-distribution-file"
    write_metadata_yaml(dataset)

    module.convert_dataset(
        dataset,
        module.Config(metadata_timestamp="2026-01-31T12:00:00Z"),
    )

    assert (dataset / "metadata.ttl").exists()
    assert not (dataset / "metadata-turtle.ttl").exists()


def test_json_check_mode_outputs_clean_json_without_diff(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    module = load_module()
    dataset = tmp_path / "models" / "json-check-model"
    write_metadata_yaml(dataset)
    write_existing_metadata_ttl(dataset)

    exit_code = module.main([str(dataset), "--check", "--format", "json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["results"][0]["changed"] is True
    assert "---" not in captured.out


def test_no_preserve_existing_uses_deterministic_iri_and_drops_existing_links(
    tmp_path: Path,
):
    module = load_module()
    dataset = tmp_path / "models" / "explicit-iri-model"
    write_metadata_yaml(dataset)
    write_existing_metadata_ttl(dataset)

    module.convert_dataset(
        dataset,
        module.Config(
            preserve_existing=False,
            metadata_timestamp="2026-01-31T12:00:00Z",
        ),
    )

    generated = (dataset / "metadata.ttl").read_text(encoding="utf-8")
    assert "d88fe48c-d574-43b4-85d6-a6e1aeaa6726" not in generated
    assert "https://w3id.org/ontouml-models/distribution/one/" not in generated
    assert "https://w3id.org/ontouml-models/model/" in generated
    assert "explicit-iri-model" not in generated.split(" a dcat:Dataset", 1)[0]
    assert_parseable_turtle(dataset / "metadata.ttl")


def test_license_alias_https_lcc_theme_and_controlled_values(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "controlled-values-model"
    write_metadata_yaml(dataset, license_line="license: CC-BY-SA-3.0")
    text = (dataset / "metadata.yaml").read_text(encoding="utf-8")
    text = text.replace(
        "theme: Class H - Social Sciences",
        "theme: https://id.loc.gov/authorities/classification/T",
    )
    text = text.replace(
        " - conceptual clarification",
        " - https://w3id.org/ontouml-models/vocabulary#Learning",
    )
    text = text.replace(" - research", " - ocmv:Industry")
    text = text.replace(" - ontouml", " - UfoStyle")
    text = text.replace(" - domain", " - Application")
    (dataset / "metadata.yaml").write_text(text, encoding="utf-8")

    module.convert_dataset(
        dataset,
        module.Config(metadata_timestamp="2026-01-31T12:00:00Z"),
    )

    generated = (dataset / "metadata.ttl").read_text(encoding="utf-8")
    assert "https://creativecommons.org/licenses/by-sa/3.0/" in generated
    assert "dcat:theme lcc:T" in generated
    assert "mod:designedForTask ocmv:Learning" in generated
    assert "ocmv:context ocmv:Industry" in generated
    assert "ocmv:representationStyle ocmv:UfoStyle" in generated
    assert "ocmv:ontologyType ocmv:Application" in generated
    assert_parseable_turtle(dataset / "metadata.ttl")


def test_language_maps_are_supported_for_literal_fields(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "rich-yaml-model"
    write_metadata_yaml(dataset)
    write_existing_metadata_ttl(dataset)
    yaml_text = (dataset / "metadata.yaml").read_text(encoding="utf-8")
    yaml_text = yaml_text.replace(
        "title: Reference Ontology of Trust",
        "title:\n  en: Reference Ontology of Trust\n  pt: Ontologia de Confiança",
    )
    (dataset / "metadata.yaml").write_text(yaml_text, encoding="utf-8")

    module.convert_dataset(dataset, module.Config())

    generated = (dataset / "metadata.ttl").read_text(encoding="utf-8")
    assert 'dct:title "Reference Ontology of Trust"@en' in generated
    assert '"Ontologia de Confiança"@pt' in generated
    assert_parseable_turtle(dataset / "metadata.ttl")


def test_keywords_are_always_emitted_in_english_independent_of_model_language(
    tmp_path: Path,
):
    module = load_module()
    dataset = tmp_path / "models" / "pt-keyword-model"
    write_metadata_yaml(dataset)
    yaml_text = (dataset / "metadata.yaml").read_text(encoding="utf-8")
    yaml_text = yaml_text.replace("language: en", "language: pt-BR")
    yaml_text = yaml_text.replace(
        "keyword:\n - trust",
        "keyword:\n - trust\n - {pt: confiança}",
    )
    (dataset / "metadata.yaml").write_text(yaml_text, encoding="utf-8")

    module.convert_dataset(
        dataset,
        module.Config(metadata_timestamp="2026-01-31T12:00:00Z"),
    )

    generated = (dataset / "metadata.ttl").read_text(encoding="utf-8")
    assert 'dct:language "pt-BR"' in generated
    assert 'dcat:keyword "trust"@en' in generated
    assert '"confiança"@en' in generated
    assert '"trust"@pt-BR' not in generated
    assert '"confiança"@pt' not in generated
    assert_parseable_turtle(dataset / "metadata.ttl")


def test_unsupported_contact_points_and_yaml_distribution_are_rejected(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "unsupported-fields"
    write_metadata_yaml(dataset)
    with (dataset / "metadata.yaml").open("a", encoding="utf-8") as stream:
        stream.write("contactPoints:\n")
        stream.write(" - name: Catalog Maintainer\n")
        stream.write("   email: maintainer@example.org\n")
        stream.write("distribution:\n")
        stream.write(" - https://w3id.org/ontouml-models/distribution/one/\n")

    with pytest.raises(
        module.MetadataConversionError, match="Unsupported metadata.yaml field"
    ):
        module.convert_dataset(
            dataset,
            module.Config(metadata_timestamp="2026-01-31T12:00:00Z"),
        )

    assert not (dataset / "metadata.ttl").exists()


def test_distribution_links_are_discovered_from_distribution_metadata_files(
    tmp_path: Path,
):
    module = load_module()
    dataset = tmp_path / "models" / "with-distribution-files"
    write_metadata_yaml(dataset)
    (dataset / "metadata-json.ttl").write_text(
        """
@prefix dcat: <http://www.w3.org/ns/dcat#> .

<https://w3id.org/ontouml-models/distribution/json/> a dcat:Distribution .
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (dataset / "metadata-png-o-diagram.ttl").write_text(
        """
@prefix dcat: <http://www.w3.org/ns/dcat#> .

<https://w3id.org/ontouml-models/distribution/png/> a dcat:Distribution .
""".strip()
        + "\n",
        encoding="utf-8",
    )

    module.convert_dataset(
        dataset,
        module.Config(metadata_timestamp="2026-01-31T12:00:00Z"),
    )

    generated = (dataset / "metadata.ttl").read_text(encoding="utf-8")
    assert "https://w3id.org/ontouml-models/distribution/json/" in generated
    assert "https://w3id.org/ontouml-models/distribution/png/" in generated
    assert_parseable_turtle(dataset / "metadata.ttl")


def test_metadata_timestamp_field_is_rejected_even_when_lexically_valid(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "bad-fdp-timestamp"
    write_metadata_yaml(dataset)
    with (dataset / "metadata.yaml").open("a", encoding="utf-8") as stream:
        stream.write("metadata_issued: 2026-02-01T00:00:00Z\n")

    with pytest.raises(
        module.MetadataConversionError, match="Unsupported metadata.yaml field"
    ):
        module.convert_dataset(dataset, module.Config())


def test_dry_run_prints_turtle_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    module = load_module()
    dataset = tmp_path / "models" / "dry-run-model"
    write_metadata_yaml(dataset)

    exit_code = module.main(
        [
            str(dataset),
            "--dry-run",
            "--metadata-timestamp",
            "2026-01-31T12:00:00Z",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "@prefix dcat:" in captured.out
    assert "Reference Ontology of Trust" in captured.out
    assert not (dataset / "metadata.ttl").exists()


def test_missing_metadata_yaml_is_setup_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    module = load_module()
    dataset = tmp_path / "models" / "missing-yaml"
    dataset.mkdir(parents=True)

    exit_code = module.main([str(dataset)])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "Missing metadata.yaml" in captured.err


def test_all_mode_continues_after_dataset_conversion_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    module = load_module()
    models = tmp_path / "models"
    valid = models / "valid"
    invalid = models / "invalid"
    write_metadata_yaml(valid)
    write_metadata_yaml(invalid, license_line=None)

    exit_code = module.main(
        [
            "--all",
            "--models-dir",
            str(models),
            "--metadata-timestamp",
            "2026-01-31T12:00:00Z",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert (valid / "metadata.ttl").exists()
    assert not (invalid / "metadata.ttl").exists()
    assert "ERROR" in captured.err


def write_catalog_metadata_pair(dataset: Path, yaml_text: str, ttl_text: str) -> None:
    dataset.mkdir(parents=True, exist_ok=True)
    (dataset / "metadata.yaml").write_text(yaml_text.strip() + "\n", encoding="utf-8")
    (dataset / "metadata.ttl").write_text(ttl_text.strip() + "\n", encoding="utf-8")


AMARAL_2019_ROT_YAML = """
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


AMARAL_2019_ROT_OLD_TTL = """
@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
@prefix lcc: <http://id.loc.gov/authorities/classification/>.
@prefix mod: <https://w3id.org/mod#>.
@prefix ocmv: <https://w3id.org/ontouml-models/vocabulary#>.
@prefix owl: <http://www.w3.org/2002/07/owl#>.
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
@prefix skos: <http://www.w3.org/2004/02/skos/core#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

<https://w3id.org/ontouml-models/model/d88fe48c-d574-43b4-85d6-a6e1aeaa6726/> a dcat:Dataset, mod:SemanticArtefact, dcat:Resource;
    dct:isPartOf <https://w3id.org/ontouml-models/catalog/b663ca18-8085-44a7-bcfe-2c2b5ba1faa8>;
    dct:title "Reference Ontology of Trust";
    mod:acronym "ROT";
    dct:issued "2019"^^xsd:gYear;
    dct:modified "2022"^^xsd:gYear;
    dcat:theme lcc:H;
    skos:editorialNote "The files listed here were imported from ROT's github repository (https://github.com/unibz-core/trust-ontology) on March 23, 2022. Therefore, the ontology is much larger than that described in the paper identified as the main source here.";
    dct:language "en";
    dcat:landingPage <https://github.com/unibz-core/trust-ontology>;
    dct:license <https://creativecommons.org/licenses/by/4.0/>;
    dct:contributor <https://dblp.org/pid/81/4277>, <https://dblp.org/pid/134/4947>, <https://dblp.org/pid/11/78>, <https://dblp.org/pid/33/8219>, <https://dblp.org/pid/91/3408>, <https://dblp.org/pid/75/5043>, <https://dblp.org/pid/m/JohnMylopoulos>;
    dcat:keyword "trust"@en;
    mod:designedForTask ocmv:ConceptualClarification;
    ocmv:context ocmv:Research;
    dct:source <https://doi.org/10.1007/978-3-030-33246-4_1>, <https://dblp.org/rec/conf/vmbo/AmaralSGP21>, <https://doi.org/10.1007/978-3-030-63479-7_6>, <https://doi.org/10.1007/978-3-030-62522-1_25>;
    ocmv:representationStyle ocmv:OntoumlStyle;
    ocmv:ontologyType ocmv:Domain;
    ocmv:storageUrl "https://github.com/OntoUML/ontouml-models/tree/master/models/amaral2019rot"^^xsd:anyURI ;
    fdpo:metadataIssued "2023-04-14T17:35:28.608937306Z"^^xsd:dateTime;
    fdpo:metadataModified "2023-04-14T17:35:28.608937306Z"^^xsd:dateTime .
    <https://w3id.org/ontouml-models/model/d88fe48c-d574-43b4-85d6-a6e1aeaa6726> dcat:distribution <https://w3id.org/ontouml-models/distribution/78713112-cf7e-45f1-8c74-c7b5906f5b7c/>, <https://w3id.org/ontouml-models/distribution/7c83f03b-c170-49d2-9dd9-0a600be6cc96/>, <https://w3id.org/ontouml-models/distribution/48c920df-896e-43db-baa4-adcc206d1b3d/>.
"""


ALPINEBITS_2022_YAML = """
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


ALPINEBITS_2022_OLD_TTL = """
@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
@prefix lcc: <http://id.loc.gov/authorities/classification/>.
@prefix mod: <https://w3id.org/mod#>.
@prefix ocmv: <https://w3id.org/ontouml-models/vocabulary#>.
@prefix skos: <http://www.w3.org/2004/02/skos/core#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

<https://w3id.org/ontouml-models/model/ad142d17-1fcd-4189-b050-faed17165bc7/> a dcat:Dataset, mod:SemanticArtefact, dcat:Resource;
    dct:isPartOf <https://w3id.org/ontouml-models/catalog/b663ca18-8085-44a7-bcfe-2c2b5ba1faa8>;
    dct:title "AlpineBits DestinationData Ontology";
    dct:issued "2020"^^xsd:gYear;
    dct:modified "2022"^^xsd:gYear;
    dcat:theme lcc:G;
    dcat:keyword "tourism"@en, "alpine tourism"@en;
    mod:designedForTask ocmv:SoftwareEngineering, ocmv:Interoperability;
    ocmv:storageUrl "https://github.com/OntoUML/ontouml-models/tree/master/models/alpinebits2022"^^xsd:anyURI ;
    fdpo:metadataIssued "2023-04-14T17:35:06.066269877Z"^^xsd:dateTime;
    fdpo:metadataModified "2023-04-14T17:35:06.066269877Z"^^xsd:dateTime .
    <https://w3id.org/ontouml-models/model/ad142d17-1fcd-4189-b050-faed17165bc7> dcat:distribution <https://w3id.org/ontouml-models/distribution/c9f1c174-5b7e-441e-9318-6a5858d053b8/>, <https://w3id.org/ontouml-models/distribution/b329a4b1-7b57-4aa4-a284-787a4c7abcf2/>, <https://w3id.org/ontouml-models/distribution/239bafd0-8488-4d1e-8653-e345eb321ddb/>.
"""


@pytest.mark.parametrize(
    (
        "folder",
        "yaml_text",
        "old_ttl",
        "model_uuid",
        "expected_theme",
        "expected_timestamp",
    ),
    [
        (
            "amaral2019rot",
            AMARAL_2019_ROT_YAML,
            AMARAL_2019_ROT_OLD_TTL,
            "d88fe48c-d574-43b4-85d6-a6e1aeaa6726",
            "dcat:theme lcc:H",
            "2023-04-14T17:35:28.608937306Z",
        ),
        (
            "alpinebits2022",
            ALPINEBITS_2022_YAML,
            ALPINEBITS_2022_OLD_TTL,
            "ad142d17-1fcd-4189-b050-faed17165bc7",
            "dcat:theme lcc:G",
            "2023-04-14T17:35:06.066269877Z",
        ),
    ],
)
def test_existing_catalog_metadata_ttl_cases_preserve_legacy_catalog_values(
    tmp_path: Path,
    folder: str,
    yaml_text: str,
    old_ttl: str,
    model_uuid: str,
    expected_theme: str,
    expected_timestamp: str,
):
    module = load_module()
    dataset = tmp_path / "models" / folder
    write_catalog_metadata_pair(dataset, yaml_text, old_ttl)

    module.convert_dataset(dataset, module.Config())

    generated = (dataset / "metadata.ttl").read_text(encoding="utf-8")
    assert f"https://w3id.org/ontouml-models/model/{model_uuid}/" in generated
    assert (
        f"https://w3id.org/ontouml-models/model/{model_uuid}> dcat:distribution"
        in generated
    )
    assert expected_theme in generated
    assert expected_timestamp in generated
    assert f"models/{folder}" in generated
    assert "metadata-turtle.ttl" not in generated
    assert_parseable_turtle(dataset / "metadata.ttl")


def test_license_mapping_form_is_rejected_to_match_yaml_validator(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "mapped-license"
    write_metadata_yaml(dataset, license_line=None)
    with (dataset / "metadata.yaml").open("a", encoding="utf-8") as stream:
        stream.write("license:\n")
        stream.write("  id: CC-BY-4.0\n")

    with pytest.raises(
        module.MetadataConversionError, match="Field 'license' must be a single scalar"
    ):
        module.convert_dataset(
            dataset,
            module.Config(metadata_timestamp="2026-02-01T00:00:00Z"),
        )

    assert not (dataset / "metadata.ttl").exists()


def test_fdp_timestamp_mapping_form_is_rejected_to_match_yaml_validator(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "mapped-timestamp"
    write_metadata_yaml(
        dataset, license_line="license: https://creativecommons.org/licenses/by/4.0/"
    )
    with (dataset / "metadata.yaml").open("a", encoding="utf-8") as stream:
        stream.write("metadata_issued:\n")
        stream.write("  value: 2026-02-01T00:00:00Z\n")
        stream.write("metadata_modified: 2026-02-02T00:00:00Z\n")

    with pytest.raises(
        module.MetadataConversionError, match="Unsupported metadata.yaml field"
    ):
        module.convert_dataset(dataset, module.Config())

    assert not (dataset / "metadata.ttl").exists()


def test_landing_page_accepts_multiple_urls_like_validator(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "core-o2023"
    write_metadata_yaml(dataset)
    text = (dataset / "metadata.yaml").read_text(encoding="utf-8")
    text = text.replace(
        "landingPage: https://github.com/unibz-core/trust-ontology\n",
        "landingPage:\n"
        " - https://core-o.github.io/ontology/\n"
        " - https://github.com/core-o\n"
        " - https://purl.org/coreo\n",
    )
    (dataset / "metadata.yaml").write_text(text, encoding="utf-8")

    module.convert_dataset(
        dataset,
        module.Config(metadata_timestamp="2026-01-31T12:00:00Z"),
    )

    generated = (dataset / "metadata.ttl").read_text(encoding="utf-8")
    assert "dcat:landingPage <https://core-o.github.io/ontology/>" in generated
    assert "<https://github.com/core-o>" in generated
    assert "<https://purl.org/coreo>" in generated
    assert_parseable_turtle(dataset / "metadata.ttl")


def test_existing_metadata_without_fdp_timestamp_requires_explicit_timestamp(
    tmp_path: Path,
):
    module = load_module()
    dataset = tmp_path / "models" / "existing-without-fdp"
    write_metadata_yaml(dataset)
    (dataset / "metadata.ttl").write_text(
        """
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
@prefix mod: <https://w3id.org/mod#>.

<https://w3id.org/ontouml-models/model/existing-without-fdp/> a dcat:Dataset, mod:SemanticArtefact, dcat:Resource;
    dct:title "Existing without FDP" .
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        module.MetadataConversionError,
        match="--metadata-timestamp 2026-01-31T12:00:00Z",
    ):
        module.convert_dataset(dataset, module.Config())

    module.convert_dataset(
        dataset,
        module.Config(metadata_timestamp="2026-01-31T12:00:00Z"),
    )
    generated = (dataset / "metadata.ttl").read_text(encoding="utf-8")
    assert "2026-01-31T12:00:00Z" in generated
    assert_parseable_turtle(dataset / "metadata.ttl")


def test_literal_mapping_uses_validator_compatible_keys_only(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "invalid-literal-map"
    write_metadata_yaml(dataset)
    yaml_text = (dataset / "metadata.yaml").read_text(encoding="utf-8")
    yaml_text = yaml_text.replace(
        "title: Reference Ontology of Trust",
        "title:\n  Value: Reference Ontology of Trust",
    )
    (dataset / "metadata.yaml").write_text(yaml_text, encoding="utf-8")

    with pytest.raises(module.MetadataConversionError, match="language tag"):
        module.convert_dataset(
            dataset,
            module.Config(metadata_timestamp="2026-01-31T12:00:00Z"),
        )


def test_controlled_value_mappings_are_rejected_like_validator(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "invalid-controlled-value"
    write_metadata_yaml(dataset)
    yaml_text = (dataset / "metadata.yaml").read_text(encoding="utf-8")
    yaml_text = yaml_text.replace(
        " - conceptual clarification",
        " - value: conceptual clarification",
    )
    (dataset / "metadata.yaml").write_text(yaml_text, encoding="utf-8")

    with pytest.raises(
        module.MetadataConversionError, match="controlled-value strings"
    ):
        module.convert_dataset(
            dataset,
            module.Config(metadata_timestamp="2026-01-31T12:00:00Z"),
        )


def test_comma_separated_language_scalar_matches_validator_behavior(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "multi-language"
    write_metadata_yaml(dataset)
    yaml_text = (dataset / "metadata.yaml").read_text(encoding="utf-8")
    yaml_text = yaml_text.replace("language: en", "language: en, pt-BR")
    (dataset / "metadata.yaml").write_text(yaml_text, encoding="utf-8")

    module.convert_dataset(
        dataset,
        module.Config(metadata_timestamp="2026-01-31T12:00:00Z"),
    )

    generated = (dataset / "metadata.ttl").read_text(encoding="utf-8")
    assert 'dct:language "en",\n                 "pt-BR"' in generated
    assert 'dcat:keyword "trust"@en' in generated
    assert_parseable_turtle(dataset / "metadata.ttl")

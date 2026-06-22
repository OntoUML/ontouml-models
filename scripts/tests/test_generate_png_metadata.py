from __future__ import annotations

import importlib.util
import struct
import sys
import zlib
from pathlib import Path

import pytest


def load_module():
    script = None
    for parent in Path(__file__).resolve().parents:
        for candidate in (parent / "generate_png_metadata.py", parent / "scripts" / "generate_png_metadata.py"):
            if candidate.exists():
                script = candidate
                break
        if script is not None:
            break
    assert script is not None
    spec = importlib.util.spec_from_file_location("generate_png_metadata", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def minimal_png() -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    return signature + png_chunk(b"IHDR", ihdr) + png_chunk(b"IDAT", b"") + png_chunk(b"IEND", b"")


def write_metadata_yaml(
    dataset: Path,
    *,
    slug: str = "example",
    title: str = "Petroleum System Model",
    issued: str = "2015",
    license_value: str | None = "https://creativecommons.org/licenses/by/4.0/",
) -> None:
    license_line = f"license: {license_value}\n" if license_value is not None else ""
    (dataset / "metadata.yaml").write_text(
        f"""
id: {slug}
title: {title}
issued: {issued}
{license_line}""".strip()
        + "\n",
        encoding="utf-8",
    )


def write_dataset(tmp_path: Path) -> Path:
    dataset = tmp_path / "models" / "example-model"
    (dataset / "original-diagrams").mkdir(parents=True)
    (dataset / "new-diagrams").mkdir()
    (dataset / "original-diagrams" / "petroleum-system.png").write_bytes(minimal_png())
    (dataset / "new-diagrams" / "petroleum-system.png").write_bytes(minimal_png())
    write_metadata_yaml(dataset)
    (dataset / "metadata-png-o-petroleum-system.ttl").write_text(
        """
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
@prefix skos: <http://www.w3.org/2004/02/skos/core#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

<https://w3id.org/ontouml-models/distribution/original-existing> a dcat:Distribution;
    dct:title "Existing original PNG title"@en;
    dcat:downloadURL <https://raw.githubusercontent.com/OntoUML/ontouml-models/master/models/example-model/original-diagrams/petroleum-system.png>;
    skos:editorialNote "Existing original editorial note."@en;
    fdpo:metadataIssued "2023-04-14T17:33:24.802284319Z"^^xsd:dateTime;
    fdpo:metadataModified "2023-04-14T17:33:25.802284319Z"^^xsd:dateTime .
""".strip(),
        encoding="utf-8",
    )
    return dataset


def test_png_metadata_regeneration_preserves_existing_catalog_values(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)

    generated = module.process_dataset(dataset, module.Config())

    assert len(generated) == 2
    original = (dataset / "metadata-png-o-petroleum-system.ttl").read_text(encoding="utf-8")

    assert "ocmv:isComplete false" in original
    assert "Existing original PNG title" in original
    assert "Existing original editorial note." in original
    assert "2023-04-14T17:33:24.802284319Z" in original
    assert "2023-04-14T17:33:25.802284319Z" in original
    assert "https://w3id.org/ontouml-models/distribution/original-existing" in original
    assert "original-diagrams/petroleum-system.png" in original


def test_png_metadata_generation_uses_yaml_defaults_for_new_files(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)

    module.process_dataset(dataset, module.Config())

    new = (dataset / "metadata-png-n-petroleum-system.ttl").read_text(encoding="utf-8")

    assert "ocmv:isComplete false" in new
    assert "dct:isPartOf <https://w3id.org/ontouml-models/model/example>" in new
    assert 'dct:issued "2015"^^xsd:gYear' in new
    assert (
        'skos:editorialNote "This image depicts a version of the original diagram re-created in the Visual Paradigm editor."@en'
        in new
    )
    assert "PNG distribution of diagram 'petroleum system' from the Petroleum System Model (Visual Paradigm version)" in new


def test_png_metadata_generation_does_not_require_metadata_ttl(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)

    assert not (dataset / "metadata.ttl").exists()

    module.process_dataset(dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z"))

    assert (dataset / "metadata-png-n-petroleum-system.ttl").exists()


def test_png_metadata_regeneration_preserves_existing_download_url_with_comma(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "alpinebits2022"
    (dataset / "original-diagrams").mkdir(parents=True)
    (dataset / "original-diagrams" / "lifts,-ski-slopes,-and-snowparks.png").write_bytes(minimal_png())
    write_metadata_yaml(
        dataset,
        slug="alpinebits",
        title="AlpineBits DestinationData Ontology",
        issued="2020",
        license_value="https://creativecommons.org/licenses/by-sa/3.0/",
    )
    (dataset / "metadata-png-o-lifts,-ski-slopes,-and-snowparks.ttl").write_text(
        """
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
@prefix skos: <http://www.w3.org/2004/02/skos/core#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

<https://w3id.org/ontouml-models/distribution/comma-existing> a dcat:Distribution;
    dct:title "PNG distribution of diagram 'lifts, ski slopes, and snowparks' from the AlpineBits DestinationData Ontology (original version)"@en;
    dcat:downloadURL <https://raw.githubusercontent.com/OntoUML/ontouml-models/master/models/alpinebits2022/original-diagrams/lifts,-ski-slopes,-and-snowparks.png>;
    skos:editorialNote "This image depicts the diagram as originally represented by its author(s)."@en;
    fdpo:metadataIssued "2023-04-14T17:35:15.384682094Z"^^xsd:dateTime;
    fdpo:metadataModified "2023-04-14T17:35:15.384682094Z"^^xsd:dateTime .
""".strip(),
        encoding="utf-8",
    )

    module.process_dataset(dataset, module.Config())

    regenerated = (dataset / "metadata-png-o-lifts,-ski-slopes,-and-snowparks.ttl").read_text(encoding="utf-8")
    assert "lifts,-ski-slopes,-and-snowparks.png" in regenerated
    assert "lifts%2C-ski-slopes%2C-and-snowparks.png" not in regenerated


def test_png_metadata_generation_keeps_commas_unescaped_in_new_download_urls(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "new-comma-model"
    (dataset / "original-diagrams").mkdir(parents=True)
    (dataset / "original-diagrams" / "lifts,-ski-slopes,-and-snowparks.png").write_bytes(minimal_png())
    write_metadata_yaml(dataset, slug="new-comma", title="New Comma Model", issued="2024")

    module.process_dataset(dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z"))

    generated = (dataset / "metadata-png-o-lifts,-ski-slopes,-and-snowparks.ttl").read_text(encoding="utf-8")
    assert "lifts,-ski-slopes,-and-snowparks.png" in generated
    assert "lifts%2C-ski-slopes%2C-and-snowparks.png" not in generated


def test_png_metadata_generation_tolerates_missing_model_license(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "missing-license-model"
    (dataset / "original-diagrams").mkdir(parents=True)
    (dataset / "original-diagrams" / "diagram.png").write_bytes(minimal_png())
    write_metadata_yaml(dataset, slug="missing-license", title="Missing License Model", issued="2024", license_value=None)

    module.process_dataset(dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z"))

    generated = (dataset / "metadata-png-o-diagram.ttl").read_text(encoding="utf-8")
    assert "dct:license" not in generated
    assert "Missing License Model" in generated


def test_png_metadata_generation_can_require_model_license(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "missing-license-model"
    (dataset / "original-diagrams").mkdir(parents=True)
    (dataset / "original-diagrams" / "diagram.png").write_bytes(minimal_png())
    write_metadata_yaml(dataset, slug="missing-license", title="Missing License Model", issued="2024", license_value=None)

    with pytest.raises(module.MetadataGenerationError, match="Missing required license"):
        module.process_dataset(dataset, module.Config(require_license=True))


def test_discover_datasets_uses_metadata_yaml(tmp_path: Path):
    module = load_module()
    models = tmp_path / "models"
    with_yaml = models / "with-yaml"
    without_yaml = models / "without-yaml"
    with_yaml.mkdir(parents=True)
    without_yaml.mkdir()
    write_metadata_yaml(with_yaml, slug="with-yaml", title="With YAML", issued="2024")
    (without_yaml / "metadata.ttl").write_text("", encoding="utf-8")

    assert module.discover_datasets(models) == [with_yaml]


def test_yaml_metadata_loader_accepts_nested_language_map_and_license_id(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "nested-yaml-model"
    (dataset / "original-diagrams").mkdir(parents=True)
    (dataset / "original-diagrams" / "diagram.png").write_bytes(minimal_png())
    (dataset / "metadata.yaml").write_text(
        """
model:
  uri: https://w3id.org/ontouml-models/model/nested-yaml/
  title:
    en: Nested YAML Model
metadata:
  issued: 2024-01-31
rights:
  license:
    id: CC-BY-4.0
""".strip()
        + "\n",
        encoding="utf-8",
    )

    module.process_dataset(dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z"))

    generated = (dataset / "metadata-png-o-diagram.ttl").read_text(encoding="utf-8")
    assert "Nested YAML Model" in generated
    assert 'dct:issued "2024-01-31"^^xsd:date' in generated
    assert "https://creativecommons.org/licenses/by/4.0/" in generated


def test_cli_all_dry_run_processes_metadata_yaml_datasets(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    module = load_module()
    models = tmp_path / "models"
    first = models / "first-model"
    second = models / "second-model"
    for dataset, slug, title in (
        (first, "first-model", "First Model"),
        (second, "second-model", "Second Model"),
    ):
        (dataset / "original-diagrams").mkdir(parents=True)
        (dataset / "original-diagrams" / "diagram.png").write_bytes(minimal_png())
        write_metadata_yaml(dataset, slug=slug, title=title, issued="2024")

    exit_code = module.main(["--all", "--models-dir", str(models), "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "would generate:" in captured.out
    assert "first-model" in captured.out
    assert "second-model" in captured.out
    assert not (first / "metadata-png-o-diagram.ttl").exists()
    assert not (second / "metadata-png-o-diagram.ttl").exists()


def test_png_metadata_generation_url_quotes_spaces_and_apostrophes_but_not_commas(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "special-name-model"
    (dataset / "original-diagrams").mkdir(parents=True)
    filename = "AUX - Object at Risk's Vulnerability, Manifestation.png"
    (dataset / "original-diagrams" / filename).write_bytes(minimal_png())
    write_metadata_yaml(dataset, slug="special-name-model", title="Special Name Model", issued="2024")

    module.process_dataset(dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z"))

    generated = (dataset / "metadata-png-o-AUX - Object at Risk's Vulnerability, Manifestation.ttl").read_text(
        encoding="utf-8"
    )
    assert "AUX%20-%20Object%20at%20Risk%27s%20Vulnerability,%20Manifestation.png" in generated
    assert "%2C" not in generated


def test_existing_png_license_is_preserved_when_model_license_is_missing(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "existing-license-model"
    (dataset / "original-diagrams").mkdir(parents=True)
    (dataset / "original-diagrams" / "diagram.png").write_bytes(minimal_png())
    write_metadata_yaml(dataset, slug="existing-license-model", title="Existing License Model", issued="2024", license_value=None)
    (dataset / "metadata-png-o-diagram.ttl").write_text(
        """
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

<https://w3id.org/ontouml-models/distribution/existing-license> a dcat:Distribution;
    dct:license <https://example.org/custom-license>;
    fdpo:metadataIssued "2023-04-14T17:33:24.802284319Z"^^xsd:dateTime;
    fdpo:metadataModified "2023-04-14T17:33:25.802284319Z"^^xsd:dateTime .
""".strip(),
        encoding="utf-8",
    )

    module.process_dataset(dataset, module.Config())

    generated = (dataset / "metadata-png-o-diagram.ttl").read_text(encoding="utf-8")
    assert "https://example.org/custom-license" in generated


def test_existing_full_iri_timestamps_are_preserved(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "full-iri-timestamp-model"
    (dataset / "original-diagrams").mkdir(parents=True)
    (dataset / "original-diagrams" / "diagram.png").write_bytes(minimal_png())
    write_metadata_yaml(dataset, slug="full-iri-timestamp-model", title="Timestamp Model", issued="2024")
    (dataset / "metadata-png-o-diagram.ttl").write_text(
        """
@prefix dcat: <http://www.w3.org/ns/dcat#>.

<https://w3id.org/ontouml-models/distribution/full-iri-time> a dcat:Distribution;
    <https://w3id.org/fdp/fdp-o#metadataIssued> "2023-04-14T17:33:24.802284319Z"^^<http://www.w3.org/2001/XMLSchema#dateTime>;
    <https://w3id.org/fdp/fdp-o#metadataModified> "2023-04-14T17:33:25.802284319Z"^^<http://www.w3.org/2001/XMLSchema#dateTime> .
""".strip(),
        encoding="utf-8",
    )

    module.process_dataset(dataset, module.Config())

    generated = (dataset / "metadata-png-o-diagram.ttl").read_text(encoding="utf-8")
    assert "2023-04-14T17:33:24.802284319Z" in generated
    assert "2023-04-14T17:33:25.802284319Z" in generated


def test_include_file_metadata_emits_dimensions_byte_size_and_checksum(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "file-metadata-model"
    (dataset / "original-diagrams").mkdir(parents=True)
    (dataset / "original-diagrams" / "diagram.png").write_bytes(minimal_png())
    write_metadata_yaml(dataset, slug="file-metadata-model", title="File Metadata Model", issued="2024")

    module.process_dataset(
        dataset,
        module.Config(metadata_timestamp="2024-01-02T03:04:05Z", include_file_metadata=True),
    )

    generated = (dataset / "metadata-png-o-diagram.ttl").read_text(encoding="utf-8")
    assert "dcat:byteSize" in generated
    assert "schema:width 1" in generated
    assert "schema:height 1" in generated
    assert "spdx:checksumValue" in generated


def test_invalid_png_fails_before_any_metadata_file_is_written(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "invalid-png-model"
    (dataset / "original-diagrams").mkdir(parents=True)
    (dataset / "original-diagrams" / "a-valid.png").write_bytes(minimal_png())
    (dataset / "original-diagrams" / "z-invalid.png").write_bytes(b"not a png")
    write_metadata_yaml(dataset, slug="invalid-png-model", title="Invalid PNG Model", issued="2024")

    with pytest.raises(module.MetadataGenerationError, match="invalid PNG"):
        module.process_dataset(dataset, module.Config())

    assert not (dataset / "metadata-png-o-a-valid.ttl").exists()
    assert not (dataset / "metadata-png-o-z-invalid.ttl").exists()

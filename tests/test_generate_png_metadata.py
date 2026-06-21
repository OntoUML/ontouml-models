from __future__ import annotations

import importlib.util
import struct
import sys
import zlib
from pathlib import Path


def load_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "generate_png_metadata.py"
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


def write_dataset(tmp_path: Path) -> Path:
    dataset = tmp_path / "models" / "example-model"
    (dataset / "original-diagrams").mkdir(parents=True)
    (dataset / "new-diagrams").mkdir()
    (dataset / "original-diagrams" / "petroleum-system.png").write_bytes(minimal_png())
    (dataset / "new-diagrams" / "petroleum-system.png").write_bytes(minimal_png())
    (dataset / "metadata.ttl").write_text(
        """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix mod: <https://w3id.org/mod#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://w3id.org/ontouml-models/model/example> a dcat:Dataset, mod:SemanticArtefact ;
    dct:title "Petroleum System Model"@en ;
    dct:issued "2015"^^xsd:gYear ;
    dct:license <https://creativecommons.org/licenses/by/4.0/> .
""".strip(),
        encoding="utf-8",
    )
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


def test_png_metadata_generation_uses_defaults_for_new_files(tmp_path: Path):
    module = load_module()
    dataset = write_dataset(tmp_path)

    module.process_dataset(dataset, module.Config())

    new = (dataset / "metadata-png-n-petroleum-system.ttl").read_text(encoding="utf-8")

    assert "ocmv:isComplete false" in new
    assert (
        'skos:editorialNote "This image depicts a version of the original diagram re-created in the Visual Paradigm editor."@en'
        in new
    )
    assert "PNG distribution of diagram 'petroleum system' from the Petroleum System Model (Visual Paradigm version)" in new


def test_png_metadata_regeneration_preserves_existing_download_url_with_comma(tmp_path: Path):
    module = load_module()
    dataset = tmp_path / "models" / "alpinebits2022"
    (dataset / "original-diagrams").mkdir(parents=True)
    (dataset / "original-diagrams" / "lifts,-ski-slopes,-and-snowparks.png").write_bytes(minimal_png())
    (dataset / "metadata.ttl").write_text(
        """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix mod: <https://w3id.org/mod#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://w3id.org/ontouml-models/model/alpinebits> a dcat:Dataset, mod:SemanticArtefact ;
    dct:title "AlpineBits DestinationData Ontology"@en ;
    dct:issued "2020"^^xsd:gYear ;
    dct:license <https://creativecommons.org/licenses/by-sa/3.0/> .
""".strip(),
        encoding="utf-8",
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
    (dataset / "metadata.ttl").write_text(
        """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix mod: <https://w3id.org/mod#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://w3id.org/ontouml-models/model/new-comma> a dcat:Dataset, mod:SemanticArtefact ;
    dct:title "New Comma Model"@en ;
    dct:issued "2024"^^xsd:gYear ;
    dct:license <https://creativecommons.org/licenses/by/4.0/> .
""".strip(),
        encoding="utf-8",
    )

    module.process_dataset(dataset, module.Config(metadata_timestamp="2024-01-02T03:04:05Z"))

    generated = (dataset / "metadata-png-o-lifts,-ski-slopes,-and-snowparks.ttl").read_text(encoding="utf-8")
    assert "lifts,-ski-slopes,-and-snowparks.png" in generated
    assert "lifts%2C-ski-slopes%2C-and-snowparks.png" not in generated

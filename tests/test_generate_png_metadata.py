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

import struct
from decimal import Decimal
import uuid
import zlib
from pathlib import Path

import pytest
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS as DCT, RDF, XSD

from scripts.generate_png_metadata import Config, MetadataGenerationError, process_dataset

DCAT = Namespace("http://www.w3.org/ns/dcat#")
FDPO = Namespace("https://w3id.org/fdp/fdp-o#")
OCMV = Namespace("https://w3id.org/ontouml-models/vocabulary#")

FIXED_TIMESTAMP = "2024-01-02T03:04:05Z"


def write_png(path: Path, width: int = 2, height: int = 3) -> None:
    """Write a minimal valid PNG file for tests."""

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + chunk_type
            + data
            + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
        )

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    # Empty IDAT is sufficient for the script because it validates only the
    # signature and IHDR, but keep a proper IEND chunk for a well-formed file.
    path.write_bytes(signature + chunk(b"IHDR", ihdr) + chunk(b"IDAT", b"") + chunk(b"IEND", b""))


def write_metadata(path: Path) -> None:
    path.write_text(
        """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix mod: <https://w3id.org/mod#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://w3id.org/ontouml-models/model/example-model/> a dcat:Dataset, mod:SemanticArtefact ;
    dct:title "Example Model" ;
    dct:issued "2024"^^xsd:gYear ;
    dct:license <https://creativecommons.org/licenses/by/4.0/> .
""".strip(),
        encoding="utf-8",
    )


def graph_for(path: Path) -> Graph:
    graph = Graph()
    graph.parse(path)
    return graph


def test_generates_metadata_for_new_and_original_diagrams_using_catalog_naming(tmp_path: Path) -> None:
    dataset = tmp_path / "models" / "example-model"
    (dataset / "new-diagrams").mkdir(parents=True)
    (dataset / "original-diagrams").mkdir()
    write_metadata(dataset / "metadata.ttl")
    write_png(dataset / "new-diagrams" / "diagram-1.png")
    write_png(dataset / "original-diagrams" / "source diagram.png")

    generated = process_dataset(
        dataset,
        Config(repository="OntoUML/ontouml-models", branch="master", metadata_timestamp=FIXED_TIMESTAMP),
    )

    generated_paths = {item.metadata_path.name for item in generated}
    assert generated_paths == {
        "metadata-png-n-diagram-1.ttl",
        "metadata-png-o-source diagram.ttl",
    }


def test_generated_png_metadata_matches_existing_distribution_file_pattern(tmp_path: Path) -> None:
    """Check PNG metadata against the RDF pattern used by existing catalog distributions.

    Existing files such as metadata-json.ttl, metadata-turtle.ttl, and
    metadata-vpp.ttl use dct:isPartOf, dct:issued, dct:license, dct:title,
    dcat:mediaType, dcat:downloadURL, ocmv:isComplete, fdpo:metadataIssued,
    and fdpo:metadataModified. PNG generation must follow the same pattern, with
    image/png and ocmv:isComplete false.
    """

    dataset = tmp_path / "models" / "example-model"
    (dataset / "new-diagrams").mkdir(parents=True)
    write_metadata(dataset / "metadata.ttl")
    write_png(dataset / "new-diagrams" / "diagram-1.png")

    generated = process_dataset(
        dataset,
        Config(repository="OntoUML/ontouml-models", branch="master", metadata_timestamp=FIXED_TIMESTAMP),
    )
    assert len(generated) == 1

    graph = graph_for(dataset / "metadata-png-n-diagram-1.ttl")
    dist_uri = generated[0].distribution_uri
    expected_uuid = uuid.uuid5(
        uuid.NAMESPACE_URL,
        "https://w3id.org/ontouml-models/model/example-model|new-diagrams/diagram-1.png",
    )
    assert dist_uri == URIRef(f"https://w3id.org/ontouml-models/distribution/{expected_uuid}/")

    assert (dist_uri, RDF.type, DCAT.Distribution) in graph
    assert (dist_uri, DCT.isPartOf, URIRef("https://w3id.org/ontouml-models/model/example-model")) in graph
    assert (dist_uri, DCT.issued, Literal("2024", datatype=XSD.gYear)) in graph
    assert (dist_uri, DCAT.mediaType, URIRef("https://www.iana.org/assignments/media-types/image/png")) in graph
    assert (dist_uri, DCT.license, URIRef("https://creativecommons.org/licenses/by/4.0/")) in graph
    assert (
        dist_uri,
        DCT.title,
        Literal('PNG new diagram distribution of Example Model (diagram-1)', lang="en"),
    ) in graph
    assert (
        dist_uri,
        DCAT.downloadURL,
        URIRef(
            "https://raw.githubusercontent.com/OntoUML/ontouml-models/master/models/example-model/new-diagrams/diagram-1.png"
        ),
    ) in graph
    assert (dist_uri, OCMV.isComplete, Literal(False, datatype=XSD.boolean)) in graph
    assert (dist_uri, FDPO.metadataIssued, Literal(FIXED_TIMESTAMP, datatype=XSD.dateTime)) in graph
    assert (dist_uri, FDPO.metadataModified, Literal(FIXED_TIMESTAMP, datatype=XSD.dateTime)) in graph

    # Distribution files, not the model file, point back to the model. The model
    # metadata file remains the place where dcat:distribution links are maintained.
    assert (URIRef("https://w3id.org/ontouml-models/model/example-model"), DCAT.distribution, dist_uri) not in graph


def test_preserves_existing_distribution_uri_and_fdpo_timestamps(tmp_path: Path) -> None:
    dataset = tmp_path / "models" / "example-model"
    (dataset / "new-diagrams").mkdir(parents=True)
    write_metadata(dataset / "metadata.ttl")
    write_png(dataset / "new-diagrams" / "diagram-1.png")

    existing_dist = URIRef("https://w3id.org/ontouml-models/distribution/00000000-0000-0000-0000-000000000001/")
    (dataset / "metadata-png-n-diagram-1.ttl").write_text(
        f"""
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix fdpo: <https://w3id.org/fdp/fdp-o#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<{existing_dist}> a dcat:Distribution ;
    fdpo:metadataIssued "2023-01-01T00:00:00Z"^^xsd:dateTime ;
    fdpo:metadataModified "2023-01-02T00:00:00Z"^^xsd:dateTime .
""".strip(),
        encoding="utf-8",
    )

    generated = process_dataset(dataset, Config(metadata_timestamp=FIXED_TIMESTAMP))
    assert generated[0].distribution_uri == existing_dist

    graph = graph_for(dataset / "metadata-png-n-diagram-1.ttl")
    assert (existing_dist, FDPO.metadataIssued, Literal("2023-01-01T00:00:00Z", datatype=XSD.dateTime)) in graph
    assert (existing_dist, FDPO.metadataModified, Literal("2023-01-02T00:00:00Z", datatype=XSD.dateTime)) in graph


def test_rejects_invalid_png(tmp_path: Path) -> None:
    dataset = tmp_path / "models" / "example-model"
    (dataset / "new-diagrams").mkdir(parents=True)
    write_metadata(dataset / "metadata.ttl")
    (dataset / "new-diagrams" / "diagram-1.png").write_text("not a png", encoding="utf-8")

    with pytest.raises(MetadataGenerationError, match="invalid PNG"):
        process_dataset(dataset, Config())


def test_requires_model_issued_date(tmp_path: Path) -> None:
    dataset = tmp_path / "models" / "example-model"
    (dataset / "new-diagrams").mkdir(parents=True)
    write_png(dataset / "new-diagrams" / "diagram-1.png")
    (dataset / "metadata.ttl").write_text(
        """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix mod: <https://w3id.org/mod#> .

<https://w3id.org/ontouml-models/model/example-model/> a dcat:Dataset, mod:SemanticArtefact ;
    dct:title "Example Model" ;
    dct:license <https://creativecommons.org/licenses/by/4.0/> .
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(MetadataGenerationError, match="dct:issued"):
        process_dataset(dataset, Config())


def test_requires_model_license(tmp_path: Path) -> None:
    dataset = tmp_path / "models" / "example-model"
    (dataset / "new-diagrams").mkdir(parents=True)
    write_png(dataset / "new-diagrams" / "diagram-1.png")
    (dataset / "metadata.ttl").write_text(
        """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix mod: <https://w3id.org/mod#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://w3id.org/ontouml-models/model/example-model/> a dcat:Dataset, mod:SemanticArtefact ;
    dct:title "Example Model" ;
    dct:issued "2024"^^xsd:gYear .
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(MetadataGenerationError, match="dct:license"):
        process_dataset(dataset, Config())


def test_does_not_partially_write_when_later_diagram_is_invalid(tmp_path: Path) -> None:
    dataset = tmp_path / "models" / "example-model"
    (dataset / "new-diagrams").mkdir(parents=True)
    write_metadata(dataset / "metadata.ttl")
    write_png(dataset / "new-diagrams" / "diagram-1.png")
    (dataset / "new-diagrams" / "diagram-2.png").write_text("not a png", encoding="utf-8")

    with pytest.raises(MetadataGenerationError, match="invalid PNG"):
        process_dataset(dataset, Config())

    assert not (dataset / "metadata-png-n-diagram-1.ttl").exists()


def test_strict_mode_does_not_partially_write_when_folder_is_missing(tmp_path: Path) -> None:
    dataset = tmp_path / "models" / "example-model"
    (dataset / "new-diagrams").mkdir(parents=True)
    write_metadata(dataset / "metadata.ttl")
    write_png(dataset / "new-diagrams" / "diagram-1.png")

    with pytest.raises(MetadataGenerationError, match="Strict mode failed"):
        process_dataset(dataset, Config(strict=True))

    assert not (dataset / "metadata-png-n-diagram-1.ttl").exists()


def test_no_overwrite_is_atomic_for_existing_later_target(tmp_path: Path) -> None:
    dataset = tmp_path / "models" / "example-model"
    (dataset / "new-diagrams").mkdir(parents=True)
    write_metadata(dataset / "metadata.ttl")
    write_png(dataset / "new-diagrams" / "diagram-1.png")
    write_png(dataset / "new-diagrams" / "diagram-2.png")
    (dataset / "metadata-png-n-diagram-2.ttl").write_text("existing", encoding="utf-8")

    with pytest.raises(MetadataGenerationError, match="overwrite is disabled"):
        process_dataset(dataset, Config(overwrite=False))

    assert not (dataset / "metadata-png-n-diagram-1.ttl").exists()
    assert (dataset / "metadata-png-n-diagram-2.ttl").read_text(encoding="utf-8") == "existing"


def test_rejects_truncated_png_with_valid_signature_and_ihdr(tmp_path: Path) -> None:
    dataset = tmp_path / "models" / "example-model"
    (dataset / "new-diagrams").mkdir(parents=True)
    write_metadata(dataset / "metadata.ttl")
    # Signature + IHDR chunk only; lacks IEND and should be rejected as truncated.
    path = dataset / "new-diagrams" / "diagram-1.png"
    ihdr_data = struct.pack(">IIBBBBB", 2, 3, 8, 2, 0, 0, 0)
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_chunk = (
        struct.pack(">I", len(ihdr_data))
        + b"IHDR"
        + ihdr_data
        + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF)
    )
    path.write_bytes(signature + ihdr_chunk)

    with pytest.raises(MetadataGenerationError, match="truncated PNG"):
        process_dataset(dataset, Config())


def test_rejects_invalid_metadata_timestamp(tmp_path: Path) -> None:
    dataset = tmp_path / "models" / "example-model"
    (dataset / "new-diagrams").mkdir(parents=True)
    write_metadata(dataset / "metadata.ttl")
    write_png(dataset / "new-diagrams" / "diagram-1.png")

    with pytest.raises(MetadataGenerationError, match="metadata-timestamp"):
        process_dataset(dataset, Config(metadata_timestamp="not-a-date"))

    assert not (dataset / "metadata-png-n-diagram-1.ttl").exists()


def test_include_file_metadata_emits_dimensions_size_and_checksum(tmp_path: Path) -> None:
    dataset = tmp_path / "models" / "example-model"
    (dataset / "new-diagrams").mkdir(parents=True)
    write_metadata(dataset / "metadata.ttl")
    png_path = dataset / "new-diagrams" / "diagram-1.png"
    write_png(png_path, width=7, height=11)

    generated = process_dataset(
        dataset,
        Config(metadata_timestamp=FIXED_TIMESTAMP, include_file_metadata=True),
    )
    graph = graph_for(dataset / "metadata-png-n-diagram-1.ttl")
    dist_uri = generated[0].distribution_uri

    byte_sizes = list(graph.objects(dist_uri, DCAT.byteSize))
    assert len(byte_sizes) == 1
    assert byte_sizes[0].toPython() == Decimal(png_path.stat().st_size)
    assert (dist_uri, URIRef("https://schema.org/width"), Literal(7, datatype=XSD.integer)) in graph
    assert (dist_uri, URIRef("https://schema.org/height"), Literal(11, datatype=XSD.integer)) in graph


def test_nested_models_dir_name_is_encoded_as_path_segments(tmp_path: Path) -> None:
    dataset = tmp_path / "catalog-data" / "models" / "example-model"
    (dataset / "new-diagrams").mkdir(parents=True)
    write_metadata(dataset / "metadata.ttl")
    write_png(dataset / "new-diagrams" / "diagram 1.png")

    generated = process_dataset(
        dataset,
        Config(models_dir_name="catalog-data/models", metadata_timestamp=FIXED_TIMESTAMP),
    )
    graph = graph_for(dataset / "metadata-png-n-diagram 1.ttl")
    dist_uri = generated[0].distribution_uri

    assert (
        dist_uri,
        DCAT.downloadURL,
        URIRef(
            "https://raw.githubusercontent.com/OntoUML/ontouml-models/master/catalog-data/models/example-model/new-diagrams/diagram%201.png"
        ),
    ) in graph

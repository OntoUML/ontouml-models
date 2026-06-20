from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "generate_metadata_turtle.py"
spec = importlib.util.spec_from_file_location("generate_metadata_turtle", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

DCAT = module.DCAT
DCT = module.DCT
FDPO = module.FDPO
OCMV = module.OCMV

MODEL_URI_WITH_SLASH = URIRef("https://w3id.org/ontouml-models/model/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/")
MODEL_URI = URIRef("https://w3id.org/ontouml-models/model/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
LICENSE = URIRef("https://creativecommons.org/licenses/by/4.0/")


def make_dataset(tmp_path: Path) -> Path:
    dataset_dir = tmp_path / "models" / "example-model"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "ontology.ttl").write_text(
        """@prefix ontouml: <https://w3id.org/ontouml#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
<https://example.org/project> rdf:type ontouml:Project .
""",
        encoding="utf-8",
    )
    (dataset_dir / "metadata.ttl").write_text(
        """@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix mod: <https://w3id.org/mod#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://w3id.org/ontouml-models/model/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/>
    a dcat:Dataset, mod:SemanticArtefact ;
    dct:title "Example Model" ;
    dct:issued "2024"^^xsd:gYear ;
    dct:license <https://creativecommons.org/licenses/by/4.0/> .
""",
        encoding="utf-8",
    )
    return dataset_dir


def parse_output(dataset_dir: Path) -> tuple[Graph, URIRef]:
    graph = Graph()
    graph.parse(dataset_dir / "metadata-turtle.ttl", format="turtle")
    distributions = list(graph.subjects(RDF.type, DCAT.Distribution))
    assert len(distributions) == 1
    return graph, distributions[0]


def test_generate_metadata_turtle(tmp_path: Path):
    dataset_dir = make_dataset(tmp_path)

    result = module.generate_metadata_turtle(
        dataset_dir,
        repo_root=tmp_path,
        raw_base_url="https://raw.githubusercontent.com/OntoUML/ontouml-models/master",
    )

    assert result.wrote_file is True
    graph, distribution = parse_output(dataset_dir)

    assert (distribution, DCT.isPartOf, MODEL_URI) in graph
    assert (distribution, DCT.issued, Literal("2024", datatype=XSD.gYear)) in graph
    assert (distribution, DCT.license, LICENSE) in graph
    assert (distribution, DCAT.mediaType, module.IANA_TURTLE_MEDIA_TYPE) in graph
    assert (distribution, DCT.title, Literal("Turtle distribution of Example Model", lang="en")) in graph
    assert (
        distribution,
        DCAT.downloadURL,
        URIRef("https://raw.githubusercontent.com/OntoUML/ontouml-models/master/models/example-model/ontology.ttl"),
    ) in graph
    assert (distribution, OCMV.isComplete, Literal(True, datatype=XSD.boolean)) in graph
    assert len(list(graph.objects(distribution, FDPO.metadataIssued))) == 1
    assert len(list(graph.objects(distribution, FDPO.metadataModified))) == 1


def test_reuse_existing_distribution_uri_and_metadata_issued(tmp_path: Path):
    dataset_dir = make_dataset(tmp_path)
    existing_distribution = URIRef("https://w3id.org/ontouml-models/distribution/existing/")
    existing_issued = Literal("2023-01-01T00:00:00Z", datatype=XSD.dateTime)
    (dataset_dir / "metadata-turtle.ttl").write_text(
        """@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix fdpo: <https://w3id.org/fdp/fdp-o#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://w3id.org/ontouml-models/distribution/existing/>
    a dcat:Distribution ;
    fdpo:metadataIssued "2023-01-01T00:00:00Z"^^xsd:dateTime .
""",
        encoding="utf-8",
    )

    result = module.generate_metadata_turtle(dataset_dir, repo_root=tmp_path, overwrite=True)

    assert result.distribution_uri == existing_distribution
    graph, distribution = parse_output(dataset_dir)
    assert distribution == existing_distribution
    assert (distribution, FDPO.metadataIssued, existing_issued) in graph


def test_missing_ontology_ttl_fails(tmp_path: Path):
    dataset_dir = make_dataset(tmp_path)
    (dataset_dir / "ontology.ttl").unlink()

    with pytest.raises(module.CatalogMetadataError, match="Missing ontology.ttl"):
        module.generate_metadata_turtle(dataset_dir, repo_root=tmp_path)


def test_invalid_ontology_ttl_fails(tmp_path: Path):
    dataset_dir = make_dataset(tmp_path)
    (dataset_dir / "ontology.ttl").write_text("not valid turtle", encoding="utf-8")

    with pytest.raises(module.CatalogMetadataError, match="Invalid Turtle"):
        module.generate_metadata_turtle(dataset_dir, repo_root=tmp_path)


def test_update_model_metadata_adds_distribution_link(tmp_path: Path):
    dataset_dir = make_dataset(tmp_path)

    result = module.generate_metadata_turtle(
        dataset_dir,
        repo_root=tmp_path,
        update_model_metadata=True,
    )

    assert result.updated_model_metadata is True
    graph = Graph()
    graph.parse(dataset_dir / "metadata.ttl", format="turtle")
    assert (MODEL_URI, DCAT.distribution, result.distribution_uri) in graph


def test_multiple_issued_values_fail(tmp_path: Path):
    dataset_dir = make_dataset(tmp_path)
    (dataset_dir / "metadata.ttl").write_text(
        """@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix mod: <https://w3id.org/mod#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://w3id.org/ontouml-models/model/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/>
    a dcat:Dataset, mod:SemanticArtefact ;
    dct:title "Example Model" ;
    dct:issued "2024"^^xsd:gYear, "2024-01-01"^^xsd:date ;
    dct:license <https://creativecommons.org/licenses/by/4.0/> .
""",
        encoding="utf-8",
    )

    with pytest.raises(module.CatalogMetadataError, match="Expected exactly one dct:issued"):
        module.generate_metadata_turtle(dataset_dir, repo_root=tmp_path)


def test_issued_with_unsupported_datatype_fails(tmp_path: Path):
    dataset_dir = make_dataset(tmp_path)
    (dataset_dir / "metadata.ttl").write_text(
        """@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix mod: <https://w3id.org/mod#> .

<https://w3id.org/ontouml-models/model/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/>
    a dcat:Dataset, mod:SemanticArtefact ;
    dct:title "Example Model" ;
    dct:issued "2024" ;
    dct:license <https://creativecommons.org/licenses/by/4.0/> .
""",
        encoding="utf-8",
    )

    with pytest.raises(module.CatalogMetadataError, match="Expected dct:issued"):
        module.generate_metadata_turtle(dataset_dir, repo_root=tmp_path)


def test_multiple_existing_metadata_issued_values_fail(tmp_path: Path):
    dataset_dir = make_dataset(tmp_path)
    (dataset_dir / "metadata-turtle.ttl").write_text(
        """@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix fdpo: <https://w3id.org/fdp/fdp-o#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://w3id.org/ontouml-models/distribution/existing/>
    a dcat:Distribution ;
    fdpo:metadataIssued "2023-01-01T00:00:00Z"^^xsd:dateTime,
                        "2023-01-02T00:00:00Z"^^xsd:dateTime .
""",
        encoding="utf-8",
    )

    with pytest.raises(module.CatalogMetadataError, match="Expected at most one fdpo:metadataIssued"):
        module.generate_metadata_turtle(dataset_dir, repo_root=tmp_path, overwrite=True)

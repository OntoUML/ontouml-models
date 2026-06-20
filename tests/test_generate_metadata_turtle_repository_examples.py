from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "generate_metadata_turtle.py"
spec = importlib.util.spec_from_file_location("generate_metadata_turtle", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

DCAT = module.DCAT
FDPO = module.FDPO


def write_amaral2019rot_example(repo_root: Path) -> Path:
    """Create a small fixture from the real OntoUML/ontouml-models example.

    The metadata.ttl and metadata-turtle.ttl contents are copied from the
    upstream `models/amaral2019rot` dataset. ontology.ttl is reduced to a valid
    excerpt because the generator only validates that it exists and parses as
    non-empty Turtle; it does not derive metadata values from ontology content.
    """

    dataset_dir = repo_root / "models" / "amaral2019rot"
    dataset_dir.mkdir(parents=True)

    (dataset_dir / "metadata.ttl").write_text(
        """@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
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
    <https://w3id.org/ontouml-models/model/d88fe48c-d574-43b4-85d6-a6e1aeaa6726> dcat:distribution <https://w3id.org/ontouml-models/distribution/78713112-cf7e-45f1-8c74-c7b5906f5b7c/>, <https://w3id.org/ontouml-models/distribution/7c83f03b-c170-49d2-9dd9-0a600be6cc96/> .
""",
        encoding="utf-8",
    )

    (dataset_dir / "ontology.ttl").write_text(
        """@prefix : <https://w3id.org/ontouml-models/model/amaral2019rot#>.
@prefix ontouml: <https://w3id.org/ontouml#>.
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
@prefix owl: <http://www.w3.org/2002/07/owl#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

<https://w3id.org/ontouml-models/model/amaral2019rot/> rdf:type ontouml:Project;
    ontouml:name "Reference Ontology of Trust"@en;
    ontouml:model :Nlnret6GAqACCgBO_root;
    ontouml:diagram :gygbet6GAqACCgWz .
""",
        encoding="utf-8",
    )

    expected = """@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
@prefix ocmv: <https://w3id.org/ontouml-models/vocabulary#>.
@prefix owl: <http://www.w3.org/2002/07/owl#>.
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
@prefix skos: <http://www.w3.org/2004/02/skos/core#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

<https://w3id.org/ontouml-models/distribution/78713112-cf7e-45f1-8c74-c7b5906f5b7c/> a dcat:Distribution;
    dct:isPartOf <https://w3id.org/ontouml-models/model/d88fe48c-d574-43b4-85d6-a6e1aeaa6726>;
    dct:issued "2019"^^xsd:gYear;
    dcat:mediaType <https://www.iana.org/assignments/media-types/text/turtle>;
    dct:license <https://creativecommons.org/licenses/by/4.0/>;
    dct:title "Turtle distribution of Reference Ontology of Trust"@en;
    dcat:downloadURL <https://raw.githubusercontent.com/OntoUML/ontouml-models/master/models/amaral2019rot/ontology.ttl>;
    ocmv:isComplete "true"^^xsd:boolean;
    fdpo:metadataIssued "2023-04-14T17:35:46.015703026Z"^^xsd:dateTime;
    fdpo:metadataModified "2023-04-14T17:35:46.015703026Z"^^xsd:dateTime .
"""
    (dataset_dir / "metadata-turtle.expected.ttl").write_text(expected, encoding="utf-8")
    (dataset_dir / "metadata-turtle.ttl").write_text(expected, encoding="utf-8")

    return dataset_dir


def graph_without_metadata_modified(path: Path) -> Graph:
    graph = Graph().parse(path, format="turtle")
    normalized = Graph()
    for triple in graph:
        if triple[1] != FDPO.metadataModified:
            normalized.add(triple)
    return normalized


def test_generated_metadata_turtle_matches_existing_amaral2019rot_example(tmp_path: Path):
    dataset_dir = write_amaral2019rot_example(tmp_path)

    result = module.generate_metadata_turtle(dataset_dir, repo_root=tmp_path, overwrite=True)

    assert result.distribution_uri == URIRef(
        "https://w3id.org/ontouml-models/distribution/78713112-cf7e-45f1-8c74-c7b5906f5b7c/"
    )
    actual = graph_without_metadata_modified(dataset_dir / "metadata-turtle.ttl")
    expected = graph_without_metadata_modified(dataset_dir / "metadata-turtle.expected.ttl")
    assert actual.isomorphic(expected)

    generated_full = Graph().parse(dataset_dir / "metadata-turtle.ttl", format="turtle")
    distributions = list(generated_full.subjects(RDF.type, DCAT.Distribution))
    assert len(distributions) == 1
    assert len(list(generated_full.objects(distributions[0], FDPO.metadataModified))) == 1

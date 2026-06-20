from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import DCTERMS, RDF, XSD

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ontouml_models_automation.metadata_json import (  # noqa: E402
    DCAT,
    FDPO,
    OCMV,
    InvalidFieldValueError,
    MetadataJsonConfig,
    MissingMandatoryFieldError,
    generate_metadata_json_ttl,
)


def copy_fixture(tmp_path: Path) -> Path:
    source = Path(__file__).parent / "fixtures" / "models" / "example-model"
    target = tmp_path / "models" / "example-model"
    shutil.copytree(source, target)
    return target


def test_generate_metadata_json_ttl(tmp_path: Path) -> None:
    dataset = copy_fixture(tmp_path)
    fixed_timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc)

    output = generate_metadata_json_ttl(
        dataset,
        MetadataJsonConfig(metadata_timestamp=fixed_timestamp),
    )

    assert output.name == "metadata-json.ttl"
    graph = Graph().parse(output, format="turtle")

    distribution = URIRef(
        "https://w3id.org/ontouml-models/distribution/7c83f03b-c170-49d2-9dd9-0a600be6cc96/"
    )
    model = URIRef("https://w3id.org/ontouml-models/model/d88fe48c-d574-43b4-85d6-a6e1aeaa6726")

    assert (distribution, RDF.type, DCAT.Distribution) in graph
    assert (distribution, DCTERMS.isPartOf, model) in graph
    assert (distribution, DCAT.mediaType, URIRef("https://www.iana.org/assignments/media-types/application/json")) in graph
    assert (distribution, DCTERMS.license, URIRef("https://creativecommons.org/licenses/by/4.0/")) in graph
    assert (distribution, OCMV.conformsToSchema, URIRef("https://w3id.org/ontouml/schema")) in graph
    assert (distribution, OCMV.isComplete, None) in graph
    assert (distribution, FDPO.metadataIssued, None) in graph
    assert (distribution, FDPO.metadataModified, None) in graph

    issued_values = list(graph.objects(distribution, DCTERMS.issued))
    assert len(issued_values) == 1
    assert issued_values[0].datatype == XSD.gYear
    assert str(issued_values[0]) == "2019"


def test_missing_distribution_id_fails_by_default(tmp_path: Path) -> None:
    dataset = copy_fixture(tmp_path)
    metadata_path = dataset / "metadata.yaml"
    metadata_path.write_text(
        """
model:
  id: d88fe48c-d574-43b4-85d6-a6e1aeaa6726
  title: Reference Ontology of Trust
  issued: 2019
  license: https://creativecommons.org/licenses/by/4.0/
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(MissingMandatoryFieldError):
        generate_metadata_json_ttl(dataset, MetadataJsonConfig())


def test_invalid_json_media_type_is_rejected(tmp_path: Path) -> None:
    dataset = copy_fixture(tmp_path)
    metadata_path = dataset / "metadata.yaml"
    metadata_path.write_text(
        """
model:
  id: d88fe48c-d574-43b4-85d6-a6e1aeaa6726
  title: Reference Ontology of Trust
  issued: 2019
  license: https://creativecommons.org/licenses/by/4.0/

distributions:
  json:
    id: 7c83f03b-c170-49d2-9dd9-0a600be6cc96
    media_type: https://www.iana.org/assignments/media-types/text/turtle
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(InvalidFieldValueError):
        generate_metadata_json_ttl(dataset, MetadataJsonConfig())


def test_string_true_is_complete_is_accepted(tmp_path: Path) -> None:
    dataset = copy_fixture(tmp_path)
    metadata_path = dataset / "metadata.yaml"
    metadata_path.write_text(
        """
model:
  id: d88fe48c-d574-43b4-85d6-a6e1aeaa6726
  title: Reference Ontology of Trust
  issued: 2019
  license: https://creativecommons.org/licenses/by/4.0/

distributions:
  json:
    id: 7c83f03b-c170-49d2-9dd9-0a600be6cc96
    is_complete: "true"
""".strip(),
        encoding="utf-8",
    )

    output = generate_metadata_json_ttl(dataset, MetadataJsonConfig())
    assert output.is_file()


def test_string_false_is_complete_is_rejected(tmp_path: Path) -> None:
    dataset = copy_fixture(tmp_path)
    metadata_path = dataset / "metadata.yaml"
    metadata_path.write_text(
        """
model:
  id: d88fe48c-d574-43b4-85d6-a6e1aeaa6726
  title: Reference Ontology of Trust
  issued: 2019
  license: https://creativecommons.org/licenses/by/4.0/

distributions:
  json:
    id: 7c83f03b-c170-49d2-9dd9-0a600be6cc96
    is_complete: "false"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(InvalidFieldValueError):
        generate_metadata_json_ttl(dataset, MetadataJsonConfig())


def test_amaral2019rot_repository_example_graph_matches_expected(tmp_path: Path) -> None:
    """Golden test based on existing catalog files for models/amaral2019rot.

    The current repository does not contain metadata.yaml files, so this test
    uses a minimal YAML source reconstructed from the existing model metadata
    and JSON distribution metadata, then compares the generated RDF graph with
    the existing metadata-json.ttl graph.
    """

    dataset = tmp_path / "models" / "amaral2019rot"
    dataset.mkdir(parents=True)
    (dataset / "ontology.json").write_text("{}\n", encoding="utf-8")
    (dataset / "metadata.yaml").write_text(
        """
model:
  id: d88fe48c-d574-43b4-85d6-a6e1aeaa6726
  title: Reference Ontology of Trust
  issued: 2019
  license: https://creativecommons.org/licenses/by/4.0/

distributions:
  json:
    id: 7c83f03b-c170-49d2-9dd9-0a600be6cc96
    metadata_issued: 2023-04-14T17:35:29.862157131Z
    metadata_modified: 2023-04-14T17:35:29.862157131Z
""".strip()
        + "\n",
        encoding="utf-8",
    )

    output = generate_metadata_json_ttl(dataset, MetadataJsonConfig())
    generated = Graph().parse(output, format="turtle")

    expected_ttl = """
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
    expected = Graph().parse(data=expected_ttl, format="turtle")

    assert generated.isomorphic(expected)


def test_full_model_uri_is_normalized_without_trailing_slash(tmp_path: Path) -> None:
    dataset = copy_fixture(tmp_path)
    metadata_path = dataset / "metadata.yaml"
    metadata_path.write_text(
        """
model:
  uri: https://w3id.org/ontouml-models/model/d88fe48c-d574-43b4-85d6-a6e1aeaa6726/
  title: Reference Ontology of Trust
  issued: 2019
  license: https://creativecommons.org/licenses/by/4.0/

distributions:
  json:
    uri: https://w3id.org/ontouml-models/distribution/7c83f03b-c170-49d2-9dd9-0a600be6cc96
""".strip(),
        encoding="utf-8",
    )

    output = generate_metadata_json_ttl(dataset, MetadataJsonConfig())
    graph = Graph().parse(output, format="turtle")

    distribution = URIRef(
        "https://w3id.org/ontouml-models/distribution/7c83f03b-c170-49d2-9dd9-0a600be6cc96/"
    )
    model = URIRef("https://w3id.org/ontouml-models/model/d88fe48c-d574-43b4-85d6-a6e1aeaa6726")
    assert (distribution, DCTERMS.isPartOf, model) in graph

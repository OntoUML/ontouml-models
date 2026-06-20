import sys
import unittest
from pathlib import Path

from rdflib import Graph, URIRef

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from metadata_yaml_to_ttl import DCAT, build_graph, read_yaml  # noqa: E402


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
AMARAL_SUBJECT = URIRef("https://w3id.org/ontouml-models/model/d88fe48c-d574-43b4-85d6-a6e1aeaa6726/")


class RepositoryMetadataExampleTests(unittest.TestCase):
    """Regression tests derived from metadata.ttl examples already in the catalog.

    The repository does not currently contain metadata.yaml examples. This test
    therefore uses an equivalent YAML fixture for a real catalog target file and
    verifies semantic parity for model-level metadata triples.
    """

    def test_amaral2019rot_yaml_generates_existing_model_metadata_triples(self):
        target = Graph()
        target.parse(FIXTURE_DIR / "amaral2019rot.metadata.ttl", format="turtle")

        yaml_data = read_yaml(FIXTURE_DIR / "amaral2019rot.metadata.yaml")
        generated_raw, warnings = build_graph(yaml_data, Path("models/amaral2019rot"))

        self.assertEqual(warnings, ())

        # RDFLib normalizes xsd:dateTime values when parsing Turtle. The
        # generated graph intentionally keeps existing timestamp lexical forms
        # before serialization, so round-trip it here to compare RDF semantics
        # rather than lexical form. Lexical preservation is covered by a
        # separate unit test.
        generated = Graph()
        generated.parse(
            data=generated_raw.serialize(format="turtle", encoding=None),
            format="turtle",
        )

        target_model_triples = {
            triple
            for triple in target.triples((AMARAL_SUBJECT, None, None))
            if triple[1] != DCAT.distribution
        }
        generated_model_triples = {
            triple
            for triple in generated.triples((AMARAL_SUBJECT, None, None))
            if triple[1] != DCAT.distribution
        }

        self.assertEqual(target_model_triples, generated_model_triples)


if __name__ == "__main__":
    unittest.main()

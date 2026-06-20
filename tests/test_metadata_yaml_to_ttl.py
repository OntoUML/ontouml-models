import tempfile
import unittest
from pathlib import Path

from rdflib import Graph, Literal, Namespace, RDF, URIRef
from rdflib.namespace import XSD

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from metadata_yaml_to_ttl import (  # noqa: E402
    CONTEXT,
    DCAT,
    DCT,
    LCC,
    MOD,
    OCMV,
    MetadataError,
    build_graph,
    convert_yaml_file,
    read_yaml,
)


class MetadataYamlToTtlTests(unittest.TestCase):
    def test_minimal_yaml_generates_expected_dataset_metadata(self):
        data = {
            "title": "Reference Ontology of Trust",
            "issued": "2019",
            "license": "https://creativecommons.org/licenses/by/4.0/",
            "theme": "H",
            "keywords": [{"value": "trust", "lang": "en"}],
        }
        graph, warnings = build_graph(data, Path("models/amaral2019rot"))
        subject = URIRef("https://w3id.org/ontouml-models/model/amaral2019rot/")

        self.assertIn((subject, RDF.type, DCAT.Dataset), graph)
        self.assertIn((subject, RDF.type, MOD.SemanticArtefact), graph)
        self.assertIn((subject, RDF.type, DCAT.Resource), graph)
        self.assertIn((subject, DCT.title, Literal("Reference Ontology of Trust")), graph)
        self.assertIn((subject, DCT.issued, Literal("2019", datatype=XSD.gYear)), graph)
        self.assertIn((subject, DCT.license, URIRef("https://creativecommons.org/licenses/by/4.0/")), graph)
        self.assertIn((subject, DCAT.theme, LCC.H), graph)
        self.assertIn((subject, DCAT.keyword, Literal("trust", lang="en")), graph)
        self.assertIn("Recommended field 'language' is missing.", warnings)

    def test_explicit_iri_and_controlled_values(self):
        subject = URIRef("https://w3id.org/ontouml-models/model/d88fe48c-d574-43b4-85d6-a6e1aeaa6726/")
        data = {
            "iri": str(subject),
            "title": {"value": "Reference Ontology of Trust", "lang": "en"},
            "issued": "2019",
            "modified": "2022",
            "license": "https://creativecommons.org/licenses/by/4.0/",
            "theme": "lcc:H",
            "keywords": ["trust"],
            "language": "en",
            "designed_for_task": ["conceptual clarification"],
            "context": ["ocmv:Research"],
            "representation_style": ["OntoumlStyle"],
            "ontology_type": ["Domain"],
            "source": ["https://doi.org/10.1007/example"],
        }
        graph, warnings = build_graph(data, Path("models/amaral2019rot"))

        self.assertEqual(warnings, ())
        self.assertIn((subject, DCT.title, Literal("Reference Ontology of Trust", lang="en")), graph)
        self.assertIn((subject, DCT.modified, Literal("2022", datatype=XSD.gYear)), graph)
        self.assertIn((subject, MOD.designedForTask, OCMV.ConceptualClarification), graph)
        self.assertIn((subject, OCMV.context, CONTEXT["Research"]), graph)
        self.assertIn((subject, OCMV.representationStyle, OCMV.OntoumlStyle), graph)
        self.assertIn((subject, OCMV.ontologyType, OCMV.Domain), graph)
        self.assertIn((subject, DCT.source, URIRef("https://doi.org/10.1007/example")), graph)

    def test_missing_required_field_raises_error(self):
        data = {
            "title": "Incomplete model",
            "issued": "2019",
            "license": "https://creativecommons.org/licenses/by/4.0/",
            "theme": "H",
        }
        with self.assertRaises(MetadataError) as context:
            build_graph(data, Path("models/incomplete"))
        self.assertIn("keyword", str(context.exception))

    def test_invalid_controlled_value_raises_error(self):
        data = {
            "title": "Invalid model",
            "issued": "2019",
            "license": "https://creativecommons.org/licenses/by/4.0/",
            "theme": "H",
            "keywords": ["invalid"],
            "context": ["Laboratory"],
        }
        with self.assertRaises(MetadataError) as context:
            build_graph(data, Path("models/invalid"))
        self.assertIn("Unsupported value for 'context'", str(context.exception))


    def test_invalid_uri_scheme_raises_error(self):
        data = {
            "title": "Invalid URI model",
            "issued": "2019",
            "license": "mailto:not-a-license@example.org",
            "theme": "H",
            "keywords": ["invalid"],
        }
        with self.assertRaises(MetadataError) as context:
            build_graph(data, Path("models/invalid-uri"))
        self.assertIn("Field 'license' must be an absolute URI using", str(context.exception))

    def test_invalid_calendar_date_raises_error(self):
        data = {
            "title": "Invalid date model",
            "issued": "2024-13-01",
            "license": "https://creativecommons.org/licenses/by/4.0/",
            "theme": "H",
            "keywords": ["invalid"],
        }
        with self.assertRaises(MetadataError) as context:
            build_graph(data, Path("models/invalid-date"))
        self.assertIn("Invalid calendar date", str(context.exception))

    def test_duplicate_title_language_raises_error(self):
        data = {
            "title": [
                {"value": "First title", "lang": "en"},
                {"value": "Second title", "lang": "en"},
            ],
            "issued": "2019",
            "license": "https://creativecommons.org/licenses/by/4.0/",
            "theme": "H",
            "keywords": ["invalid"],
        }
        with self.assertRaises(MetadataError) as context:
            build_graph(data, Path("models/duplicate-title"))
        self.assertIn("at most one value per language", str(context.exception))

    def test_unknown_top_level_key_generates_warning(self):
        data = {
            "title": "Unknown key model",
            "issued": "2019",
            "license": "https://creativecommons.org/licenses/by/4.0/",
            "theme": "H",
            "keywords": ["example"],
            "unkown_typo": "value",
        }
        _graph, warnings = build_graph(data, Path("models/unknown-key"))
        self.assertTrue(any("unkown_typo" in warning for warning in warnings))


    def test_yaml_loader_preserves_timestamp_lexical_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            yaml_path = Path(tmp) / "metadata.yaml"
            yaml_path.write_text(
                "metadata_issued: 2023-04-14T17:35:28.608937306Z\n",
                encoding="utf-8",
            )

            data = read_yaml(yaml_path)

            self.assertEqual(data["metadata_issued"], "2023-04-14T17:35:28.608937306Z")

    def test_serialized_turtle_preserves_datetime_lexical_value(self):
        data = {
            "title": "Timestamp model",
            "issued": "2019",
            "license": "https://creativecommons.org/licenses/by/4.0/",
            "theme": "H",
            "keywords": ["timestamp"],
            "metadata_issued": "2023-04-14T17:35:28.608937306Z",
        }
        graph, _warnings = build_graph(data, Path("models/timestamp-model"))
        turtle = graph.serialize(format="turtle", encoding=None)

        self.assertIn(
            '"2023-04-14T17:35:28.608937306Z"^^xsd:dateTime',
            turtle,
        )

    def test_conversion_writes_parseable_turtle(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "models" / "example"
            folder.mkdir(parents=True)
            yaml_path = folder / "metadata.yaml"
            yaml_path.write_text(
                "\n".join(
                    [
                        "title: Example Model",
                        "issued: 2024",
                        "license: https://creativecommons.org/licenses/by/4.0/",
                        "theme: T",
                        "keywords:",
                        "  - value: example",
                        "    lang: en",
                        "language: en",
                    ]
                ),
                encoding="utf-8",
            )

            result = convert_yaml_file(
                yaml_path,
                output_name="metadata.ttl",
                overwrite=True,
                dry_run=False,
                model_iri_base="https://w3id.org/ontouml-models/model/",
                repository_url="https://github.com/OntoUML/ontouml-models",
                branch="master",
                add_default_storage_url=True,
            )

            self.assertTrue(result.ttl_path.exists())
            parsed = Graph()
            parsed.parse(result.ttl_path, format="turtle")
            subject = URIRef("https://w3id.org/ontouml-models/model/example/")
            self.assertIn((subject, DCAT.theme, LCC.T), parsed)


if __name__ == "__main__":
    unittest.main()

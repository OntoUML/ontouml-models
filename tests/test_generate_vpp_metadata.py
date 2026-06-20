from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

from rdflib import Graph, URIRef
from rdflib.namespace import RDF

# Allow importing the repository script when tests run from the repository root.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_vpp_metadata as gvm


class GenerateVppMetadataTest(TestCase):
    def test_generate_vpp_metadata_from_dataset_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "models" / "example2024model"
            dataset.mkdir(parents=True)
            (dataset / "ontology.vpp").write_bytes(b"fake-vpp-binary")
            (dataset / "metadata.ttl").write_text(
                """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix mod: <https://w3id.org/mod#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://w3id.org/ontouml-models/model/00000000-0000-0000-0000-000000000001/> a dcat:Dataset, mod:SemanticArtefact ;
    dct:title "Example Model" ;
    dct:issued "2024"^^xsd:gYear ;
    dct:license <https://creativecommons.org/licenses/by/4.0/> .
""",
                encoding="utf-8",
            )

            generated = gvm.generate_for_dataset(dataset, repository_root=root)

            expected_output_path = dataset / "metadata-vpp.ttl"
            self.assertTrue(generated.output_path.exists())
            self.assertTrue(
                generated.output_path.samefile(expected_output_path),
                f"{generated.output_path} does not refer to {expected_output_path}",
            )

            graph = Graph().parse(generated.output_path, format="turtle")
            distribution = generated.distribution_uri
            self.assertIn((distribution, RDF.type, gvm.DCAT.Distribution), graph)
            self.assertIn(
                (
                    distribution,
                    gvm.DCT.isPartOf,
                    URIRef("https://w3id.org/ontouml-models/model/00000000-0000-0000-0000-000000000001"),
                ),
                graph,
            )
            self.assertIn((distribution, gvm.DCAT.mediaType, gvm.OCTET_STREAM_URI), graph)
            self.assertIn((distribution, gvm.DCT["format"], gvm.VPP_FORMAT_URI), graph)
            self.assertIn((distribution, gvm.OCMV.isComplete, None), graph)
            self.assertIn((distribution, gvm.DCAT.byteSize, None), graph)
            self.assertIn((distribution, gvm.SPDX.checksum, None), graph)

    def test_missing_vpp_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "models" / "missingvpp"
            dataset.mkdir(parents=True)
            (dataset / "metadata.ttl").write_text("", encoding="utf-8")

            with self.assertRaises(gvm.VppMetadataError):
                gvm.generate_for_dataset(dataset, repository_root=root)

    def test_missing_license_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "models" / "missinglicense"
            dataset.mkdir(parents=True)
            (dataset / "ontology.vpp").write_bytes(b"fake-vpp-binary")
            (dataset / "metadata.ttl").write_text(
                """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix mod: <https://w3id.org/mod#> .

<https://w3id.org/ontouml-models/model/00000000-0000-0000-0000-000000000001/> a dcat:Dataset, mod:SemanticArtefact ;
    dct:title "Example Model" .
""",
                encoding="utf-8",
            )

            with self.assertRaises(gvm.VppMetadataError):
                gvm.generate_for_dataset(dataset, repository_root=root)


class GenerateVppMetadataRegressionTest(TestCase):
    def test_existing_distribution_uri_and_metadata_issued_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "models" / "existingvpp"
            dataset.mkdir(parents=True)
            (dataset / "ontology.vpp").write_bytes(b"fake-vpp-binary")
            (dataset / "metadata.ttl").write_text(
                """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix mod: <https://w3id.org/mod#> .

<https://w3id.org/ontouml-models/model/00000000-0000-0000-0000-000000000002/> a dcat:Dataset, mod:SemanticArtefact ;
    dct:title "Example Model" ;
    dct:license <https://creativecommons.org/licenses/by/4.0/> .
""",
                encoding="utf-8",
            )
            existing_uri = URIRef("https://w3id.org/ontouml-models/distribution/11111111-1111-1111-1111-111111111111/")
            (dataset / "metadata-vpp.ttl").write_text(
                f"""
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix fdpo: <https://w3id.org/fdp/fdp-o#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<{existing_uri}> a dcat:Distribution ;
    fdpo:metadataIssued "2024-01-01T00:00:00Z"^^xsd:dateTime .
""",
                encoding="utf-8",
            )

            generated = gvm.generate_for_dataset(dataset, repository_root=root)
            graph = Graph().parse(generated.output_path, format="turtle")

            self.assertEqual(generated.distribution_uri, existing_uri)
            self.assertIn((existing_uri, gvm.FDPO.metadataIssued, None), graph)
            self.assertIn((existing_uri, gvm.FDPO.metadataModified, None), graph)

    def test_empty_vpp_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "models" / "emptyvpp"
            dataset.mkdir(parents=True)
            (dataset / "ontology.vpp").write_bytes(b"")
            (dataset / "metadata.ttl").write_text(
                """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix mod: <https://w3id.org/mod#> .

<https://w3id.org/ontouml-models/model/00000000-0000-0000-0000-000000000003/> a dcat:Dataset, mod:SemanticArtefact ;
    dct:title "Example Model" ;
    dct:license <https://creativecommons.org/licenses/by/4.0/> .
""",
                encoding="utf-8",
            )

            with self.assertRaises(gvm.VppMetadataError):
                gvm.generate_for_dataset(dataset, repository_root=root)

    def test_prefer_english_title_when_multiple_titles_are_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "models" / "multilangtitle"
            dataset.mkdir(parents=True)
            (dataset / "ontology.vpp").write_bytes(b"fake-vpp-binary")
            (dataset / "metadata.ttl").write_text(
                """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix mod: <https://w3id.org/mod#> .

<https://w3id.org/ontouml-models/model/00000000-0000-0000-0000-000000000004/> a dcat:Dataset, mod:SemanticArtefact ;
    dct:title "Modelo de Exemplo"@pt, "Example Model"@en ;
    dct:license <https://creativecommons.org/licenses/by/4.0/> .
""",
                encoding="utf-8",
            )

            generated = gvm.generate_for_dataset(dataset, repository_root=root)
            graph = Graph().parse(generated.output_path, format="turtle")
            titles = list(graph.objects(generated.distribution_uri, gvm.DCT.title))

            self.assertEqual([str(value) for value in titles], ["Visual Paradigm distribution of Example Model"])
            self.assertEqual(titles[0].language, "en")

    def test_distribution_title_is_english_even_when_source_title_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "models" / "portuguesetitle"
            dataset.mkdir(parents=True)
            (dataset / "ontology.vpp").write_bytes(b"fake-vpp-binary")
            (dataset / "metadata.ttl").write_text(
                """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix mod: <https://w3id.org/mod#> .

<https://w3id.org/ontouml-models/model/00000000-0000-0000-0000-000000000005/> a dcat:Dataset, mod:SemanticArtefact ;
    dct:title "Modelo de Exemplo"@pt ;
    dct:license <https://creativecommons.org/licenses/by/4.0/> .
""",
                encoding="utf-8",
            )

            generated = gvm.generate_for_dataset(dataset, repository_root=root)
            graph = Graph().parse(generated.output_path, format="turtle")
            titles = list(graph.objects(generated.distribution_uri, gvm.DCT.title))

            self.assertEqual([str(value) for value in titles], ["Visual Paradigm distribution of Modelo de Exemplo"])
            self.assertEqual(titles[0].language, "en")

    def test_existing_vpp_metadata_without_distribution_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "models" / "badvppmetadata"
            dataset.mkdir(parents=True)
            (dataset / "ontology.vpp").write_bytes(b"fake-vpp-binary")
            (dataset / "metadata.ttl").write_text(
                """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix mod: <https://w3id.org/mod#> .

<https://w3id.org/ontouml-models/model/00000000-0000-0000-0000-000000000006/> a dcat:Dataset, mod:SemanticArtefact ;
    dct:title "Example Model" ;
    dct:license <https://creativecommons.org/licenses/by/4.0/> .
""",
                encoding="utf-8",
            )
            (dataset / "metadata-vpp.ttl").write_text(
                """
@prefix dct: <http://purl.org/dc/terms/> .
<https://example.org/not-a-distribution> dct:title "Invalid VPP metadata" .
""",
                encoding="utf-8",
            )

            with self.assertRaises(gvm.VppMetadataError):
                gvm.generate_for_dataset(dataset, repository_root=root)


AMARAL2019ROT_METADATA_TTL = """@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
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
    <https://w3id.org/ontouml-models/model/d88fe48c-d574-43b4-85d6-a6e1aeaa6726> dcat:distribution <https://w3id.org/ontouml-models/distribution/78713112-cf7e-45f1-8c74-c7b5906f5b7c/>, <https://w3id.org/ontouml-models/distribution/7c83f03b-c170-49d2-9dd9-0a600be6cc96/>, <https://w3id.org/ontouml-models/distribution/48c920df-896e-43db-baa4-adcc206d1b3d/>, <https://w3id.org/ontouml-models/distribution/669a3a1a-fd31-436e-8f31-932b4119de47>, <https://w3id.org/ontouml-models/distribution/59c1c3b5-7621-45a0-b1b9-2538e01c1b3c>, <https://w3id.org/ontouml-models/distribution/56072ed6-b5ff-467d-8424-965d41535e23>, <https://w3id.org/ontouml-models/distribution/dc069a25-ecdb-400e-83e1-5e77a4286b28>, <https://w3id.org/ontouml-models/distribution/72eba497-015a-4513-8364-3f2db1d58a2e>, <https://w3id.org/ontouml-models/distribution/abfd6260-2036-4561-9aef-2e5699d19c0e>, <https://w3id.org/ontouml-models/distribution/2a78d0c1-b55f-49bf-a915-1490005b1de8>, <https://w3id.org/ontouml-models/distribution/412737ce-27ad-44af-a1ea-d25b919d0c5f>, <https://w3id.org/ontouml-models/distribution/aba47a58-1fa8-4281-a03c-5455bd860a03>.
"""


AMARAL2019ROT_METADATA_VPP_TTL = """@prefix fdpo: <https://w3id.org/fdp/fdp-o#>.
@prefix dcat: <http://www.w3.org/ns/dcat#>.
@prefix dct: <http://purl.org/dc/terms/>.
@prefix ocmv: <https://w3id.org/ontouml-models/vocabulary#>.
@prefix owl: <http://www.w3.org/2002/07/owl#>.
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>.
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
@prefix skos: <http://www.w3.org/2004/02/skos/core#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

<https://w3id.org/ontouml-models/distribution/48c920df-896e-43db-baa4-adcc206d1b3d/> a dcat:Distribution;
    dct:isPartOf <https://w3id.org/ontouml-models/model/d88fe48c-d574-43b4-85d6-a6e1aeaa6726>;
    dct:issued "2019"^^xsd:gYear;
    dcat:mediaType <https://www.iana.org/assignments/media-types/application/octet-stream>;
    dct:license <https://creativecommons.org/licenses/by/4.0/>;
    dct:format <https://www.file-extension.info/format/vpp>;
    dct:title "Visual Paradigm distribution of Reference Ontology of Trust"@en;
    dcat:downloadURL <https://raw.githubusercontent.com/OntoUML/ontouml-models/master/models/amaral2019rot/ontology.vpp>;
    ocmv:isComplete "true"^^xsd:boolean;
    fdpo:metadataIssued "2023-04-14T17:35:47.572748333Z"^^xsd:dateTime;
    fdpo:metadataModified "2023-04-14T17:35:47.572748333Z"^^xsd:dateTime .
"""


class GenerateVppMetadataRepositoryExampleTest(TestCase):
    def test_amaral2019rot_static_triples_match_repository_example(self) -> None:
        """Regression test based on a real catalog example.

        The target fixture is the existing repository file
        `models/amaral2019rot/metadata-vpp.ttl`. The source fixture is the
        corresponding `metadata.ttl`. A tiny placeholder `ontology.vpp` is used
        because this generator does not parse VPP internals; it only needs a
        readable non-empty binary file to generate distribution-level metadata.
        """

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "models" / "amaral2019rot"
            dataset.mkdir(parents=True)
            (dataset / "ontology.vpp").write_bytes(b"placeholder-vpp-binary")
            (dataset / "metadata.ttl").write_text(AMARAL2019ROT_METADATA_TTL, encoding="utf-8")
            (dataset / "metadata-vpp.ttl").write_text(AMARAL2019ROT_METADATA_VPP_TTL, encoding="utf-8")

            generated = gvm.generate_for_dataset(
                dataset,
                repository_root=root,
                include_file_metadata=False,
            )

            expected = Graph().parse(data=AMARAL2019ROT_METADATA_VPP_TTL, format="turtle")
            actual = Graph().parse(generated.output_path, format="turtle")

            expected_static = {
                triple for triple in expected if triple[1] != gvm.FDPO.metadataModified
            }
            actual_static = {
                triple for triple in actual if triple[1] != gvm.FDPO.metadataModified
            }

            self.assertEqual(expected_static, actual_static)
            self.assertEqual(
                generated.distribution_uri,
                URIRef("https://w3id.org/ontouml-models/distribution/48c920df-896e-43db-baa4-adcc206d1b3d/"),
            )
            self.assertEqual(
                len(list(actual.objects(generated.distribution_uri, gvm.FDPO.metadataModified))),
                1,
            )


if __name__ == "__main__":
    main()

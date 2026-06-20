from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ontouml_json_to_ttl.py"
spec = importlib.util.spec_from_file_location("ontouml_json_to_ttl", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

ONTOUML = Namespace("https://w3id.org/ontouml#")
BASE = "https://w3id.org/ontouml-models/model/"


def copy_fixture(tmp_path: Path, name: str) -> Path:
    src = ROOT / "tests" / "fixtures" / "ontology_json_to_ttl" / name
    dst = tmp_path / name
    shutil.copytree(src, dst)
    return dst


def test_legacy_nested_ontology_json_generates_expected_core_triples(tmp_path: Path) -> None:
    dataset = copy_fixture(tmp_path, "legacy")
    converter = module.OntoUMLJsonToTurtleConverter(
        module.ConverterOptions(engine="fallback", catalog_model_base_uri=BASE)
    )

    result = converter.convert_dataset_folder(dataset)

    assert result.output_ttl.exists()
    graph = Graph().parse(result.output_ttl, format="turtle")
    base = BASE + "legacy/"
    project = URIRef(base)
    package = URIRef(base + "package_1")
    agent = URIRef(base + "class_agent")
    person = URIRef(base + "class_person")
    gen = URIRef(base + "gen_person_agent")
    gs = URIRef(base + "gs_agent_types")
    prop = URIRef(base + "att_name")
    card = URIRef(base + "att_name_cardinality")

    assert (project, RDF.type, ONTOUML.Project) in graph
    assert (project, ONTOUML.model, package) in graph
    assert (package, ONTOUML.containsModelElement, agent) in graph
    assert (agent, ONTOUML.stereotype, ONTOUML.category) in graph
    assert (agent, ONTOUML.restrictedTo, ONTOUML.functionalComplex) in graph
    assert (agent, ONTOUML.order, Literal(1, datatype=XSD.positiveInteger)) in graph
    assert (agent, ONTOUML.attribute, prop) in graph
    assert (prop, ONTOUML.cardinality, card) in graph
    assert (card, ONTOUML.cardinalityValue, Literal("0..*")) in graph
    assert (gen, ONTOUML.general, agent) in graph
    assert (gen, ONTOUML.specific, person) in graph
    assert (gs, ONTOUML.generalization, gen) in graph
    assert (gs, ONTOUML.isComplete, Literal(True, datatype=XSD.boolean)) in graph


def test_current_flat_ontology_json_generates_expected_core_triples(tmp_path: Path) -> None:
    dataset = copy_fixture(tmp_path, "current")
    converter = module.OntoUMLJsonToTurtleConverter(
        module.ConverterOptions(engine="fallback", catalog_model_base_uri=BASE)
    )

    result = converter.convert_dataset_folder(dataset)

    graph = Graph().parse(result.output_ttl, format="turtle")
    base = BASE + "current/"
    project = URIRef(base)
    root = URIRef(base + "pkg_root")
    a = URIRef(base + "class_a")
    b = URIRef(base + "class_b")
    gen = URIRef(base + "gen_ab")

    assert (project, RDF.type, ONTOUML.Project) in graph
    assert (project, ONTOUML.model, root) in graph
    assert (root, ONTOUML.project, URIRef(base + "project_current")) in graph
    assert (root, ONTOUML.containsModelElement, a) in graph
    assert (root, ONTOUML.containsModelElement, b) in graph
    assert (gen, ONTOUML.general, a) in graph
    assert (gen, ONTOUML.specific, b) in graph
    assert (a, ONTOUML.name, Literal("A", lang="en")) in graph


def test_check_mode_detects_stale_output(tmp_path: Path) -> None:
    dataset = copy_fixture(tmp_path, "legacy")
    converter = module.OntoUMLJsonToTurtleConverter(
        module.ConverterOptions(engine="fallback", catalog_model_base_uri=BASE, check=True)
    )

    result = converter.convert_dataset_folder(dataset)

    assert result.changed is True
    assert not result.output_ttl.exists()


def test_unresolved_reference_raises_error(tmp_path: Path) -> None:
    dataset = copy_fixture(tmp_path, "current")
    text = (dataset / "ontology.json").read_text(encoding="utf-8")
    text = text.replace('"specific": "class_b"', '"specific": "missing_class"')
    (dataset / "ontology.json").write_text(text, encoding="utf-8")
    converter = module.OntoUMLJsonToTurtleConverter(
        module.ConverterOptions(engine="fallback", catalog_model_base_uri=BASE)
    )

    try:
        converter.convert_dataset_folder(dataset)
    except module.OntoUMLConversionError as exc:
        assert "Unresolved reference" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected unresolved reference error")


def test_note_text_literal_and_note_view_text_reference_are_disambiguated(tmp_path: Path) -> None:
    dataset = tmp_path / "diagram_text_case"
    dataset.mkdir()
    (dataset / "ontology.json").write_text(
        '''{
  "id": "project_text",
  "name": "Text Case",
  "description": null,
  "type": "Project",
  "root": "pkg_root",
  "elements": [
    {"id": "pkg_root", "name": "Root", "description": null, "type": "Package", "contents": ["note_1"]},
    {"id": "note_1", "name": null, "description": null, "type": "Note", "text": {"en": "Check this constraint."}},
    {"id": "diagram_1", "name": "Diagram", "description": null, "type": "Diagram", "owner": "pkg_root", "views": ["note_view_1"]},
    {"id": "text_shape_1", "type": "Text", "topLeft": {"x": 1, "y": 2}, "width": 10, "height": 20},
    {"id": "note_view_1", "type": "NoteView", "isViewOf": "note_1", "text": "text_shape_1"}
  ]
}''',
        encoding="utf-8",
    )
    converter = module.OntoUMLJsonToTurtleConverter(
        module.ConverterOptions(engine="fallback", catalog_model_base_uri=BASE)
    )

    result = converter.convert_dataset_folder(dataset)

    assert result.issues == []
    graph = Graph().parse(result.output_ttl, format="turtle")
    base = BASE + "diagram_text_case/"
    note = URIRef(base + "note_1")
    note_view = URIRef(base + "note_view_1")
    text_shape = URIRef(base + "text_shape_1")

    assert (note, ONTOUML.text, Literal("Check this constraint.", lang="en")) in graph
    assert (note_view, ONTOUML.text, text_shape) in graph


def test_repository_lindeberg_fragment_matches_existing_ontology_ttl_conventions(tmp_path: Path) -> None:
    """Golden regression based on an existing catalog dataset.

    Source: models/lindeberg2024legal-enforcement/ontology.json.
    Target conventions checked against the corresponding ontology.ttl: the
    project is identified by the dataset URI, class restrictedTo values use the
    catalog vocabulary individuals (e.g., ontouml:event), and legacy null class
    attributes are materialized with conservative defaults.
    """
    dataset = tmp_path / "lindeberg2024legal-enforcement"
    dataset.mkdir()
    ontology_json = {
        "id": "9z6Z.fGD.AACARNt",
        "name": "Legal Enforcement",
        "description": None,
        "type": "Project",
        "model": {
            "id": "9z6Z.fGD.AACARNt_root",
            "name": "Legal Enforcement",
            "description": None,
            "type": "Package",
            "propertyAssignments": None,
            "contents": [
                {
                    "id": "ye.Z.fGD.AACARdi",
                    "name": "Appealable Legal Case Decision",
                    "description": None,
                    "type": "Class",
                    "propertyAssignments": None,
                    "stereotype": "event",
                    "isAbstract": False,
                    "isDerived": False,
                    "properties": None,
                    "isExtensional": None,
                    "isPowertype": None,
                    "order": None,
                    "literals": None,
                    "restrictedTo": ["event"],
                }
            ],
        },
    }
    import json

    (dataset / "ontology.json").write_text(json.dumps(ontology_json, indent=2), encoding="utf-8")
    converter = module.OntoUMLJsonToTurtleConverter(
        module.ConverterOptions(engine="fallback", catalog_model_base_uri=BASE)
    )

    result = converter.convert_dataset_folder(dataset)

    graph = Graph().parse(result.output_ttl, format="turtle")
    base = BASE + "lindeberg2024legal-enforcement/"
    project = URIRef(base)
    root = URIRef(base + "9z6Z.fGD.AACARNt_root")
    cls = URIRef(base + "ye.Z.fGD.AACARdi")

    assert (project, RDF.type, ONTOUML.Project) in graph
    assert (project, ONTOUML.model, root) in graph
    assert (root, ONTOUML.project, URIRef(base + "9z6Z.fGD.AACARNt")) in graph
    assert (cls, RDF.type, ONTOUML.Class) in graph
    assert (cls, ONTOUML.project, URIRef(base + "9z6Z.fGD.AACARNt")) in graph
    assert (cls, ONTOUML.name, Literal("Appealable Legal Case Decision", lang="en")) in graph
    assert (cls, ONTOUML.stereotype, ONTOUML.event) in graph
    assert (cls, ONTOUML.restrictedTo, ONTOUML.event) in graph
    assert (cls, ONTOUML.isAbstract, Literal(False, datatype=XSD.boolean)) in graph
    assert (cls, ONTOUML.isDerived, Literal(False, datatype=XSD.boolean)) in graph
    assert (cls, ONTOUML.isExtensional, Literal(False, datatype=XSD.boolean)) in graph
    assert (cls, ONTOUML.isPowertype, Literal(False, datatype=XSD.boolean)) in graph
    assert (cls, ONTOUML.order, Literal(1, datatype=XSD.positiveInteger)) in graph


def test_existing_hash_element_uri_style_is_preserved(tmp_path: Path) -> None:
    """Golden regression for older catalog files such as amaral2019rot.

    Some existing ontology.ttl files use the dataset URI for the project
    individual but mint element URIs with a hash namespace, e.g.
    https://w3id.org/ontouml-models/model/amaral2019rot#Nlnret6GAqACCgBO_root.
    The default auto mode must preserve that style when an ontology.ttl already
    exists.
    """
    dataset = tmp_path / "amaral2019rot"
    dataset.mkdir()
    (dataset / "ontology.json").write_text(
        '''{
  "id": "Nlnret6GAqACCgBO",
  "name": "Reference Ontology of Trust",
  "description": null,
  "type": "Project",
  "model": {
    "id": "Nlnret6GAqACCgBO_root",
    "name": "Reference Ontology of Trust",
    "description": null,
    "type": "Package",
    "contents": []
  }
}''',
        encoding="utf-8",
    )
    (dataset / "ontology.ttl").write_text(
        '''@prefix ontouml: <https://w3id.org/ontouml#> .
<https://w3id.org/ontouml-models/model/amaral2019rot/> a ontouml:Project ;
    ontouml:model <https://w3id.org/ontouml-models/model/amaral2019rot#Nlnret6GAqACCgBO_root> .
''',
        encoding="utf-8",
    )
    converter = module.OntoUMLJsonToTurtleConverter(
        module.ConverterOptions(engine="fallback", catalog_model_base_uri=BASE)
    )

    result = converter.convert_dataset_folder(dataset)

    graph = Graph().parse(result.output_ttl, format="turtle")
    project = URIRef(BASE + "amaral2019rot/")
    root_hash = URIRef(BASE + "amaral2019rot#Nlnret6GAqACCgBO_root")
    project_id_hash = URIRef(BASE + "amaral2019rot#Nlnret6GAqACCgBO")
    root_slash = URIRef(BASE + "amaral2019rot/Nlnret6GAqACCgBO_root")

    assert (project, RDF.type, ONTOUML.Project) in graph
    assert (project, ONTOUML.model, root_hash) in graph
    assert (root_hash, ONTOUML.project, project_id_hash) in graph
    assert (project, ONTOUML.model, root_slash) not in graph

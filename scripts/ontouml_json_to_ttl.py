#!/usr/bin/env python3
"""Generate OntoUML `ontology.ttl` files from mandatory `ontology.json` files.

Repository usage examples
-------------------------

Generate one dataset's Turtle serialization::

    python scripts/ontouml_json_to_ttl.py models/amaral2019rot

Generate several dataset folders::

    python scripts/ontouml_json_to_ttl.py models/amaral2019rot models/lindeberg2024legal-enforcement

Generate every `ontology.ttl` under `models/`::

    python scripts/ontouml_json_to_ttl.py --all models

Check whether generated files are current without writing them::

    python scripts/ontouml_json_to_ttl.py --all models --check

The default engine is the built-in RDFLib transformer because it is calibrated
against the catalog repository examples. The optional `official` engine delegates
to `ontouml-json2graph` when that package is installed, but its output may follow
newer OntoUML Vocabulary conventions than the current catalog examples.

The built-in transformer preserves the element URI style of an existing
`ontology.ttl` file when possible. This matters because older catalog files may
use hash-style element URIs (`.../model-id#element-id`), while newer files may
use slash-style element URIs (`.../model-id/element-id`).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable, Iterator, Mapping, MutableMapping, Sequence
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

ONTOUML = Namespace("https://w3id.org/ontouml#")
DCT = Namespace("http://purl.org/dc/terms/")
DEFAULT_CATALOG_MODEL_BASE_URI = "https://w3id.org/ontouml-models/model/"
DEFAULT_JSON_FILE = "ontology.json"
DEFAULT_TTL_FILE = "ontology.ttl"

SUPPORTED_ENGINES = ("auto", "official", "fallback")
SUPPORTED_ELEMENT_URI_STYLES = ("auto", "slash", "hash")

# References that should resolve to another OntoUML element in the same project.
# Values may be string ids, legacy {"id": ..., "type": ...} objects, or lists.
REFERENCE_FIELDS = {
    "model",
    "root",
    "contents",
    "properties",
    "literals",
    "general",
    "specific",
    "generalizations",
    "categorizer",
    "propertyType",
    "subsettedProperties",
    "redefinedProperties",
    "owner",
    "views",
    "isViewOf",
    "rectangle",
    "sourceView",
    "targetView",
    "path",
    "members",
    "diamond",
    "paths",
    "note",
    "element",
}

# Predicates used when a field must be renamed from the JSON schema to the
# OntoUML vocabulary. Fields not listed here are mapped directly to ontouml:<key>.
FIELD_TO_PREDICATE = {
    "model": "model",
    "root": "model",
    "contents": "containsModelElement",
    "general": "general",
    "specific": "specific",
    "generalizations": "generalization",
    "categorizer": "categorizer",
    "propertyType": "propertyType",
    "subsettedProperties": "subsetsProperty",
    "redefinedProperties": "redefinesProperty",
    "owner": "owner",
    "views": "view",
    "isViewOf": "isViewOf",
    "rectangle": "rectangle",
    "sourceView": "sourceView",
    "targetView": "targetView",
    "path": "path",
    "members": "member",
    "diamond": "diamond",
    "paths": "path",
    "text": "text",
    "note": "note",
    "element": "element",
}

CLASS_PROPERTY_PREDICATE = "attribute"
RELATION_PROPERTY_PREDICATE = "relationEnd"

STRING_FIELDS = {"name", "description", "text", "value"}
BOOLEAN_FIELDS = {
    "isAbstract",
    "isDerived",
    "isDisjoint",
    "isComplete",
    "isOrdered",
    "isReadOnly",
    "isExtensional",
    "isPowertype",
}
INTEGER_FIELDS = {"width", "height", "x", "y"}
DATE_OR_METADATA_FIELDS = {"created", "modified"}
SKIP_FIELDS = {
    "id",
    "type",
    "elements",  # current schema container; each element is serialized independently.
    "diagrams",  # legacy project-level container; linked via ontouml:diagram explicitly.
    "propertyAssignments",  # legacy VP export metadata not represented in OntoUML Vocabulary here.
    "customProperties",  # current schema extension point; skipped by fallback unless external engine is used.
    "alternativeNames",
    "editorialNotes",
    "creators",
    "contributors",
    "publisher",
    "designedForTasks",
    "license",
    "accessRights",
    "themes",
    "contexts",
    "ontologyTypes",
    "representationStyle",
    "namespace",
    "landingPages",
    "sources",
    "bibliographicCitations",
    "keywords",
    "acronyms",
    "languages",
}

# Current ontouml-schema uses kebab-case ontological natures. Older catalog
# examples sometimes used the shorter term directly. The fallback uses the
# current OntoUML Vocabulary convention used by ontouml-json2graph.
ONTOLOGICAL_NATURE_MAP = {
    # Catalog ontology.ttl examples and the catalog paper use these OntoUML
    # Vocabulary individuals directly, e.g., ontouml:functionalComplex and
    # ontouml:event, not the newer *Nature terms used by some later tools.
    "abstract": "abstract",
    "collective": "collective",
    "event": "event",
    "extrinsic-mode": "extrinsicMode",
    "extrinsicMode": "extrinsicMode",
    "functional-complex": "functionalComplex",
    "functionalComplex": "functionalComplex",
    "intrinsic-mode": "intrinsicMode",
    "intrinsicMode": "intrinsicMode",
    "quality": "quality",
    "quantity": "quantity",
    "relator": "relator",
    "situation": "situation",
    "type": "type",
}

VALID_CLASS_STEREOTYPES = {
    "type",
    "historicalRole",
    "historicalRoleMixin",
    "event",
    "situation",
    "category",
    "mixin",
    "roleMixin",
    "phaseMixin",
    "kind",
    "collective",
    "quantity",
    "relator",
    "quality",
    "mode",
    "subkind",
    "role",
    "phase",
    "enumeration",
    "datatype",
    "abstract",
}
VALID_RELATION_STEREOTYPES = {
    "mediation",
    "characterization",
    "comparative",
    "material",
    "derivation",
    "componentOf",
    "memberOf",
    "subCollectionOf",
    "subQuantityOf",
    "bringsAbout",
    "creation",
    "historicalDependence",
    "manifestation",
    "participation",
    "participational",
    "termination",
    "triggers",
}
VALID_PROPERTY_STEREOTYPES = {"begin", "end"}
VALID_AGGREGATION_KINDS = {"COMPOSITE", "SHARED", "NONE", "composite", "shared", "none"}

# Types treated as model elements when checking diagram-model boundaries.
MODEL_ELEMENT_TYPES = {
    "Project",
    "Package",
    "Class",
    "Relation",
    "BinaryRelation",
    "NaryRelation",
    "Property",
    "Generalization",
    "GeneralizationSet",
    "Literal",
    "Note",
    "Anchor",
}


class OntoUMLConversionError(RuntimeError):
    """Raised when an ontology JSON file cannot be converted safely."""


@dataclass
class ConversionIssue:
    severity: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.path}: {self.message}"


@dataclass
class ConversionResult:
    dataset_folder: Path
    input_json: Path
    output_ttl: Path
    engine: str
    graph: Graph
    issues: list[ConversionIssue] = field(default_factory=list)
    written: bool = False
    changed: bool | None = None


@dataclass
class ConverterOptions:
    engine: str = "fallback"
    catalog_model_base_uri: str = DEFAULT_CATALOG_MODEL_BASE_URI
    base_uri: str | None = None
    element_uri_style: str = "auto"
    language: str = "en"
    include_diagrams: bool = True
    correct: bool = False
    fail_on_warning: bool = False
    overwrite: bool = True
    check: bool = False


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    options = ConverterOptions(
        engine=args.engine,
        catalog_model_base_uri=args.catalog_model_base_uri,
        base_uri=args.base_uri,
        element_uri_style=args.element_uri_style,
        language=args.language or "",
        include_diagrams=not args.model_only,
        correct=args.correct,
        fail_on_warning=args.fail_on_warning,
        overwrite=not args.no_overwrite,
        check=args.check,
    )

    try:
        dataset_folders = resolve_dataset_folders(args.paths, all_models=args.all)
        if not dataset_folders:
            raise OntoUMLConversionError("No dataset folders containing ontology.json were found.")

        converter = OntoUMLJsonToTurtleConverter(options)
        results = [converter.convert_dataset_folder(folder) for folder in dataset_folders]
    except OntoUMLConversionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    has_error = False
    has_warning = False
    has_change = False

    for result in results:
        rel_output = result.output_ttl.as_posix()
        state = "checked" if options.check else "written"
        if options.check:
            if result.changed:
                has_change = True
                state = "stale"
            else:
                state = "current"
        print(f"{state}: {rel_output} ({len(result.graph)} triples, engine={result.engine})")
        for issue in result.issues:
            print(f"  {issue}", file=sys.stderr)
            if issue.severity == "ERROR":
                has_error = True
            elif issue.severity == "WARNING":
                has_warning = True

    if has_error:
        return 2
    if options.fail_on_warning and has_warning:
        return 3
    if options.check and has_change:
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate ontology.ttl files from OntoUML ontology.json files.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Dataset folders or ontology.json files. Use --all models to process every dataset under models/.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Treat the provided path as a models directory and process all immediate children containing ontology.json.",
    )
    parser.add_argument(
        "--engine",
        choices=SUPPORTED_ENGINES,
        default="fallback",
        help="Transformation engine. Use 'fallback' for catalog-compatible RDFLib output; 'official' delegates to ontouml-json2graph; 'auto' tries official first and then fallback.",
    )
    parser.add_argument(
        "--catalog-model-base-uri",
        default=DEFAULT_CATALOG_MODEL_BASE_URI,
        help="Base URI used to infer dataset URIs from folder names.",
    )
    parser.add_argument(
        "--base-uri",
        default=None,
        help="Explicit dataset URI for one input. For multiple inputs, prefer --catalog-model-base-uri.",
    )
    parser.add_argument(
        "--element-uri-style",
        choices=SUPPORTED_ELEMENT_URI_STYLES,
        default="auto",
        help="How to mint element URIs below the dataset URI. 'auto' preserves an existing ontology.ttl convention when possible; otherwise it uses slash style.",
    )
    parser.add_argument(
        "--language",
        default="en",
        help="Default language tag for legacy plain-string names/descriptions. Use '' for no language tag.",
    )
    parser.add_argument(
        "--model-only",
        action="store_true",
        help="Exclude diagrammatic/concrete-syntax elements where the selected engine supports it.",
    )
    parser.add_argument(
        "--correct",
        action="store_true",
        help="Ask the official engine to apply its basic corrections when available. The fallback remains conservative.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write files. Exit 1 if any generated ontology.ttl differs from the existing file.",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Fail if ontology.ttl already exists instead of overwriting it.",
    )
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Exit non-zero when validation emits warnings.",
    )
    return parser


def resolve_dataset_folders(paths: Sequence[Path], all_models: bool = False) -> list[Path]:
    if not paths:
        paths = [Path("models")]
        all_models = True

    folders: list[Path] = []
    for path in paths:
        path = path.resolve()
        if all_models:
            if not path.is_dir():
                raise OntoUMLConversionError(f"Expected a models directory, got: {path}")
            folders.extend(sorted(p for p in path.iterdir() if (p / DEFAULT_JSON_FILE).is_file()))
            continue

        if path.is_file() and path.name == DEFAULT_JSON_FILE:
            folders.append(path.parent)
        elif path.is_dir() and (path / DEFAULT_JSON_FILE).is_file():
            folders.append(path)
        else:
            raise OntoUMLConversionError(f"Path is neither a dataset folder nor ontology.json: {path}")

    # Preserve order while removing duplicates.
    unique: list[Path] = []
    seen: set[Path] = set()
    for folder in folders:
        if folder not in seen:
            seen.add(folder)
            unique.append(folder)
    return unique


class OntoUMLJsonToTurtleConverter:
    """Dataset-folder level converter from mandatory ontology.json to ontology.ttl."""

    def __init__(self, options: ConverterOptions | None = None):
        self.options = options or ConverterOptions()

    def convert_dataset_folder(self, dataset_folder: Path) -> ConversionResult:
        dataset_folder = dataset_folder.resolve()
        input_json = dataset_folder / DEFAULT_JSON_FILE
        output_ttl = dataset_folder / DEFAULT_TTL_FILE

        if not input_json.is_file():
            raise OntoUMLConversionError(f"Missing mandatory file: {input_json}")
        if output_ttl.exists() and not self.options.overwrite and not self.options.check:
            raise OntoUMLConversionError(f"Output already exists and --no-overwrite was used: {output_ttl}")

        dataset_uri = self._dataset_uri_for_dataset(dataset_folder)
        element_base_uri = self._element_base_uri_for_dataset(dataset_uri, output_ttl)
        graph, engine, issues = self._build_graph(input_json, dataset_uri, element_base_uri)
        ttl_text = graph.serialize(format="turtle")

        changed = None
        written = False
        if self.options.check:
            changed = (not output_ttl.exists()) or output_ttl.read_text(encoding="utf-8") != ttl_text
        else:
            output_ttl.write_text(ttl_text, encoding="utf-8")
            written = True

        return ConversionResult(
            dataset_folder=dataset_folder,
            input_json=input_json,
            output_ttl=output_ttl,
            engine=engine,
            graph=graph,
            issues=issues,
            written=written,
            changed=changed,
        )

    def _dataset_uri_for_dataset(self, dataset_folder: Path) -> str:
        if self.options.base_uri:
            return ensure_uri_separator(self.options.base_uri)
        base = ensure_uri_separator(self.options.catalog_model_base_uri)
        return ensure_uri_separator(base + dataset_folder.name)

    def _element_base_uri_for_dataset(self, dataset_uri: str, output_ttl: Path) -> str:
        style = self.options.element_uri_style
        if style == "auto":
            style = infer_existing_element_uri_style(output_ttl, dataset_uri) or "slash"
        if style == "hash":
            return dataset_uri.rstrip("/") + "#"
        if style == "slash":
            return ensure_uri_separator(dataset_uri)
        raise OntoUMLConversionError(f"Unsupported element URI style: {style}")

    def _build_graph(self, input_json: Path, dataset_uri: str, element_base_uri: str) -> tuple[Graph, str, list[ConversionIssue]]:
        requested = self.options.engine
        if requested in {"auto", "official"}:
            try:
                graph = self._build_graph_with_official_engine(input_json, element_base_uri)
                return graph, "official", []
            except ImportError as exc:
                if requested == "official":
                    raise OntoUMLConversionError(
                        "The official engine requires `ontouml-json2graph`. Install dependencies with "
                        "`pip install -r requirements-automation.txt`."
                    ) from exc
            except Exception as exc:  # pragma: no cover - exercised only when optional engine is present.
                if requested == "official":
                    raise OntoUMLConversionError(f"Official ontouml-json2graph conversion failed: {exc}") from exc
                print(
                    f"WARNING: official ontouml-json2graph engine failed for {input_json}: {exc}. "
                    "Falling back to built-in converter.",
                    file=sys.stderr,
                )

        data = load_json_object(input_json)
        fallback = FallbackRDFLibTransformer(
            dataset_uri=dataset_uri,
            element_base_uri=element_base_uri,
            language=self.options.language,
            include_diagrams=self.options.include_diagrams,
            fail_on_warning=self.options.fail_on_warning,
        )
        graph = fallback.transform(data)
        return graph, "fallback", fallback.issues

    def _build_graph_with_official_engine(self, input_json: Path, base_uri: str) -> Graph:
        # Import lazily to keep the built-in fallback usable with only RDFLib.
        from json2graph.decode import decode_ontouml_json2graph  # type: ignore[import-not-found]

        graph = decode_ontouml_json2graph(
            json_file_path=str(input_json),
            base_uri=base_uri,
            language=self.options.language,
            model_only=not self.options.include_diagrams,
            silent=True,
            correct=self.options.correct,
            execution_mode="import",
        )
        if not isinstance(graph, Graph):
            raise OntoUMLConversionError("Official engine did not return an RDFLib Graph.")
        return graph


class FallbackRDFLibTransformer:
    """Conservative RDFLib implementation for OntoUML JSON to Turtle.

    The fallback supports both:
    - legacy VP-plugin exports used in many existing catalog entries, where the
      project has `model` and nested `contents` objects;
    - the current flat `elements`/`root` form from ontouml-schema v1.

    It intentionally focuses on vocabulary-preserving structural RDF and does not
    replace the official ontouml-json2graph validations/corrections.
    """

    def __init__(
        self,
        dataset_uri: str,
        element_base_uri: str,
        language: str = "en",
        include_diagrams: bool = True,
        fail_on_warning: bool = False,
    ):
        self.dataset_uri = ensure_uri_separator(dataset_uri)
        self.element_base_uri = ensure_element_base_uri(element_base_uri)
        self.language = language
        self.include_diagrams = include_diagrams
        self.fail_on_warning = fail_on_warning
        self.issues: list[ConversionIssue] = []
        self.id_index: dict[str, Mapping[str, Any]] = {}
        self.parent_type_by_id: dict[str, str] = {}
        self.graph = Graph()
        self.project_id: str | None = None
        self.project_uri: URIRef | None = None
        self.project_reference_uri: URIRef | None = None

    def transform(self, data: Mapping[str, Any]) -> Graph:
        self._validate_project(data)
        self._index_elements(data)
        self._validate_references(data)
        self._validate_supported_values()
        self._init_graph()
        self._emit_project(data)
        self._emit_elements(data)
        self._raise_if_errors()
        return self.graph

    def _validate_project(self, data: Mapping[str, Any]) -> None:
        if not isinstance(data, Mapping):
            raise OntoUMLConversionError("ontology.json must contain a JSON object at the top level.")
        if data.get("type") != "Project":
            raise OntoUMLConversionError("ontology.json top-level object must have type 'Project'.")
        project_id = data.get("id")
        if not isinstance(project_id, str) or not project_id.strip():
            raise OntoUMLConversionError("Project must have a non-empty string id.")
        if "model" not in data and "root" not in data:
            self._issue("WARNING", "$", "Project has neither legacy `model` nor current `root` field.")
        self.project_id = project_id
        # Existing catalog ontology.ttl files identify the project individual
        # itself with the dataset URI, while element-level ontouml:project
        # statements point to the project-id URI under the dataset namespace.
        # Example: the dataset URI is rdf:type ontouml:Project, but packages and
        # classes use <dataset-uri>/<project-id> as the object of ontouml:project.
        self.project_uri = URIRef(self.dataset_uri)
        self.project_reference_uri = self._uri(project_id)

    def _index_elements(self, data: Mapping[str, Any]) -> None:
        for element, path, parent in iter_ontouml_element_objects(data):
            element_type = element.get("type")
            element_id = element.get("id")
            if not isinstance(element_type, str) or not element_type:
                self._issue("ERROR", path, "Element is missing mandatory string field `type`.")
                continue
            if not isinstance(element_id, str) or not element_id:
                self._issue("ERROR", path, "Element is missing mandatory string field `id`.")
                continue
            if not self.include_diagrams and element_type not in MODEL_ELEMENT_TYPES:
                continue
            if element_id in self.id_index:
                self._issue("ERROR", path, f"Duplicate OntoUML element id: {element_id}")
                continue
            self.id_index[element_id] = element
            if parent and parent.get("id"):
                self.parent_type_by_id[element_id] = str(parent.get("type"))

    def _validate_references(self, data: Mapping[str, Any]) -> None:
        known_ids = set(self.id_index)
        for element, path, _ in iter_ontouml_element_objects(data):
            if not self.include_diagrams and element.get("type") not in MODEL_ELEMENT_TYPES:
                continue
            element_id = element.get("id", "<unknown>")
            for field in reference_fields_for_element(element):
                if field not in element or element[field] is None:
                    continue
                for ref_id in iter_reference_ids(element[field]):
                    if ref_id not in known_ids:
                        self._issue(
                            "ERROR",
                            f"{path}.{field}",
                            f"Unresolved reference `{ref_id}` from element `{element_id}`.",
                        )

    def _validate_supported_values(self) -> None:
        for element_id, element in self.id_index.items():
            element_type = str(element.get("type"))
            stereotype = element.get("stereotype")
            if stereotype is not None:
                if not isinstance(stereotype, str) or not stereotype:
                    self._issue("ERROR", element_id, "`stereotype` must be a non-empty string or null.")
                elif element_type == "Class" and stereotype not in VALID_CLASS_STEREOTYPES:
                    self._issue("WARNING", element_id, f"Unsupported/unknown Class stereotype `{stereotype}`.")
                elif element_type in {"Relation", "BinaryRelation", "NaryRelation"} and stereotype not in VALID_RELATION_STEREOTYPES:
                    self._issue("WARNING", element_id, f"Unsupported/unknown Relation stereotype `{stereotype}`.")
                elif element_type == "Property" and stereotype not in VALID_PROPERTY_STEREOTYPES:
                    self._issue("WARNING", element_id, f"Unsupported/unknown Property stereotype `{stereotype}`.")

            if element_type == "Class":
                restricted_to = element.get("restrictedTo")
                if restricted_to is not None:
                    if not isinstance(restricted_to, list):
                        self._issue("ERROR", element_id, "`restrictedTo` must be an array when present.")
                    else:
                        for nature in restricted_to:
                            if nature not in ONTOLOGICAL_NATURE_MAP:
                                self._issue("WARNING", element_id, f"Unsupported ontological nature `{nature}`.")

            if element_type == "Property":
                aggregation = element.get("aggregationKind")
                if aggregation is not None and aggregation not in VALID_AGGREGATION_KINDS:
                    self._issue("WARNING", element_id, f"Unsupported aggregationKind `{aggregation}`.")

    def _init_graph(self) -> None:
        self.graph.bind("", Namespace(self.element_base_uri))
        self.graph.bind("ontouml", ONTOUML)
        self.graph.bind("rdf", RDF)
        self.graph.bind("rdfs", RDFS)
        self.graph.bind("owl", OWL)
        self.graph.bind("xsd", XSD)

    def _emit_project(self, data: Mapping[str, Any]) -> None:
        assert self.project_uri is not None
        self._emit_common(data, self.project_uri)
        self.graph.add((self.project_uri, RDF.type, ONTOUML.Project))

        root_ref = data.get("model", data.get("root"))
        for root_id in iter_reference_ids(root_ref):
            self.graph.add((self.project_uri, ONTOUML.model, self._uri(root_id)))

        # Legacy exports often keep diagrams in a top-level `diagrams` array. Current
        # schema keeps diagrams in `elements`. Emit project-diagram links for both.
        if self.include_diagrams:
            diagram_ids = set()
            for diagram in data.get("diagrams") or []:
                if isinstance(diagram, Mapping) and diagram.get("id"):
                    diagram_ids.add(str(diagram["id"]))
            for element_id, element in self.id_index.items():
                if element.get("type") == "Diagram":
                    diagram_ids.add(element_id)
            for diagram_id in sorted(diagram_ids):
                self.graph.add((self.project_uri, ONTOUML.diagram, self._uri(diagram_id)))

    def _emit_elements(self, data: Mapping[str, Any]) -> None:
        for element_id, element in self.id_index.items():
            if element_id == self.project_id:
                continue
            element_type = element.get("type")
            if not self.include_diagrams and element_type not in MODEL_ELEMENT_TYPES:
                continue
            self._emit_element(element)

    def _emit_element(self, element: Mapping[str, Any]) -> None:
        element_id = str(element["id"])
        element_type = str(element["type"])
        subject = self._uri(element_id)

        self._emit_type(subject, element_type)
        if self.project_reference_uri is not None and element_type != "Project":
            self.graph.add((subject, ONTOUML.project, self.project_reference_uri))
        self._emit_common(element, subject)

        if element_type == "Package":
            self._emit_references(subject, "contents", element.get("contents"), ONTOUML.containsModelElement)
        elif element_type == "Class":
            self._emit_decoratable(element, subject)
            self._emit_classifier(element, subject, CLASS_PROPERTY_PREDICATE)
            self._emit_class(element, subject)
        elif element_type in {"Relation", "BinaryRelation", "NaryRelation"}:
            self._emit_decoratable(element, subject)
            self._emit_classifier(element, subject, RELATION_PROPERTY_PREDICATE)
        elif element_type == "Property":
            self._emit_decoratable(element, subject)
            self._emit_property(element, subject)
        elif element_type == "Generalization":
            self._emit_references(subject, "general", element.get("general"), ONTOUML.general)
            self._emit_references(subject, "specific", element.get("specific"), ONTOUML.specific)
        elif element_type == "GeneralizationSet":
            self._emit_references(subject, "generalizations", element.get("generalizations"), ONTOUML.generalization)
            self._emit_references(subject, "categorizer", element.get("categorizer"), ONTOUML.categorizer)
        elif element_type == "Diagram":
            self._emit_references(subject, "owner", element.get("owner"), ONTOUML.owner)
            self._emit_references(subject, "views", element.get("views"), ONTOUML.view)
        elif element_type.endswith("View"):
            self._emit_view(element, subject)
        elif element_type == "Path":
            self._emit_path(element, subject)
        elif element_type in {"Rectangle", "Diamond", "Text"}:
            self._emit_rectangular_shape(element, subject)
        elif element_type == "Anchor":
            self._emit_references(subject, "note", element.get("note"), ONTOUML.note)
            self._emit_references(subject, "element", element.get("element"), ONTOUML.element)
        elif element_type == "Note":
            # Note text is emitted by _emit_common when present.
            pass
        elif element_type == "Literal":
            pass
        else:
            self._issue("WARNING", element_id, f"Unknown OntoUML element type `{element_type}`; emitted generic triples only.")
            self._emit_generic_supported_fields(element, subject)

    def _emit_type(self, subject: URIRef, element_type: str) -> None:
        self.graph.add((subject, RDF.type, ONTOUML[self._term_name(element_type)]))
        if element_type in {"BinaryRelation", "NaryRelation"}:
            self.graph.add((subject, RDF.type, ONTOUML.Relation))

    def _emit_common(self, element: Mapping[str, Any], subject: URIRef) -> None:
        for field_name in STRING_FIELDS:
            if field_name in element and element[field_name] is not None:
                # In the OntoUML Schema, `text` is a literal only for Note elements.
                # For NoteView and GeneralizationSetView, `text` is a reference to a
                # Text shape and is emitted by _emit_view instead.
                if field_name == "text" and element.get("type") != "Note":
                    continue
                predicate_name = "text" if field_name == "value" else field_name
                self._emit_language_value(subject, ONTOUML[predicate_name], element[field_name])

        for field_name in BOOLEAN_FIELDS:
            if field_name in element and element[field_name] is not None:
                value = element[field_name]
                if not isinstance(value, bool):
                    self._issue("ERROR", str(element.get("id", "<unknown>")), f"`{field_name}` must be boolean or null.")
                    continue
                self.graph.add((subject, ONTOUML[field_name], Literal(value, datatype=XSD.boolean)))

        for field_name in INTEGER_FIELDS:
            if field_name in element and element[field_name] is not None:
                value = element[field_name]
                if not isinstance(value, int) or value < 0:
                    self._issue("ERROR", str(element.get("id", "<unknown>")), f"`{field_name}` must be a non-negative integer.")
                    continue
                self.graph.add((subject, ONTOUML[field_name], Literal(value, datatype=XSD.nonNegativeInteger)))

        if "created" in element and element["created"]:
            self.graph.add((subject, DCT.created, self._date_literal(str(element["created"]))))
        if "modified" in element and element["modified"]:
            self.graph.add((subject, DCT.modified, self._date_literal(str(element["modified"]))))

    def _emit_decoratable(self, element: Mapping[str, Any], subject: URIRef) -> None:
        stereotype = element.get("stereotype")
        if stereotype:
            self.graph.add((subject, ONTOUML.stereotype, ONTOUML[self._term_name(str(stereotype))]))

    def _emit_classifier(self, element: Mapping[str, Any], subject: URIRef, properties_predicate_name: str) -> None:
        self._emit_references(subject, "properties", element.get("properties"), ONTOUML[properties_predicate_name])

    def _emit_class(self, element: Mapping[str, Any], subject: URIRef) -> None:
        # Existing catalog ontology.ttl files materialize conservative defaults
        # for class attributes omitted/null in legacy VP-plugin JSON exports.
        for field_name in ("isAbstract", "isDerived", "isExtensional", "isPowertype"):
            if element.get(field_name) is None:
                self.graph.add((subject, ONTOUML[field_name], Literal(False, datatype=XSD.boolean)))

        for nature in element.get("restrictedTo") or []:
            if nature in ONTOLOGICAL_NATURE_MAP:
                self.graph.add((subject, ONTOUML.restrictedTo, ONTOUML[ONTOLOGICAL_NATURE_MAP[str(nature)]]))
        self._emit_references(subject, "literals", element.get("literals"), ONTOUML.literal)

        order_value = element.get("order")
        if order_value is None:
            order_value = "2" if element.get("stereotype") == "type" else "1"
        else:
            order_value = str(order_value)

        if order_value == "*":
            self.graph.add((subject, ONTOUML.order, Literal(0, datatype=XSD.nonNegativeInteger)))
        elif str(order_value).isdigit() and int(order_value) > 0:
            self.graph.add((subject, ONTOUML.order, Literal(int(order_value), datatype=XSD.positiveInteger)))
        else:
            self._issue("WARNING", str(element["id"]), f"Invalid class order `{order_value}`; emitted as string literal.")
            self.graph.add((subject, ONTOUML.order, Literal(str(order_value))))

    def _emit_property(self, element: Mapping[str, Any], subject: URIRef) -> None:
        aggregation = element.get("aggregationKind")
        if aggregation:
            self.graph.add((subject, ONTOUML.aggregationKind, ONTOUML[self._term_name(str(aggregation).lower())]))
        self._emit_references(subject, "propertyType", element.get("propertyType"), ONTOUML.propertyType)
        self._emit_references(subject, "subsettedProperties", element.get("subsettedProperties"), ONTOUML.subsetsProperty)
        self._emit_references(subject, "redefinedProperties", element.get("redefinedProperties"), ONTOUML.redefinesProperty)
        if element.get("cardinality") is not None:
            cardinality_value = str(element["cardinality"])
            card_uri = URIRef(f"{subject}_cardinality")
            lower, upper, normalized = normalize_cardinality(cardinality_value)
            self.graph.add((card_uri, RDF.type, ONTOUML.Cardinality))
            self.graph.add((subject, ONTOUML.cardinality, card_uri))
            self.graph.add((card_uri, ONTOUML.cardinalityValue, Literal(normalized)))
            self.graph.add((card_uri, ONTOUML.lowerBound, Literal(lower)))
            self.graph.add((card_uri, ONTOUML.upperBound, Literal(upper)))

    def _emit_view(self, element: Mapping[str, Any], subject: URIRef) -> None:
        for field, predicate_name in FIELD_TO_PREDICATE.items():
            if field in element and field not in {"contents", "model", "root", "general", "specific", "generalizations", "categorizer", "properties", "literals", "owner", "views"}:
                self._emit_references(subject, field, element.get(field), ONTOUML[predicate_name])

    def _emit_path(self, element: Mapping[str, Any], subject: URIRef) -> None:
        # Point objects have no ids. Represent each point as a deterministic URIRef.
        points = element.get("points") or []
        if not isinstance(points, list):
            self._issue("ERROR", str(element.get("id", "<unknown>")), "`points` must be a list.")
            return
        for index, point in enumerate(points, start=1):
            if not isinstance(point, Mapping):
                self._issue("ERROR", str(element.get("id", "<unknown>")), "Path point must be an object.")
                continue
            point_uri = URIRef(f"{subject}_point_{index}")
            self.graph.add((point_uri, RDF.type, ONTOUML.Point))
            self.graph.add((subject, ONTOUML.point, point_uri))
            for coord in ("x", "y"):
                value = point.get(coord)
                if isinstance(value, int) and value >= 0:
                    self.graph.add((point_uri, ONTOUML[coord], Literal(value, datatype=XSD.nonNegativeInteger)))
                else:
                    self._issue("ERROR", str(element.get("id", "<unknown>")), f"Point `{coord}` must be a non-negative integer.")

    def _emit_rectangular_shape(self, element: Mapping[str, Any], subject: URIRef) -> None:
        top_left = element.get("topLeft")
        if isinstance(top_left, Mapping):
            point_uri = URIRef(f"{subject}_topLeft")
            self.graph.add((point_uri, RDF.type, ONTOUML.Point))
            self.graph.add((subject, ONTOUML.topLeft, point_uri))
            for coord in ("x", "y"):
                value = top_left.get(coord)
                if isinstance(value, int) and value >= 0:
                    self.graph.add((point_uri, ONTOUML[coord], Literal(value, datatype=XSD.nonNegativeInteger)))
                else:
                    self._issue("ERROR", str(element.get("id", "<unknown>")), f"topLeft `{coord}` must be a non-negative integer.")

    def _emit_generic_supported_fields(self, element: Mapping[str, Any], subject: URIRef) -> None:
        for field, value in element.items():
            if field in SKIP_FIELDS or value is None:
                continue
            if field in REFERENCE_FIELDS:
                predicate = ONTOUML[FIELD_TO_PREDICATE.get(field, field)]
                self._emit_references(subject, field, value, predicate)

    def _emit_references(self, subject: URIRef, field: str, value: Any, predicate: URIRef) -> None:
        if value is None:
            return
        for ref_id in iter_reference_ids(value):
            if ref_id in self.id_index:
                self.graph.add((subject, predicate, self._uri(ref_id)))

    def _emit_language_value(self, subject: URIRef, predicate: URIRef, value: Any) -> None:
        if isinstance(value, Mapping):
            for lang, text in value.items():
                if text is None:
                    continue
                if not isinstance(text, str):
                    self._issue("ERROR", str(subject), "Language string values must be strings.")
                    continue
                if lang:
                    self.graph.add((subject, predicate, Literal(text, lang=str(lang))))
                else:
                    self.graph.add((subject, predicate, Literal(text)))
        elif isinstance(value, str):
            if self.language:
                self.graph.add((subject, predicate, Literal(value, lang=self.language)))
            else:
                self.graph.add((subject, predicate, Literal(value)))
        else:
            self._issue("ERROR", str(subject), "Expected string or language-string object.")

    def _date_literal(self, value: str) -> Literal:
        if re.fullmatch(r"\d{4}", value):
            return Literal(value, datatype=XSD.gYear)
        if re.fullmatch(r"\d{4}-\d{2}", value):
            return Literal(value, datatype=XSD.gYearMonth)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return Literal(value, datatype=XSD.date)
        return Literal(value, datatype=XSD.dateTime)

    def _uri(self, element_id: str) -> URIRef:
        return URIRef(self.element_base_uri + quote(str(element_id), safe="._~:@!$&'()*+,;=-"))

    def _term_name(self, value: str) -> str:
        if value in ONTOLOGICAL_NATURE_MAP:
            return ONTOLOGICAL_NATURE_MAP[value]
        if value.upper() in VALID_AGGREGATION_KINDS:
            return value.lower()
        if "-" in value:
            parts = value.split("-")
            return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])
        return value

    def _issue(self, severity: str, path: str, message: str) -> None:
        self.issues.append(ConversionIssue(severity=severity, path=path, message=message))

    def _raise_if_errors(self) -> None:
        errors = [issue for issue in self.issues if issue.severity == "ERROR"]
        warnings = [issue for issue in self.issues if issue.severity == "WARNING"]
        if errors:
            joined = "\n".join(str(issue) for issue in errors[:20])
            raise OntoUMLConversionError(f"Conversion produced errors:\n{joined}")
        if self.fail_on_warning and warnings:
            joined = "\n".join(str(issue) for issue in warnings[:20])
            raise OntoUMLConversionError(f"Conversion produced warnings and --fail-on-warning was used:\n{joined}")


def load_json_object(path: Path) -> MutableMapping[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError as exc:
        raise OntoUMLConversionError(f"Missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise OntoUMLConversionError(f"Invalid JSON in {path}: {exc.msg} at line {exc.lineno}, column {exc.colno}") from exc
    if not isinstance(data, MutableMapping):
        raise OntoUMLConversionError(f"Expected JSON object in {path}.")
    return data


def iter_ontouml_element_objects(
    obj: Any,
    path: str = "$",
    parent: Mapping[str, Any] | None = None,
) -> Iterator[tuple[Mapping[str, Any], str, Mapping[str, Any] | None]]:
    """Yield JSON objects that look like OntoUML elements.

    Legacy JSON uses nested objects in fields such as `model`, `contents`,
    `properties`, and `diagrams`. Current JSON uses a flat `elements` array.
    Reference objects such as {"id": "class1", "type": "Class"} have no
    semantic payload and are skipped unless they contain more fields.
    """
    if isinstance(obj, Mapping):
        is_element = isinstance(obj.get("id"), str) and isinstance(obj.get("type"), str)
        is_reference_only = set(obj.keys()).issubset({"id", "type"})
        if is_element and not is_reference_only:
            yield obj, path, parent
            parent = obj
        elif is_element and obj.get("type") == "Project":
            # A minimal current-schema Project in tests may have only id/type + containers.
            yield obj, path, parent
            parent = obj

        for key, value in obj.items():
            if key in {"general", "specific", "propertyType"} and isinstance(value, Mapping) and set(value.keys()).issubset({"id", "type"}):
                continue
            next_path = f"{path}.{key}"
            yield from iter_ontouml_element_objects(value, next_path, parent)
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            yield from iter_ontouml_element_objects(item, f"{path}[{index}]", parent)


def reference_fields_for_element(element: Mapping[str, Any]) -> set[str]:
    """Return fields whose values are intra-model references for this element.

    Most reference fields are global, but `text` is ambiguous in OntoUML JSON:
    it is literal content for Note elements and a Text-shape reference for
    NoteView/GeneralizationSetView elements. Treat it as a reference only in
    view elements.
    """
    fields = set(REFERENCE_FIELDS)
    if element.get("type") in {"NoteView", "GeneralizationSetView"}:
        fields.add("text")
    return fields


def iter_reference_ids(value: Any) -> Iterator[str]:
    if value is None:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        ref_id = value.get("id")
        if isinstance(ref_id, str):
            yield ref_id
        else:
            # Current schema language strings/resources are mappings but not references.
            return
    elif isinstance(value, list):
        for item in value:
            yield from iter_reference_ids(item)


def normalize_cardinality(value: str) -> tuple[str, str, str]:
    value = value.strip()
    if value == "*":
        return "0", "*", "0..*"
    if ".." in value:
        lower, upper = value.split("..", 1)
        if lower == "*":
            lower = "0"
        return lower, upper, f"{lower}..{upper}"
    return value, value, f"{value}..{value}"


def ensure_uri_separator(uri: str) -> str:
    if uri.endswith(("/", "#")):
        return uri
    return uri + "/"


def ensure_element_base_uri(uri: str) -> str:
    if uri.endswith(("/", "#")):
        return uri
    return uri + "/"


def infer_existing_element_uri_style(output_ttl: Path, dataset_uri: str) -> str | None:
    """Infer slash/hash element URI style from an existing ontology.ttl file.

    Existing catalog files are not uniform: some datasets mint element URIs
    below `<dataset>/`, while others use `<dataset>#`. When regenerating an
    existing dataset, preserving this convention avoids unnecessary identifier
    churn.
    """
    if not output_ttl.is_file():
        return None
    graph = Graph()
    try:
        graph.parse(output_ttl, format="turtle")
    except Exception:
        return None

    dataset = URIRef(ensure_uri_separator(dataset_uri))
    slash_prefix = str(dataset)
    hash_prefix = slash_prefix.rstrip("/") + "#"
    for root in graph.objects(dataset, ONTOUML.model):
        root_value = str(root)
        if root_value.startswith(hash_prefix):
            return "hash"
        if root_value.startswith(slash_prefix):
            return "slash"
    return None


if __name__ == "__main__":
    raise SystemExit(main())

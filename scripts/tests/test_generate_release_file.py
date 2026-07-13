from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import XSD


PREDICATE = URIRef("https://example.org/p")
MODEL_NAMESPACE_BASE = "https://w3id.org/ontouml-models/model/"
PREFIX_DECLARATION_PATTERN = re.compile(
    r"^@prefix\s+([A-Za-z][A-Za-z0-9_]*)\s*:\s*<([^>]+)>\s*\.\s*$",
    re.MULTILINE,
)
DEFAULT_PREFIX_DECLARATION_PATTERN = re.compile(
    r"^@prefix\s+default\d*\s*:", re.MULTILINE
)
MODEL_DEFAULT_PREFIX_DECLARATION_PATTERN = re.compile(
    rf"^@prefix\s*:\s*<{re.escape(MODEL_NAMESPACE_BASE)}", re.MULTILINE
)


def load_module():
    script = None
    for parent in Path(__file__).resolve().parents:
        for candidate in (
            parent / "generate_release_file.py",
            parent / "scripts" / "generate_release_file.py",
        ):
            if candidate.exists():
                script = candidate
                break
        if script is not None:
            break

    assert script is not None
    spec = importlib.util.spec_from_file_location("generate_release_file", script)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_ttl(path: Path, subject: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"<https://example.org/{subject}> <https://example.org/p> {value!r} .\n",
        encoding="utf-8",
    )


def write_model_ttl(
    path: Path,
    namespace: str,
    local_name: str,
    value: str,
    *,
    include_blank_node: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blank_node_statement = ""
    if include_blank_node:
        blank_node_statement = (
            f":{local_name} <https://example.org/detail> "
            '[ <https://example.org/value> "nested" ] .\n'
        )
    path.write_text(
        f"@prefix : <{namespace}> .\n"
        f"@prefix ex: <https://example.org/> .\n\n"
        f':{local_name} ex:p "{value}" .\n'
        f"{blank_node_statement}",
        encoding="utf-8",
    )


def parse_graph(path: Path) -> Graph:
    graph = Graph()
    graph.parse(path, format="turtle")
    return graph


def parse_catalog_sources(module, catalog_path: Path) -> Graph:
    graph = Graph()
    for ttl_file in module.list_release_ttl_files(catalog_path):
        graph.parse(ttl_file, format="turtle")
    return graph


def model_prefixes(turtle_text: str) -> dict[str, str]:
    return {
        namespace: prefix
        for prefix, namespace in PREFIX_DECLARATION_PATTERN.findall(turtle_text)
        if namespace.startswith(MODEL_NAMESPACE_BASE)
    }


def assert_triple(
    graph: Graph, subject: str, value: str, *, present: bool = True
) -> None:
    triple = (URIRef(f"https://example.org/{subject}"), PREDICATE, Literal(value))
    if present:
        assert triple in graph
    else:
        assert triple not in graph


def test_generate_release_file_aggregates_catalog_and_model_ttl_but_excludes_non_release_files(
    tmp_path: Path,
):
    module = load_module()

    write_ttl(tmp_path / "catalog.ttl", "catalog", "catalog")
    write_ttl(tmp_path / "models" / "example" / "metadata.ttl", "metadata", "metadata")
    write_ttl(tmp_path / "models" / "example" / "ontology.ttl", "ontology", "ontology")

    write_ttl(tmp_path / "shapes" / "Resource-shape.ttl", "shape", "shape")
    write_ttl(
        tmp_path / "models" / "example" / "metadata-shape.ttl",
        "model-shape",
        "model-shape",
    )
    write_ttl(tmp_path / "vocabulary.ttl", "vocabulary", "vocabulary")
    write_ttl(tmp_path / "results" / "ontouml-models-19990101.ttl", "old", "old")
    write_ttl(tmp_path / "catalog-release.ttl", "ignored-release", "ignored-release")
    write_ttl(tmp_path / ".cache" / "hidden.ttl", "hidden", "hidden")

    output_file = module.generate_release_file(
        module.ReleaseConfig(
            catalog_path=tmp_path,
            output_dir=tmp_path / "results",
            release_tag="20260702",
        )
    )

    assert output_file == tmp_path / "results" / "ontouml-models-20260702.ttl"
    assert output_file.exists()

    graph = parse_graph(output_file)

    assert_triple(graph, "catalog", "catalog")
    assert_triple(graph, "metadata", "metadata")
    assert_triple(graph, "ontology", "ontology")

    assert_triple(graph, "shape", "shape", present=False)
    assert_triple(graph, "model-shape", "model-shape", present=False)
    assert_triple(graph, "vocabulary", "vocabulary", present=False)
    assert_triple(graph, "old", "old", present=False)
    assert_triple(graph, "ignored-release", "ignored-release", present=False)
    assert_triple(graph, "hidden", "hidden", present=False)


def test_relative_output_dir_is_resolved_under_catalog_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    module = load_module()

    catalog = tmp_path / "catalog"
    other_cwd = tmp_path / "other"
    other_cwd.mkdir()

    write_ttl(catalog / "catalog.ttl", "catalog", "catalog")
    (catalog / "models").mkdir(exist_ok=True)

    monkeypatch.chdir(other_cwd)

    output_file = module.generate_release_file(
        module.ReleaseConfig(
            catalog_path=catalog,
            output_dir=Path("custom-results"),
            release_tag="20260702",
        )
    )

    assert output_file == catalog / "custom-results" / "ontouml-models-20260702.ttl"
    assert output_file.exists()
    assert not (other_cwd / "custom-results").exists()


def test_release_tag_whitespace_is_normalized(tmp_path: Path):
    module = load_module()

    write_ttl(tmp_path / "catalog.ttl", "catalog", "catalog")
    (tmp_path / "models").mkdir(exist_ok=True)

    output_file = module.generate_release_file(
        module.ReleaseConfig(
            catalog_path=tmp_path,
            output_dir=tmp_path / "results",
            release_tag=" 20260702 ",
        )
    )

    assert output_file.name == "ontouml-models-20260702.ttl"


@pytest.mark.parametrize(
    "release_tag",
    ["", "2026072", "202607020", "release", "2026-07-02"],
)
def test_release_tag_must_use_yyyymmdd_format(tmp_path: Path, release_tag: str):
    module = load_module()
    (tmp_path / "models").mkdir()

    with pytest.raises(module.ReleaseGenerationError, match="YYYYMMDD"):
        module.generate_release_file(
            module.ReleaseConfig(
                catalog_path=tmp_path,
                output_dir=tmp_path / "results",
                release_tag=release_tag,
            )
        )


@pytest.mark.parametrize("release_tag", ["20260230", "20261301", "20260001"])
def test_release_tag_must_be_valid_calendar_date(tmp_path: Path, release_tag: str):
    module = load_module()
    (tmp_path / "models").mkdir()

    with pytest.raises(module.ReleaseGenerationError, match="valid calendar date"):
        module.generate_release_file(
            module.ReleaseConfig(
                catalog_path=tmp_path,
                output_dir=tmp_path / "results",
                release_tag=release_tag,
            )
        )


def test_missing_catalog_path_fails_clearly(tmp_path: Path):
    module = load_module()

    missing_path = tmp_path / "missing"

    with pytest.raises(module.ReleaseGenerationError, match="does not exist"):
        module.generate_release_file(
            module.ReleaseConfig(
                catalog_path=missing_path,
                output_dir=tmp_path / "results",
                release_tag="20260702",
            )
        )


def test_catalog_path_must_be_directory(tmp_path: Path):
    module = load_module()

    file_path = tmp_path / "not-a-directory"
    file_path.write_text("content", encoding="utf-8")

    with pytest.raises(module.ReleaseGenerationError, match="not a directory"):
        module.generate_release_file(
            module.ReleaseConfig(
                catalog_path=file_path,
                output_dir=tmp_path / "results",
                release_tag="20260702",
            )
        )


def test_catalog_path_must_contain_models_directory(tmp_path: Path):
    module = load_module()

    write_ttl(tmp_path / "catalog.ttl", "catalog", "catalog")

    with pytest.raises(module.ReleaseGenerationError, match="models/ directory"):
        module.generate_release_file(
            module.ReleaseConfig(
                catalog_path=tmp_path,
                output_dir=tmp_path / "results",
                release_tag="20260702",
            )
        )


def test_no_includable_turtle_files_fails_clearly(tmp_path: Path):
    module = load_module()

    (tmp_path / "models").mkdir()
    write_ttl(tmp_path / "shapes" / "Resource-shape.ttl", "shape", "shape")
    write_ttl(tmp_path / "vocabulary.ttl", "vocabulary", "vocabulary")

    with pytest.raises(module.ReleaseGenerationError, match="No Turtle files found"):
        module.generate_release_file(
            module.ReleaseConfig(
                catalog_path=tmp_path,
                output_dir=tmp_path / "results",
                release_tag="20260702",
            )
        )


def test_invalid_turtle_fails_with_clear_file_path(tmp_path: Path):
    module = load_module()

    (tmp_path / "models" / "broken").mkdir(parents=True)
    (tmp_path / "models" / "broken" / "metadata.ttl").write_text(
        "not valid turtle",
        encoding="utf-8",
    )

    with pytest.raises(
        module.ReleaseGenerationError, match="models/broken/metadata.ttl"
    ):
        module.generate_release_file(
            module.ReleaseConfig(
                catalog_path=tmp_path,
                output_dir=tmp_path / "results",
                release_tag="20260702",
            )
        )


def test_list_release_ttl_files_is_deterministic_and_repository_relative(
    tmp_path: Path,
):
    module = load_module()

    write_ttl(tmp_path / "models" / "z-model" / "metadata.ttl", "z", "z")
    write_ttl(tmp_path / "catalog.ttl", "catalog", "catalog")
    write_ttl(tmp_path / "models" / "a-model" / "metadata.ttl", "a", "a")

    listed = [
        module.repository_relative_path(path, tmp_path)
        for path in module.list_release_ttl_files(tmp_path)
    ]

    assert listed == [
        "catalog.ttl",
        "models/a-model/metadata.ttl",
        "models/z-model/metadata.ttl",
    ]


def test_list_files_prints_included_files_but_not_excluded_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    module = load_module()

    write_ttl(tmp_path / "catalog.ttl", "catalog", "catalog")
    write_ttl(tmp_path / "models" / "example" / "metadata.ttl", "metadata", "metadata")
    write_ttl(tmp_path / "shapes" / "Resource-shape.ttl", "shape", "shape")
    write_ttl(tmp_path / "vocabulary.ttl", "vocabulary", "vocabulary")

    module.generate_release_file(
        module.ReleaseConfig(
            catalog_path=tmp_path,
            output_dir=tmp_path / "results",
            release_tag="20260702",
            list_files=True,
        )
    )

    output = capsys.readouterr().out

    assert "- catalog.ttl" in output
    assert "- models/example/metadata.ttl" in output
    assert "- shapes/Resource-shape.ttl" not in output
    assert "- vocabulary.ttl" not in output


def test_main_returns_zero_and_writes_release_file(tmp_path: Path):
    module = load_module()

    write_ttl(tmp_path / "catalog.ttl", "catalog", "catalog")
    (tmp_path / "models").mkdir(exist_ok=True)

    exit_code = module.main(
        [
            str(tmp_path),
            "--release-tag",
            "20260702",
            "--output-dir",
            str(tmp_path / "results"),
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "results" / "ontouml-models-20260702.ttl").exists()


def test_main_returns_nonzero_for_invalid_input(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    module = load_module()

    (tmp_path / "models").mkdir()

    exit_code = module.main(
        [
            str(tmp_path),
            "--release-tag",
            "2026-07-02",
            "--output-dir",
            str(tmp_path / "results"),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "ERROR:" in captured.err
    assert "YYYYMMDD" in captured.err


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("Abel2015Petroleum-System", "abel2015petroleum_system"),
        ("123-model", "model_123_model"),
        ("--A  B///C--", "a_b_c"),
        ("___", "model"),
        ("Straße", "strasse"),
    ],
)
def test_sanitize_model_prefix_handles_edge_cases_deterministically(
    identifier: str,
    expected: str,
):
    module = load_module()

    result = module.sanitize_model_prefix(identifier)

    assert result == expected
    assert module.VALID_GENERATED_PREFIX_PATTERN.fullmatch(result)


@pytest.mark.parametrize(
    ("namespace", "expected"),
    [
        (
            f"{MODEL_NAMESPACE_BASE}abel2015petroleum-system#",
            "abel2015petroleum-system",
        ),
        (
            f"{MODEL_NAMESPACE_BASE}slash-style/",
            "slash-style",
        ),
        (MODEL_NAMESPACE_BASE, ""),
        (f"{MODEL_NAMESPACE_BASE}not-a-namespace", None),
        ("https://example.org/model/example#", None),
    ],
)
def test_model_identifier_from_namespace_supports_hash_and_slash_styles(
    namespace: str,
    expected: str | None,
):
    module = load_module()

    assert module.model_identifier_from_namespace(namespace) == expected


def test_generated_release_uses_meaningful_prefixes_for_hash_and_slash_namespaces(
    tmp_path: Path,
):
    module = load_module()

    hash_namespace = f"{MODEL_NAMESPACE_BASE}abel2015petroleum-system#"
    slash_namespace = f"{MODEL_NAMESPACE_BASE}abrahao2018agriculture-operations/"
    write_model_ttl(
        tmp_path / "models" / "hash-model" / "ontology.ttl",
        hash_namespace,
        "HashSubject",
        "hash",
    )
    write_model_ttl(
        tmp_path / "models" / "slash-model" / "ontology.ttl",
        slash_namespace,
        "SlashSubject",
        "slash",
    )

    output_file = module.generate_release_file(
        module.ReleaseConfig(
            catalog_path=tmp_path,
            output_dir=tmp_path / "results",
            release_tag="20260702",
        )
    )
    turtle_text = output_file.read_text(encoding="utf-8")
    prefixes = model_prefixes(turtle_text)

    assert prefixes == {
        hash_namespace: "abel2015petroleum_system",
        slash_namespace: "abrahao2018agriculture_operations",
    }
    assert not DEFAULT_PREFIX_DECLARATION_PATTERN.search(turtle_text)
    assert not MODEL_DEFAULT_PREFIX_DECLARATION_PATTERN.search(turtle_text)

    graph = parse_graph(output_file)
    assert (
        URIRef(f"{hash_namespace}HashSubject"),
        PREDICATE,
        Literal("hash"),
    ) in graph
    assert (
        URIRef(f"{slash_namespace}SlashSubject"),
        PREDICATE,
        Literal("slash"),
    ) in graph


def test_normalization_collisions_are_resolved_by_sorted_namespace_iri(
    tmp_path: Path,
):
    module = load_module()

    first_namespace = f"{MODEL_NAMESPACE_BASE}collision-model#"
    second_namespace = f"{MODEL_NAMESPACE_BASE}collision_model#"
    write_model_ttl(
        tmp_path / "models" / "z-model" / "ontology.ttl",
        second_namespace,
        "Second",
        "second",
    )
    write_model_ttl(
        tmp_path / "models" / "a-model" / "ontology.ttl",
        first_namespace,
        "First",
        "first",
    )

    output_file = module.generate_release_file(
        module.ReleaseConfig(
            catalog_path=tmp_path,
            output_dir=tmp_path / "results",
            release_tag="20260702",
        )
    )

    assert model_prefixes(output_file.read_text(encoding="utf-8")) == {
        first_namespace: "collision_model",
        second_namespace: "collision_model_2",
    }


def test_prefix_assignment_is_independent_of_graph_parse_order():
    module = load_module()

    namespaces = [
        f"{MODEL_NAMESPACE_BASE}collision_model#",
        f"{MODEL_NAMESPACE_BASE}collision-model#",
        f"{MODEL_NAMESPACE_BASE}123-model/",
    ]
    graphs = []
    for parse_order in (namespaces, list(reversed(namespaces))):
        graph = Graph()
        for index, namespace in enumerate(parse_order):
            graph.parse(
                data=(
                    f"@prefix : <{namespace}> .\n"
                    f"@prefix ex: <https://example.org/> .\n"
                    f':subject{index} ex:p "value{index}" .\n'
                ),
                format="turtle",
            )
        module.bind_release_prefixes(graph)
        graphs.append(module.bind_model_prefixes(graph))

    assert (
        graphs[0]
        == graphs[1]
        == {
            f"{MODEL_NAMESPACE_BASE}123-model/": "model_123_model",
            f"{MODEL_NAMESPACE_BASE}collision-model#": "collision_model",
            f"{MODEL_NAMESPACE_BASE}collision_model#": "collision_model_2",
        }
    )


def test_generated_model_prefixes_do_not_replace_established_shared_prefixes(
    tmp_path: Path,
):
    module = load_module()

    namespace = f"{MODEL_NAMESPACE_BASE}dcat#"
    ontology_file = tmp_path / "models" / "dcat" / "ontology.ttl"
    write_model_ttl(
        ontology_file,
        namespace,
        "Subject",
        "value",
    )
    ontology_file.write_text(
        ontology_file.read_text(encoding="utf-8")
        + "@prefix dcat: <http://www.w3.org/ns/dcat#> .\n"
        + ":Subject a dcat:Dataset .\n",
        encoding="utf-8",
    )

    output_file = module.generate_release_file(
        module.ReleaseConfig(
            catalog_path=tmp_path,
            output_dir=tmp_path / "results",
            release_tag="20260702",
        )
    )
    turtle_text = output_file.read_text(encoding="utf-8")

    assert "@prefix dcat: <http://www.w3.org/ns/dcat#> ." in turtle_text
    assert model_prefixes(turtle_text)[namespace] == "dcat_2"


def test_generated_model_prefix_labels_use_a_valid_conservative_turtle_subset(
    tmp_path: Path,
):
    module = load_module()

    namespaces = [
        f"{MODEL_NAMESPACE_BASE}123%20model#",
        f"{MODEL_NAMESPACE_BASE}Repeated---Separators/",
        f"{MODEL_NAMESPACE_BASE}___#",
        f"{MODEL_NAMESPACE_BASE}mixed.CASE-model#",
    ]
    for index, namespace in enumerate(namespaces):
        write_model_ttl(
            tmp_path / "models" / f"model-{index}" / "ontology.ttl",
            namespace,
            f"Subject{index}",
            f"value-{index}",
        )

    output_file = module.generate_release_file(
        module.ReleaseConfig(
            catalog_path=tmp_path,
            output_dir=tmp_path / "results",
            release_tag="20260702",
        )
    )
    prefixes = model_prefixes(output_file.read_text(encoding="utf-8"))

    assert set(prefixes) == set(namespaces)
    assert all(
        module.VALID_GENERATED_PREFIX_PATTERN.fullmatch(prefix)
        for prefix in prefixes.values()
    )
    assert len(prefixes.values()) == len(set(prefixes.values()))


def test_prefix_correction_preserves_rdf_graph_semantics_including_blank_nodes(
    tmp_path: Path,
):
    module = load_module()

    write_ttl(tmp_path / "catalog.ttl", "catalog", "catalog")
    namespace = f"{MODEL_NAMESPACE_BASE}semantic-check#"
    ontology_file = tmp_path / "models" / "hash-model" / "ontology.ttl"
    write_model_ttl(
        ontology_file,
        namespace,
        "Subject",
        "value",
        include_blank_node=True,
    )
    ontology_file.write_text(
        ontology_file.read_text(encoding="utf-8")
        + "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
        + ':Subject <https://example.org/label> "Label"@en ;\n'
        + '    <https://example.org/count> "1"^^xsd:integer .\n',
        encoding="utf-8",
    )

    expected_graph = parse_catalog_sources(module, tmp_path)
    output_file = module.generate_release_file(
        module.ReleaseConfig(
            catalog_path=tmp_path,
            output_dir=tmp_path / "results",
            release_tag="20260702",
        )
    )
    actual_graph = parse_graph(output_file)

    assert len(actual_graph) == len(expected_graph)
    assert isomorphic(actual_graph, expected_graph)
    assert any(isinstance(term, BNode) for triple in actual_graph for term in triple)
    assert (
        URIRef(f"{namespace}Subject"),
        URIRef("https://example.org/label"),
        Literal("Label", lang="en"),
    ) in actual_graph
    assert (
        URIRef(f"{namespace}Subject"),
        URIRef("https://example.org/count"),
        Literal(1, datatype=XSD.integer),
    ) in actual_graph


def test_model_prefix_results_are_stable_across_repeated_runs(tmp_path: Path):
    module = load_module()

    namespaces = [
        f"{MODEL_NAMESPACE_BASE}stable-model#",
        f"{MODEL_NAMESPACE_BASE}stable_model#",
        f"{MODEL_NAMESPACE_BASE}another-model/",
    ]
    for index, namespace in enumerate(namespaces):
        write_model_ttl(
            tmp_path / "models" / f"model-{index}" / "ontology.ttl",
            namespace,
            f"Subject{index}",
            f"value-{index}",
        )

    outputs = []
    graphs = []
    for output_dir in (tmp_path / "results-a", tmp_path / "results-b"):
        output_file = module.generate_release_file(
            module.ReleaseConfig(
                catalog_path=tmp_path,
                output_dir=output_dir,
                release_tag="20260702",
            )
        )
        outputs.append(model_prefixes(output_file.read_text(encoding="utf-8")))
        graphs.append(parse_graph(output_file))

    assert outputs[0] == outputs[1]
    assert isomorphic(graphs[0], graphs[1])

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef


PREDICATE = URIRef("https://example.org/p")


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


def parse_graph(path: Path) -> Graph:
    graph = Graph()
    graph.parse(path, format="turtle")
    return graph


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

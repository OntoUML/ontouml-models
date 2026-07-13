from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCAT, DCTERMS, RDF, XSD


CATALOG_IRI = "https://w3id.org/ontouml-models/catalog/test-catalog"
FDPO_METADATA_MODIFIED = URIRef("https://w3id.org/fdp/fdp-o#metadataModified")
INITIAL_TIMESTAMP = "2025-01-02T03:04:05Z"


def load_module():
    script = None
    for parent in Path(__file__).resolve().parents:
        for candidate in (
            parent / "generate_catalog_file.py",
            parent / "scripts" / "generate_catalog_file.py",
        ):
            if candidate.exists():
                script = candidate
                break
        if script is not None:
            break
    assert script is not None
    spec = importlib.util.spec_from_file_location("generate_catalog_file", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def catalog_source() -> dict:
    return {
        "catalog_iri": CATALOG_IRI,
        "title": "Test Catalog",
        "alternative": "TC",
        "description": "A catalog used by tests.",
        "language": "en",
        "storage_url": "https://example.org/catalog/",
        "theme_taxonomy": "https://example.org/themes",
        "bibliographic_citation": "Example citation.",
        "license": "https://creativecommons.org/licenses/by-sa/4.0/",
        "access_rights": "https://example.org/access/public",
        "issued": "2020-01-02",
        "contact_point": {
            "name": "Catalog Maintainer",
            "email": "mailto:maintainer@example.org",
        },
        "publisher": "https://example.org/publisher",
        "creators": ["https://example.org/creator/a", "https://example.org/creator/b"],
        "is_part_of": "https://example.org/collection",
        "metadata_issued": "2020-01-02T03:04:05Z",
    }


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "models").mkdir(parents=True)
    (root / "catalog.yaml").write_text(
        yaml.safe_dump(catalog_source(), sort_keys=False), encoding="utf-8"
    )
    return root


def write_model_metadata(
    root: Path,
    model_name: str,
    dataset_iri: str,
    *,
    title: str = "Example Model",
    catalog_iri: str = CATALOG_IRI,
    contributors: tuple[str, ...] = (),
) -> Path:
    model = root / "models" / model_name
    model.mkdir(parents=True, exist_ok=True)
    statements = [
        f"<{dataset_iri}> a dcat:Dataset ;",
        f"    dct:isPartOf <{catalog_iri}> ;",
    ]
    if contributors:
        statements.append(f'    dct:title "{title}" ;')
        rendered = ",\n                    ".join(
            f"<{contributor}>" for contributor in contributors
        )
        statements.append(f"    dct:contributor {rendered} .")
    else:
        statements.append(f'    dct:title "{title}" .')
    path = model / "metadata.ttl"
    path.write_text(
        "\n".join(
            [
                "@prefix dcat: <http://www.w3.org/ns/dcat#> .",
                "@prefix dct: <http://purl.org/dc/terms/> .",
                "",
                *statements,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def config(
    module,
    root: Path,
    *,
    check: bool = False,
    generation_timestamp: str | None = INITIAL_TIMESTAMP,
):
    return module.Config(
        repository_path=root,
        source_path=root / "catalog.yaml",
        output_path=root / "catalog.ttl",
        models_path=root / "models",
        check=check,
        generation_timestamp=generation_timestamp,
    )


def catalog_datasets(root: Path) -> list[str]:
    graph = Graph().parse(root / "catalog.ttl", format="turtle")
    return sorted(
        str(value) for value in graph.objects(URIRef(CATALOG_IRI), DCAT.dataset)
    )


def catalog_contributors(root: Path) -> list[str]:
    graph = Graph().parse(root / "catalog.ttl", format="turtle")
    return sorted(
        str(value) for value in graph.objects(URIRef(CATALOG_IRI), DCTERMS.contributor)
    )


def catalog_timestamps(root: Path) -> tuple[Literal, Literal]:
    graph = Graph().parse(root / "catalog.ttl", format="turtle")
    catalog = URIRef(CATALOG_IRI)
    modified = list(graph.objects(catalog, DCTERMS.modified))
    metadata_modified = list(graph.objects(catalog, FDPO_METADATA_MODIFIED))
    assert len(modified) == 1
    assert len(metadata_modified) == 1
    assert isinstance(modified[0], Literal)
    assert isinstance(metadata_modified[0], Literal)
    return modified[0], metadata_modified[0]


def assert_datetime_literal(actual: Literal, lexical: str) -> None:
    expected = Literal(lexical, datatype=XSD.dateTime, normalize=False)
    assert actual.datatype == XSD.dateTime
    assert actual.eq(expected)


def test_write_generates_parseable_catalog_with_sorted_exact_dataset_iris(
    tmp_path: Path,
):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(root, "z-model", "https://example.org/model/z/")
    write_model_metadata(root, "a-model", "https://example.org/model/a")

    synchronized = module.generate_catalog(config(module, root))

    assert synchronized is False
    assert catalog_datasets(root) == [
        "https://example.org/model/a",
        "https://example.org/model/z/",
    ]
    text = (root / "catalog.ttl").read_text(encoding="utf-8")
    assert text.index("<https://example.org/model/a>") < text.index(
        "<https://example.org/model/z/>"
    )
    modified, metadata_modified = catalog_timestamps(root)
    expected = Literal(INITIAL_TIMESTAMP, datatype=XSD.dateTime, normalize=False)
    assert modified.eq(expected)
    assert metadata_modified.eq(expected)


def test_repeated_write_is_deterministic_and_idempotent(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(root, "example", "https://example.org/model/example/")

    assert module.generate_catalog(config(module, root)) is False
    first = (root / "catalog.ttl").read_bytes()
    assert (
        module.generate_catalog(
            config(
                module,
                root,
                generation_timestamp="2026-02-03T04:05:06Z",
            )
        )
        is True
    )
    second = (root / "catalog.ttl").read_bytes()

    assert second == first


def test_catalog_metadata_change_preserves_modified_and_updates_metadata_modified(
    tmp_path: Path,
):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(root, "example", "https://example.org/model/example/")
    module.generate_catalog(config(module, root))

    source = catalog_source()
    source["title"] = "Updated Test Catalog"
    (root / "catalog.yaml").write_text(
        yaml.safe_dump(source, sort_keys=False), encoding="utf-8"
    )
    next_timestamp = "2026-02-03T04:05:06Z"
    module.generate_catalog(config(module, root, generation_timestamp=next_timestamp))

    modified, metadata_modified = catalog_timestamps(root)
    assert_datetime_literal(modified, INITIAL_TIMESTAMP)
    assert_datetime_literal(metadata_modified, next_timestamp)


def test_catalog_membership_change_updates_both_timestamps(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(root, "one", "https://example.org/model/one/")
    module.generate_catalog(config(module, root))

    write_model_metadata(root, "two", "https://example.org/model/two/")
    next_timestamp = "2026-02-03T04:05:06Z"
    module.generate_catalog(config(module, root, generation_timestamp=next_timestamp))

    modified, metadata_modified = catalog_timestamps(root)
    assert_datetime_literal(modified, next_timestamp)
    assert_datetime_literal(metadata_modified, next_timestamp)


def test_catalog_iri_change_initializes_timestamps_for_new_catalog_subject(
    tmp_path: Path,
):
    module = load_module()
    root = make_repo(tmp_path)
    metadata_path = write_model_metadata(
        root, "example", "https://example.org/model/example/"
    )
    module.generate_catalog(config(module, root))

    new_catalog_iri = "https://example.org/catalog/new"
    source = catalog_source()
    source["catalog_iri"] = new_catalog_iri
    (root / "catalog.yaml").write_text(
        yaml.safe_dump(source, sort_keys=False), encoding="utf-8"
    )
    metadata_path.write_text(
        metadata_path.read_text(encoding="utf-8").replace(CATALOG_IRI, new_catalog_iri),
        encoding="utf-8",
    )

    next_timestamp = "2026-02-03T04:05:06Z"
    module.generate_catalog(config(module, root, generation_timestamp=next_timestamp))

    graph = Graph().parse(root / "catalog.ttl", format="turtle")
    catalog = URIRef(new_catalog_iri)
    timestamp = Literal(next_timestamp, datatype=XSD.dateTime, normalize=False)
    assert any(
        value.eq(timestamp) for value in graph.objects(catalog, DCTERMS.modified)
    )
    assert any(
        value.eq(timestamp) for value in graph.objects(catalog, FDPO_METADATA_MODIFIED)
    )


def test_explicit_generation_timestamp_is_normalized_to_utc(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(root, "example", "https://example.org/model/example/")

    module.generate_catalog(
        config(
            module,
            root,
            generation_timestamp="2025-01-02T05:04:05+02:00",
        )
    )

    modified, metadata_modified = catalog_timestamps(root)
    assert_datetime_literal(modified, INITIAL_TIMESTAMP)
    assert_datetime_literal(metadata_modified, INITIAL_TIMESTAMP)


def test_existing_date_precision_modified_is_preserved_until_membership_changes(
    tmp_path: Path,
):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(root, "example", "https://example.org/model/example/")
    module.generate_catalog(config(module, root))

    catalog_path = root / "catalog.ttl"
    catalog_path.write_text(
        catalog_path.read_text(encoding="utf-8").replace(
            f'dct:modified "{INITIAL_TIMESTAMP}"^^xsd:dateTime',
            'dct:modified "2023-03-15"^^xsd:date',
        ),
        encoding="utf-8",
    )
    source = catalog_source()
    source["title"] = "Updated Test Catalog"
    (root / "catalog.yaml").write_text(
        yaml.safe_dump(source, sort_keys=False), encoding="utf-8"
    )

    next_timestamp = "2026-02-03T04:05:06Z"
    module.generate_catalog(config(module, root, generation_timestamp=next_timestamp))

    modified, metadata_modified = catalog_timestamps(root)
    assert modified == Literal("2023-03-15", datatype=XSD.date)
    assert_datetime_literal(metadata_modified, next_timestamp)


def test_serialization_only_difference_preserves_timestamps(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(root, "example", "https://example.org/model/example/")
    module.generate_catalog(config(module, root))

    catalog_path = root / "catalog.ttl"
    graph = Graph().parse(catalog_path, format="turtle")
    graph.serialize(destination=catalog_path, format="turtle")
    noncanonical = catalog_path.read_bytes()

    assert (
        module.generate_catalog(
            config(
                module,
                root,
                generation_timestamp="2026-02-03T04:05:06Z",
            )
        )
        is False
    )
    assert catalog_path.read_bytes() != noncanonical
    modified, metadata_modified = catalog_timestamps(root)
    assert_datetime_literal(modified, INITIAL_TIMESTAMP)
    assert_datetime_literal(metadata_modified, INITIAL_TIMESTAMP)


def test_check_mode_accepts_semantically_equivalent_serialization(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(root, "example", "https://example.org/model/example/")
    module.generate_catalog(config(module, root))

    catalog_path = root / "catalog.ttl"
    graph = Graph().parse(catalog_path, format="turtle")
    graph.serialize(destination=catalog_path, format="turtle")
    noncanonical = catalog_path.read_bytes()

    assert module.generate_catalog(config(module, root, check=True)) is True
    assert catalog_path.read_bytes() == noncanonical


def test_check_mode_passes_when_synchronized(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(root, "example", "https://example.org/model/example/")
    module.generate_catalog(config(module, root))

    assert module.generate_catalog(config(module, root, check=True)) is True
    assert module.main([str(root), "--check"]) == 0


def test_check_mode_reports_missing_expected_dataset_without_writing(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(root, "one", "https://example.org/model/one/")
    module.generate_catalog(config(module, root))
    original = (root / "catalog.ttl").read_text(encoding="utf-8")
    write_model_metadata(root, "two", "https://example.org/model/two/")

    assert module.generate_catalog(config(module, root, check=True)) is False
    assert (root / "catalog.ttl").read_text(encoding="utf-8") == original
    assert module.main([str(root), "--check"]) == 1


def test_check_mode_reports_change_category_without_updating_timestamps(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(root, "example", "https://example.org/model/example/")
    module.generate_catalog(config(module, root))
    original = (root / "catalog.ttl").read_bytes()

    source = catalog_source()
    source["description"] = "Updated catalog metadata."
    (root / "catalog.yaml").write_text(
        yaml.safe_dump(source, sort_keys=False), encoding="utf-8"
    )

    assert module.generate_catalog(config(module, root, check=True)) is False
    captured = capsys.readouterr()
    assert "catalog metadata changed" in captured.err
    assert (root / "catalog.ttl").read_bytes() == original


def test_write_adds_new_dataset_and_removes_stale_dataset(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    first_path = write_model_metadata(root, "first", "https://example.org/model/first/")
    module.generate_catalog(config(module, root))

    write_model_metadata(root, "second", "https://example.org/model/second/")
    module.generate_catalog(config(module, root))
    assert catalog_datasets(root) == [
        "https://example.org/model/first/",
        "https://example.org/model/second/",
    ]

    first_path.unlink()
    first_path.parent.rmdir()
    module.generate_catalog(config(module, root))
    assert catalog_datasets(root) == ["https://example.org/model/second/"]


def test_directory_rename_preserves_output_when_dataset_iri_is_stable(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(root, "old-name", "https://example.org/model/stable/")
    module.generate_catalog(config(module, root))
    before = (root / "catalog.ttl").read_bytes()

    (root / "models" / "old-name").rename(root / "models" / "new-name")
    assert module.generate_catalog(config(module, root)) is True

    assert (root / "catalog.ttl").read_bytes() == before


def test_dataset_iri_change_updates_catalog(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    path = write_model_metadata(root, "example", "https://example.org/model/old/")
    module.generate_catalog(config(module, root))

    path.write_text(
        path.read_text(encoding="utf-8").replace("/old/", "/new/"),
        encoding="utf-8",
    )
    module.generate_catalog(config(module, root))

    assert catalog_datasets(root) == ["https://example.org/model/new/"]


def test_non_identity_metadata_change_does_not_change_catalog(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    path = write_model_metadata(root, "example", "https://example.org/model/stable/")
    module.generate_catalog(config(module, root))
    before = (root / "catalog.ttl").read_bytes()

    path.write_text(
        path.read_text(encoding="utf-8").replace("Example Model", "Renamed Model"),
        encoding="utf-8",
    )

    assert module.generate_catalog(config(module, root)) is True
    assert (root / "catalog.ttl").read_bytes() == before


def test_catalog_level_metadata_is_generated_from_yaml(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(
        root,
        "example",
        "https://example.org/model/example/",
        contributors=("https://example.org/contributor/a",),
    )
    module.generate_catalog(config(module, root))

    graph = Graph().parse(root / "catalog.ttl", format="turtle")
    catalog = URIRef(CATALOG_IRI)
    assert (catalog, DCTERMS.title, Literal("Test Catalog", lang="en")) in graph
    assert (
        catalog,
        DCTERMS.description,
        Literal("A catalog used by tests.", lang="en"),
    ) in graph
    assert (
        catalog,
        DCTERMS.contributor,
        URIRef("https://example.org/contributor/a"),
    ) in graph

    text = (root / "catalog.ttl").read_text(encoding="utf-8")
    assert '"2020-01-02"^^xsd:date' in text
    assert '"2020-01-02T03:04:05Z"^^xsd:dateTime' in text
    assert text.count(f'"{INITIAL_TIMESTAMP}"^^xsd:dateTime') == 2


def test_missing_output_fails_in_check_mode_without_creating_file(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(root, "example", "https://example.org/model/example/")

    assert module.generate_catalog(config(module, root, check=True)) is False
    assert not (root / "catalog.ttl").exists()


def test_rejects_duplicate_catalog_source_field(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    source_path = root / "catalog.yaml"
    source_path.write_text(
        source_path.read_text(encoding="utf-8") + "title: Duplicate title\n",
        encoding="utf-8",
    )
    write_model_metadata(root, "example", "https://example.org/model/example/")

    with pytest.raises(module.CatalogGenerationError, match="duplicate key 'title'"):
        module.generate_catalog(config(module, root))


def test_rejects_unknown_catalog_source_field(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    source = catalog_source()
    source["unexpected"] = "value"
    (root / "catalog.yaml").write_text(
        yaml.safe_dump(source, sort_keys=False), encoding="utf-8"
    )
    write_model_metadata(root, "example", "https://example.org/model/example/")

    with pytest.raises(module.CatalogGenerationError, match="unsupported: unexpected"):
        module.generate_catalog(config(module, root))


def test_rejects_missing_catalog_source_field(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    source = catalog_source()
    del source["title"]
    (root / "catalog.yaml").write_text(
        yaml.safe_dump(source, sort_keys=False), encoding="utf-8"
    )
    write_model_metadata(root, "example", "https://example.org/model/example/")

    with pytest.raises(module.CatalogGenerationError, match="missing: title"):
        module.generate_catalog(config(module, root))


@pytest.mark.parametrize("value", ["20230401", "2023-W13-6"])
def test_rejects_non_canonical_catalog_dates(tmp_path: Path, value: str):
    module = load_module()
    root = make_repo(tmp_path)
    source = catalog_source()
    source["issued"] = value
    (root / "catalog.yaml").write_text(
        yaml.safe_dump(source, sort_keys=False), encoding="utf-8"
    )
    write_model_metadata(root, "example", "https://example.org/model/example/")

    with pytest.raises(module.CatalogGenerationError, match="must use YYYY-MM-DD"):
        module.generate_catalog(config(module, root))


@pytest.mark.parametrize(
    "value",
    [
        "20230401T123456Z",
        "2023-04-01 12:34:56+00:00",
        "2023-04-01T12:34Z",
        "2023-04-01T12:34:56+15:00",
    ],
)
def test_rejects_non_canonical_catalog_datetimes(tmp_path: Path, value: str):
    module = load_module()
    root = make_repo(tmp_path)
    source = catalog_source()
    source["metadata_issued"] = value
    (root / "catalog.yaml").write_text(
        yaml.safe_dump(source, sort_keys=False), encoding="utf-8"
    )
    write_model_metadata(root, "example", "https://example.org/model/example/")

    with pytest.raises(module.CatalogGenerationError, match="date-time"):
        module.generate_catalog(config(module, root))


def test_cli_rejects_non_canonical_generation_timestamp(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(root, "example", "https://example.org/model/example/")

    assert (
        module.main([str(root), "--generation-timestamp", "2025-01-02 03:04:05Z"]) == 2
    )


def test_catalog_contributors_include_values_on_other_subjects(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    path = write_model_metadata(
        root,
        "example",
        "https://example.org/model/example/",
        contributors=("https://example.org/contributor/dataset",),
    )
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n<https://example.org/other> dct:contributor "
        + "<https://example.org/contributor/other> .\n",
        encoding="utf-8",
    )

    module.generate_catalog(config(module, root))

    assert catalog_contributors(root) == [
        "https://example.org/contributor/dataset",
        "https://example.org/contributor/other",
    ]


def test_catalog_contributors_are_union_of_model_contributors(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(
        root,
        "one",
        "https://example.org/model/one/",
        contributors=(
            "https://example.org/contributor/a",
            "https://example.org/contributor/b",
        ),
    )
    write_model_metadata(
        root,
        "two",
        "https://example.org/model/two/",
        contributors=(
            "https://example.org/contributor/b",
            "https://example.org/contributor/c",
        ),
    )

    module.generate_catalog(config(module, root))

    assert catalog_contributors(root) == [
        "https://example.org/contributor/a",
        "https://example.org/contributor/b",
        "https://example.org/contributor/c",
    ]
    text = (root / "catalog.ttl").read_text(encoding="utf-8")
    assert text.count("<https://example.org/contributor/b>") == 1


def test_catalog_contributors_collapse_scheme_and_trailing_slash_variants(
    tmp_path: Path,
):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(
        root,
        "one",
        "https://example.org/model/one/",
        contributors=("http://example.org/person/a/",),
    )
    write_model_metadata(
        root,
        "two",
        "https://example.org/model/two/",
        contributors=("https://example.org/person/a",),
    )
    write_model_metadata(
        root,
        "three",
        "https://example.org/model/three/",
        contributors=("https://example.org/person/a/",),
    )

    module.generate_catalog(config(module, root))

    assert catalog_contributors(root) == ["https://example.org/person/a"]


def test_contributor_change_updates_catalog(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    path = write_model_metadata(
        root,
        "example",
        "https://example.org/model/stable/",
        contributors=("https://example.org/contributor/old",),
    )
    module.generate_catalog(config(module, root))
    before = (root / "catalog.ttl").read_bytes()

    path.write_text(
        path.read_text(encoding="utf-8").replace("/old", "/new"),
        encoding="utf-8",
    )
    next_timestamp = "2026-02-03T04:05:06Z"
    assert (
        module.generate_catalog(
            config(module, root, generation_timestamp=next_timestamp)
        )
        is False
    )

    assert (root / "catalog.ttl").read_bytes() != before
    assert catalog_contributors(root) == ["https://example.org/contributor/new"]
    modified, metadata_modified = catalog_timestamps(root)
    assert_datetime_literal(modified, INITIAL_TIMESTAMP)
    assert_datetime_literal(metadata_modified, next_timestamp)


def test_contributor_source_change_with_same_derived_union_changes_nothing(
    tmp_path: Path,
):
    module = load_module()
    root = make_repo(tmp_path)
    contributor = "https://example.org/contributor/shared"
    write_model_metadata(
        root,
        "one",
        "https://example.org/model/one/",
        contributors=(contributor,),
    )
    write_model_metadata(
        root,
        "two",
        "https://example.org/model/two/",
        contributors=(contributor,),
    )
    module.generate_catalog(config(module, root))
    before = (root / "catalog.ttl").read_bytes()

    write_model_metadata(root, "one", "https://example.org/model/one/")
    assert (
        module.generate_catalog(
            config(
                module,
                root,
                generation_timestamp="2026-02-03T04:05:06Z",
            )
        )
        is True
    )

    assert (root / "catalog.ttl").read_bytes() == before


def test_catalog_omits_contributor_when_models_have_none(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(root, "anonymous", "https://example.org/model/anonymous/")

    module.generate_catalog(config(module, root))

    assert catalog_contributors(root) == []
    assert "dct:contributor" not in (root / "catalog.ttl").read_text(encoding="utf-8")


def test_rejects_literal_model_contributor(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    path = write_model_metadata(root, "broken", "https://example.org/model/broken/")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '    dct:title "Example Model" .',
            '    dct:title "Example Model" ;\n    dct:contributor "Not an IRI" .',
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.CatalogGenerationError, match="not an IRI"):
        module.generate_catalog(config(module, root))


def test_rejects_non_http_model_contributor_iri(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(
        root,
        "broken",
        "https://example.org/model/broken/",
        contributors=("urn:example:contributor",),
    )

    with pytest.raises(module.CatalogGenerationError, match=r"HTTP\(S\) IRI"):
        module.generate_catalog(config(module, root))


def test_catalog_source_rejects_manually_configured_contributors(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    source = catalog_source()
    source["contributors"] = ["https://example.org/contributor/manual"]
    (root / "catalog.yaml").write_text(
        yaml.safe_dump(source, sort_keys=False), encoding="utf-8"
    )
    write_model_metadata(root, "example", "https://example.org/model/example/")

    with pytest.raises(
        module.CatalogGenerationError, match="unsupported: contributors"
    ):
        module.generate_catalog(config(module, root))


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("modified", "2024-05-06"),
        ("metadata_modified", "2024-05-06T07:08:09Z"),
    ],
)
def test_catalog_source_rejects_dynamic_timestamp_fields(
    tmp_path: Path, field_name: str, value: str
):
    module = load_module()
    root = make_repo(tmp_path)
    source = catalog_source()
    source[field_name] = value
    (root / "catalog.yaml").write_text(
        yaml.safe_dump(source, sort_keys=False), encoding="utf-8"
    )
    write_model_metadata(root, "example", "https://example.org/model/example/")

    with pytest.raises(
        module.CatalogGenerationError, match=f"unsupported: {field_name}"
    ):
        module.generate_catalog(config(module, root))


def test_rejects_malformed_model_metadata(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = root / "models" / "broken"
    model.mkdir()
    (model / "metadata.ttl").write_text("not turtle", encoding="utf-8")

    with pytest.raises(module.CatalogGenerationError, match="Could not parse"):
        module.generate_catalog(config(module, root))


def test_rejects_model_metadata_without_exactly_one_dataset_subject(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    model = root / "models" / "broken"
    model.mkdir()
    (model / "metadata.ttl").write_text(
        "@prefix dct: <http://purl.org/dc/terms/> .\n"
        '<https://example.org/model/x/> dct:title "No type" .\n',
        encoding="utf-8",
    )

    with pytest.raises(module.CatalogGenerationError, match="found 0"):
        module.generate_catalog(config(module, root))


def test_rejects_dataset_linked_to_different_catalog(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(
        root,
        "wrong",
        "https://example.org/model/wrong/",
        catalog_iri="https://example.org/catalog/other",
    )

    with pytest.raises(
        module.CatalogGenerationError, match="must declare dct:isPartOf"
    ):
        module.generate_catalog(config(module, root))


def test_rejects_duplicate_dataset_iri_across_model_folders(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(root, "one", "https://example.org/model/duplicate/")
    write_model_metadata(root, "two", "https://example.org/model/duplicate/")

    with pytest.raises(module.CatalogGenerationError, match="Duplicate dataset IRI"):
        module.generate_catalog(config(module, root))


def test_rejects_missing_models_directory(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    (root / "models").rmdir()

    with pytest.raises(module.CatalogGenerationError, match="does not exist"):
        module.generate_catalog(config(module, root))


def test_generated_catalog_has_expected_catalog_types(tmp_path: Path):
    module = load_module()
    root = make_repo(tmp_path)
    write_model_metadata(root, "example", "https://example.org/model/example/")
    module.generate_catalog(config(module, root))

    graph = Graph().parse(root / "catalog.ttl", format="turtle")
    catalog = URIRef(CATALOG_IRI)
    assert (catalog, RDF.type, DCAT.Catalog) in graph
    assert (catalog, RDF.type, DCAT.Dataset) in graph
    assert (catalog, RDF.type, DCAT.Resource) in graph

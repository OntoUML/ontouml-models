# Generating `ontology.ttl` from `ontology.json`

This document describes the repository automation for generating each dataset's
linked-data serialization, `ontology.ttl`, from its mandatory `ontology.json` file.

## Purpose

The catalog stores OntoUML/UFO models in machine-readable JSON and Turtle. The
repository documentation states that `ontology.json` is the JSON serialization of
a model and that `ontology.ttl` is the linked-data serialization described with
the OntoUML Vocabulary. The latter is a generated artifact and should not be
manually edited when the corresponding JSON source changes.

## Source and generated files

For this transformation, the source-of-truth file is:

```txt
models/<dataset-folder>/ontology.json
```

The generated file is:

```txt
models/<dataset-folder>/ontology.ttl
```

## Installation

Install the automation dependencies from the repository root:

```bash
pip install -r scripts/requirements.txt
```

The script requires RDFLib. It also supports the official `ontouml-json2graph`
package when requested. The default mode is the built-in RDFLib fallback because it is calibrated against the existing catalog examples. The optional official engine can be selected explicitly, or tried first with `--engine auto`.

## Usage

Generate one dataset:

```bash
python scripts/ontouml_json_to_ttl.py models/<dataset-folder>
```

Generate multiple datasets:

```bash
python scripts/ontouml_json_to_ttl.py models/<dataset-a> models/<dataset-b>
```

Generate all datasets under `models/`:

```bash
python scripts/ontouml_json_to_ttl.py --all models
```

Check whether generated files are current without writing them:

```bash
python scripts/ontouml_json_to_ttl.py --all models --check
```

The `--check` mode is suitable for CI. It exits with status code `1` when at
least one `ontology.ttl` file is missing or stale.

## URI convention

By default, the dataset URI is inferred from the dataset folder name. The dataset URI is used as the `ontouml:Project` subject. Element URIs are minted below the dataset URI.

Existing catalog files are not completely uniform: some use slash-style element URIs, while others use hash-style element URIs. In `--element-uri-style auto` mode, the script inspects an existing `ontology.ttl` and preserves its convention. If no previous `ontology.ttl` exists, it uses slash style.

```txt
Dataset/project URI:
https://w3id.org/ontouml-models/model/<dataset-folder>/

Slash-style element URI:
https://w3id.org/ontouml-models/model/<dataset-folder>/<element-id>

Hash-style element URI:
https://w3id.org/ontouml-models/model/<dataset-folder>#<element-id>
```

Override it for a single dataset with:

```bash
python scripts/ontouml_json_to_ttl.py models/<dataset-folder> \
  --base-uri https://w3id.org/ontouml-models/model/<dataset-folder>/
```

Or change the catalog-wide model URI prefix with:

```bash
python scripts/ontouml_json_to_ttl.py --all models \
  --catalog-model-base-uri https://w3id.org/ontouml-models/model/
```

Force a URI style when needed:

```bash
python scripts/ontouml_json_to_ttl.py models/<dataset-folder> --element-uri-style hash
python scripts/ontouml_json_to_ttl.py models/<dataset-folder> --element-uri-style slash
```

## Engines

The script has three engine modes:

```txt
--engine auto      Prefer ontouml-json2graph, fallback to the built-in RDFLib converter.
--engine official  Require ontouml-json2graph.
--engine fallback  Use only the built-in RDFLib converter.
```

Recommended mode for repository use when matching existing catalog examples:

```bash
python scripts/ontouml_json_to_ttl.py --all models --engine fallback
```

Recommended mode for testing the official engine when installed:

```bash
python scripts/ontouml_json_to_ttl.py --all models --engine auto
```

Recommended mode for a strict CI environment where the official package must be
available:

```bash
python scripts/ontouml_json_to_ttl.py --all models --engine official --check
```

## Error handling

The script reports and fails on:

- missing `ontology.json` files;
- invalid JSON syntax;
- top-level objects that are not OntoUML `Project` objects;
- missing mandatory element IDs or types;
- duplicate element IDs;
- unresolved intra-model references;
- invalid boolean and coordinate values.

The script reports warnings for unsupported or unknown OntoUML stereotypes,
ontological natures, aggregation kinds, and element types. Use
`--fail-on-warning` to make warnings fail the command.

## Diagrammatic data

By default, the script keeps diagrammatic/concrete-syntax data when the selected
engine supports it. To generate only abstract model elements, use:

```bash
python scripts/ontouml_json_to_ttl.py models/<dataset-folder> --model-only
```

## Notes for maintainers

- `ontology.ttl` should be regenerated whenever `ontology.json` changes.
- PRs that manually edit `ontology.ttl` should be reviewed as generated-file
  changes, not as independent source changes.
- The built-in fallback is intentionally conservative and does not replace the
  full validation/correction behavior of the official `ontouml-json2graph`
  package.

# Validate metadata.yaml files

`metadata.yaml` is the authoring source for model-level catalog metadata. The validator implemented in `scripts/validate_metadata_yaml.py` checks that dataset folders contain a usable `metadata.yaml` file before metadata generation, SHACL validation, or future CI/workflow steps.

## What the validator checks

For each selected dataset folder, the script checks:

- `metadata.yaml` file presence;
- YAML syntax;
- duplicate top-level YAML keys;
- whether the root YAML node is a mapping/object;
- presence of mandatory metadata fields;
- presence of expected catalog-template fields;
- non-empty values for mandatory fields;
- field types, such as scalar values versus YAML lists;
- date-like values used by catalog metadata;
- HTTP(S) URI fields;
- Library of Congress Classification values in `theme`;
- controlled values for `ontologyType`, `designedForTask`, `context`, and `representationStyle`;
  accepted forms include compact names, friendly labels, `ocmv:` names, and full OCMV URIs;
- language-tag format for `language`;
- common repository quality rules, such as preferring DBLP/ORCID contributor identifiers and DOI/DBLP source identifiers.

The validator is intentionally YAML-level tooling. RDF/SHACL validation should still be applied to generated Turtle files as a separate stage.

## Mandatory fields

The minimum mandatory fields are aligned with the current `metadata_yaml_to_ttl.py` conversion logic and the metadata YAML documentation:

```yaml
title: Reference Ontology of Trust
issued: 2019
license: https://creativecommons.org/licenses/by/4.0/
theme: H
keyword:
  - trust
```

The script also checks expected catalog-template fields, including `acronym`, `modified`, `contributor`, `editorialNote`, `ontologyType`, `language`, `designedForTask`, `context`, `source`, `representationStyle`, and `landingPage`. Missing expected but non-mandatory fields are warnings by default. Use `--missing-expected-fields error` or `--strict` to make them fatal.

## Supported field spelling

The repository currently contains metadata files using names such as:

```yaml
editorialNote:
ontologyType:
designedForTask:
representationStyle:
landingPage:
```

The converter also accepts snake_case aliases such as `editorial_note`, `ontology_type`, `designed_for_task`, `representation_style`, and `landing_page`. The validator accepts both forms. When `--fix` is used, it rewrites recognized aliases to the repository-preferred template spelling used above.

The optional `iri` field may be either an absolute HTTP(S) IRI or a local slug accepted by the YAML-to-Turtle converter. A local slug must not contain a URI prefix.

## Safe automatic fixes

Use `--fix` to apply deterministic fixes only. The script does **not** guess missing mandatory metadata.

Safe fixes include:

- adding missing non-mandatory expected fields with `null` values;
- wrapping scalar values in lists where the catalog template expects a vector/list;
- normalizing controlled values to the catalog style, for example `Domain` to `domain`;
- normalizing existing `theme` labels such as `Class H - Social Sciences` to compact LCC codes such as `H`;
- replacing known license shorthands such as `CC-BY-4.0` with their canonical URI;
- trimming surrounding whitespace in scalar strings;
- rewriting recognized aliases to repository-preferred field names.

The fix mode rewrites YAML with PyYAML. Comments and hand-formatted spacing are not preserved. Run it only when this is acceptable.

Preview fixes without writing files:

```bash
python scripts/validate_metadata_yaml.py models/<model-directory> --fix --dry-run
```

Apply fixes:

```bash
python scripts/validate_metadata_yaml.py models/<model-directory> --fix
```

## Usage

Run from the repository root.

Validate one dataset folder:

```bash
python scripts/validate_metadata_yaml.py models/<model-directory>
```

Validate multiple dataset folders:

```bash
python scripts/validate_metadata_yaml.py models/<model-1> models/<model-2>
```

Validate all direct dataset folders under `models/`:

```bash
python scripts/validate_metadata_yaml.py --all --models-dir models
```

Run from inside a dataset folder that contains `metadata.yaml`:

```bash
python ../../scripts/validate_metadata_yaml.py
```

Emit JSON output for logs or later workflow integration:

```bash
python scripts/validate_metadata_yaml.py --all --format json
```

Fail on warnings as well as errors:

```bash
python scripts/validate_metadata_yaml.py --all --fail-on-warning
```

Promote policy warnings to errors during validation:

```bash
python scripts/validate_metadata_yaml.py --all --strict
```

## Command-line arguments

| Argument | Required | Default | Meaning |
| --- | --- | --- | --- |
| `datasets` | No | current directory if it contains `metadata.yaml` | One or more dataset folders or `metadata.yaml` files to validate. |
| `--all` | No | off | Validate all direct dataset folders below `--models-dir`. Cannot be combined with explicit dataset folders. |
| `--models-dir PATH` | No | `models` | Models directory used with `--all`. |
| `--fix` | No | off | Apply safe deterministic fixes. |
| `--dry-run` | No | off | Show planned fixes without writing files. Mainly useful with `--fix`. |
| `--format {text,json}` | No | `text` | Output format. |
| `--unknown-fields {error,warning,ignore}` | No | `error` | Policy for unknown top-level fields. |
| `--missing-expected-fields {error,warning,ignore}` | No | `warning` | Policy for expected but non-mandatory fields that are absent. |
| `--strict` | No | off | Promote warnings to errors. |
| `--fail-on-warning` | No | off | Return exit code 1 when warnings are present. |

## Exit codes

| Exit code | Meaning |
| --- | --- |
| `0` | No validation errors were found. |
| `1` | Validation errors were found, or warnings were present with `--fail-on-warning`. |
| `2` | Command-line, discovery, or write problem prevented normal execution. |

## CI/workflow use

For a future workflow that validates new catalog submissions, use non-interactive validation first:

```bash
python scripts/validate_metadata_yaml.py --all --models-dir models --format text
```

After existing metadata files have been normalized, a stricter workflow can use:

```bash
python scripts/validate_metadata_yaml.py --all --models-dir models --strict
```

Do not use `--fix` in CI unless the workflow is explicitly designed to commit generated changes.

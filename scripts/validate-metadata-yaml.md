# Validate metadata.yaml files

[Script index and local setup](README.md)

`metadata.yaml` is the authoring source for model-level catalog metadata. The validator implemented in `scripts/validate_metadata_yaml.py` checks it as the first stage of the [current submission helper](process-new-model-submission.md#processing-order), before ontology and metadata generation. It also supports standalone validation and fixing.

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
- `modified` date/year values that are earlier than `issued`;
- HTTP(S) URI fields;
- Library of Congress Classification values in `theme`;
- controlled values for `ontologyType`, `designedForTask`, `context`, and `representationStyle`;
  accepted forms include compact names, friendly labels, `ocmv:` names, and full OCMV URIs;
- language-tag format for `language`;
- common repository quality rules, such as preferring DBLP/ORCID contributor identifiers and DOI/DBLP source identifiers.

The validator is intentionally YAML-level tooling. Neither it nor the current submission workflow runs a JSON Schema validator or the [archived SHACL shapes](../shapes/). Those shapes are outdated and non-authoritative. The workflow parses generated Turtle and checks particular generation/synchronization rules; that does not establish conformance with the archived shapes or model semantics. See the [submission validation boundary](process-new-model-submission.md#what-the-helper-checks-before-generation).

## Mandatory fields

The following shows the **YAML validator's minimum mandatory fields**, not a complete submission:

```yaml
title: Reference Ontology of Trust
issued: 2019
license: https://creativecommons.org/licenses/by/4.0/
theme: Class H - Social Sciences
keyword:
 - trust
```

The script also checks expected catalog-template fields, including `acronym`, `modified`, `contributor`, `editorialNote`, `ontologyType`, `language`, `designedForTask`, `context`, `source`, `representationStyle`, and `landingPage`. Missing expected but non-mandatory fields are warnings by default. Use `--missing-expected-fields error` or `--strict` to make them fatal.

The next ontology-generation stage additionally requires a non-empty, usable `language`, for example `language: en`; an empty field inserted by `--fix` is not sufficient. See the [language requirements](generate-ontology-turtle.md#requirements), the full field list below, and this [existing model metadata example](https://github.com/OntoUML/ontouml-models/blob/617dc16ee30a94d8c0587463f1b9ba3b3aef07d7/models/amaral2019rot/metadata.yaml). Use the example's structure, but supply your own model's values. A complete submission also needs the [required source files](process-new-model-submission.md#required-source-files).

Some older catalog datasets have no license value. This is semantically incomplete, but the validator must not invent license metadata. Use `--allow-missing-license` to report a missing or empty `license` as a warning instead of an error when validating legacy datasets.

## Supported field spelling

The validator only accepts the repository-facing `metadata.yaml` fields currently used by catalog datasets:

```yaml
title:
acronym:
issued:
modified:
contributor:
keyword:
theme:
editorialNote:
ontologyType:
language:
designedForTask:
context:
source:
representationStyle:
landingPage:
license:
```

RDF predicate names, converter-only aliases, and extension fields are intentionally treated as unexpected fields. For example, `dct:title`, `dcat:keyword`, `editorial_note`, `ontology_type`, `iri`, `storage_url`, `distribution`, and `contactPoints` are not accepted unless the official YAML format is explicitly extended later.

Contact-point metadata is not part of the supported `metadata.yaml` field set. This validator therefore treats `contact_points`, `contactPoints`, and `dcat:contactPoint` as unexpected YAML fields.

`landingPage` may be empty, a single HTTP(S) URI, or a YAML list of HTTP(S) URIs. The validator and metadata converter accept multiple landing pages, so `--fix` does not unwrap `landingPage` lists.

`language` may be a single language tag, a comma-separated scalar used by existing catalog files, or a YAML list of language tags. For example, `language: en, pt-br` is accepted. When `--fix` is used, comma-separated multi-language scalars are normalized to YAML lists, but only when every language tag is valid:

```yaml
language:
 - en
 - pt-br
```

Single-language scalars such as `language: en` are kept as scalars to avoid unnecessary churn.

## Safe automatic fixes

Use `--fix` to apply deterministic fixes only. The script does **not** guess missing mandatory metadata.

Safe fixes include:

- adding missing non-mandatory expected fields with empty YAML values, e.g. `acronym:` rather than `acronym: null`;
- wrapping scalar values in lists where the catalog template expects a vector/list;
- converting comma-separated multi-language scalar values into YAML lists when every language tag is valid;
- unwrapping one-item lists where the catalog template expects a scalar URI, for example `license:
 - https://creativecommons.org/licenses/by/4.0/` to `license: https://creativecommons.org/licenses/by/4.0/`; this does **not** apply to `landingPage`, which may have multiple values;
- normalizing controlled values to the catalog style, for example `Domain` to `domain`;
- normalizing compact `theme` values such as `H`, `lcc:H`, or an LCC URI to the full catalog label, e.g. `Class H - Social Sciences`;
- replacing known license shorthands such as `CC-BY-4.0` with their canonical URI;
- trimming surrounding whitespace in scalar strings;

The fix mode rewrites YAML with PyYAML plus catalog-specific post-processing. It preserves the repository convention of one leading space before top-level list markers (` - value`) and empty values as `field:` rather than `field: null`. Comments and some hand-formatted spacing are not preserved. Run it only when this is acceptable.

Preview fixes without writing files:

```bat
python scripts/validate_metadata_yaml.py models/example-model --fix --dry-run
```

Apply fixes:

```bat
python scripts/validate_metadata_yaml.py models/example-model --fix
```

## YAML formatting produced by `--fix`

The original repository metadata files use one leading space before list markers:

```yaml
contributor:
 - https://dblp.org/pid/81/4277
```

This is valid YAML and is the style preserved by the fixer. The previous implementation emitted PyYAML's default style without that leading space; that was valid YAML, but it caused unnecessary repository-wide diffs and did not follow the catalog's established formatting.

Empty optional values are written as:

```yaml
acronym:
editorialNote:
```

not as:

```yaml
acronym: null
editorialNote: null
```

The `theme` field is written using the full Library of Congress class label used in existing catalog metadata files:

```yaml
theme: Class H - Social Sciences
```

Compact values such as `H`, `lcc:H`, or an id.loc.gov LCC URI are accepted as fixable input only. With `--fix`, they are expanded to the full repository-style label.

Multiline `editorialNote` values are serialized as YAML block scalars instead of single-quoted multiline scalars. This avoids churn such as doubled apostrophes (`isn''t`) while keeping the output valid YAML:

```yaml
editorialNote: |
 The ontology was developed in the context of a master thesis which isn't yet published.
 The cardinalities in derivation link were represented in UML notes.
```

## Usage

Run from the repository root.

Validate one dataset folder:

```bat
python scripts/validate_metadata_yaml.py models/example-model
```

Validate multiple dataset folders:

```bat
python scripts/validate_metadata_yaml.py models/example-a models/example-b
```

Validate all direct dataset folders under `models/`:

```bat
python scripts/validate_metadata_yaml.py --all --models-dir models
```

Run from inside a dataset folder that contains `metadata.yaml`:

```bat
python ../../scripts/validate_metadata_yaml.py
```

Emit JSON output for logs or automation:

```bat
python scripts/validate_metadata_yaml.py --all --format json
```

Fail on warnings as well as errors:

```bat
python scripts/validate_metadata_yaml.py --all --fail-on-warning
```

Promote policy warnings to errors during validation:

```bat
python scripts/validate_metadata_yaml.py --all --strict
```

Relax missing license values for legacy datasets where the license cannot be safely inferred:

```bat
python scripts/validate_metadata_yaml.py models/example-model --allow-missing-license
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
| `--allow-missing-license` | No | off | Report missing or empty `license` values as warnings instead of errors for legacy datasets. |
| `--fail-on-warning` | No | off | Return exit code 1 when warnings are present. |

## Exit codes

| Exit code | Meaning |
| --- | --- |
| `0` | No validation errors were found. |
| `1` | Validation errors were found, or warnings were present with `--fail-on-warning`. |
| `2` | Command-line, discovery, or write problem prevented normal execution. |

## CI/workflow use

The current submission helper runs this validator with `--fix` for the selected model folder. The workflow can commit the normalized YAML, so review comment/formatting changes as well as metadata values. Its normal mode does not enable `--strict`.

For standalone validation of the existing collection without writes:

```bat
python scripts/validate_metadata_yaml.py --all --models-dir models --format text
```

For an explicitly stricter standalone check, which may reject otherwise warning-only metadata:

```bat
python scripts/validate_metadata_yaml.py --all --models-dir models --strict
```

For legacy-wide checks before license metadata has been curated, use:

```bat
python scripts/validate_metadata_yaml.py --all --models-dir models --allow-missing-license
```

Use `--fix` in CI only when the workflow is designed to review or commit normalized source changes, as the current submission workflow is. A successful YAML check alone does not establish that every later submission stage will pass.

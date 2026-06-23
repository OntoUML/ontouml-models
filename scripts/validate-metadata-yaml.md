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
- `modified` date/year values that are earlier than `issued`;
- HTTP(S) URI fields;
- Library of Congress Classification values in `theme`;
- controlled values for `ontologyType`, `designedForTask`, `context`, and `representationStyle`;
  accepted forms include compact names, friendly labels, `ocmv:` names, and full OCMV URIs;
- language-tag format for `language`;
- common repository quality rules, such as preferring DBLP/ORCID contributor identifiers and DOI/DBLP source identifiers.

The validator is intentionally YAML-level tooling. RDF/SHACL validation should still be applied to generated Turtle files as a separate stage.

## Mandatory fields

The minimum mandatory fields are aligned with the catalog metadata schema and the existing repository metadata.yaml files:

```yaml
title: Reference Ontology of Trust
issued: 2019
license: https://creativecommons.org/licenses/by/4.0/
theme: Class H - Social Sciences
keyword:
 - trust
```

The script also checks expected catalog-template fields, including `acronym`, `modified`, `contributor`, `editorialNote`, `ontologyType`, `language`, `designedForTask`, `context`, `source`, `representationStyle`, and `landingPage`. Missing expected but non-mandatory fields are warnings by default. Use `--missing-expected-fields error` or `--strict` to make them fatal.

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

Although the RDF dataset shape includes `dcat:contactPoint`, contact-point metadata is not part of the supported `metadata.yaml` field set. This validator therefore treats `contact_points`, `contactPoints`, and `dcat:contactPoint` as unexpected YAML fields.

`landingPage` may be empty, a single HTTP(S) URI, or a YAML list of HTTP(S) URIs. The underlying RDF property has no maximum-count constraint in the catalog SHACL shape, so multiple landing pages are allowed. `--fix` therefore does not unwrap `landingPage` lists.

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

```bash
python scripts/validate_metadata_yaml.py models/<model-directory> --fix --dry-run
```

Apply fixes:

```bash
python scripts/validate_metadata_yaml.py models/<model-directory> --fix
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

Relax missing license values for legacy datasets where the license cannot be safely inferred:

```bash
python scripts/validate_metadata_yaml.py models/<model-directory> --allow-missing-license
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

For a future workflow that validates new catalog submissions, use non-interactive validation first:

```bash
python scripts/validate_metadata_yaml.py --all --models-dir models --format text
```

After existing metadata files have been normalized, a stricter workflow can use:

```bash
python scripts/validate_metadata_yaml.py --all --models-dir models --strict
```

For legacy-wide checks before license metadata has been curated, use:

```bash
python scripts/validate_metadata_yaml.py --all --models-dir models --allow-missing-license
```

Do not use `--fix` in CI unless the workflow is explicitly designed to commit generated changes.

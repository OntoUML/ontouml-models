# `metadata_yaml_to_ttl.py`

`metadata_yaml_to_ttl.py` generates model-level `metadata.ttl` files for the OntoUML/UFO Catalog from the canonical `metadata.yaml` files stored in each dataset folder.

This script generates `metadata.ttl`. It does **not** generate `metadata-turtle.ttl`, which is the distribution metadata file for `ontology.ttl`.

## Purpose

The catalog keeps manually maintained model metadata in `metadata.yaml`. This converter materializes that metadata as RDF/Turtle in `metadata.ttl`, preserving catalog-managed identifiers and links already present in existing `metadata.ttl` files.

The converter is designed for repository maintenance and later CI/workflow integration:

- non-interactive execution;
- clear CLI arguments;
- stable output ordering;
- explicit exit codes;
- `--check` mode for CI;
- JSON summary output for logs;
- per-dataset progress logs in text mode;
- tests under `scripts/tests/`.

## Scope

The converter assumes that `metadata.yaml` has already been validated and fixed by `validate_metadata_yaml.py`. It does not duplicate the full validator/linter responsibilities, but it does enforce the same strict top-level field set used by the validator/fixer.

The only supported top-level `metadata.yaml` fields are:

```text
title, acronym, issued, modified, contributor, keyword, theme,
editorialNote, ontologyType, language, designedForTask, context,
source, representationStyle, landingPage, license
```

RDF predicate aliases, converter-only fields, and extension fields are intentionally rejected. For example, `dct:title`, `metadata_issued`, `storage_url`, `distribution`, `contactPoints`, and `iri` are not valid `metadata.yaml` fields for this converter.

Nested literal and controlled-value syntax is also kept aligned with the validator/fixer. For example, literal mappings must use the exact `value`, `lang`, `language`, and `datatype` keys supported by the validator, and controlled-value fields must contain strings, not mappings.

`dcat:keyword` values are always generated with the English language tag (`@en`). This is independent of the model language declared with `dct:language`; for example, a model with `language: pt-BR` still generates `dcat:keyword "example"@en`.

It still fails clearly when data needed for conversion is missing or malformed, for example:

- missing `title`;
- missing `issued`;
- missing `theme`;
- missing `keyword`;
- missing `license`, unless `--allow-missing-license` is used;
- malformed URI values;
- unsupported date lexical forms;
- unsupported controlled-vocabulary values.

## Repository placement

Expected repository layout:

```text
scripts/
  metadata_yaml_to_ttl.py
  metadata_yaml_to_ttl.md
  tests/
    test_metadata_yaml_to_ttl.py
```

## Basic usage

Run from the repository root.

Generate `metadata.ttl` for one dataset:

```bash
python scripts/metadata_yaml_to_ttl.py models/amaral2019rot
```

Generate `metadata.ttl` for multiple selected datasets:

```bash
python scripts/metadata_yaml_to_ttl.py models/dataset-a models/dataset-b
```

Generate `metadata.ttl` for all datasets under `models/`:

```bash
python scripts/metadata_yaml_to_ttl.py --all --models-dir models
```

If some existing or new datasets do not have `fdpo:metadataIssued` in `metadata.ttl`, provide an explicit deterministic timestamp for the generation run:

```bash
python scripts/metadata_yaml_to_ttl.py --all --models-dir models --metadata-timestamp 2026-01-31T12:00:00Z
```

Allow legacy datasets without license metadata:

```bash
python scripts/metadata_yaml_to_ttl.py --all --allow-missing-license
```

Check whether generated files are up to date without writing files:

```bash
python scripts/metadata_yaml_to_ttl.py --all --check
```

Print machine-readable summary output:

```bash
python scripts/metadata_yaml_to_ttl.py --all --format json
```

When `--format json` is used together with `--check`, diff output is suppressed so stdout remains valid JSON for CI parsers.

In text mode, the script prints one progress line after each processed dataset and a final summary. To suppress non-error progress output, use:

```bash
python scripts/metadata_yaml_to_ttl.py --all --quiet
```

`--silent` is accepted as an alias for `--quiet`. Errors are still printed to `stderr`.

Print generated Turtle without writing it:

```bash
python scripts/metadata_yaml_to_ttl.py models/amaral2019rot --dry-run
```

## License handling

By default, `license` is required. This is intended for new datasets and future automated submission workflows.

The license value must be a single scalar value: either an absolute HTTP(S) URI or a supported compact identifier such as `CC-BY-4.0`, `CC-BY-SA-4.0`, `CC-BY-SA-3.0`, `CC0-1.0`, or `MIT`. Mapping forms such as `license: {id: CC-BY-4.0}` are intentionally not supported because they are not accepted by the metadata.yaml validator/fixer.

Some older catalog datasets do not currently have license information. For those legacy cases, use:

```bash
python scripts/metadata_yaml_to_ttl.py models/legacy-dataset --allow-missing-license
```

When this option is used, it only relaxes the missing-license error. It does **not** suppress available license metadata:

- if `metadata.yaml` has `license`, the converter generates `dct:license`;
- if `metadata.yaml` lacks `license` but existing `metadata.ttl` has `dct:license`, the existing license is preserved;
- if neither file has license metadata, `dct:license` is omitted and the command reports a warning.

## Existing `metadata.ttl` preservation

When `metadata.ttl` already exists, the converter reads it to preserve values that are not maintained in `metadata.yaml`:

- the stable model IRI;
- the model IRI form used for `dcat:distribution` links;
- the catalog IRI used in `dct:isPartOf`;
- existing `ocmv:storageUrl`;
- existing `fdpo:metadataIssued` and `fdpo:metadataModified` timestamps;
- existing `dcat:distribution` links.

The converter also discovers distribution IRIs from distribution-specific metadata files already present in the dataset folder, such as `metadata-vpp.ttl`, `metadata-json.ttl`, `metadata-turtle.ttl`, and `metadata-png-*.ttl`.

The remaining model-level descriptive metadata is regenerated from `metadata.yaml`.

This behavior allows safe regeneration of existing datasets without replacing stable catalog identifiers or distribution links.

## New datasets

For new datasets that do not yet have `metadata.ttl`, the converter uses:

- a deterministic UUIDv5 model IRI derived from the dataset folder name;
- the default catalog IRI;
- a default GitHub storage URL derived from `--repository`, `--branch`, `--models-dir`, and the dataset folder name;
- `dcat:distribution` links discovered from distribution-specific metadata files generated earlier in the workflow.

New datasets must be generated with an explicit metadata timestamp unless one is preserved from an existing `metadata.ttl`:

```bash
python scripts/metadata_yaml_to_ttl.py models/new-dataset --metadata-timestamp 2026-01-31T12:00:00Z
```

Use `--metadata-timestamp now` only when non-deterministic current timestamps are intentionally acceptable. Existing datasets keep their current `fdpo:metadataIssued` and `fdpo:metadataModified` values by default. Existing datasets that currently lack FDP metadata timestamps require `--metadata-timestamp`; this avoids silently inventing catalog metadata timestamps.

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | Conversion completed successfully. In `--check` mode, no generated files differ. |
| `1` | One or more datasets could not be converted, or `--check` found files that need updates. |
| `2` | Command-line, dataset discovery, read, or write setup problem. |

## CI pattern

A typical CI sequence for future dataset submissions is:

```bash
python scripts/validate_metadata_yaml.py --all --fix --allow-missing-license
# Run distribution-specific metadata generators here, e.g. JSON/Turtle/VPP/PNG metadata.
python scripts/metadata_yaml_to_ttl.py --all --check --allow-missing-license --metadata-timestamp 2026-01-31T12:00:00Z
```

For stricter future-only validation where license must be present, omit `--allow-missing-license`.

## Notes

- `metadata.yaml` is the only editable input source for regenerated model-level metadata.
- The converter does not read `metadata-turtle.ttl`.
- The converter writes only `metadata.ttl`.
- Existing distribution-specific metadata files, such as `metadata-json.ttl`, `metadata-turtle.ttl`, and `metadata-png-*.ttl`, are read to discover `dcat:Distribution` IRIs but are not modified.

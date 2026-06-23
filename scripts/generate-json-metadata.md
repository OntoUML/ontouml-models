# JSON distribution metadata generator

`scripts/generate_json_metadata.py` generates RDF/Turtle metadata for the OntoUML JSON distribution of a model dataset.

For each processed dataset folder, it reads:

- `metadata.yaml`
- `ontology.json`
- existing distribution metadata files, when needed to preserve stable identifiers and curated values

It writes:

- `metadata-json.ttl`

The script is intended for repository maintenance and for a future metadata-generation workflow. It does **not** create or modify a GitHub Actions workflow.

## Purpose

The generator describes the `ontology.json` distribution of an OntoUML/UFO Catalog model as a `dcat:Distribution`.

The generated metadata follows the repository’s established JSON distribution pattern:

- source file: `ontology.json`
- output file: `metadata-json.ttl`
- media type: `https://www.iana.org/assignments/media-types/application/json`
- schema: `https://w3id.org/ontouml/schema`
- completeness: `ocmv:isComplete true`
- default title pattern: `JSON distribution of {model title}`
- default download URL pattern: `https://raw.githubusercontent.com/{repository}/{branch}/models/{dataset}/ontology.json`

## Relationship to `metadata.ttl`

`metadata.ttl` is the final model-level aggregation product of the metadata workflow.

This generator does not read `metadata.ttl` and does not require it to exist. It generates distribution-level metadata first. Later, `scripts/metadata_yaml_to_ttl.py` can aggregate `metadata-json.ttl` and the other generated distribution metadata files into model-level `metadata.ttl`.

A future generation order may therefore be:

```text
python scripts/validate_metadata_yaml.py --all --models-dir models --fix --allow-missing-license
python scripts/generate_png_metadata.py --all --models-dir models --allow-missing-license --metadata-timestamp now
python scripts/generate_json_metadata.py --all --models-dir models --allow-missing-license --metadata-timestamp now
python scripts/generate_turtle_metadata.py --all --models-dir models --allow-missing-license --metadata-timestamp now
python scripts/generate_vpp_metadata.py --all --models-dir models --allow-missing-license --metadata-timestamp now
python scripts/metadata_yaml_to_ttl.py --all --models-dir models --allow-missing-license --metadata-timestamp now
```

This document describes the JSON generator only; no workflow is created by this task.

## Inputs

### `metadata.yaml`

`metadata.yaml` is the canonical editable source for model-level values used in `metadata-json.ttl`, especially:

- model title;
- issued date;
- license;
- optional explicit model URI, when such a field is present in a compatible YAML variant.

The current standard repository-facing `metadata.yaml` template does not need to expose a model URI. For existing catalog datasets, the generator should preserve the model URI from existing distribution metadata files instead.

### `ontology.json`

By default, the script requires `ontology.json` to exist and be parseable JSON with a JSON object at the top level. This prevents creating metadata for a missing or invalid source distribution.

Use `--no-check-ontology-json` only for exceptional compatibility cases where the metadata record must be generated before the source file is available.

### Existing distribution metadata

The script reads existing distribution metadata files only to preserve stable catalog identifiers and curated distribution-level values. It does not treat model-level `metadata.ttl` as an input.

## Model IRI resolution

The generated `dct:isPartOf` value is resolved without reading `metadata.ttl`.

Resolution order:

1. Existing `metadata-json.ttl`, when present, by reading its `dct:isPartOf`.
2. Other existing distribution metadata files in the same dataset folder, when available and unambiguous, by reading their `dct:isPartOf`.
3. Explicit HTTP(S) model URI in `metadata.yaml`, if present in a compatible YAML form.
4. Deterministic UUIDv5 model IRI for genuinely new datasets.

The deterministic model IRI uses the same strategy as `metadata_yaml_to_ttl.py`:

```text
uuid5(NAMESPACE_URL, "https://w3id.org/ontouml-models/model|{dataset-folder-name}")
```

The generator does not replace existing UUID-based model IRIs with folder-name-based IRIs.

If the folder appears to be an existing catalog dataset, but no existing distribution metadata file provides a stable `dct:isPartOf`, the generator fails instead of silently creating a new model IRI. A folder is treated as likely existing when it already contains `metadata.ttl` or another `metadata-*.ttl` file.

If multiple distribution metadata files provide conflicting `dct:isPartOf` values, generation fails and reports the conflict.

## Distribution IRI strategy

For existing `metadata-json.ttl`, the existing distribution IRI is preserved.

For new `metadata-json.ttl`, the script generates a deterministic UUIDv5 distribution IRI from stable repository/catalog information:

```text
{model IRI}|models/{dataset-folder-name}/ontology.json
```

The seed uses the repository-relative source path, not a local absolute filesystem path.

## Preserved values

When regenerating an existing `metadata-json.ttl`, the script preserves these values when present and applicable:

- existing distribution IRI;
- existing `dct:isPartOf`;
- existing `dct:title`;
- existing `skos:editorialNote`;
- existing `dcat:downloadURL`;
- existing distribution-level `dct:license`, when `metadata.yaml` lacks a license and `--allow-missing-license` is used;
- existing `ocmv:conformsToSchema`;
- existing `fdpo:metadataIssued`;
- existing `fdpo:metadataModified` when the regenerated file is unchanged.

When `metadata.yaml` provides a license, that license is emitted regardless of `--allow-missing-license`.

## Timestamp behavior

`--metadata-timestamp` controls `fdpo:metadataIssued` and `fdpo:metadataModified`.

Use a fixed value for deterministic runs:

```bash
python scripts/generate_json_metadata.py models/amaral2019rot --metadata-timestamp 2026-06-23T12:00:00Z
```

Use `now` only for intentionally non-deterministic maintenance runs:

```bash
python scripts/generate_json_metadata.py models/amaral2019rot --metadata-timestamp now
```

Rules:

- existing `fdpo:metadataIssued` is preserved;
- missing `fdpo:metadataIssued` is initialized from `--metadata-timestamp`;
- existing `fdpo:metadataModified` is preserved when the regenerated file is unchanged;
- `fdpo:metadataModified` is updated from `--metadata-timestamp` when the regenerated file changes;
- new files initialize both timestamps from the same supplied timestamp;
- if a new or changed file needs a timestamp and none is supplied, generation fails clearly.

The script does not silently use the current time by default.

## Missing-license behavior

By default, missing license metadata is an error.

Use `--allow-missing-license` only for legacy datasets that intentionally lack license metadata:

```bash
python scripts/generate_json_metadata.py models/legacy-model --allow-missing-license --metadata-timestamp 2026-06-23T12:00:00Z
```

Behavior:

- if `metadata.yaml` has a license, the generated metadata includes it;
- if `metadata.yaml` has no license and `--allow-missing-license` is not used, generation fails;
- if `metadata.yaml` has no license and `--allow-missing-license` is used, the script preserves an existing distribution-level `dct:license` when available;
- if no license is available and `--allow-missing-license` is used, `dct:license` is omitted.

Do not use `--allow-missing-license` for new submissions.

## Usage

### One dataset

```bash
python scripts/generate_json_metadata.py models/amaral2019rot --metadata-timestamp 2026-06-23T12:00:00Z
```

### Multiple datasets

```bash
python scripts/generate_json_metadata.py models/amaral2019rot models/albuquerque2011ontobio --metadata-timestamp 2026-06-23T12:00:00Z
```

### All datasets

```bash
python scripts/generate_json_metadata.py --all --models-dir models --metadata-timestamp 2026-06-23T12:00:00Z
```

### Check mode

Use `--check` to verify whether files are up to date without writing changes:

```bash
python scripts/generate_json_metadata.py --all --models-dir models --check --metadata-timestamp 2026-06-23T12:00:00Z
```

Exit code `1` means at least one file would change or at least one dataset failed.

### Dry run

Use `--dry-run` to validate inputs and report intended outputs without writing files:

```bash
python scripts/generate_json_metadata.py --all --models-dir models --dry-run --metadata-timestamp 2026-06-23T12:00:00Z
```

### JSON output

```bash
python scripts/generate_json_metadata.py --all --models-dir models --format json --metadata-timestamp 2026-06-23T12:00:00Z
```

### Quiet mode

```bash
python scripts/generate_json_metadata.py --all --models-dir models --quiet --metadata-timestamp 2026-06-23T12:00:00Z
```

`--silent` is accepted as an alias for `--quiet`.

### Download URL options

By default, the script creates raw GitHub URLs using:

```text
repository: OntoUML/ontouml-models
branch: master
models path: models
```

Override them when testing a branch or fork:

```bash
python scripts/generate_json_metadata.py models/example \
  --repository pedropaulofb/ontouml-models-dev \
  --branch regenerate-json-metadata \
  --models-dir-name models \
  --metadata-timestamp 2026-06-23T12:00:00Z
```

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | Generation/check completed successfully. In `--check` mode, no updates are needed. |
| `1` | Dataset processing failed, or `--check` detected required updates. |
| `2` | Command-line, discovery, or setup error prevented normal execution. |

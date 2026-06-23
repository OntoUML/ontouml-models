# Generate VPP distribution metadata

This repository contains one RDF/Turtle metadata file for each Visual Paradigm project distribution of a model.

The generator implemented in `scripts/generate_vpp_metadata.py` scans one or more model dataset folders and creates this file:

| Source file | Generated metadata file |
| --- | --- |
| `ontology.vpp` | `metadata-vpp.ttl` |

## Purpose and pipeline role

The script generates distribution-level metadata for Visual Paradigm project files. It is intended to run **before** model-level `metadata.ttl` is generated.

The model-level source of truth is `metadata.yaml`. The VPP generator does **not** update `metadata.ttl`, and it does **not** add model-level `dcat:distribution` triples. Instead, the generated `metadata-vpp.ttl` file points back to the model with `dct:isPartOf`.

For existing catalog datasets, the script preserves the already published model W3ID used in `dct:isPartOf` from existing distribution metadata. It does not use model-level `metadata.ttl` as an input dependency. This supports a future workflow in which distribution metadata files are generated first, and `scripts/metadata_yaml_to_ttl.py` later aggregates them into model-level `metadata.ttl`.

Recommended future generation order:

```text
metadata.yaml + ontology.vpp
  -> metadata-vpp.ttl

metadata.yaml + generated distribution metadata
  -> metadata.ttl
```

This document only describes the VPP metadata generator. No GitHub Actions workflow, CI configuration, or full automation pipeline is created by this script.

## Generated RDF semantics

For `ontology.vpp`, the script creates a `dcat:Distribution` metadata file following the RDF pattern already used by existing `metadata-vpp.ttl` files.

The generated distribution includes:

- `rdf:type dcat:Distribution`
- `dct:isPartOf`, pointing to the preserved or generated model dataset URI
- `dct:issued`, derived from model-level `metadata.yaml`
- `dct:license`, copied from existing VPP metadata or derived from model-level `metadata.yaml` when available
- `dct:title`
- `dcat:mediaType <https://www.iana.org/assignments/media-types/application/octet-stream>`
- `dct:format <https://www.file-extension.info/format/vpp>`
- `dcat:downloadURL`, pointing to the raw GitHub URL of `ontology.vpp`
- `ocmv:isComplete true`, because the Visual Paradigm project file is treated as a complete model distribution in the current catalog metadata pattern
- `fdpo:metadataIssued`
- `fdpo:metadataModified`

If an existing `metadata-vpp.ttl` contains `skos:editorialNote`, the note is preserved. New VPP metadata files do not receive a default editorial note because the current VPP metadata pattern does not require one.

## Existing metadata preservation

When regenerating an existing VPP metadata file, the script preserves curated values that should not be changed accidentally:

- the existing distribution URI;
- the existing model URI used in `dct:isPartOf`;
- `dct:title`;
- `skos:editorialNote`, when present;
- `dcat:downloadURL`;
- `dct:license`;
- the exact lexical value of `fdpo:metadataIssued`;
- the exact lexical value of `fdpo:metadataModified` when the regenerated file is otherwise unchanged.

Preserving exact timestamp lexical values avoids changes such as nanosecond truncation or conversion from `Z` to `+00:00` when existing `xsd:dateTime` literals are parsed.

Timestamp handling follows the same maintenance strategy used by `scripts/metadata_yaml_to_ttl.py` and the PNG generator:

- if an existing VPP metadata file has `fdpo:metadataIssued`, that value is preserved;
- if there is no existing VPP metadata file, or the existing file has no `fdpo:metadataIssued`, the value is initialized from `--metadata-timestamp`;
- if an existing VPP metadata file changes during regeneration, `fdpo:metadataModified` is updated from `--metadata-timestamp`;
- if an existing VPP metadata file is already up to date, `fdpo:metadataModified` is preserved.

For existing files, the script still regenerates the remaining script-owned triples from model metadata and script defaults, including `dct:issued`, `dcat:mediaType`, `dct:format`, and `ocmv:isComplete`.

## License handling

By default, model-level `metadata.yaml` must contain a usable `license` value. This matches the policy of `scripts/metadata_yaml_to_ttl.py`: license metadata is mandatory unless the legacy-compatibility option is explicitly used.

Use `--allow-missing-license` only for legacy datasets that intentionally lack license metadata:

```bash
python scripts/generate_vpp_metadata.py models/<model-directory> --allow-missing-license \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

When `--allow-missing-license` is used and no model-level license is present:

- an existing VPP-level `dct:license` is preserved when regenerating an existing `metadata-vpp.ttl` file;
- new VPP metadata files omit `dct:license`;
- generation continues so older catalog entries can be processed.

When `--allow-missing-license` is not used, missing or unusable license metadata is a fatal error. This keeps license metadata enforceable for future datasets.

When model-level license metadata is available, it is emitted for new VPP metadata files even if `--allow-missing-license` is also used.

## Defaults for new VPP metadata files

For new files, the script generates a catalog-style title:

```text
Visual Paradigm distribution of <model title>
```

For example:

```text
Visual Paradigm distribution of Petroleum System Model
```

## Distribution identifiers

Existing `metadata-vpp.ttl` files keep their current distribution URI. This avoids changing already published W3IDs.

For new VPP metadata files, the script creates a deterministic UUIDv5 distribution URI under:

```text
https://w3id.org/ontouml-models/distribution/<uuid>/
```

The deterministic UUID input is:

```text
<model-uri>|ontology.vpp
```

This keeps new-file generation reproducible while preserving the catalog's established UUID-based distribution URI pattern.

## Model identifiers used in `dct:isPartOf`

The script resolves the model URI for VPP distribution metadata in this order:

1. the existing `dct:isPartOf` value in `metadata-vpp.ttl`, when present;
2. a unique existing `dct:isPartOf` value in other distribution metadata files in the same dataset folder, such as `metadata-json.ttl`, `metadata-turtle.ttl`, or `metadata-png-*.ttl`;
3. an explicit HTTP(S) model URI in `metadata.yaml`, if present;
4. a deterministic UUIDv5 URI generated from the dataset folder name, using the same strategy as `scripts/metadata_yaml_to_ttl.py`, only for genuinely new datasets.

The script intentionally does **not** read model-level `metadata.ttl` to resolve the model URI. `metadata.ttl` is the final aggregation product of the metadata workflow, not an input dependency for VPP distribution metadata generation.

If the dataset appears to be an existing catalog dataset but no existing distribution metadata file provides a stable model URI, the script fails clearly instead of silently generating a new deterministic model URI. This prevents published UUID-based model W3IDs from being replaced accidentally.

If multiple existing distribution metadata files provide conflicting `dct:isPartOf` values, the script fails and reports the conflict.

## Download URLs

For new metadata files, `dcat:downloadURL` values are generated as raw GitHub URLs using:

- `--repository`
- `--branch`
- `--models-dir-name`
- the dataset folder name
- `ontology.vpp`

By default, generated URLs point to:

```text
https://raw.githubusercontent.com/OntoUML/ontouml-models/master/models/<model-directory>/ontology.vpp
```

Existing `dcat:downloadURL` values are preserved when regenerating existing metadata files.

When generating new URLs, path segments are URL-quoted where needed, but commas are left unescaped to match the existing catalog style.

## Requirements

Install the script dependencies:

```bash
python -m pip install -r scripts/requirements.txt
```

The VPP metadata generator requires `rdflib` and `PyYAML`. Tests require `pytest`. These are already used by the existing metadata scripts.

## Usage

Run from the repository root.

Commands that create new VPP metadata files, initialize missing `fdpo:metadataIssued`, or update `fdpo:metadataModified` require `--metadata-timestamp`. Use a fixed timestamp for deterministic automation runs. Use `--metadata-timestamp now` only for manual, intentionally non-deterministic execution.

Generate metadata for one dataset folder:

```bash
python scripts/generate_vpp_metadata.py models/<model-directory> \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Generate metadata for multiple dataset folders:

```bash
python scripts/generate_vpp_metadata.py models/<model-1> models/<model-2> \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Generate metadata for all dataset folders under `models/`:

```bash
python scripts/generate_vpp_metadata.py --all --models-dir models \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Generate all VPP metadata while allowing legacy datasets without license metadata:

```bash
python scripts/generate_vpp_metadata.py --all --models-dir models --allow-missing-license \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Preview generation without writing files:

```bash
python scripts/generate_vpp_metadata.py models/<model-directory> --dry-run \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Check whether files are up to date without writing them. The command exits with code `1` if any VPP metadata file would change:

```bash
python scripts/generate_vpp_metadata.py models/<model-directory> --check \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Fail when the generated file already exists:

```bash
python scripts/generate_vpp_metadata.py models/<model-directory> --no-overwrite \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Use a different repository or branch in generated `dcat:downloadURL` values:

```bash
python scripts/generate_vpp_metadata.py models/<model-directory> \
  --repository pedropaulofb/ontouml-models-dev \
  --branch master \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Use a different repository-relative models path in generated `dcat:downloadURL` values:

```bash
python scripts/generate_vpp_metadata.py models/<model-directory> \
  --models-dir-name models \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Use JSON output:

```bash
python scripts/generate_vpp_metadata.py models/<model-directory> --format json \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Suppress normal text output:

```bash
python scripts/generate_vpp_metadata.py models/<model-directory> --quiet \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Run from inside a dataset folder that contains `metadata.yaml`:

```bash
python ../../scripts/generate_vpp_metadata.py \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

## Command-line arguments

| Argument | Required | Default | Meaning |
| --- | --- | --- | --- |
| `datasets` | No | current directory if it contains `metadata.yaml` | One or more model dataset folders to process. |
| `--all` | No | off | Process all dataset folders below `--models-dir`. |
| `--models-dir` | No | `models` | Dataset parent directory used with `--all`. |
| `--allow-missing-license` | No | off | Allow legacy datasets without model-level license metadata. |
| `--metadata-timestamp` | Conditionally | none | Required for new files, changed files, or missing existing `fdpo:metadataIssued`. |
| `--check` | No | off | Do not write; exit `1` if a file would change. |
| `--dry-run` | No | off | Validate and report without writing. |
| `--format` | No | `text` | Use `text` or `json` output. |
| `--quiet`, `--silent` | No | off | Suppress normal text output. |
| `--repository` | No | `OntoUML/ontouml-models` | Repository used in generated download URLs. |
| `--branch` | No | `master` | Branch used in generated download URLs. |
| `--models-dir-name` | No | `models` | Repository-relative models directory used in generated download URLs. |
| `--model-iri-base` | No | `https://w3id.org/ontouml-models/model` | Base IRI used for deterministic model UUIDs for new datasets. |
| `--no-overwrite` | No | off | Fail if `metadata-vpp.ttl` already exists. |

`--check` and `--dry-run` cannot be used together.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Generation or check completed successfully. In `--check` mode, no file would change. |
| `1` | Dataset processing failed, or `--check` detected required updates. |
| `2` | Command-line, discovery, or setup error prevented normal execution. |

## Notes for future automation

The script is workflow-ready but does not create a workflow. A future pipeline can run it before `scripts/metadata_yaml_to_ttl.py`, after validating or fixing `metadata.yaml`.

Use a fixed `--metadata-timestamp` value in CI-like maintenance runs to keep results deterministic. Use `--metadata-timestamp now` only for intentionally non-deterministic manual regeneration.

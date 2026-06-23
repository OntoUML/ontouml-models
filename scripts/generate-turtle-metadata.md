# Generate Turtle distribution metadata

This repository contains one RDF/Turtle metadata file for the Turtle linked-data distribution of each model.

The generator implemented in `scripts/generate_turtle_metadata.py` scans one or more model dataset folders and creates this file:

| Source file | Generated metadata file |
| --- | --- |
| `ontology.ttl` | `metadata-turtle.ttl` |

For example:

```text
models/example/ontology.ttl
models/example/metadata-turtle.ttl
```

## Purpose and pipeline role

The script generates distribution-level metadata for the model's Turtle serialization. It is intended to run **before** model-level `metadata.ttl` is generated.

The model-level source of truth is `metadata.yaml`. The Turtle generator does **not** update `metadata.ttl`, and it does **not** add model-level `dcat:distribution` triples. Instead, the generated `metadata-turtle.ttl` file points back to the model with `dct:isPartOf`.

`metadata.ttl` is the final model-level aggregation product of the metadata workflow. The later `scripts/metadata_yaml_to_ttl.py` step should aggregate `metadata-turtle.ttl` and the other distribution metadata files into model-level `metadata.ttl`.

Recommended future generation order:

```text
metadata.yaml + ontology.ttl
  -> metadata-turtle.ttl

metadata.yaml + metadata-turtle.ttl + other distribution metadata
  -> metadata.ttl
```

This document only describes the Turtle metadata generator. No GitHub Actions workflow, CI configuration, or full automation pipeline is created by this script.

## Generated RDF semantics

For each `ontology.ttl` file, the script creates one `dcat:Distribution` metadata file following the RDF pattern used by existing Turtle distribution metadata files.

The generated distribution includes:

- `rdf:type dcat:Distribution`
- `dct:isPartOf`, pointing to the preserved or generated model dataset URI
- `dct:issued`, derived from model-level `metadata.yaml`
- `dct:license`, copied from existing Turtle metadata or derived from model-level `metadata.yaml` when available
- `dcat:mediaType <https://www.iana.org/assignments/media-types/text/turtle>`
- `dct:title`
- `dcat:downloadURL`, pointing to the raw GitHub URL of `ontology.ttl`
- `ocmv:isComplete true`, because `ontology.ttl` is the complete linked-data materialization of the model
- `fdpo:metadataIssued`
- `fdpo:metadataModified`

If an existing `metadata-turtle.ttl` contains `skos:editorialNote`, the value is preserved. The generator does not add a new editorial note by default because existing Turtle distribution metadata does not require one.

## Existing metadata preservation

When regenerating an existing `metadata-turtle.ttl` file, the script preserves curated values that should not be changed accidentally:

- the existing distribution URI;
- the existing model URI used in `dct:isPartOf`;
- `dct:title`;
- `skos:editorialNote`, if present;
- `dcat:downloadURL`;
- `dct:license`;
- the exact lexical value of `fdpo:metadataIssued`;
- the exact lexical value of `fdpo:metadataModified` when the regenerated file is otherwise unchanged.

Preserving exact timestamp lexical values avoids changes such as nanosecond truncation or conversion from `Z` to `+00:00` when existing `xsd:dateTime` literals are parsed.

Timestamp handling follows the same maintenance strategy used by `scripts/metadata_yaml_to_ttl.py` and `scripts/generate_png_metadata.py`:

- if an existing Turtle metadata file has `fdpo:metadataIssued`, that value is preserved;
- if there is no existing Turtle metadata file, or the existing file has no `fdpo:metadataIssued`, the value is initialized from `--metadata-timestamp`;
- if an existing Turtle metadata file changes during regeneration, `fdpo:metadataModified` is updated from `--metadata-timestamp`;
- if an existing Turtle metadata file is already up to date, `fdpo:metadataModified` is preserved.

For existing files, the script still regenerates the remaining triples from model metadata and script defaults, including `dct:issued`, `dcat:mediaType`, and `ocmv:isComplete`.

## License handling

By default, model-level `metadata.yaml` must contain a usable `license` value. This matches the policy of `scripts/metadata_yaml_to_ttl.py` and `scripts/generate_png_metadata.py`: license metadata is mandatory unless the legacy-compatibility option is explicitly used.

Use `--allow-missing-license` only for legacy datasets that intentionally lack license metadata:

```bash
python scripts/generate_turtle_metadata.py models/<model-directory> --allow-missing-license \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

When `--allow-missing-license` is used and no model-level license is present:

- an existing Turtle-level `dct:license` is preserved when regenerating an existing `metadata-turtle.ttl` file;
- new Turtle metadata files omit `dct:license`;
- generation continues so older catalog entries can be processed.

When `--allow-missing-license` is not used, missing or unusable license metadata is a fatal error. This keeps license metadata enforceable for future datasets.

When model-level license metadata is available, the generated metadata contains a `dct:license` triple even if `--allow-missing-license` is also used.

## Defaults for new Turtle metadata files

For new files, the script generates a catalog-style title:

```text
Turtle distribution of <model title>
```

The generated media type is:

```text
https://www.iana.org/assignments/media-types/text/turtle
```

The generated completeness value is:

```text
ocmv:isComplete true
```

This differs from PNG distribution metadata. PNG diagrams are incomplete diagrammatic views, whereas `ontology.ttl` is a complete machine-readable linked-data serialization of the model.

## Distribution identifiers

Existing `metadata-turtle.ttl` files keep their current distribution URI. This avoids changing already published W3IDs.

For new Turtle metadata files, the script creates a deterministic UUIDv5 distribution URI under:

```text
https://w3id.org/ontouml-models/distribution/<uuid>/
```

The deterministic UUID input is:

```text
<model-uri>|ontology.ttl
```

This keeps new-file generation reproducible while preserving the catalog's established UUID-based distribution URI pattern.

## Model identifiers used in `dct:isPartOf`

The script resolves the model URI for Turtle distribution metadata in this order:

1. an existing `dct:isPartOf` value in `metadata-turtle.ttl`, when present;
2. an existing `dct:isPartOf` value in another distribution metadata file in the same dataset folder, when available and unambiguous;
3. an explicit HTTP(S) model URI in `metadata.yaml`, if such a field is present;
4. a deterministic UUIDv5 URI generated from the dataset folder name, using the same strategy as `scripts/metadata_yaml_to_ttl.py`.

The script intentionally does **not** read model-level `metadata.ttl` for model URI preservation. This avoids making distribution metadata generation depend on a later aggregation product.

If `metadata.ttl` exists but no existing distribution metadata file provides a usable `dct:isPartOf`, the script fails clearly instead of silently minting a new model URI. This protects existing catalog datasets from accidental replacement of UUID-based model W3IDs by newly generated identifiers.

The same protection applies when an existing `metadata-turtle.ttl` file is present but does not contain a usable `dct:isPartOf`, unless another distribution metadata file or an explicit HTTP(S) URI in `metadata.yaml` provides the model URI.

If multiple existing distribution metadata files provide conflicting `dct:isPartOf` values, including conflicts between `metadata-turtle.ttl` and another distribution metadata file, the script fails clearly and reports the conflict instead of guessing.

## Download URLs

For new metadata files, `dcat:downloadURL` values are generated as raw GitHub URLs using:

- `--repository`
- `--branch`
- `--models-dir-name`
- the dataset folder name
- `ontology.ttl`

By default, generated URLs point to:

```text
https://raw.githubusercontent.com/OntoUML/ontouml-models/master/models/<model-directory>/ontology.ttl
```

Existing `dcat:downloadURL` values are preserved when regenerating existing metadata files.

When generating new URLs, path segments are URL-quoted where needed, but commas are left unescaped to match the existing catalog style.

## Source validation

Before writing metadata, the script validates that:

- the dataset folder exists;
- `metadata.yaml` exists and can be parsed as YAML;
- `ontology.ttl` exists;
- `ontology.ttl` can be parsed as Turtle by RDFLib;
- existing distribution metadata files used for preservation can be read and parsed when needed;
- no conflicting model IRIs are found;
- a required timestamp is available.

The script builds the complete output content before writing the file, preventing partial dataset updates when validation fails.

## Requirements

Install the script dependencies:

```bash
python -m pip install -r scripts/requirements.txt
```

The Turtle metadata generator requires `rdflib` and `PyYAML`. Tests require `pytest`. These dependencies are already used by the repository scripts.

## Usage

Run from the repository root.

Commands that create new Turtle metadata files, initialize missing `fdpo:metadataIssued`, or update `fdpo:metadataModified` require `--metadata-timestamp`. Use a fixed timestamp for deterministic automation runs. Use `--metadata-timestamp now` only for manual, intentionally non-deterministic execution.

Generate metadata for one dataset folder:

```bash
python scripts/generate_turtle_metadata.py models/<model-directory> \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Generate metadata for multiple dataset folders:

```bash
python scripts/generate_turtle_metadata.py models/<model-1> models/<model-2> \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Generate metadata for all dataset folders under `models/`:

```bash
python scripts/generate_turtle_metadata.py --all --models-dir models \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Generate all Turtle metadata while allowing legacy datasets without license metadata:

```bash
python scripts/generate_turtle_metadata.py --all --models-dir models --allow-missing-license \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Preview generation without writing files:

```bash
python scripts/generate_turtle_metadata.py models/<model-directory> --dry-run \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Check whether files are up to date without writing them. The command exits with code `1` if `metadata-turtle.ttl` would change:

```bash
python scripts/generate_turtle_metadata.py models/<model-directory> --check \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Fail when the generated file already exists. This check is atomic at dataset level: no metadata file is written if the target already exists:

```bash
python scripts/generate_turtle_metadata.py models/<model-directory> --no-overwrite \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Use a different repository or branch in generated `dcat:downloadURL` values:

```bash
python scripts/generate_turtle_metadata.py models/<model-directory> \
  --repository pedropaulofb/ontouml-models-dev \
  --branch master \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Use a different repository-relative models path in generated `dcat:downloadURL` values:

```bash
python scripts/generate_turtle_metadata.py models/<model-directory> \
  --models-dir-name models \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Use a fixed timestamp for new metadata files, for existing metadata files that do not already contain `fdpo:metadataIssued`, or for existing metadata files that will change and therefore need an updated `fdpo:metadataModified`. The value must use an `xsd:dateTime` lexical form such as `2024-01-02T03:04:05Z`:

```bash
python scripts/generate_turtle_metadata.py models/<model-directory> \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Use `--metadata-timestamp now` only when a non-deterministic current execution timestamp is intentionally desired.

Run from inside a dataset folder that contains `metadata.yaml`:

```bash
python ../../scripts/generate_turtle_metadata.py \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

## Command-line arguments

| Argument | Required | Default | Meaning |
| --- | --- | --- | --- |
| `datasets` | No | current directory if it contains `metadata.yaml` | One or more model dataset folders to process. |
| `--all` | No | off | Process all dataset folders below `--models-dir`. Cannot be combined with explicit dataset folders. |
| `--models-dir PATH` | No | `models` | Models directory used with `--all`. |
| `--allow-missing-license` | No | off | Allow legacy datasets without license metadata. Without it, license is mandatory. |
| `--check` | No | off | Do not write files; exit `1` if `metadata-turtle.ttl` would change. |
| `--dry-run` | No | off | Validate inputs and report files that would be generated without writing them. |
| `--format {text,json}` | No | `text` | Summary output format for non-interactive use. |
| `--quiet`, `--silent`, `-q` | No | off | Suppress progress and text summary output. Errors still go to `stderr`. |
| `--repository OWNER/REPO` | No | `OntoUML/ontouml-models` | GitHub repository used for generated `dcat:downloadURL` values. |
| `--branch BRANCH` | No | `master` | Git branch used for generated `dcat:downloadURL` values. |
| `--models-dir-name PATH` | No | `models` | Repository-relative models path used inside generated `dcat:downloadURL` values. |
| `--model-iri-base IRI` | No | `https://w3id.org/ontouml-models/model` | Base IRI used for deterministic UUIDv5 model IRIs when no existing catalog model IRI is available. |
| `--no-overwrite` | No | overwrite enabled | Fail if `metadata-turtle.ttl` already exists. |
| `--metadata-timestamp VALUE` | Conditional | none | `xsd:dateTime` value used to initialize missing `fdpo:metadataIssued` values and update `fdpo:metadataModified` when existing metadata files change. Required when creating new metadata files, when existing metadata files lack `fdpo:metadataIssued`, or when existing files need regeneration changes. |

## Input assumptions

Each dataset folder must contain:

```text
metadata.yaml
ontology.ttl
```

The model-level `metadata.yaml` must provide enough information for the script to determine:

- the model title;
- the model issued date;
- the model license, unless `--allow-missing-license` is used for a legacy dataset.

The model URI is normally preserved from existing distribution metadata. For a genuinely new dataset, the script uses the same deterministic UUIDv5 fallback strategy as `scripts/metadata_yaml_to_ttl.py`.

## Exit codes

| Exit code | Meaning |
| --- | --- |
| `0` | Generation/check completed successfully. In `--check` mode, no changes are needed. |
| `1` | Dataset processing failed, or `--check` detected required updates. |
| `2` | Command-line, discovery, or setup error prevented normal execution. |

## JSON and quiet output

Use JSON output for automation-friendly reporting:

```bash
python scripts/generate_turtle_metadata.py models/<model-directory> \
  --format json \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Use quiet mode to suppress normal text progress and summary output:

```bash
python scripts/generate_turtle_metadata.py models/<model-directory> --quiet \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Errors are still printed to `stderr`.

## Future workflow context

A future maintenance workflow may eventually run the distribution metadata generators before the final model-level converter, for example:

```text
python scripts/validate_metadata_yaml.py --all --models-dir models --fix --allow-missing-license
python scripts/generate_png_metadata.py --all --models-dir models --allow-missing-license --metadata-timestamp now
python scripts/generate_json_metadata.py --all --models-dir models --allow-missing-license --metadata-timestamp now
python scripts/generate_turtle_metadata.py --all --models-dir models --allow-missing-license --metadata-timestamp now
python scripts/generate_vpp_metadata.py --all --models-dir models --allow-missing-license --metadata-timestamp now
python scripts/metadata_yaml_to_ttl.py --all --models-dir models --allow-missing-license --metadata-timestamp now
```

This workflow is only context. This script does not create or modify any workflow configuration.

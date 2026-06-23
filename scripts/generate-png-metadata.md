# Generate PNG distribution metadata

This repository contains one RDF/Turtle metadata file for each PNG diagram distribution of a model.

The generator implemented in `scripts/generate_png_metadata.py` scans one or more model dataset folders and creates these files:

| Source PNG folder | Generated metadata file |
| --- | --- |
| `original-diagrams/<diagram>.png` | `metadata-png-o-<diagram>.ttl` |
| `new-diagrams/<diagram>.png` | `metadata-png-n-<diagram>.ttl` |

`<diagram>` is the PNG filename stem, i.e., the filename without the `.png` extension. For example:

```text
models/example/new-diagrams/main-diagram.png
models/example/metadata-png-n-main-diagram.ttl
```

## Purpose and pipeline role

The script generates distribution-level metadata for PNG diagram images. It is intended to run **before** model-level `metadata.ttl` is generated.

The model-level source of truth is `metadata.yaml`. The PNG generator does **not** update `metadata.ttl`, and it does **not** add model-level `dcat:distribution` triples. Instead, each generated PNG metadata file points back to the model with `dct:isPartOf`.

For existing catalog datasets, the script preserves the already published model W3ID used in `dct:isPartOf`. When an existing model-level `metadata.ttl` is present, its model subject is treated as the canonical model URI. If `metadata.ttl` is absent, the script falls back to existing `metadata-png-*.ttl` files. This is not a generation-order dependency: when `metadata.ttl` is absent, the script still runs and uses the same deterministic UUIDv5 model URI strategy as `scripts/metadata_yaml_to_ttl.py`.

Recommended future generation order:

```text
metadata.yaml + PNG files
  -> metadata-png-*.ttl

metadata.yaml + metadata-png-*.ttl + other distribution metadata
  -> metadata.ttl
```

This document only describes the PNG metadata generator. No GitHub Actions workflow, CI configuration, or full automation pipeline is created by this script.

## Generated RDF semantics

For each PNG file, the script creates a `dcat:Distribution` metadata file following the RDF pattern used by existing generated distribution files such as `metadata-json.ttl`, `metadata-turtle.ttl`, and `metadata-vpp.ttl`.

The generated distribution includes:

- `rdf:type dcat:Distribution`
- `dct:isPartOf`, pointing to the preserved or generated model dataset URI
- `dct:issued`, derived from the model-level `metadata.yaml`
- `dct:license`, copied from existing PNG metadata or derived from model-level `metadata.yaml` when available
- `dct:title`
- `skos:editorialNote`
- `dcat:mediaType <https://www.iana.org/assignments/media-types/image/png>`
- `dcat:downloadURL`, pointing to the raw GitHub URL of the PNG file
- `ocmv:isComplete false`, because PNG diagrams are not complete materializations of the model
- `fdpo:metadataIssued`
- `fdpo:metadataModified`

## Existing metadata preservation

When regenerating an existing PNG metadata file, the script preserves curated values that should not be changed accidentally:

- the existing distribution URI;
- the existing model URI used in `dct:isPartOf`;
- `dct:title`;
- `skos:editorialNote`;
- `dcat:downloadURL`;
- `dct:license`;
- the exact lexical value of `fdpo:metadataIssued`;
- the exact lexical value of `fdpo:metadataModified` when the regenerated file is otherwise unchanged.

Preserving exact timestamp lexical values avoids changes such as nanosecond truncation or conversion from `Z` to `+00:00` when existing `xsd:dateTime` literals are parsed.

Timestamp handling follows the same maintenance strategy used by `scripts/metadata_yaml_to_ttl.py`:

- if an existing PNG metadata file has `fdpo:metadataIssued`, that value is preserved;
- if there is no existing PNG metadata file, or the existing file has no `fdpo:metadataIssued`, the value is initialized from `--metadata-timestamp`;
- if an existing PNG metadata file changes during regeneration, `fdpo:metadataModified` is updated from `--metadata-timestamp`;
- if an existing PNG metadata file is already up to date, `fdpo:metadataModified` is preserved.

For existing files, the script still regenerates the remaining triples from model metadata and script defaults, including `dct:issued`, `dcat:mediaType`, and `ocmv:isComplete`. The `dct:isPartOf` value is preserved from existing `metadata.ttl` when present, or otherwise from existing PNG metadata.

## License handling

By default, model-level `metadata.yaml` must contain a usable `license` value. This matches the policy of `scripts/metadata_yaml_to_ttl.py`: license metadata is mandatory unless the legacy-compatibility option is explicitly used.

Use `--allow-missing-license` only for legacy datasets that intentionally lack license metadata:

```bash
python scripts/generate_png_metadata.py models/<model-directory> --allow-missing-license \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

When `--allow-missing-license` is used and no model-level license is present:

- an existing PNG-level `dct:license` is preserved when regenerating an existing `metadata-png-*.ttl` file;
- new PNG metadata files omit `dct:license`;
- generation continues so older catalog entries can be processed.

When `--allow-missing-license` is not used, missing or unusable license metadata is a fatal error. This keeps license metadata enforceable for future datasets.

## Defaults for new PNG metadata files

For new files, the script generates a catalog-style title:

```text
PNG distribution of diagram '<diagram label>' from the <model title> (<version>)
```

The diagram label is derived from the filename stem by replacing spaces, underscores, and hyphens with spaces.

| PNG filename | Diagram label |
| --- | --- |
| `petroleum-system.png` | `petroleum system` |
| `lifts,-ski-slopes,-and-snowparks.png` | `lifts, ski slopes, and snowparks` |

The version suffix is determined by the source folder:

| Source folder | Version label |
| --- | --- |
| `original-diagrams` | `original version` |
| `new-diagrams` | `Visual Paradigm version` |

The default editorial notes are:

| Source folder | Default `skos:editorialNote` |
| --- | --- |
| `original-diagrams` | `This image depicts the diagram as originally represented by its author(s).` |
| `new-diagrams` | `This image depicts a version of the original diagram re-created in the Visual Paradigm editor.` |

## Distribution identifiers

Existing target metadata files keep their current distribution URI. This avoids changing already published W3IDs.

For new PNG metadata files, the script creates a deterministic UUIDv5 distribution URI under:

```text
https://w3id.org/ontouml-models/distribution/<uuid>/
```

The deterministic UUID input is:

```text
<model-uri>|<diagram-folder>/<png-filename>
```

For example, if the same PNG filename exists in both `original-diagrams` and `new-diagrams`, the generated UUIDs differ because the diagram folder is part of the UUID input.

This keeps new-file generation reproducible while preserving the catalog's established UUID-based distribution URI pattern.

## Model identifiers used in `dct:isPartOf`

The script resolves the model URI for PNG distribution metadata in this order:

1. the subject URI of an existing model-level `metadata.ttl`, when available;
2. an existing `dct:isPartOf` value in any `metadata-png-*.ttl` file in the dataset folder, when `metadata.ttl` is absent;
3. an explicit HTTP(S) model URI in `metadata.yaml`, if present;
4. a deterministic UUIDv5 URI generated from the dataset folder name, using the same strategy as `scripts/metadata_yaml_to_ttl.py`.

This prevents existing UUID-based model W3IDs such as `https://w3id.org/ontouml-models/model/<uuid>` from being replaced by folder-name IRIs such as `https://w3id.org/ontouml-models/model/<folder-name>` during PNG metadata regeneration. For new datasets where no model-level `metadata.ttl` exists yet, the deterministic UUIDv5 fallback keeps the PNG generator compatible with the later `metadata.yaml` to `metadata.ttl` conversion step.

## Download URLs

For new metadata files, `dcat:downloadURL` values are generated as raw GitHub URLs using:

- `--repository`
- `--branch`
- `--models-dir-name`
- the dataset folder name
- the diagram source folder
- the PNG filename

By default, generated URLs point to:

```text
https://raw.githubusercontent.com/OntoUML/ontouml-models/master/models/<model-directory>/<diagram-folder>/<png-filename>
```

Existing `dcat:downloadURL` values are preserved when regenerating existing metadata files.

When generating new URLs, path segments are URL-quoted where needed, but commas are left unescaped to match the existing catalog style.

## Optional file-derived metadata

By default, the script does not add image dimensions, file size, or checksum metadata because these are not part of the current required distribution metadata shape. Use `--include-file-metadata` to emit optional file-derived triples:

- `dcat:byteSize`
- `schema:width`
- `schema:height`
- `spdx:checksum` with SHA-256

PNG validation always checks the PNG signature, IHDR chunk, chunk boundaries, CRC values, and IEND chunk before any metadata is written. This validation uses only the Python standard library.

## Requirements

Install the script dependencies:

```bash
python -m pip install -r scripts/requirements.txt
```

The PNG metadata generator requires `rdflib` and `PyYAML`. Tests require `pytest`. All are listed in `scripts/requirements.txt`.

## Usage

Run from the repository root.

Commands that create new PNG metadata files, initialize missing `fdpo:metadataIssued`, or update `fdpo:metadataModified` require `--metadata-timestamp`. Use a fixed timestamp for deterministic automation runs. Use `--metadata-timestamp now` only for manual, intentionally non-deterministic execution.

Generate metadata for one dataset folder:

```bash
python scripts/generate_png_metadata.py models/<model-directory> \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Generate metadata for multiple dataset folders:

```bash
python scripts/generate_png_metadata.py models/<model-1> models/<model-2> \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Generate metadata for all dataset folders under `models/`:

```bash
python scripts/generate_png_metadata.py --all --models-dir models \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Generate all PNG metadata while allowing legacy datasets without license metadata:

```bash
python scripts/generate_png_metadata.py --all --models-dir models --allow-missing-license \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Preview generation without writing files:

```bash
python scripts/generate_png_metadata.py models/<model-directory> --dry-run \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Check whether files are up to date without writing them. The command exits with code `1` if any PNG metadata file would change:

```bash
python scripts/generate_png_metadata.py models/<model-directory> --check \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Fail when a generated file already exists. This check is atomic at dataset level: no metadata files are written if any target already exists:

```bash
python scripts/generate_png_metadata.py models/<model-directory> --no-overwrite \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Use a different repository or branch in generated `dcat:downloadURL` values:

```bash
python scripts/generate_png_metadata.py models/<model-directory> \
  --repository pedropaulofb/ontouml-models-dev \
  --branch master \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Use a different repository-relative models path in generated `dcat:downloadURL` values:

```bash
python scripts/generate_png_metadata.py models/<model-directory> \
  --models-dir-name models \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Use a fixed timestamp for new metadata files, for existing metadata files that do not already contain `fdpo:metadataIssued`, or for existing metadata files that will change and therefore need an updated `fdpo:metadataModified`. The value must use an `xsd:dateTime` lexical form such as `2024-01-02T03:04:05Z`:

```bash
python scripts/generate_png_metadata.py models/<model-directory> \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Use `--metadata-timestamp now` only when a non-deterministic current execution timestamp is intentionally desired.

Add optional file-derived metadata:

```bash
python scripts/generate_png_metadata.py models/<model-directory> --include-file-metadata \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Run from inside a dataset folder that contains `metadata.yaml`:

```bash
python ../../scripts/generate_png_metadata.py \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

## Command-line arguments

| Argument | Required | Default | Meaning |
| --- | --- | --- | --- |
| `datasets` | No | current directory if it contains `metadata.yaml` | One or more model dataset folders to process. |
| `--all` | No | off | Process all dataset folders below `--models-dir`. Cannot be combined with explicit dataset folders. |
| `--models-dir PATH` | No | `models` | Models directory used with `--all`. |
| `--allow-missing-license` | No | off | Allow legacy datasets without license metadata. Without it, license is mandatory. |
| `--check` | No | off | Do not write files; exit `1` if any PNG metadata file would change. |
| `--dry-run` | No | off | Validate inputs and report files that would be generated without writing them. |
| `--format {text,json}` | No | `text` | Summary output format for non-interactive use. |
| `--quiet`, `--silent`, `-q` | No | off | Suppress progress and text summary output. Errors still go to `stderr`. |
| `--repository OWNER/REPO` | No | `OntoUML/ontouml-models` | GitHub repository used for generated `dcat:downloadURL` values. |
| `--branch BRANCH` | No | `master` | Git branch used for generated `dcat:downloadURL` values. |
| `--models-dir-name PATH` | No | `models` | Repository-relative models path used inside generated `dcat:downloadURL` values. |
| `--model-iri-base IRI` | No | `https://w3id.org/ontouml-models/model` | Base IRI used for deterministic UUIDv5 model IRIs when no existing catalog model IRI is available. |
| `--no-overwrite` | No | overwrite enabled | Fail if a target metadata file already exists. |
| `--strict` | No | off | Fail if an expected diagram folder is missing or empty. |
| `--include-file-metadata` | No | off | Also add optional byte size, SHA-256 checksum, width, and height triples. |
| `--metadata-timestamp VALUE` | Conditional | none | `xsd:dateTime` value used to initialize missing `fdpo:metadataIssued` values and update `fdpo:metadataModified` when existing metadata files change. Required when creating new metadata files, when existing metadata files lack `fdpo:metadataIssued`, or when existing files need regeneration changes. |

## Input assumptions

Each dataset folder must contain:

```text
metadata.yaml
```

The model-level `metadata.yaml` must provide enough information for the script to determine:

- the model title;
- the model issued date;
- the model license, unless `--allow-missing-license` is used for a legacy dataset.

The model URI is preserved from existing catalog metadata when available. Otherwise, it is generated deterministically from the dataset folder name using the same UUIDv5 approach used by the model-level metadata converter.

Each dataset must contain at least one PNG file in one of these folders:

```text
original-diagrams/
new-diagrams/
```

In normal mode, a missing or empty `original-diagrams` or `new-diagrams` folder is tolerated as long as at least one PNG diagram is found. Use `--strict` to fail if either expected diagram folder is missing or empty.

Only direct PNG files inside these folders are processed. The `.png` extension is matched case-insensitively. Nested files are not scanned.

## Error handling and exit codes

The script uses these exit codes:

| Exit code | Meaning |
| --- | --- |
| `0` | Generation completed successfully. In `--check` mode, no changes are needed. |
| `1` | Generation failed for at least one dataset, or `--check` detected changes. |
| `2` | Command-line parsing, target discovery, or setup prevented normal execution. |

The script fails for critical problems, including:

- missing dataset folder;
- missing or unparsable `metadata.yaml`;
- missing model title in `metadata.yaml`;
- missing model issued date in `metadata.yaml`;
- missing or unusable model license in `metadata.yaml`, unless `--allow-missing-license` is used;
- no PNG diagrams found;
- unsupported PNG filenames with control characters;
- unreadable, invalid, or truncated PNG files;
- duplicate generated metadata paths;
- duplicate generated distribution URIs;
- missing `--metadata-timestamp` when `fdpo:metadataIssued` must be initialized or `fdpo:metadataModified` must be updated;
- invalid `--metadata-timestamp` values;
- malformed existing PNG metadata files;
- existing target files when `--no-overwrite` is used.

## Atomicity

For each processed dataset, the script completes input validation and builds all RDF graphs before writing any target file. This prevents partial generation when a later diagram is invalid, when `--strict` fails, when `--no-overwrite` detects an existing target, or when optional file-derived metadata cannot be computed.

## Terminal output

For each generated file, the script prints:

```text
generated: <metadata-file> <- <png-file>
```

In dry-run mode, it prints:

```text
would generate: <metadata-file> <- <png-file>
```

In check mode, it prints either:

```text
needs update: <metadata-file> <- <png-file>
up to date: <metadata-file> <- <png-file>
```

Use `--format json` for machine-readable output.

## Run tests

Run the PNG metadata generator tests:

```bash
python -m pytest -q scripts/tests/test_generate_png_metadata.py
```

Optional syntax check:

```bash
python -m py_compile scripts/generate_png_metadata.py scripts/tests/test_generate_png_metadata.py
```

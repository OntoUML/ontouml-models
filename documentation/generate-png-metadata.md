# Generate PNG distribution metadata

This repository contains one generated RDF/Turtle metadata file for each PNG diagram distribution of a model.

The generator implemented in `scripts/generate_png_metadata.py` scans model dataset folders and creates these files:

| Source PNG folder | Generated metadata file |
| --- | --- |
| `original-diagrams/<diagram>.png` | `metadata-png-o-<diagram>.ttl` |
| `new-diagrams/<diagram>.png` | `metadata-png-n-<diagram>.ttl` |

`<diagram>` is the PNG filename stem, i.e., the filename without the `.png` extension. For example:

```text
models/example/new-diagrams/main-diagram.png
models/example/metadata-png-n-main-diagram.ttl
```

## Generated RDF semantics

For each PNG file, the script creates a `dcat:Distribution` metadata file following the same RDF pattern used by existing generated distribution files such as `metadata-json.ttl`, `metadata-turtle.ttl`, and `metadata-vpp.ttl`.

The generated distribution includes:

- `rdf:type dcat:Distribution`
- `dct:isPartOf`, pointing to the model dataset
- `dct:issued`, copied from the model-level `metadata.ttl`
- `dct:license`, copied from the model-level `metadata.ttl`
- `dct:title`
- `dcat:mediaType <https://www.iana.org/assignments/media-types/image/png>`
- `ocmv:isComplete false`, because PNG diagrams are not complete materializations of the model
- `dcat:downloadURL`, pointing to the raw GitHub URL of the PNG file
- `fdpo:metadataIssued`
- `fdpo:metadataModified`

The script does **not** add a model-level `dcat:distribution` triple to the generated PNG metadata file. In the current catalog convention, distribution metadata files point back to the model with `dct:isPartOf`; the model-level metadata file is where `dcat:distribution` links are maintained.

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

This makes generation reproducible while preserving the catalog's established UUID-based distribution URI pattern.

## Optional file-derived metadata

By default, the script does not add image dimensions, file size, or checksum metadata because these are not part of the current required distribution metadata shape. Use `--include-file-metadata` to emit optional `dcat:byteSize`, SHA-256 checksum, width, and height triples.

PNG validation always checks the PNG signature, IHDR chunk, chunk boundaries, CRC values, and IEND chunk before any metadata is written.

## Requirements

Install the Python dependency:

```bash
python -m pip install -r requirements-png-metadata.txt
```

For tests:

```bash
python -m pip install pytest
```

## Usage

Run from the repository root.

Generate metadata for one dataset folder:

```bash
python scripts/generate_png_metadata.py models/<model-directory>
```

Generate metadata for multiple dataset folders:

```bash
python scripts/generate_png_metadata.py models/<model-1> models/<model-2>
```

Generate metadata for all dataset folders under `models/`:

```bash
python scripts/generate_png_metadata.py --all --models-dir models
```

Preview generation without writing files:

```bash
python scripts/generate_png_metadata.py models/<model-directory> --dry-run
```

Fail when a generated file already exists. This check is atomic at dataset level: no metadata files are written if any target already exists:

```bash
python scripts/generate_png_metadata.py models/<model-directory> --no-overwrite
```

Use a different repository or branch in `dcat:downloadURL` values:

```bash
python scripts/generate_png_metadata.py models/<model-directory> \
  --repository pedropaulofb/ontouml-models-dev \
  --branch master
```

Use a fixed timestamp for new metadata files. The value must use an `xsd:dateTime` lexical form such as `2024-01-02T03:04:05Z`:

```bash
python scripts/generate_png_metadata.py models/<model-directory> \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

## Input assumptions

Each dataset folder must contain:

```text
metadata.ttl
```

The model-level `metadata.ttl` must identify the model as `mod:SemanticArtefact` or `dcat:Dataset`, and must provide:

- `dct:title`
- `dct:issued`
- `dct:license`

## Error handling

The script fails with a non-zero exit code for critical problems, including:

- missing dataset folder
- missing or unparsable `metadata.ttl`
- missing model `dct:title`
- missing model `dct:issued`
- missing model `dct:license`
- no PNG diagrams found
- unsupported PNG filenames with control characters
- unreadable, invalid, or truncated PNG files
- duplicate generated metadata paths
- duplicate generated distribution URIs
- invalid `--metadata-timestamp` values
- malformed existing PNG metadata files

In normal mode, missing or empty `new-diagrams` or `original-diagrams` folders are tolerated as long as at least one PNG diagram is found. Use `--strict` to fail if either expected diagram folder is missing or empty.

## Atomicity

For each processed dataset, the script completes input validation and builds all RDF graphs before writing any target file. This prevents partial generation when a later diagram is invalid, when `--strict` fails, when `--no-overwrite` detects an existing target, or when optional file-derived metadata cannot be computed.

## Run tests

```bash
python -m pytest tests/test_generate_png_metadata.py
```

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

## Generated RDF semantics

For each PNG file, the script creates a `dcat:Distribution` metadata file following the same RDF pattern used by existing generated distribution files such as `metadata-json.ttl`, `metadata-turtle.ttl`, and `metadata-vpp.ttl`.

The generated distribution includes:

- `rdf:type dcat:Distribution`
- `dct:isPartOf`, pointing to the model dataset
- `dct:issued`, copied from the model-level `metadata.ttl`
- `dct:license`, copied from the model-level `metadata.ttl`
- `dct:title`
- `skos:editorialNote`
- `dcat:mediaType <https://www.iana.org/assignments/media-types/image/png>`
- `dcat:downloadURL`, pointing to the raw GitHub URL of the PNG file
- `ocmv:isComplete false`, because PNG diagrams are not complete materializations of the model
- `fdpo:metadataIssued`
- `fdpo:metadataModified`

The script does **not** add a model-level `dcat:distribution` triple to the generated PNG metadata file. In the current catalog convention, distribution metadata files point back to the model with `dct:isPartOf`; the model-level metadata file is where `dcat:distribution` links are maintained.

## Existing metadata preservation

When regenerating an existing PNG metadata file, the script preserves curated values that should not be changed accidentally:

- the existing distribution URI;
- `dct:title`;
- `skos:editorialNote`;
- `dcat:downloadURL`;
- the exact lexical values of `fdpo:metadataIssued` and `fdpo:metadataModified`.

Preserving the exact timestamp lexical values avoids changes such as nanosecond truncation or conversion from `Z` to `+00:00` when existing `xsd:dateTime` literals are parsed.

For existing files, the script still regenerates the remaining required triples from the model metadata and script defaults, including `dct:isPartOf`, `dct:issued`, `dct:license`, `dcat:mediaType`, and `ocmv:isComplete`.

## Defaults for new PNG metadata files

For new files, the script generates a catalog-style title:

```text
PNG distribution of diagram '<diagram label>' from the <model title> (<version>)
```

The diagram label is derived from the filename stem by replacing spaces, underscores, and hyphens with spaces. For example:

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

This makes generation reproducible while preserving the catalog's established UUID-based distribution URI pattern.

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

When generating new URLs, path segments are URL-quoted where needed, but commas are left unescaped to match the existing catalog style. For example, the script generates:

```text
lifts,-ski-slopes,-and-snowparks.png
```

not:

```text
lifts%2C-ski-slopes%2C-and-snowparks.png
```

## Optional file-derived metadata

By default, the script does not add image dimensions, file size, or checksum metadata because these are not part of the current required distribution metadata shape. Use `--include-file-metadata` to emit optional file-derived triples:

- `dcat:byteSize`
- `schema:width`
- `schema:height`
- `spdx:checksum` with SHA-256

PNG validation always checks the PNG signature, IHDR chunk, chunk boundaries, CRC values, and IEND chunk before any metadata is written. This validation uses only the Python standard library.

## Requirements

Install the automation dependencies:

```bash
python -m pip install -r requirements-automation.txt
```

The PNG metadata generator requires `rdflib`. Tests require `pytest`. Both are listed in `requirements-automation.txt`.

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

Use a different repository or branch in generated `dcat:downloadURL` values:

```bash
python scripts/generate_png_metadata.py models/<model-directory> \
  --repository pedropaulofb/ontouml-models-dev \
  --branch master
```

Use a different repository-relative models path in generated `dcat:downloadURL` values:

```bash
python scripts/generate_png_metadata.py models/<model-directory> \
  --models-dir-name models
```

Use a fixed timestamp for new metadata files. The value must use an `xsd:dateTime` lexical form such as `2024-01-02T03:04:05Z`:

```bash
python scripts/generate_png_metadata.py models/<model-directory> \
  --metadata-timestamp 2024-01-02T03:04:05Z
```

Add optional file-derived metadata:

```bash
python scripts/generate_png_metadata.py models/<model-directory> --include-file-metadata
```

Run from inside a dataset folder that contains `metadata.ttl`:

```bash
python ../../scripts/generate_png_metadata.py
```

## Command-line arguments

| Argument | Required | Default | Meaning |
| --- | --- | --- | --- |
| `datasets` | No | current directory if it contains `metadata.ttl` | One or more model dataset folders to process. |
| `--all` | No | off | Process all dataset folders below `--models-dir`. Cannot be combined with explicit dataset folders. |
| `--models-dir PATH` | No | `models` | Models directory used with `--all`. |
| `--repository OWNER/REPO` | No | `OntoUML/ontouml-models` | GitHub repository used for generated `dcat:downloadURL` values. |
| `--branch BRANCH` | No | `master` | Git branch used for generated `dcat:downloadURL` values. |
| `--models-dir-name PATH` | No | `models` | Repository-relative models path used inside generated `dcat:downloadURL` values. |
| `--no-overwrite` | No | overwrite enabled | Fail if a target metadata file already exists. |
| `--strict` | No | off | Fail if an expected diagram folder is missing or empty. |
| `--dry-run` | No | off | Validate inputs and report files that would be generated without writing them. |
| `--include-file-metadata` | No | off | Also add optional byte size, SHA-256 checksum, width, and height triples. |
| `--metadata-timestamp VALUE` | No | current UTC timestamp | `xsd:dateTime` value used for `fdpo:metadataIssued` and `fdpo:metadataModified` on new files. |

## Input assumptions

Each dataset folder must contain:

```text
metadata.ttl
```

The model-level `metadata.ttl` must identify the model as `mod:SemanticArtefact` or `dcat:Dataset`, and must provide:

- `dct:title`
- `dct:issued`
- `dct:license`

Each dataset must contain at least one PNG file in one of these folders:

```text
original-diagrams/
new-diagrams/
```

In normal mode, a missing or empty `original-diagrams` or `new-diagrams` folder is tolerated as long as at least one PNG diagram is found. Use `--strict` to fail if either expected diagram folder is missing or empty.

Only direct `.png` files inside these folders are processed. Nested files are not scanned.

## Error handling

The script fails with a non-zero exit code for critical problems, including:

- missing dataset folder;
- missing or unparsable `metadata.ttl`;
- missing model `dct:title`;
- missing model `dct:issued`;
- missing model `dct:license`;
- no PNG diagrams found;
- unsupported PNG filenames with control characters;
- unreadable, invalid, or truncated PNG files;
- duplicate generated metadata paths;
- duplicate generated distribution URIs;
- invalid `--metadata-timestamp` values;
- malformed existing PNG metadata files;
- existing target files when `--no-overwrite` is used.

## Atomicity

For each processed dataset, the script completes input validation and builds all RDF graphs before writing any target file. This prevents partial generation when a later diagram is invalid, when `--strict` fails, when `--no-overwrite` detects an existing target, or when optional file-derived metadata cannot be computed.

## Serialization notes

RDFLib serializes Turtle using its own formatting. Regenerated files may therefore differ from older manually generated files in non-semantic ways, such as:

- prefix order;
- whitespace before `;` and `.`;
- omission of unused prefixes;
- predicate order;
- compact boolean syntax, e.g., `ocmv:isComplete false` instead of `"false"^^xsd:boolean`.

These are Turtle serialization differences and do not change the RDF graph.

## Terminal output

For each generated file, the script prints:

```text
generated: <metadata-file> <- <png-file>
```

In dry-run mode, it prints:

```text
would generate: <metadata-file> <- <png-file>
```

## Run tests

Run the PNG metadata generator tests:

```bash
python -m pytest -q tests/test_generate_png_metadata.py
```

Optional syntax check:

```bash
python -m py_compile scripts/generate_png_metadata.py tests/test_generate_png_metadata.py
```

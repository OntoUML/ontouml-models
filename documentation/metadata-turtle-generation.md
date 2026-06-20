# Metadata Turtle distribution generation

This document describes the automation added to generate `metadata-turtle.ttl` files for OntoUML/UFO Catalog dataset folders.

## Purpose

The script `tools/generate_metadata_turtle.py` generates metadata for an existing Turtle representation of a model:

```txt
models/<model-directory>/ontology.ttl
```

It creates or replaces:

```txt
models/<model-directory>/metadata-turtle.ttl
```

The script does **not** generate `ontology.ttl` from `ontology.json`. It only describes the already existing `ontology.ttl` distribution.

## Metadata generated

For each dataset folder, the generated RDF describes one `dcat:Distribution` with the catalog's existing Turtle-distribution convention:

- `rdf:type dcat:Distribution`
- `dct:isPartOf <model-uri>`
- `dct:issued` copied from the model-level `metadata.ttl`
- `dcat:mediaType <https://www.iana.org/assignments/media-types/text/turtle>`
- `dct:license` copied from the model-level `metadata.ttl`
- `dct:title "Turtle distribution of <model title>"@en`
- `dcat:downloadURL` pointing to the raw GitHub `ontology.ttl` file
- `ocmv:isComplete true`
- `fdpo:metadataIssued`
- `fdpo:metadataModified`

If `metadata-turtle.ttl` already exists and `--overwrite` is used, the script reuses the existing distribution URI and preserves the existing `fdpo:metadataIssued` value by default.

## Required input files

Each processed dataset folder must contain:

```txt
metadata.ttl
ontology.ttl
```

`metadata.ttl` must describe exactly one model resource typed as `mod:SemanticArtefact` and must contain:

- `dct:title`
- `dct:issued` using `xsd:dateTime`, `xsd:date`, `xsd:gYearMonth`, or `xsd:gYear`
- `dct:license` as an IRI

`ontology.ttl` must be syntactically valid Turtle and non-empty.

## Usage

From the repository root, generate one file:

```bash
python tools/generate_metadata_turtle.py models/amaral2019rot
```

Generate files for all model folders:

```bash
python tools/generate_metadata_turtle.py models --recursive
```

Overwrite existing files while preserving existing distribution URIs and `fdpo:metadataIssued` values:

```bash
python tools/generate_metadata_turtle.py models --recursive --overwrite
```

Preview without writing files:

```bash
python tools/generate_metadata_turtle.py models --recursive --dry-run
```

Use a different raw-file URL base, for example for the development fork:

```bash
python tools/generate_metadata_turtle.py models --recursive \
  --raw-base-url https://raw.githubusercontent.com/pedropaulofb/ontouml-models-dev/master
```

Also add the generated distribution URI to the model-level `metadata.ttl` when missing:

```bash
python tools/generate_metadata_turtle.py models/<model-directory> --update-model-metadata
```

This option is intentionally explicit because it modifies `metadata.ttl` in addition to generating `metadata-turtle.ttl`.

## Error handling

The script fails with a non-zero exit code when it finds:

- a missing dataset folder;
- a missing `ontology.ttl`;
- a missing `metadata.ttl`;
- invalid Turtle syntax;
- an empty `ontology.ttl`;
- no identifiable model resource in `metadata.ttl`;
- multiple possible model resources in `metadata.ttl`;
- missing required model metadata;
- multiple `dct:issued` values;
- unsupported `dct:issued` datatypes;
- non-IRI license values;
- inconsistent existing `metadata-turtle.ttl` files.

Warnings are printed when the script cannot compute a repository-relative path from `--repo-root`. Use `--strict` to treat warnings as errors.

## Development

Install the minimal dependencies in an isolated environment:

```bash
python -m pip install -r requirements-automation.txt
```

Run tests:

```bash
pytest tests
```

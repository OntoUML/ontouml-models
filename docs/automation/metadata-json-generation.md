# Generating `metadata-json.ttl` from `metadata.yaml`

This document describes the automation that generates the RDF/Turtle metadata file for the JSON distribution of a cataloged model.

The generated file is:

```txt
models/<model-slug>/metadata-json.ttl
```

It describes:

```txt
models/<model-slug>/ontology.json
```

It does **not** generate:

- `metadata.ttl` from `metadata.yaml`;
- `ontology.ttl` from `ontology.json`;
- metadata for VPP, Turtle, or PNG distributions.

## RDF structure

The generated RDF follows the current catalog convention for JSON distribution metadata. The distribution resource is typed as `dcat:Distribution` and includes:

- `dct:isPartOf` pointing to the model dataset URI;
- `dct:issued` copied from the model metadata unless overridden for the JSON distribution;
- `dcat:mediaType` set to `https://www.iana.org/assignments/media-types/application/json`;
- `dct:license` copied from the model metadata unless overridden for the JSON distribution;
- `ocmv:conformsToSchema` set to `https://w3id.org/ontouml/schema` by default;
- `dct:title`, defaulting to `JSON distribution of <model title>` with language tag `@en`;
- `dcat:downloadURL`, defaulting to the raw GitHub URL for `ontology.json`;
- `ocmv:isComplete` set to `true`;
- `fdpo:metadataIssued` and `fdpo:metadataModified`.

## Required input file

Each processed dataset folder must contain:

```txt
metadata.yaml
```

By default, it must also contain:

```txt
ontology.json
```

This check can be disabled with `--no-check-ontology-json`, mainly for tests or staged migrations.

## Recommended `metadata.yaml` shape

```yaml
model:
  id: d88fe48c-d574-43b4-85d6-a6e1aeaa6726
  title: Reference Ontology of Trust
  issued: 2019
  license: https://creativecommons.org/licenses/by/4.0/

distributions:
  json:
    id: 7c83f03b-c170-49d2-9dd9-0a600be6cc96
```

This is the minimum recommended input. The script derives the default download URL from the dataset folder name, repository, and branch.

## Optional JSON distribution fields

```yaml
distributions:
  json:
    id: 7c83f03b-c170-49d2-9dd9-0a600be6cc96
    title:
      value: JSON distribution of Reference Ontology of Trust
      lang: en
    issued: 2019
    license: https://creativecommons.org/licenses/by/4.0/
    download_url: https://raw.githubusercontent.com/OntoUML/ontouml-models/master/models/amaral2019rot/ontology.json
    conforms_to_schema: https://w3id.org/ontouml/schema
    metadata_issued: 2023-04-14T17:35:29.862157Z
    metadata_modified: 2023-04-14T17:35:29.862157Z
```

## Supported model identifier forms

Preferred:

```yaml
model:
  id: d88fe48c-d574-43b4-85d6-a6e1aeaa6726
```

Alternative:

```yaml
model:
  uri: https://w3id.org/ontouml-models/model/d88fe48c-d574-43b4-85d6-a6e1aeaa6726
```

If a full URI is not provided, `model.id` must be a UUID.

## Supported distribution identifier forms

Preferred:

```yaml
distributions:
  json:
    id: 7c83f03b-c170-49d2-9dd9-0a600be6cc96
```

Alternative:

```yaml
distributions:
  json:
    uri: https://w3id.org/ontouml-models/distribution/7c83f03b-c170-49d2-9dd9-0a600be6cc96/
```

If a full URI is not provided, `distributions.json.id` must be a UUID.

The script can generate a deterministic UUID5 for missing JSON distribution IDs with `--generate-missing-distribution-id`, but explicit persistent distribution IDs are preferred.

## Running for one dataset

```bash
python scripts/generate_metadata_json_ttl.py models/amaral2019rot
```

## Running for all datasets with `metadata.yaml`

```bash
python scripts/generate_metadata_json_ttl.py --models-dir models --all
```

## Useful options

```bash
# Use the development fork in generated download URLs
python scripts/generate_metadata_json_ttl.py models/example --repository pedropaulofb/ontouml-models-dev

# Use a fixed metadata timestamp for reproducible output
python scripts/generate_metadata_json_ttl.py models/example --metadata-timestamp 2025-01-01T00:00:00Z

# Refuse to overwrite existing metadata-json.ttl
python scripts/generate_metadata_json_ttl.py models/example --no-overwrite
```

## Dependencies

Install the automation dependencies with:

```bash
python -m pip install -r requirements-automation.txt
```

## Validation against repository examples

The test suite includes a golden RDF-graph comparison based on the existing catalog file:

```txt
models/amaral2019rot/metadata-json.ttl
```

The current repository version inspected did not include `metadata.yaml` files, so the test reconstructs a minimal `metadata.yaml` source from the existing model metadata and JSON-distribution metadata, then verifies that the generated RDF graph is isomorphic to the existing `metadata-json.ttl` graph.

The YAML loader preserves scalar lexical forms intentionally. This avoids losing nanosecond precision in existing `fdpo:metadataIssued` and `fdpo:metadataModified` date-time literals.

# `metadata.yaml` validator

This document explains how to run the dataset-level `metadata.yaml` validator added under `tools/validation/`.

## Purpose

The validator checks the YAML authoring metadata file expected in each catalog dataset/model folder. It validates:

- YAML syntax, including duplicate top-level keys;
- required top-level keys;
- required non-empty values;
- expected scalar, list, and null handling;
- date-like values used for `issued` and `modified`;
- URL-valued fields;
- contributor identifier conventions;
- source URL persistence recommendations;
- LCC theme labels or URIs;
- controlled values for `ontologyType`, `designedForTask`, `context`, and `representationStyle`;
- unknown top-level fields.

The validator does not use RDFLib. It validates the YAML authoring format directly. RDFLib/SHACL validation should be used separately for generated RDF/Turtle metadata.

## Install dependencies

From the repository root:

```bash
python -m pip install -r tools/validation/requirements.txt
```

## Validate one dataset folder

```bash
python tools/validation/metadata_yaml_validator.py models/amaral2019rot
```

## Validate all datasets under `models/`

```bash
python tools/validation/metadata_yaml_validator.py models --recursive
```

## JSON output for automation

```bash
python tools/validation/metadata_yaml_validator.py models --recursive --format json
```

## Unknown fields

By default, unexpected top-level fields are errors. This can be relaxed:

```bash
python tools/validation/metadata_yaml_validator.py models --recursive --unknown-fields warning
python tools/validation/metadata_yaml_validator.py models --recursive --unknown-fields ignore
```

## Strict mode

By default, an empty `license` is reported as a warning because the catalog has legacy metadata files without explicit licenses. Use `--strict` to make this an error:

```bash
python tools/validation/metadata_yaml_validator.py models --recursive --strict
```

## Exit codes

- `0`: all checked `metadata.yaml` files have no validation errors;
- `1`: at least one validation error was found;
- `2`: command-line, file-system, or discovery problem.

## Expected top-level fields

The validator expects the following fields to be present:

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

Fields may be null only where catalog examples and metadata semantics allow missing information. The following fields must have non-empty values: `title`, `issued`, `keyword`, `theme`, `ontologyType`, `language`, `designedForTask`, `context`, and `representationStyle`.

`source` may contain any HTTP(S) URL, but the validator emits a warning when the value is not a DOI URL or DBLP URL because persistent bibliographic identifiers are preferred when available.

## Controlled values

### `ontologyType`

```yaml
ontologyType:
  - core
  - domain
  - application
```

### `designedForTask`

```yaml
designedForTask:
  - conceptual clarification
  - data publication
  - decision support system
  - example
  - information retrieval
  - interoperability
  - language engineering
  - learning
  - ontological analysis
  - software engineering
```

### `context`

```yaml
context:
  - research
  - industry
  - classroom
```

### `representationStyle`

```yaml
representationStyle:
  - ontouml
  - ufo
```

## Run tests

```bash
python -m pytest tests/test_metadata_yaml_validator.py
```

## Notes from audit

The validator accepts LCC labels such as `Class H - Social Sciences` and LCC URIs under `http://id.loc.gov/authorities/classification/`. Non-canonical labels for valid class codes are reported as warnings, not errors.

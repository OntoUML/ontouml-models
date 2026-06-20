# Metadata YAML to Turtle transformation

This document defines the initial `metadata.yaml` authoring format used to generate each dataset's `metadata.ttl` file.

The transformation is implemented in:

```txt
scripts/metadata_yaml_to_ttl.py
```

The script uses RDFLib to create RDF triples and serialize them as Turtle. It performs local validation before writing output so common metadata errors are caught before SHACL validation or FDP synchronization.

## Purpose

Dataset metadata is currently maintained in Turtle. The YAML format is intended to become the manually curated source file for model-level metadata. The generated `metadata.ttl` file preserves the RDF semantics used by the OntoUML/UFO Catalog metadata schema.

The transformation covers metadata for resources typed as:

```turtle
dcat:Dataset, mod:SemanticArtefact, dcat:Resource
```

It supports the catalog's main metadata vocabularies: DCAT, DCT, MOD, SKOS, VCARD, FDP-O, and OCMV.

## Minimum required fields

The following fields are required because they correspond to current required metadata constraints for catalog resources and semantic artefacts:

```yaml
title: Reference Ontology of Trust
issued: 2019
license: https://creativecommons.org/licenses/by/4.0/
theme: H
keywords:
  - value: trust
    lang: en
```

If `iri` is omitted, the script infers it from the dataset folder name:

```txt
https://w3id.org/ontouml-models/model/<dataset-folder-name>/
```

Use an explicit `iri` when a dataset already has a persistent UUID-based W3ID or another established catalog IRI.

## Recommended fields

The following fields are recommended for catalog completeness and FAIRness:

```yaml
language: en
modified: 2022
acronym: ROT
contributors:
  - https://orcid.org/0000-0000-0000-0000
source:
  - https://doi.org/10.1000/example
designed_for_task:
  - ConceptualClarification
context:
  - Research
representation_style:
  - OntoumlStyle
ontology_type:
  - Domain
storage_url: https://github.com/OntoUML/ontouml-models/tree/master/models/example
```

## Complete example

```yaml
iri: https://w3id.org/ontouml-models/model/d88fe48c-d574-43b4-85d6-a6e1aeaa6726/
title: Reference Ontology of Trust
acronym: ROT
issued: 2019
modified: 2022
theme: H
editorial_note: >-
  Files were imported from the source repository and curated for the catalog.
language: en
landing_page: https://github.com/unibz-core/trust-ontology
license: https://creativecommons.org/licenses/by/4.0/
contributors:
  - https://dblp.org/pid/81/4277
  - https://dblp.org/pid/134/4947
keywords:
  - value: trust
    lang: en
designed_for_task:
  - ConceptualClarification
context:
  - Research
source:
  - https://doi.org/10.1007/978-3-030-33246-4_1
representation_style:
  - OntoumlStyle
ontology_type:
  - Domain
storage_url: https://github.com/OntoUML/ontouml-models/tree/master/models/amaral2019rot
metadata_issued: 2023-04-14T17:35:28.608937306Z
metadata_modified: 2023-04-14T17:35:28.608937306Z
```


The implementation preserves the lexical form of date and dateTime values during Turtle serialization. This is important for existing FDP metadata timestamps that use nanosecond precision, such as `2023-04-14T17:35:28.608937306Z`.

## Field mapping

| YAML field | RDF predicate | Value type |
|---|---|---|
| `iri` | subject IRI | URI or slug |
| `title` | `dct:title` | literal or language-tagged literal |
| `alternative` | `dct:alternative` | literal or language-tagged literal |
| `description` | `dct:description` | literal or language-tagged literal |
| `issued` | `dct:issued` | `xsd:gYear`, `xsd:gYearMonth`, `xsd:date`, or `xsd:dateTime` |
| `modified` | `dct:modified` | `xsd:gYear`, `xsd:gYearMonth`, `xsd:date`, or `xsd:dateTime` |
| `license` | `dct:license` | IRI |
| `access_rights` | `dct:accessRights` | IRI or literal |
| `editorial_note` | `skos:editorialNote` | literal or language-tagged literal |
| `creator` / `creators` | `dct:creator` | IRI |
| `contributor` / `contributors` | `dct:contributor` | IRI |
| `publisher` | `dct:publisher` | IRI, max one |
| `metadata_issued` | `fdpo:metadataIssued` | date literal |
| `metadata_modified` | `fdpo:metadataModified` | date literal |
| `landing_page` | `dcat:landingPage` | IRI |
| `bibliographic_citation` | `dct:bibliographicCitation` | literal or language-tagged literal |
| `storage_url` | `ocmv:storageUrl` | `xsd:anyURI` literal |
| `contact_points` | `dcat:contactPoint` | blank `vcard:VCard` nodes |
| `keywords` | `dcat:keyword` | literal or language-tagged literal |
| `acronym` | `mod:acronym` | literal |
| `source` / `sources` | `dct:source` | IRI |
| `language` / `languages` | `dct:language` | string literal |
| `theme` | `dcat:theme` | LCC IRI |
| `designed_for_task` | `mod:designedForTask` | OCMV controlled value |
| `context` | `ocmv:context` | OCMV controlled value |
| `representation_style` | `ocmv:representationStyle` | OCMV controlled value |
| `ontology_type` | `ocmv:ontologyType` | OCMV controlled value |
| `is_part_of` | `dct:isPartOf` | IRI |
| `distributions` | `dcat:distribution` | IRI or distribution mapping |

## Literal syntax

Simple literal:

```yaml
title: Reference Ontology of Trust
```

Language-tagged literal:

```yaml
title:
  value: Reference Ontology of Trust
  lang: en
```

Language map:

```yaml
title:
  en: Reference Ontology of Trust
  pt: Ontologia de Referencia de Confianca
```

List of literals:

```yaml
keywords:
  - value: trust
    lang: en
  - value: social relations
    lang: en
```

## Controlled values

The script accepts compact names, friendly labels, `ocmv:` prefixed names, or full OCMV URIs for controlled values.

### `designed_for_task`

Supported values:

- `ConceptualClarification`
- `DataPublication`
- `DecisionSupportSystem`
- `Example`
- `InformationRetrieval`
- `Interoperability`
- `LanguageEngineering`
- `Learning`
- `OntologicalAnalysis`
- `SoftwareEngineering`

Example:

```yaml
designed_for_task:
  - conceptual clarification
  - interoperability
```

### `context`

Supported values:

- `Research`
- `Industry`
- `Classroom`

### `representation_style`

Supported values:

- `OntoumlStyle`
- `UfoStyle`

### `ontology_type`

Supported values:

- `Domain`
- `Application`
- `Core`

## Theme values

The `theme` field must identify exactly one Library of Congress Classification class. These forms are accepted:

```yaml
theme: H
```

```yaml
theme: lcc:H
```

```yaml
theme: http://id.loc.gov/authorities/classification/H
```

All forms generate:

```turtle
dcat:theme lcc:H .
```

## Optional distribution references

The transformation can include distribution links in `metadata.ttl` when they are explicitly listed in YAML. Distribution metadata can be represented minimally as IRIs:

```yaml
distributions:
  - https://w3id.org/ontouml-models/distribution/7c83f03b-c170-49d2-9dd9-0a600be6cc96/
```

Or with a compact mapping:

```yaml
distributions:
  - id: json
    title:
      value: JSON distribution of "Reference Ontology of Trust"
      lang: en
    media_type: https://www.iana.org/assignments/media-types/application/json
    download_url: https://raw.githubusercontent.com/OntoUML/ontouml-models/master/models/amaral2019rot/ontology.json
    is_complete: true
    conforms_to_schema: https://w3id.org/ontouml/schema
```

The recommended restructuring direction is still to generate distribution metadata from repository files in a separate step. Use distribution entries in `metadata.yaml` only when explicit distribution links must be preserved during migration.

## Running the transformation

Install dependencies:

```bash
python -m pip install -r requirements-metadata.txt
```

Generate one file:

```bash
python scripts/metadata_yaml_to_ttl.py models/amaral2019rot
```

Generate all files below `models/`:

```bash
python scripts/metadata_yaml_to_ttl.py models --recursive
```

Run recursive conversion on `models/`, not on the repository root, because every file named `metadata.yaml` below the selected path is treated as a dataset metadata source.

Print Turtle without writing a file:

```bash
python scripts/metadata_yaml_to_ttl.py models/amaral2019rot --dry-run
```

Refuse to overwrite existing `metadata.ttl`:

```bash
python scripts/metadata_yaml_to_ttl.py models/amaral2019rot --no-overwrite
```

Add a generated `ocmv:storageUrl` when `storage_url` is missing:

```bash
python scripts/metadata_yaml_to_ttl.py models/amaral2019rot --add-default-storage-url
```

## Error handling

The script fails with a non-zero exit code when:

- `metadata.yaml` is missing;
- YAML is invalid;
- the top-level YAML value is not a mapping;
- a mandatory field is missing;
- a URI field is not an absolute HTTP(S) URI, except contact e-mail values, which are converted to `mailto:` IRIs;
- a date field does not match a supported XML Schema date form or contains an invalid calendar date;
- a controlled value is unsupported;
- more than one `theme` or `publisher` value is provided;
- more than one `title` value is provided for the same language tag.

The script emits warnings, but does not fail, for unknown top-level YAML keys. These warnings are intended to catch typos while allowing forward-compatible fields during migration.


## Repository-derived regression test

The implementation includes a regression fixture derived from the existing catalog dataset `models/amaral2019rot/metadata.ttl`.

Files:

```txt
/tests/fixtures/amaral2019rot.metadata.yaml
/tests/fixtures/amaral2019rot.metadata.ttl
/tests/test_repository_metadata_examples.py
```

The test verifies that the YAML fixture generates the same model-level RDF triples as the existing Turtle metadata example. It intentionally ignores `dcat:distribution` triples because distribution metadata generation is planned as a separate automation step.

When using YAML block scalars for fields such as `editorial_note`, prefer the chomping form `>-` to avoid accidental trailing newline characters in generated RDF literals.

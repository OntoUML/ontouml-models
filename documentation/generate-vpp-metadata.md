# Generate `metadata-vpp.ttl`

This repository helper generates RDF/Turtle metadata for the Visual Paradigm project distribution of a cataloged model.

## Purpose

For each dataset folder containing `ontology.vpp`, the script creates or updates:

```txt
models/<model-directory>/metadata-vpp.ttl
```

The generated file describes the VPP file as a `dcat:Distribution` using the catalog's existing metadata pattern:

- `rdf:type dcat:Distribution`
- `dct:isPartOf` the model dataset URI
- `dct:issued`, copied from the model metadata when present
- `dct:license`, copied from the model metadata
- `dcat:mediaType <https://www.iana.org/assignments/media-types/application/octet-stream>`
- `dct:format <https://www.file-extension.info/format/vpp>`
- `dct:title "Visual Paradigm distribution of ..."@en`
- `dcat:downloadURL` pointing to the raw GitHub VPP file
- `ocmv:isComplete true`
- `fdpo:metadataIssued` and `fdpo:metadataModified`
- `dcat:byteSize`
- `spdx:checksum` with SHA-256

## Limitations

The script does not parse the proprietary internal structure of Visual Paradigm `.vpp` files. It treats `ontology.vpp` as a binary file and generates file-level distribution metadata only.

This means it does not extract:

- diagrams from the VPP project;
- model elements;
- Visual Paradigm project metadata;
- OntoUML plugin metadata stored inside the VPP file.

Those transformations require Visual Paradigm-specific tooling and are outside the scope of this script.

## Requirements

Install RDFLib before running the script:

```bash
python -m pip install rdflib
```

## Usage

Run from the repository root.

Generate metadata for one dataset folder:

```bash
python scripts/generate_vpp_metadata.py models/amaral2019rot
```

Generate metadata for every dataset folder below `models/`:

```bash
python scripts/generate_vpp_metadata.py models --recursive
```

Validate and preview without writing files:

```bash
python scripts/generate_vpp_metadata.py models --recursive --dry-run
```

Use a different raw download URL base, for example while testing in a fork:

```bash
python scripts/generate_vpp_metadata.py models --recursive \
  --base-download-url https://raw.githubusercontent.com/pedropaulofb/ontouml-models-dev/master
```

Disable file size and checksum metadata:

```bash
python scripts/generate_vpp_metadata.py models --recursive --no-file-metadata
```

## Error handling

The script fails with a non-zero exit code when it detects problems such as:

- missing dataset folder;
- missing `ontology.vpp`;
- empty or unreadable `ontology.vpp`;
- missing `metadata.ttl`;
- invalid Turtle in `metadata.ttl` or existing `metadata-vpp.ttl`;
- existing `metadata-vpp.ttl` files that do not declare exactly one `dcat:Distribution`;
- ambiguous model dataset subjects;
- missing required `dct:title`;
- missing, ambiguous, or non-IRI `dct:license`;
- ambiguous `dct:issued`;
- ambiguous `fdpo:metadataIssued` in an existing `metadata-vpp.ttl`.

## Distribution URI policy

If `metadata-vpp.ttl` already exists and contains exactly one `dcat:Distribution`, the script preserves that distribution URI.

If no previous VPP distribution metadata exists, the script creates a stable UUIDv5-based URI under:

```txt
https://w3id.org/ontouml-models/distribution/<uuid>/
```

The UUID seed is based on the model dataset URI and the repository-relative path of `ontology.vpp`, so repeated generation is deterministic. If an existing `metadata-vpp.ttl` already declares exactly one `dcat:Distribution`, that URI is preserved instead.

## Tests

Run the tests from the repository root:

```bash
python -m unittest tests/test_generate_vpp_metadata.py
```

The test suite includes a regression test based on the real catalog dataset `models/amaral2019rot`, using the repository's existing `metadata.ttl` and `metadata-vpp.ttl` as source and target fixtures. Because the generator does not parse VPP internals, that regression test uses a small placeholder `ontology.vpp` file and compares the generated RDF graph with the existing target metadata, excluding only `fdpo:metadataModified`, which is intentionally refreshed on regeneration. The test suite also verifies language-tag behavior for generated titles and error handling for malformed existing VPP metadata files.

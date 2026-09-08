# Archived SHACL metadata shapes

> [!WARNING]
> The SHACL files in this directory are outdated and are retained only for provenance and persistent-link compatibility. They are not authoritative for current catalog metadata, are not executed by repository workflows, and must not be used as the validation contract for new model submissions.

The five existing `*-shape.ttl` files remain unchanged at their historical paths because the public `https://w3id.org/ontouml-models/shape/...` identifiers redirect to those locations.

Current implemented behavior is defined by the repository's Python tooling, particularly:

- the [model metadata validator](../scripts/validate_metadata_yaml.py);
- the [model metadata generator](../scripts/metadata_yaml_to_ttl.py);
- the [catalog generator](../scripts/generate_catalog_file.py);
- the distribution metadata generators listed in the [script index](../scripts/README.md).

The current metadata overview is available as an [exported PNG](../documentation/metadata-schema.png) with its [editable Visual Paradigm source](../documentation/metadata-schema.vpp).

# Documentation

The [OntoUML/UFO Catalog](../README.md) stores conceptual models and their representations for research and reuse. Choose a path according to your task:

| Your task | Start here |
| --- | --- |
| View, download, reuse, or cite models | [Using models](using-models.md) — format chooser, fixed-snapshot walkthrough, and citation guidance |
| Submit a model or report a problem | [Contributing](contributing.md) — routes, source-file requirements, and review checklist |
| Understand files, identifiers, conversion, and validation | [Technical overview](technical-overview.md) |
| Run or maintain repository automation | [Script index](../scripts/README.md) — setup, individual tools, submission and release guides |
| Check existing rights statements | [License disclaimer and caution](../README.md#license-disclaimer), [LICENSE](../LICENSE), and the selected model's metadata/sources |
| Find the preferred catalog citation | [How to Cite this Catalog](../README.md#how-to-cite-this-catalog) and [CITATION.cff](../CITATION.cff) |

> [!IMPORTANT]
> **Use GitHub for current catalog content.** This repository is actively maintained and updated. The separate [FAIR Data Point](https://w3id.org/ontouml-models) has not been updated since its initial release, is currently outdated, and has no planned update or synchronization work at this time. See the [responsibility boundary](technical-overview.md#github-storage-and-fdp-discovery).

## Supporting assets

- [Metadata overview figure](metadata-schema.png) and [editable Visual Paradigm source](metadata-schema.vpp): the intended metadata structure, with its scope and the known `ontologyType` implementation misalignment explained in the [technical overview](technical-overview.md#reading-the-metadata-overview-figure).
- [Full Goal Diagram](Full%20Goal%20Diagram.png): a design-goal artifact, not a statement that every depicted goal is implemented or an architecture diagram of current automation.
- [Logo assets](logo/): existing images and branding archives. No asset replacement or rights determination is implied by this index.

No editable source for the Full Goal Diagram was identified in the inspected repository. Its existing file is retained; this index does not assign new authorship, dates, or licensing terms.

## Historical material

> [!WARNING]
> The material listed below is preserved for provenance and context. It is not current contribution, automation, validation, or product-support guidance. Follow the tracked repository guidance and current Python implementation first.

- [Archived SHACL metadata shapes](../shapes/): outdated constraints retained at their existing paths for provenance and persistent-link compatibility. They are not authoritative for current metadata and are not executed by repository workflows.
- [Historical model-reconstruction guidance](historical/model-reconstruction.md): preserved reconstruction rules from a dated Wiki snapshot, pending curator confirmation.
- [Historical Visual Paradigm import guide](historical/importing-models-to-visual-paradigm.md): preserved, version-specific editor instructions from the same snapshot; it does not assert current product behavior.
- [Repository Wiki](https://github.com/OntoUML/ontouml-models/wiki): source history and deprecated operational instructions. Consult current tracked guidance first.

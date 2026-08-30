# Contributing and reporting problems

[Documentation index](README.md) · [Using models](using-models.md) · [Technical overview](technical-overview.md)

Contributions help researchers study and reuse OntoUML and UFO models. Current repository mechanics are documented here and in the [submission workflow guide](../scripts/process-new-model-submission.md). Human curation remains necessary; passing automated checks is not a guarantee of semantic quality or rights clearance.

## Choose a route

| You want to… | Route |
| --- | --- |
| Offer a model without repository branch access | Use the [contribution form](https://forms.gle/wNSMfaJfkS3hi69o7) or contact a [catalog administrator](../README.md#catalog-administration). The form is an existing documented route; its current fields and access behavior have not been verified in this repository documentation. |
| Submit source files with same-repository branch access | Prepare one model folder, open a PR to `master`, and review the automated changes and checks before curator review. |
| Report a model, script, or documentation problem, or suggest an application | [Open an issue](https://github.com/OntoUML/ontouml-models/issues), or use the existing form/administrator route. Include the information relevant to your report below. |
| Ask about rights or removal | Use the routes in the [license disclaimer](../README.md#license-disclaimer) or contact an administrator. Do not post sensitive evidence publicly. |

> [!IMPORTANT]
> **Automatic submission writeback requires a PR branch inside the same repository as its target. Fork-based PR writeback is not supported.** This restriction belongs to the model-submission workflow; the separate [release validation workflow](../scripts/generate-release-file.md#pull-request-validation) does not require a same-repository PR.

The README also documents [anonymous model contributions](../README.md#contribute-by-submitting-an-ontology). If helping catalog someone else's model, consult the existing [List of UFO and OntoUML Ontology Models](https://docs.google.com/spreadsheets/d/1JXEA3k58yAkV_jbmEc7HP9QK7RgZC5Jk1y8MR7ylFyQ/edit?usp=sharing) and confirm the entry's current status and any working branch with an administrator before duplicating work. A spreadsheet entry does not establish permission to redistribute a model.

## Prepare a repository submission

Create one direct child of `models/`. Its folder name (slug) must start with an ASCII letter or digit and contain only ASCII letters, digits, `.`, `_`, or `-`; parent-directory (`..`) path components are rejected by the ontology generator.

| Contributor input | Requirement |
| --- | --- |
| `metadata.yaml` | Descriptive model metadata using the supported field names and values. |
| `ontology.vpp` | Non-empty native project file. Keep it consistent with the JSON export; automation does not export or parse the native project. |
| `ontology.json` | UTF-8 JSON with an object root and a non-empty project `id`; canonical input for ontology RDF. |
| Direct PNG(s) in `original-diagrams/` or `new-diagrams/` | At least one valid PNG directly inside either directory. Both directories are not required; nested images do not satisfy the direct-image requirement. Use the former for original representations and the latter for Visual Paradigm recreations. |
| `references.bib` | Optional bibliography; if present it must pass the structural bibliography validator. |

Do not supply a manually generated `ontology.ttl` for a new model or edit it to change model content. Update JSON instead. Automation generates the ontology Turtle, distribution sidecars, model-level `metadata.ttl`, and root `catalog.ttl`. Existing generated metadata can preserve identifiers and curated values, so do not delete it merely to force regeneration; see the [input/output map](technical-overview.md#inputs-and-generated-outputs).

A normal model-submission PR may change the one target model folder and generated root `catalog.ttl`, not unrelated files. Keep script, documentation, and workflow changes in separate PRs from a model submission. The [generated-only bulk-maintenance exception](../scripts/process-new-model-submission.md#generated-artifact-only-bulk-maintenance) is not a route for multi-model source submissions.

### Write the metadata

Use the [16-field YAML reference](../scripts/validate-metadata-yaml.md#supported-field-spelling) and the [pinned ROT example](https://github.com/OntoUML/ontouml-models/blob/617dc16ee30a94d8c0587463f1b9ba3b3aef07d7/models/amaral2019rot/metadata.yaml) as structural guidance. Supply your own model's contributors, sources, dates, and license information; do not copy another model's values.

The YAML validator's minimum required fields are not a complete submission. In particular, ontology generation additionally requires a non-empty, usable `language`; adding an empty field does not satisfy that stage. One declared language tags generated names; multiple declared languages leave those names untagged. See the [language requirements](../scripts/generate-ontology-turtle.md#requirements).

A usable `license` value is required by default in normal new submissions. The legacy `--allow-missing-license` option relaxes a processing error; it does not resolve rights or grant permission. Consult the [existing license statements and caution](../README.md#license-disclaimer) for uncertainty or conflicting statements.

## What happens after submission

For a normal same-repository model PR, the workflow validates/fixes YAML, checks the input files, generates ontology RDF, validates an optional bibliography, generates distribution metadata, aggregates model metadata, and synchronizes the root catalog. See the [exact processing order](../scripts/process-new-model-submission.md#processing-order) for local versus workflow responsibilities.

The initial YAML normalization can remove comments and change formatting. The bot commit can therefore contain **normalized source YAML as well as generated artifacts**. Review both. For deliberate local checks and their prerequisites, use the [script index](../scripts/README.md#local-setup) and the submission guide's [local usage](../scripts/process-new-model-submission.md#local-usage); do not run writing examples merely to inspect a model.

| Outcome | What to review or do |
| --- | --- |
| Nonfatal warning | Read the affected model and message in the workflow logs. Converter warnings can describe omitted information; a passing check does not make them irrelevant. |
| Failed processing | Inspect the first failing stage and its diagnostic, correct the relevant input, and review the new run. The workflow skips its commit step on failure; a failed local run can leave earlier local writes. |
| Successful processing with changes | Review the bot's source/generated diff and check results for the bot-updated PR head, not only the original submission commit. |
| Successful synchronized rerun | No additional bot commit is expected when there are no generated changes. |
| Approval pending or curator review outstanding | Treat it as pending, not as successful validation or acceptance. Follow the actual GitHub prompts and curator feedback. |

Diagnostics are in check results and workflow logs, not automatically posted as PR comments. Curator review and actual branch protections are different things: this guide does not claim a particular required-review count or permission bypass. Detailed protection/approval settings have not been verified here. Read the [workflow's failure behavior](../scripts/process-new-model-submission.md#failure-behavior) before rerunning or attempting recovery.

## Submission and report checklist

- **New model:** identify the model, sources, rights information, and required files; keep native/JSON representations consistent; review generated changes and warnings.
- **Correction to an existing model:** identify its exact `models/<slug>/` path and the commit/release being discussed; explain what is wrong and the proposed source-level correction. Preserve published identifiers unless a separately reviewed change requires otherwise.
- **Script or documentation issue:** provide the affected path/section, baseline commit, expected versus observed behavior, and exact command/check with relevant output when applicable. Include the platform and Python version for execution problems; exclude credentials and unrelated personal data.
- **Rights/removal request:** identify the model or asset and the concern through the existing issue/form/administrator routes. Arrange any sensitive evidence directly with an administrator rather than placing it in a public issue. This guide adds no new response-time or removal-time commitment.

## Historical modeling and import advice

> [!WARNING]
> The tracked [historical model-reconstruction guidance](historical/model-reconstruction.md) and [historical Visual Paradigm import guide](historical/importing-models-to-visual-paradigm.md) preserve older Wiki material, including version-specific instructions. Treat them as historical references pending curator confirmation, not as the current automated conversion contract or an endorsement of present editor/edition support. Ask a curator when applying those modeling rules requires interpretation. Current submission mechanics are the tracked guidance linked above.

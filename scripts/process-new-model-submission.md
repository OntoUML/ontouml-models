# New model submission workflow

[Script index and local setup](README.md)

This document describes the automation for processing a single OntoUML/UFO Catalog model folder from contributor source files into its generated Turtle distribution and catalog-ready metadata.

The workflow is implemented by:

- `.github/workflows/pr-validation.yml` (automatic PR controller)
- `.github/workflows/validate-pr-state.yml` (final-head validation)
- `.github/workflows/process-new-model-submission.yml` (manual maintenance only)
- `scripts/process_new_model_submission.py`

It also expects the repository's validation/generation scripts to be available, including:

- `scripts/validate_metadata_yaml.py`
- `scripts/generate_ontology_turtle.py`
- `scripts/validate_references_bib.py`
- `scripts/generate_png_metadata.py`
- `scripts/generate_json_metadata.py`
- `scripts/generate_turtle_metadata.py`
- `scripts/generate_vpp_metadata.py`
- `scripts/metadata_yaml_to_ttl.py`
- `scripts/generate_catalog_file.py` (called by the workflow after the helper)

The helper script is intentionally an orchestrator. It does not duplicate conversion, metadata-generation, or BibTeX-validation logic. It validates/fixes `metadata.yaml`, validates the submission envelope, classifies changed model paths, runs the ontology and metadata generators in the intended order, and performs final Turtle/RDF checks.

## Automatic processing and merge eligibility

All PRs to `master` enter the [PR validation controller](pr-validation.md). It classifies the complete changed-file list and runs only applicable processing and validation. Documentation and script-only PRs do not invoke model-submission generation. Mixed changes receive the union of applicable checks.

For a one-model submission, automation validates the source files, generates `ontology.ttl`, synchronizes distribution/model metadata and `catalog.ttl`, and commits changed generated files to the PR branch. It then explicitly dispatches validation of that exact final head. The App-owned `PR validation` check succeeds only after final-state validation succeeds. The required repository ruleset, not a maintainer's memory of workflow progress, blocks an incomplete submission.

Same-repository writeback uses `GITHUB_TOKEN`. Fork writeback uses a narrowly scoped GitHub App installation token, which requires the fork owner to install the catalog automation App on that fork. A fork PR without applicable generation needs no fork write permission. Missing write authorization blocks generation explicitly; it does not silently accept missing outputs or require contributors to generate them manually. See the [setup and trust boundary](pr-validation.md#external-repository-configuration).

### Generated-artifact-only bulk maintenance

The existing bulk mode remains: more than one model folder is supported only when every changed model file is a direct automation-generated output: `ontology.ttl`, `metadata.ttl`, `metadata-json.ttl`, `metadata-turtle.ttl`, `metadata-vpp.ttl`, or `metadata-png-(n|o)-*.ttl`. Deletions are not bulk maintenance. This mode checks all six generator families and final RDF/catalog/release consistency without writeback. Multiple model source submissions must be split into separate PRs. A one-model generated-file change still invokes normal processing.

### Manual maintenance

`Process new model submission` retains its `workflow_dispatch` interface and inputs: `model_path`, `metadata_timestamp`, `metadata_repository`, `metadata_branch`, `allow_missing_license`, `dry_run`, and `commit_changes`. It no longer has an automatic PR trigger. Use it only on a branch whose workflow, scripts and dependencies a maintainer already trusts. Do not dispatch it on unreviewed PR code: its existing commit mode has write credentials.

For automatic PR recovery, dispatch `Orchestrate PR validation` on `master` with the PR number, as documented in the [recovery instructions](pr-validation.md#recovery). Manual maintenance is not a substitute for the required final-head check and cannot bypass the protected `master` ruleset.

## Required source files

A new model folder must be a direct child of `models/`, for example:

```text
models/example-model/
```

The folder must contain:

```text
metadata.yaml
ontology.json
ontology.vpp
```

The folder must also contain at least one `.png` diagram image directly inside one of the repository’s accepted image folders:

```text
original-diagrams/
new-diagrams/
```

The optional file is:

```text
references.bib
```

`ontology.json` is the canonical source for the RDF graph. `ontology.ttl` is a generated, committed distribution, not a required contributor input. Manual Turtle edits are unsupported: change the JSON source and let the generator synchronize the Turtle. Contributors remain responsible for keeping `ontology.vpp` and its JSON export consistent; the workflow does not export JSON from VPP.

## What the helper checks before generation

After validating/fixing `metadata.yaml` and before running the ontology generator, `scripts/process_new_model_submission.py` checks that:

- the target folder is a direct child of `models/`;
- `metadata.yaml`, `ontology.json`, and `ontology.vpp` exist as files;
- `ontology.json` is UTF-8 JSON with a top-level object;
- `ontology.vpp` exists, is non-empty, and has a valid filename shape;
- at least one `.png` diagram exists in `original-diagrams/` or `new-diagrams/`;
- each `.png` diagram has a PNG signature and IHDR header;
- `references.bib`, when present, is a file rather than a directory.

The ontology generator then validates the dataset slug, the metadata language declaration, the JSON project ID, and the generated graph's namespace, project identity, and name-language policy. If an `ontology.ttl` already exists, it must be readable, valid Turtle; a missing file is generated normally.

Full basic BibTeX/BibLaTeX validation is delegated to `scripts/validate_references_bib.py`. The workflow calls this validator without `--require`, because `references.bib` is optional for catalog datasets. The workflow fails when `references.bib` exists and the validator reports errors, but it does not fail when the file is absent.

The BibTeX/BibLaTeX validator checks structural compliance, including UTF-8 encoding, non-empty existing files, entry starts, entry types, balanced delimiters, citation keys, duplicate keys, field assignments, malformed values, duplicate fields, and special entries such as `@string`, `@preamble`, and `@comment`. It deliberately does not enforce mandatory fields per entry type.

The existing PNG generator still performs its own PNG validation during generation.

These checks do not run a JSON Schema or SHACL validation engine, parse the Visual Paradigm project, or prove that the native project and JSON have the same semantics. Converter warnings can describe omitted information even when processing succeeds. Curator review remains necessary; successful parsing and synchronization are not a semantic-quality guarantee.

## Processing order

In a normal non-dry-run execution, the helper runs the repository scripts in this order (shared metadata options are omitted below for readability):

```text
1. python scripts/validate_metadata_yaml.py [MODEL_FOLDER] --fix
2. Helper-level source preflight checks for ontology.json, ontology.vpp, PNG diagrams, and optional references.bib path shape
3. python scripts/generate_ontology_turtle.py [MODEL_FOLDER]
4. python scripts/validate_references_bib.py [MODEL_FOLDER]
5. python scripts/generate_png_metadata.py [MODEL_FOLDER]
6. python scripts/generate_json_metadata.py [MODEL_FOLDER] --validate-ontology-json
7. python scripts/generate_turtle_metadata.py [MODEL_FOLDER]
8. python scripts/generate_vpp_metadata.py [MODEL_FOLDER]
9. python scripts/metadata_yaml_to_ttl.py [MODEL_FOLDER]
10. Verify expected generated outputs exist and parse all .ttl files directly in the model folder with RDFLib
```

Ontology generation precedes Turtle distribution metadata generation. The distribution-specific metadata files are generated before `metadata.ttl` so that the model-level metadata can aggregate the distribution IRIs discovered from all `metadata-*.ttl` sidecars.

After the helper succeeds, the workflow runs `python scripts/generate_catalog_file.py .`, then stages and commits changes. The local helper does not synchronize root `catalog.ttl` itself.

The initial `--fix` step can rewrite `metadata.yaml`, removing comments and changing hand-formatted spacing. Its normalized source is inside the model folder staged by the workflow and can therefore appear in the bot commit alongside generated files. Review that source diff as well as the generated artifacts. The standalone helper's `--no-fix-metadata-yaml` option disables automatic YAML fixing; the workflow does not expose that option.

## Ontology generation and warnings

The catalog wrapper uses the exact `ontouml-json2graph==2.0.1` dependency and the namespace `https://w3id.org/ontouml-models/model/<slug>#`. Project identity uses the JSON project ID under that namespace. If `metadata.yaml` declares one distinct language, generated names use that language tag; with multiple declared languages, names are untagged.

The selected policies preserve invalid cardinalities and invalid stereotypes with warnings, omit unresolved diagram target links with warnings, and warn about unrepresented path-point order and property assignments. These warnings are nonfatal and remain visible in the workflow logs. Generation does not enable automatic source correction or transformation-provenance sidecars. See the [ontology generator guide](generate-ontology-turtle.md) for the exact policy effects and validation contract.

The wrapper generates and validates a candidate in temporary storage. It creates a missing `ontology.ttl`, atomically replaces an existing valid graph when it differs semantically, and preserves an isomorphic file byte-for-byte. Normal submissions do not use migration-only `--force-materialization`.

## Generated files

For a valid complete submission, the generated or updated files are expected to include:

```text
ontology.ttl
metadata-json.ttl
metadata-turtle.ttl
metadata-vpp.ttl
metadata-png-o-*.ttl
metadata-png-n-*.ttl
metadata.ttl
```

The exact PNG metadata filenames depend on the diagram folder and the PNG filename stem:

```text
original-diagrams/example.png -> metadata-png-o-example.ttl
new-diagrams/example.png      -> metadata-png-n-example.ttl
```

The workflow also synchronizes root `catalog.ttl`. Change detection differs by layer:

- `ontology.ttl` uses RDF graph isomorphism and preserves an equivalent existing file byte-for-byte in normal mode.
- Model and distribution metadata compare serialized content. Formatting-only differences can require a rewrite and an updated `fdpo:metadataModified`; existing `fdpo:metadataIssued` is preserved. See the [model metadata timestamp rules](metadata_yaml_to_ttl.md#existing-metadatattl-preservation) and each distribution guide.
- The catalog compares RDF semantics, with separate membership and metadata timestamp rules. A serialization-only catalog rewrite does not advance those dates; see the [catalog generator guide](generate-catalog-file.md#modification-timestamps).

Regenerating `ontology.ttl` alone does not require a new `fdpo:metadataModified` in `metadata-turtle.ttl` when that distribution metadata remains unchanged.

## Local usage

Install dependencies first:

```bat
python -m pip install -r scripts/requirements.txt
```

Run the full processing pipeline with a deterministic timestamp:

```bat
python scripts/process_new_model_submission.py models/example-model --metadata-timestamp 2026-06-24T12:00:00Z
```

Run the same command using the current timestamp:

```bat
python scripts/process_new_model_submission.py models/example-model --metadata-timestamp now
```

Run a dry run without retaining generated files:

```bat
python scripts/process_new_model_submission.py models/example-model --metadata-timestamp 2026-06-24T12:00:00Z --dry-run
```

If `ontology.ttl` is missing, the helper temporarily creates it so downstream metadata dry runs can inspect the distribution, then removes it on completion or failure. An existing `ontology.ttl` is left unchanged. The final non-dry-run output inventory and all-Turtle parse are not performed in this mode; the ontology candidate is still validated by the wrapper.

After a successful non-dry-run local run, synchronize the catalog separately if preparing the complete generated change set:

```bat
python scripts/generate_catalog_file.py .
```

Check an existing dataset's JSON/Turtle synchronization without writing:

```bat
python scripts/generate_ontology_turtle.py models/example-model --check
```

Detect the changed model folder between two refs for a normal one-model PR:

```bat
python scripts/process_new_model_submission.py --detect-model-folder origin/master HEAD
```

For fork-only URL testing, override the repository used in generated storage/download URLs:

```bat
python scripts/process_new_model_submission.py models/example-model --metadata-timestamp 2026-06-24T12:00:00Z --repository pedropaulofb/ontouml-models-dev --branch master
```

For PR-ready metadata intended for the main repository, keep the default:

```text
--repository OntoUML/ontouml-models
--branch master
```

## Testing in GitHub Actions

Use the [eight-scenario integration matrix](pr-validation.md#live-github-regression-matrix) in an isolated test repository whose default branch contains the complete implementation. Test source-only submissions, failed generation, failed final validation, documentation, script changes, new heads, bot updates, and bulk distribution-metadata maintenance. Confirm merge denial while the required check is pending or failing, not just the workflow conclusion.

## Automatic commits

The controller writes only allowlisted generated files, permitted `metadata.yaml` normalization, and `catalog.ttl`. An atomic commit operation requires the PR branch still to have the expected source SHA; concurrent contributor updates are never overwritten. A no-op generation creates no commit. The final validation dispatch uses the resulting SHA whether or not a commit was necessary.

For legacy manual runs, commits still occur only when `commit_changes` is `true` and `dry_run` is `false`. Review the local/manual diff before committing after any failure. Required PR validation must still pass on the resulting head before merge.

## Failure behavior

If validation or generation fails:

- the helper exits with a non-zero status;
- GitHub Actions marks the run as failed;
- the commit step is skipped;
- partial generated changes are not committed by the workflow.

Malformed JSON, a fatal converter error, or an invalid generated graph stops processing before the dependent metadata generators run. Converter failure does not replace an existing `ontology.ttl`. A later failure does not roll back earlier successful local writes, so inspect the local diff before committing after a failed local run.

Diagnostics are reported in GitHub check results and grouped workflow logs, not posted as PR comments. Review warnings separately from fatal errors; warnings do not by themselves make generation fail.

For pull requests, the required check also blocks when generation/writeback is unauthorized, the complete changed-file list cannot be obtained, multi-model source changes violate the existing boundary, final artifacts are absent or stale, or the head/base changes during processing or validation. It never treats an irrelevant workflow's absence as failure. See [PR validation](pr-validation.md) for the exact state transitions and recovery procedure.

## Current limitations

- Normal submission processing and manual runs handle one model folder; multi-model generated-only maintenance is read-only.
- Fork writeback requires an explicitly authorized App installation on the fork; no write-capable credential is exposed to contributor code.
- Generation uses trusted base-branch tools. Land generator changes first if a new submission requires behavior unavailable on `master`.
- `references.bib` is optional and receives structural BibTeX/BibLaTeX validation, not semantic validation of mandatory fields per entry type.
- The existing submission envelope requires `ontology.vpp`; it is checked at file level only. VPP-to-JSON export and synchronization remain the contributor's responsibility.

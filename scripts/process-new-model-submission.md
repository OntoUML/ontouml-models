# New model submission workflow

[Script index and local setup](README.md)

This document describes the automation for processing a single OntoUML/UFO Catalog model folder from contributor source files into its generated Turtle distribution and catalog-ready metadata.

The workflow is implemented by:

- `.github/workflows/process-new-model-submission.yml`
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

## Supported submission mode

Automatic model-submission processing supports **pull requests opened from branches inside the catalog repository**.

The intended flow is:

1. A trusted contributor creates a branch in `OntoUML/ontouml-models` and adds the source files for one model folder, without `ontology.ttl`.
2. The contributor opens a PR to `master`.
3. The workflow validates the sources, generates `ontology.ttl`, synchronizes distribution/model metadata and `catalog.ttl`, and commits changed files back to the PR branch.
4. The generated files and release validation results are reviewed before a curator merges the complete PR manually.

**Fork-based PR writeback is not supported.** If a PR is opened from a fork, the submission workflow fails with an explicit message explaining the same-repository restriction. Contributors without branch access should use the contribution form linked in the [README](../README.md#contribute-by-submitting-an-ontology) or contact a catalog administrator.

## Triggers

The workflow supports two triggers.

### Automatic same-repository pull request trigger

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
    paths:
      - "models/**"
```

For normal one-model PRs, the workflow:

1. rejects fork-based PRs;
2. detects the unique changed model folder under `models/`;
3. rejects PRs that modify files outside the target model folder, except generated root `catalog.ttl`;
4. processes that model folder;
5. commits generated files back to the PR branch when changes exist.

### Generated-artifact-only bulk maintenance

A same-repository PR touching more than one model folder is accepted only when every changed model file is directly inside `models/<slug>/` and is one of:

- `ontology.ttl`;
- `metadata.ttl`;
- `metadata-turtle.ttl`.

Generated root `catalog.ttl` may also change. This selects `bulk-generated` mode: a read-only job checks full-catalog ontology and dependent metadata synchronization, parses model Turtle files, and verifies that validation did not modify the checkout. It does not generate a bot commit.

This narrowly scoped migration/maintenance mode does not allow multi-model contributor-source submissions or unrelated code/workflow changes. A PR touching only one model folder still uses normal processing, even if its changes are generated files only.

### Manual trigger

The manual `workflow_dispatch` trigger remains available for controlled testing, recovery, and fork-side experimentation.

Manual inputs include:

- `model_path`
- `metadata_timestamp`
- `metadata_repository`
- `metadata_branch`
- `allow_missing_license`
- `dry_run`
- `commit_changes`

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

## Testing in GitHub Actions in the fork

1. Ensure the workflow, helper, and pinned dependencies are committed and pushed to the branch being tested in `pedropaulofb/ontouml-models-dev`.
2. Create a separate temporary test branch from that branch inside the fork repository.
3. Add one model folder with the required source files and no `ontology.ttl` or generated metadata.
4. Open a test PR back to the implementation branch in the same fork repository, not to the upstream catalog. Keep workflow/helper changes out of the test PR's diff.
5. Confirm that the workflow creates and commits `ontology.ttl`, distribution/model metadata, and the catalog update.
6. Inspect the generated commit and release validation. If GitHub requests approval for a follow-up run, a maintainer must approve it before its results can be assessed.
7. Confirm that processing the bot-updated head reports `No generated changes to commit.` and creates no further commit.
8. Close the temporary test PR without merging it; keep smoke-test data out of the implementation branch.

To test the same workflow manually, use **Actions** → **Process new model submission** → **Run workflow**.

## Automatic commits

For normal same-repository PRs, the workflow automatically commits `ontology.ttl`, generated metadata, and any normalized source YAML back to the PR branch after validation, generation, and catalog synchronization succeed. The read-only bulk-maintenance job never writes back.

For manual runs, commits occur only when `commit_changes` is `true` and `dry_run` is `false`.

The workflow:

1. runs all validation and generation steps;
2. stops immediately if any step fails;
3. stages only the requested model folder (including normalized `metadata.yaml`) and generated root catalog with this GitHub Actions Bash excerpt, not a local Cmder command:

   ```bash
   git add -- "$MODEL_PATH" catalog.ttl
   ```

4. commits only when staged changes exist;
5. pushes the commit to the PR branch or, for manual runs, to the checked-out branch.

A synchronized rerun leaves the generated files unchanged and logs `No generated changes to commit.`. Converter warnings alone do not cause a commit. Workflow results must be checked on the bot-updated PR head; pending approval is not a successful validation.

The commit message has this form:

```text
chore(metadata): process model submission example-model
```

The normal processing job requires:

```yaml
permissions:
  contents: write
  pull-requests: read
```

## Failure behavior

If validation or generation fails:

- the helper exits with a non-zero status;
- GitHub Actions marks the run as failed;
- the commit step is skipped;
- partial generated changes are not committed by the workflow.

Malformed JSON, a fatal converter error, or an invalid generated graph stops processing before the dependent metadata generators run. Converter failure does not replace an existing `ontology.ttl`. A later failure does not roll back earlier successful local writes, so inspect the local diff before committing after a failed local run.

Diagnostics are reported in GitHub check results and grouped workflow logs, not posted as PR comments. Review warnings separately from fatal errors; warnings do not by themselves make generation fail.

For pull requests, the workflow also fails when:

- the PR comes from a fork;
- files outside the permitted model folder(s) and generated root `catalog.ttl` are changed;
- multiple model folders are changed without satisfying the generated-artifact-only bulk-maintenance rules;
- changed paths under `models/` are not inside a direct model folder.

## Current limitations

- Automatic write-back is limited to same-repository PR branches.
- Fork-based PR automation is intentionally deferred.
- Normal submission processing and manual runs handle one model folder; multi-model generated-only maintenance is read-only.
- `references.bib` is optional and is validated only when present; the workflow does not pass `--require` to `scripts/validate_references_bib.py`.
- `references.bib` receives structural BibTeX/BibLaTeX validation only, not semantic validation of mandatory fields per entry type.
- `ontology.vpp` is checked at file level only; no Visual Paradigm parser is introduced.
- VPP-to-JSON export and synchronization are the contributor's responsibility.

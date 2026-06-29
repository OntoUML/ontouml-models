# New model submission workflow

This document describes the automation for processing a single OntoUML/UFO Catalog model folder from its basic source files into the catalog-ready metadata structure.

The workflow is implemented by:

- `.github/workflows/process-new-model-submission.yml`
- `scripts/process_new_model_submission.py`

It also expects the repository's metadata-related validation/generation scripts to be available, including:

- `scripts/validate_metadata_yaml.py`
- `scripts/validate_references_bib.py`
- `scripts/generate_png_metadata.py`
- `scripts/generate_json_metadata.py`
- `scripts/generate_turtle_metadata.py`
- `scripts/generate_vpp_metadata.py`
- `scripts/metadata_yaml_to_ttl.py`

The helper script is intentionally an orchestrator. It does not duplicate metadata-generation or BibTeX-validation logic. It validates/fixes `metadata.yaml`, validates the submission envelope, detects the target model folder for same-repository pull requests, runs the existing metadata scripts in the intended order, and performs final Turtle/RDF checks.

## Supported submission mode

The first automatic implementation supports **pull requests opened from branches inside the catalog repository**.

The intended flow is:

```text
Trusted contributor creates a branch in OntoUML/ontouml-models
        ↓
Contributor adds the basic source files for one model folder
        ↓
Contributor opens a PR to master
        ↓
The workflow detects the model folder, validates/fixes inputs, generates metadata, and commits generated files back to the PR branch
        ↓
A curator reviews the complete PR and merges it manually
```

Fork-based PR write-back is intentionally not supported in this first phase. If a PR is opened from a fork, the workflow fails with an explicit message explaining that automatic metadata generation currently requires a same-repository PR branch.

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

For PRs, the workflow:

1. rejects fork-based PRs;
2. detects the unique changed model folder under `models/`;
3. rejects PRs that modify files outside the target model folder;
4. processes that model folder;
5. commits generated files back to the PR branch when changes exist.

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
ontology.ttl
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

## What the helper checks before generation

After validating/fixing `metadata.yaml` and before running the metadata generators, `scripts/process_new_model_submission.py` checks that:

- the target folder is a direct child of `models/`;
- `metadata.yaml`, `ontology.json`, `ontology.ttl`, and `ontology.vpp` exist as files;
- `ontology.json` is UTF-8 JSON with a top-level object;
- `ontology.ttl` parses as Turtle/RDF with RDFLib;
- `ontology.vpp` exists, is non-empty, and has a valid filename shape;
- at least one `.png` diagram exists in `original-diagrams/` or `new-diagrams/`;
- each `.png` diagram has a PNG signature and IHDR header;
- `references.bib`, when present, is a file rather than a directory.

Full basic BibTeX/BibLaTeX validation is delegated to `scripts/validate_references_bib.py`. The workflow calls this validator without `--require`, because `references.bib` is optional for catalog datasets. The workflow fails when `references.bib` exists and the validator reports errors, but it does not fail when the file is absent.

The BibTeX/BibLaTeX validator checks structural compliance, including UTF-8 encoding, non-empty existing files, entry starts, entry types, balanced delimiters, citation keys, duplicate keys, field assignments, malformed values, duplicate fields, and special entries such as `@string`, `@preamble`, and `@comment`. It deliberately does not enforce mandatory fields per entry type.

The existing PNG generator still performs its own PNG validation during generation.

## Processing order

The helper runs the existing repository scripts in this order:

```text
1. python scripts/validate_metadata_yaml.py [MODEL_FOLDER] --fix
2. Helper-level source preflight checks for ontology.json, ontology.ttl, ontology.vpp, PNG diagrams, and optional references.bib path shape
3. python scripts/validate_references_bib.py [MODEL_FOLDER]
4. python scripts/generate_png_metadata.py [MODEL_FOLDER]
5. python scripts/generate_json_metadata.py [MODEL_FOLDER] --validate-ontology-json
6. python scripts/generate_turtle_metadata.py [MODEL_FOLDER]
7. python scripts/generate_vpp_metadata.py [MODEL_FOLDER]
8. python scripts/metadata_yaml_to_ttl.py [MODEL_FOLDER]
9. Final RDFLib parse validation over all .ttl files in the model folder
```

The distribution-specific metadata files are generated before `metadata.ttl` so that the model-level metadata can aggregate the distribution IRIs discovered from `metadata-*.ttl`.

## Generated files

For a valid complete submission, the generated or updated files are expected to include:

```text
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

## Local usage

Install dependencies first:

```bash
python -m pip install -r scripts/requirements.txt
```

Run the full processing pipeline with a deterministic timestamp:

```bash
python scripts/process_new_model_submission.py models/example-model \
  --metadata-timestamp 2026-06-24T12:00:00Z
```

Run the same command using the current timestamp:

```bash
python scripts/process_new_model_submission.py models/example-model \
  --metadata-timestamp now
```

Run a dry run without writing generated files:

```bash
python scripts/process_new_model_submission.py models/example-model \
  --metadata-timestamp 2026-06-24T12:00:00Z \
  --dry-run
```

Detect the changed model folder between two refs, as the PR workflow does:

```bash
python scripts/process_new_model_submission.py --detect-model-folder origin/master HEAD
```

For fork-only URL testing, override the repository used in generated storage/download URLs:

```bash
python scripts/process_new_model_submission.py models/example-model \
  --metadata-timestamp 2026-06-24T12:00:00Z \
  --repository pedropaulofb/ontouml-models-dev \
  --branch master
```

For PR-ready metadata intended for the main repository, keep the default:

```text
--repository OntoUML/ontouml-models
--branch master
```

## Testing in GitHub Actions in the fork

1. Extract the patch into the root of `pedropaulofb/ontouml-models-dev`.
2. Commit and push the workflow/helper-script changes.
3. Create a branch inside the fork repository.
4. Add or update one model folder under `models/` with the required source files.
5. Open a PR from that branch to the fork repository’s `master` branch.
6. Confirm that the workflow detects the changed model folder and commits generated metadata back to the PR branch.
7. Inspect the workflow logs and the generated commit.

To test the same workflow manually, use **Actions** → **Process new model submission** → **Run workflow**.

## Automatic commits

For same-repository PRs, the workflow automatically commits generated metadata back to the PR branch after all validation and generation steps succeed.

For manual runs, commits occur only when `commit_changes` is `true` and `dry_run` is `false`.

The workflow:

1. runs all validation and generation steps;
2. stops immediately if any step fails;
3. stages only the requested model folder with:

```bash
git add -- "$MODEL_PATH"
```

4. commits only when staged changes exist;
5. pushes the commit to the PR branch or, for manual runs, to the checked-out branch.

The commit message has this form:

```text
chore(metadata): process model submission example-model
```

The workflow requires:

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

For pull requests, the workflow also fails when:

- the PR comes from a fork;
- files outside `models/<model-folder>/` are changed;
- more than one model folder is changed;
- changed paths under `models/` are not inside a direct model folder.

## Current limitations

- Automatic write-back is limited to same-repository PR branches.
- Fork-based PR automation is intentionally deferred.
- One model folder is processed per PR/run.
- `references.bib` is optional and is validated only when present; the workflow does not pass `--require` to `scripts/validate_references_bib.py`.
- `references.bib` receives structural BibTeX/BibLaTeX validation only, not semantic validation of mandatory fields per entry type.
- `ontology.vpp` is checked at file level only; no Visual Paradigm parser is introduced.

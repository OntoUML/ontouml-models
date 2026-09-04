# Catalog scripts

[Repository overview](../README.md)

These Python tools validate contributor files, generate committed model/catalog metadata, and assemble RDF releases.

> [!NOTE]
> These tools operate only on the GitHub repository's storage layer. They do not deploy, index, synchronize, or verify the separately operated FAIR Data Point (FDP).

For a complete model submission, start with the [submission workflow guide](process-new-model-submission.md). For release artifacts and publication behavior, use the [release operator guide](generate-release-file.md). Running an individual generator does not run the whole pipeline or publish anything to GitHub.

## Script index

Existing metadata can supply retained identifiers, timestamps, and curated values as described in each guide. The inputs below include those preservation dependencies; generation is not always a stateless conversion of YAML.

| Script and guide | Main inputs | Output or purpose | Modes without retained source/output changes |
| --- | --- | --- | --- |
| [process_new_model_submission.py](process-new-model-submission.md) | One model folder: YAML, JSON, VPP, direct PNGs, optional bibliography, and existing generated files | Orchestrates validation, YAML normalization, ontology generation, and distribution/model metadata; the workflow updates root `catalog.ttl` separately | `--dry-run`; it may temporarily create a missing `ontology.ttl` for downstream checks, then removes it |
| [validate_metadata_yaml.py](validate-metadata-yaml.md) | `metadata.yaml` | Validates YAML; `--fix` can rewrite that source file | Default validation; `--fix --dry-run` previews normalization |
| [generate_ontology_turtle.py](generate-ontology-turtle.md) | `ontology.json`, YAML language declaration, existing `ontology.ttl` when present | Generates `ontology.ttl` using the pinned JSON2Graph converter | `--check` or `--dry-run`; both generate and validate a temporary candidate |
| [validate_references_bib.py](validate-references-bib.md) | Optional `references.bib` | Checks basic BibTeX/BibLaTeX syntax; no file writes | Normal execution; missing files are accepted unless `--require` is selected |
| [generate_png_metadata.py](generate-png-metadata.md) | YAML, direct PNGs, existing model/PNG metadata | Generates `metadata-png-o-*.ttl` and `metadata-png-n-*.ttl` | `--check` or `--dry-run` |
| [generate_json_metadata.py](generate-json-metadata.md) | YAML, `ontology.json`, existing distribution metadata | Generates `metadata-json.ttl`; JSON parsing is opt-in standalone and enabled by the submission helper | `--check` or `--dry-run` |
| [generate_turtle_metadata.py](generate-turtle-metadata.md) | YAML, `ontology.ttl`, existing distribution metadata | Generates `metadata-turtle.ttl` | `--check` or `--dry-run` |
| [generate_vpp_metadata.py](generate-vpp-metadata.md) | YAML, `ontology.vpp`, existing distribution metadata | Generates `metadata-vpp.ttl`; does not export JSON from VPP | `--check` or `--dry-run` |
| [metadata_yaml_to_ttl.py](metadata_yaml_to_ttl.md) | YAML, distribution sidecars, existing model metadata | Generates model-level `metadata.ttl` | `--check` or `--dry-run` |
| [generate_catalog_file.py](generate-catalog-file.md) | `catalog.yaml`, model-level `metadata.ttl` files, existing catalog | Generates root `catalog.ttl` | `--check`; there is no `--dry-run` |
| [generate_release_file.py](generate-release-file.md) | Eligible Turtle files recursively under the checkout | Writes `ontouml-models-YYYYMMDD.ttl` to the output directory | No generation preview mode; `--list-files` also writes the release |

Every script supports `--help`. Read each guide's exit codes: a synchronization check can return a nonzero status because output is stale, not because parsing failed. `--format json`, `--quiet`, and an output directory outside the repository do not make an otherwise writing command read-only.

## Local setup

Use a disposable checkout for generation experiments. Keep environments, downloaded archives, and generated release checks outside the repository. In particular, the release generator scans eligible Turtle files in the working directory tree, including untracked files.

The workflows use Python **3.11**, but local use is not restricted to that version. The pinned converter declares Python `>=3.10,<4.0`, which includes **3.13**. Use an installed compatible interpreter and verify the resolved dependencies and repository tests below; the declared range alone does not guarantee that every environment works. Install the existing [requirements](requirements.txt); the ontology wrapper requires exactly `ontouml-json2graph==2.0.1` and rejects another converter version. The repository's date-based release tags do not version the converter, schema, or vocabularies together.

The following commands are for **Windows, Cmder, `cmd.exe`**, from the repository root. They require Git and the Windows `py` launcher. The examples select Python **3.13**; replace `-3.13` with another installed compatible version if needed. There is no need to install 3.11 solely to match CI. Use a new environment directory; do not overwrite an unrelated environment.

```bat
py -3.13 --version
```

Create the local environment, activate it, and install the existing dependencies. These commands modify only the selected environment and may download packages:

```bat
py -3.13 -m venv ..\ontouml-models-script-env
```

```bat
call ..\ontouml-models-script-env\Scripts\activate.bat
```

```bat
python -m pip install -r scripts/requirements.txt
```

Verify the active interpreter and installed dependency compatibility before running the repository tests:

```bat
python --version && python -m pip check
```

Confirm interfaces without running generation:

```bat
python scripts/process_new_model_submission.py --help && python scripts/generate_release_file.py --help
```

Other guides use single-line Python commands as well. Names such as `models/example-model`, `models/example-a`, `models/dataset-a`, or `models/legacy-dataset` are illustrative: replace them with the intended folder before running a command. Angle-bracket notation in format/contract descriptions is also a placeholder, not a literal path. Commands for an existing named model are examples, not a request to regenerate that model. Quote a path if it contains spaces.

## Writes, timestamps, and automation

Normal generator commands can change files. Model/distribution metadata generators require an explicit `--metadata-timestamp` when timestamps must be initialized or updated; their guides explain the exact conditions. The submission helper defaults to `now`. Use a fixed timestamp for reproducible local experiments, and do not assume all generators use the same change comparison.

- Ontology generation normally compares RDF graphs semantically.
- Model/distribution metadata compare serialized content and can change on formatting differences.
- Catalog timestamps follow semantic membership/metadata changes; a formatting-only catalog rewrite preserves those dates.

See the [submission sequence](process-new-model-submission.md#processing-order), [metadata timestamp rules](metadata_yaml_to_ttl.md#existing-metadatattl-preservation), and [catalog timestamp rules](generate-catalog-file.md#modification-timestamps).

The submission workflow can normalize YAML and commit changes to a same-repository PR branch. Fork-based submission writeback is not supported. Release PR validation is a separate read-only job; scheduled or explicitly publishing manual release runs can commit the catalog and publish a release. Local script execution does not grant permission for those remote actions. Review the [submission](process-new-model-submission.md#automatic-commits) and [release](generate-release-file.md#github-actions-behavior) guides before using GitHub Actions.

## Tests and documentation review

With the environment activated, run the existing suite:

```bat
python -m pytest -q scripts/tests
```

Tests use temporary fixtures. A passing suite does not prove that every stored model has correct semantics, native/JSON equivalence, JSON Schema conformance, conformance with the [archived SHACL shapes](../shapes/), or confirmed reuse rights.

For script-documentation changes:

- Check paths, links, heading fragments, and GitHub Markdown rendering. Retain existing guide URLs and anchors when moving explanations.
- Compare commands with each script's `--help` and source. Keep executable examples on one line; label workflow Bash excerpts as source rather than local commands.
- Distinguish authored inputs, retained metadata, generated outputs, local writes, GitHub writeback, and publication. Do not run publishing or writeback examples merely to check documentation.
- Recheck workflow triggers, defaults, failure/skip outcomes, and the current dependency pin. Read the actual workflow files rather than inferring that every PR runs the entire suite.
- Check the complete diff, including staged changes, commits in the change set, and untracked additions. Documentation-only work must not silently alter models, generated metadata, executable logic, or workflow behavior.
- Record the environment and commands actually run, separately from inspected examples, historical workflow results, and checks that could not be performed.

For pending unstaged changes, a whitespace/conflict-marker check is:

```bat
git diff --check
```

Check staged and committed changes separately when present. Tests and Markdown previews complement each other; neither substitutes for checking the claims against the implementation.

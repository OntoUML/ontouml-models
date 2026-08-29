# Generate and publish an RDF release

[Script index and local setup](README.md)

[`generate_release_file.py`](generate_release_file.py) assembles repository Turtle files into one RDF distribution named `ontouml-models-YYYYMMDD.ttl`. The separate [release workflow](../.github/workflows/publish-models-release.yml) validates that artifact and, in publishing modes, creates a GitHub Release. The script itself does not commit, push, create tags, publish, or operate the FDP.

## Choose the right artifact

| Artifact | Contents and use |
| --- | --- |
| GitHub Release `.ttl` asset | One aggregated RDF graph, including eligible model, distribution, and catalog Turtle. Use with RDF tools. It is not an archive of native projects, JSON exports, images, or bibliographies. |
| GitHub's source ZIP or tarball for a tag | The Git-tracked repository snapshot at that tag, including the source formats and diagrams present there. It is distinct from the attached RDF asset. |
| GitHub Actions artifact | A generated validation/release file from a workflow run. The workflow sets retention to 30 days. An uploaded Actions artifact is not proof that a GitHub Release was published. |

For reproducibility, record the tag and commit, not just a moving “latest” URL. Date-based repository tags do not imply a matching JSON2Graph, schema, or vocabulary version. The stored RDF retains the conversion limits described in the [ontology generator guide](generate-ontology-turtle.md#explicit-warning-policies).

## Local aggregation contract

The script requires a repository directory containing `models/` and at least one eligible Turtle file. It scans recursively for `*.ttl`, including untracked working files, rather than limiting itself to Git's inventory or to `models/`.

It excludes:

- paths with any component beginning with `.`;
- files under the root `shapes/` or `results/` directories;
- files whose names end with `-shape.ttl`;
- files named `vocabulary.ttl` or `catalog-release.ttl`;
- files named `ontouml-models-*.ttl`.

All other matching files are candidates, including root `catalog.ttl`, model ontologies, and metadata sidecars. Keep unrelated Turtle files out of the checkout. The script does not regenerate ontology or metadata inputs and does not synchronize `catalog.ttl` itself.

Files are parsed in sorted repository-relative path order into one RDFLib graph. Duplicate RDF triples collapse in that graph. The serializer assigns readable, collision-safe model prefix labels; changing a prefix label does not change the namespace IRI or normalize legacy slash/hash identifiers. The result is an RDF aggregation, not a byte-preserving concatenation of source files.

### Command-line interface

| Argument | Default | Behavior |
| --- | --- | --- |
| `catalog_path` | `.` | Repository directory to scan; optional positional argument |
| `--release-tag YYYYMMDD` | Current UTC date | Valid calendar date used in the filename; does not create or select a Git tag |
| `--output-dir PATH` | `results` | Relative paths resolve under `catalog_path`; absolute paths are accepted |
| `--list-files` | Off | Prints the included paths **and then generates the release** |
| `--help` | — | Prints usage and exits without aggregation |

There is no `--dry-run`, `--check`, or `--no-overwrite`. Normal execution creates the output directory if needed and can overwrite an existing file with the same name. The date label does not check out a historical snapshot: the artifact contains the selected directory's current files.

## Local use

Use the [existing Python environment](README.md#local-setup). Commands below are single-line commands for Windows/Cmder `cmd.exe`, run from the repository root.

Inspect the interface without writing:

```bat
python scripts/generate_release_file.py --help
```

For a deliberate local aggregation check, first ensure the inputs are ready and root catalog metadata is synchronized:

```bat
python scripts/generate_catalog_file.py . --check
```

Stop if this fails and inspect the diagnostic. Catalog synchronization alone does not validate every ontology, sidecar, or model.

The next command **writes a local file** outside the repository. Use the synthetic validation date `19700101`, also used by PR validation, to avoid confusing this check with a historical release. Ensure the output location does not contain an unrelated file of the same name:

```bat
python scripts/generate_release_file.py . --release-tag 19700101 --output-dir ../ontouml-models-release-check --list-files
```

Expected output: `../ontouml-models-release-check/ontouml-models-19700101.ttl`, plus included-file and triple counts. Parse the generated artifact independently:

```bat
python -c "from pathlib import Path; from rdflib import Graph; p=Path('../ontouml-models-release-check/ontouml-models-19700101.ttl'); assert p.is_file() and p.stat().st_size; g=Graph(); g.parse(p, format='turtle'); print('Parsed release triples:', len(g))"
```

The count depends on the checkout; do not compare it with a permanent hard-coded value. These commands do not publish anything. Full aggregation is not required merely to validate documentation changes.

### Exit and write behavior

- `0`: aggregation and serialization completed.
- `1`: a handled release-generation error, such as an invalid repository/date, no eligible files, an input parse failure, or a handled output-write failure.
- `2`: invalid command-line usage from the argument parser. Unexpected runtime errors can also terminate execution; inspect the actual diagnostic rather than inferring the cause from the number alone.

Inputs are parsed before the output is serialized, so an input parse failure does not replace an existing release file. Output serialization is not an atomic replacement contract: a filesystem/write failure can leave an incomplete output. Inspect the destination before reusing it. The script never repairs the inputs or rolls back earlier, separately run generators.

## GitHub Actions behavior

The workflow has PR, scheduled, and manual triggers; it has no `push` trigger. Both jobs use Python 3.11 and install `scripts/requirements.txt`.

### Pull-request validation

The PR trigger handles `opened`, `synchronize`, `reopened`, and `ready_for_review` events when paths match:

- `models/**`, `catalog.yaml`, or `catalog.ttl`;
- `scripts/requirements.txt`;
- the ontology, catalog, or release generator `.py` files and their corresponding test modules;
- `scripts/tests/fixtures/json2graph/**`;
- `.github/workflows/publish-models-release.yml`.

The [workflow source](../.github/workflows/publish-models-release.yml) contains the exact path list. A script-guide Markdown edit alone does not match it. Do not assume an absent run means these documentation changes passed validation.

This job uses `contents: read` and a checkout without persisted credentials. It runs the ontology-generator, catalog-generator, and release-generator test modules; checks catalog synchronization; generates and parses `ontouml-models-19700101.ttl`; and uploads `ontouml-models-release-pr-<PR number>` for 30 days. It neither commits nor publishes.

It does **not** run the entire script suite or check every model with the ontology generator. The job has no same-repository PR condition; the fork restriction in the [submission workflow](process-new-model-submission.md#supported-submission-mode) applies to that separate writeback workflow.

### Scheduled and manual runs

The configured schedule is daily at **03:00 UTC**, from the default branch; this is a schedule definition, not a guarantee of an exact start or a release every day. The publication job requires `contents: write`. Catalog writeback and release publication are restricted in the script to `refs/heads/master`.

Manual inputs are:

| Input | Default | Effect |
| --- | --- | --- |
| `release_tag` | Empty | Uses the current UTC date when empty; otherwise requires a valid `YYYYMMDD` date |
| `dry_run` | `true` | Disables publication and catalog commit/push, but still allows local catalog synchronization, release generation/validation, and Actions artifact upload |
| `publish_release` | `false` | Requests publication only when `dry_run=false` |
| `force_release` | `false` | Allows manual publication without detected release-relevant changes; does not bypass date, branch, tag-target, or existing-release checks |

For scheduled runs the effective settings are `dry_run=false`, `publish_release=true`, and `force_release=false`. A manual run with publication disabled can generate a check artifact even when no release-relevant change is found.

The publication job:

1. Runs the catalog and release generator tests; it does not run the full suite or the PR job's ontology-generator tests.
2. Synchronizes root `catalog.ttl`. If changed, it commits and pushes that file on scheduled runs or on manual runs with `dry_run=false` and `publish_release=true`. It records the resulting commit SHA.
3. Resolves the date and publication settings, evaluates relevant changes, and checks for skip/failure conditions.
4. For publishing runs that continue, checks the existing tag/release against the synchronized commit.
5. Generates the Turtle artifact, checks that it is nonempty and parseable, and uploads an Actions artifact with 30-day retention.
6. Creates a GitHub Release with the date as title/tag, the RDF asset, generated release notes, and the synchronized commit as its target, unless that release is already published for the same commit.

**Catalog writeback occurs before the later settings and tag checks.** A run can commit the catalog and subsequently skip generation or fail without publishing. Even `dry_run=true` is not a no-write execution inside the runner; it suppresses repository writeback/publication, not local generation.

### Relevant changes, skips, and existing releases

The comparison baseline is the lexicographically greatest eight-digit Git tag. It need not have a GitHub Release. With no matching tag, the workflow treats relevant changes as present. Otherwise, relevant changes are a diff in `models/`, `catalog.yaml`, or `catalog.ttl`, or a catalog change detected by the synchronization step. Code/documentation changes alone do not satisfy that comparison.

| Condition | Result |
| --- | --- |
| Scheduled run; target date tag already exists | Skip generation/publication, even if other changes exist |
| Scheduled run; no relevant changes | Skip generation/publication |
| Manual publication; no relevant changes and `force_release=false` | Fail rather than publish |
| Publishing run reaches the existing-release check; tag points to a different commit | Fail; the workflow does not move the tag |
| Release exists but the matching tag/commit cannot be confirmed | Fail |
| Release and tag already refer to the synchronized commit | Do not create another GitHub Release; generation/validation and Actions artifact upload still run |
| Tag refers to the synchronized commit but has no GitHub Release | Publication may continue against that tag |

The earlier settings checks still apply on reruns. In particular, an existing release does not bypass the manual no-relevant-change gate, and `force_release` does not authorize replacing a published release.

Concurrency is grouped by PR number or branch ref, with `cancel-in-progress: false`. Workflow permissions are only requested capabilities; GitHub approval policies, branch rules, concurrent updates, or unavailable credentials can still prevent execution or a push. Check the current repository settings and run diagnostics; do not infer approval from a queued job or from this guide.

## Failure handling and reruns

Before retrying, identify which steps completed and inspect the final synchronized SHA, any catalog commit, target tag, existing release, and generated or uploaded artifact. A green workflow may be a successful skip; an uploaded artifact may belong to a non-publishing run.

- A failed catalog push stops the workflow before publication. Resolve the reported branch-rule or concurrent-update problem through the normal maintainer process; do not bypass protection merely to make the run pass.
- A failure after catalog synchronization does not undo an already pushed catalog commit.
- A parse/test/generation failure requires inspection of the failing input or environment. Fixing runtime or dataset defects is a separate change, not a reason to rewrite metadata silently during documentation work.
- A tag/commit mismatch is not fixed by blindly forcing, deleting a release, or moving a tag. First establish the intended snapshot and obtain authorization for any consequential action.
- Inspect the run log after a failed publication step to establish whether a release exists before retrying. Do not assume an attempted command completed or that rerunning is automatically side-effect-free.

Normal local generators can also leave successful earlier writes in place when a later step fails. See [submission failure behavior](process-new-model-submission.md#failure-behavior) and the [catalog lifecycle](generate-catalog-file.md#automated-lifecycle).

No workflow here demonstrates live FDP indexing, synchronization, or availability.

## Release description convention

Keep generated changelog entries and comparison links. When maintaining release text, add a short explanation of the RDF asset versus the source archive, consequential format/converter changes, compatibility or omission warnings, and the tag/commit needed for reproducibility. Describe only changes actually included in that release; link to the relevant guide rather than duplicating its contract.

Editing a release description is separate from changing tracked Markdown or publishing a new release. Nothing in this guide grants permission to modify a release, tag, repository setting, or external service.

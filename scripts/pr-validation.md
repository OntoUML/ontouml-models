# PR processing, final-state validation and merge gating

The required check is **PR validation**, created by a dedicated GitHub App on
the actual PR head SHA. A successful controller job alone never authorizes a
merge. The repository configuration below is required; copying workflow files
does not configure branch rules, install an App or create secrets.

## Architecture

`pr-validation.yml` runs trusted base-branch code for every PR targeting
`master`, without a path filter. It obtains the complete paginated PR file list,
including previous paths for renames, and opens a pending App check before
classification. Missing, inconsistent or over-3,000-file API results fail closed.

1. Classify the changes and identify required generation.
2. If applicable, run existing trusted generators on a regular-file-only copy
   of contributor model/catalog data, without write credentials.
3. Validate an allowlisted generated bundle from that same run and attempt.
   Commit only if changes exist, using GraphQL `createCommitOnBranch` with
   `expectedHeadOid`. A concurrent contributor update rejects the commit.
4. Advance the pending check to final validation (or create one on the new SHA
   after writeback) and explicitly dispatch
   `validate-pr-state.yml` from `master`, with the PR number, head, base and check
   ID. When the head changes, mark the old-head processing check as superseded,
   never successful. An unchanged head keeps its single pending check.
5. Validate the immutable final checkout. Check that its head/base still match
   the PR and that the current base is an ancestor. The trusted harness runs
   applicable data checks, candidate tests and workflow lint in isolated
   containers. It checks required model outputs **before** regenerating in a
   temporary directory; regeneration must leave the final data unchanged.
6. A `workflow_run` reporter verifies the exact workflow path, dispatch event,
   trusted base SHA/branch, run title, App/check identity, final-validation phase,
   newest check, latest run attempt, live PR head/base, and the successful
   unconditional validation job. It does not consume validation artifacts.
   Only then does it complete the App check successfully.

`Process new model submission` remains available for trusted manual maintenance;
it no longer has a PR trigger. `Publish models release` retains scheduled/manual
publication but no longer races PR generation. Publication checks an already
synchronized catalog instead of committing directly to protected `master`.
No generator semantics, model metadata or dependencies were changed.

## Applicability

| Change | Processing | Final validation |
| --- | --- | --- |
| Markdown / `documentation/**` only | None | Git whitespace checks; changed Markdown UTF-8/conflict checks; regular-file snapshot safety |
| Scripts, dependencies, workflow/configuration files | No model generation | Full script tests, trusted catalog/release checks, candidate catalog/release checks; actionlint for workflow changes |
| One model folder, including deleted generated artifacts | Existing submission helper, then catalog synchronization | Source envelope, required output inventory, no-drift regeneration, model RDF, catalog check and release generation/parse |
| Entire one-model folder removed | Catalog synchronization | Verify full deletion and final catalog/release consistency |
| Multi-model generated-only maintenance | None | All six ontology/distribution/model-metadata generator checks, RDF and catalog/release validation |
| `catalog.yaml` | Catalog synchronization | No-drift catalog generation, catalog/release checks |
| `catalog.ttl` only | None | Catalog/release checks |
| `shapes/**` | None | Parse changed Turtle shapes |
| Mixed changes | Union of applicable processing | Union of applicable validations |

The existing bulk boundary permits only direct automation-generated output
changes across models: `ontology.ttl`, `metadata.ttl`, `metadata-json.ttl`,
`metadata-turtle.ttl`, `metadata-vpp.ttl`, and files matching
`metadata-png-(n|o)-*.ttl`. Deletions, nested paths, unknown metadata names and
multiple-model source changes fail closed. Final validation checks all six
generator families. Unknown configuration files conservatively select script
and catalog checks. No documentation build/link checker existed; this change
adds only the lightweight documentation checks above, not a new documentation
toolchain. Existing source requirements, including VPP and PNG requirements,
remain unchanged.

## Trust boundary

- The `pull_request_target` controller checks out the trusted base separately
  from contributor data. The data checkout's explicit unsafe-checkout opt-in
  does **not** authorize executing that checkout. Only tracked regular
  `models/**`, `catalog.yaml` and `catalog.ttl` files enter generation; symlinks,
  submodules and unsafe paths are rejected. Trusted scripts/dependencies come
  from the base. Contributor scripts, actions and dependencies never execute in
  `pull_request_target` or in a secret-bearing reporter/writeback job.
- Generation has only `contents: read`. The subsequent writer has no PR code
  checkout and accepts only model metadata, ontology Turtle, metadata YAML
  normalization and root catalog output. It cannot write PR workflow files,
  scripts, JSON/VPP sources or unrelated model folders.
- Final validation is explicitly dispatched from the default branch with a
  read-only token and no environment/App secret. Candidate code and dependency
  installation run in a separate disposable Docker container from trusted data
  validation. Containers have read-only source mounts, a non-root user, dropped
  capabilities, no added privileges, and temporary writable storage. They do
  not receive host environment variables, tokens, credentials, caches, runtime
  artifact credentials, host `.git`, or the Docker socket. Public dependency
  downloads require network access; workflow lint has no network access.
- Automatic execution of fork-proposed code/dependencies is not authorized by
  this dispatch mechanism. A fork PR with code/configuration changes first
  blocks with an explanation; a maintainer must dispatch the controller from
  `master` with its PR number. GitHub requires repository write access for a
  manual workflow run, and the controller additionally requires a User sender,
  not a bot dispatch. This is a deliberate authorization step for untrusted
  fork code, distinct from technical validation. New contributor commits need
  authorization again; the resulting generated bot head is validated by the
  same authorized processing chain. Fork model-data/documentation PRs execute
  only trusted tools and do not require this code-execution authorization.
- The App private key must exist **only** in the restricted `pr-automation`
  environment. A repository-wide secret would let an added same-repository PR
  workflow request it and forge the required App check. The environment's
  selected-branch policy, not a PR-editable YAML condition, enforces this boundary.
- The required check must be pinned to this dedicated App's integration ID.
  Requiring a name from “any source” or from the shared GitHub Actions App would
  allow unrelated PR-controlled workflows to imitate it.
- Fork writeback requires an App installation authorized by the fork owner on
  that repository. The writer obtains a token restricted to that one fork and
  `contents: write`. No privileged token is passed to fork code. Without this
  authorization, a model PR remains blocked with a token/writeback error; a
  maintainer may instead process an authorized same-repository submission branch.
- Legacy manual maintenance still executes the selected branch's scripts with
  its existing write mode. Only dispatch it on reviewed/trusted branches. The
  automatic controller is the supported way to recover an untrusted PR.

Use GitHub-hosted ephemeral runners. Do not replace them with a persistent
self-hosted runner for untrusted validation. Review future generator/parser
changes as part of the trusted processing boundary.

## Bot updates, concurrency and stale results

Same-repository generated commits use `GITHUB_TOKEN`. Current GitHub behavior
creates approval-required `pull_request` runs for token-generated
opened/synchronize/reopened events; ordinary token-generated `push` events do
not recursively start workflows. This implementation removes the old automatic
PR consumers and uses the documented `workflow_dispatch` exception explicitly.
It never depends on a token-generated event starting follow-up validation.

Fork App writeback can emit a new PR event. Per-PR controller concurrency
serializes it after writeback; an authenticated matching App actor with a
matching pending/successful final check does not repeat generation. Commit
messages and claimed Git authors are not used as authorization. Manual recovery
is never suppressed by this bot check. There are no sleeps or polling loops.

Different heads have different App checks. Reporters reject stale heads/bases
and old attempts, and do not complete an older check when a newer App check for
the same head exists. Required-check rules apply to the current SHA; an older
successful commit is insufficient. Strict up-to-date checks additionally prevent
an outdated base from being merged. Update the PR branch after `master` changes;
the new head re-enters processing. Merge queue is not configured or supported
by this design; add a reviewed `merge_group` path before enabling it.

Failed generation prevents dispatch. Failed/skipped/cancelled/neutral/pending
validation cannot produce success. If an outage or cancellation prevents the
reporter from completing, the gate stays pending and blocks merge; use recovery.
The obsolete source-head processing check can display failure ("superseded");
the final head's App check represents eligibility. Native workflow
jobs, including intentionally skipped generation, are not individually required.

## External repository configuration

These are **administrator actions**, separate from the repository ZIP. Do not
activate an incomplete setup on a busy repository. No setting is changed by
these files or by local tests.

1. Create a dedicated GitHub App (for example `ontouml-pr-validation`) with
   repository **Checks: read and write**, **Commit statuses: read and write**,
   **Contents: read and write**, and implicit **Metadata: read**. No webhook
   subscriptions or organization/user permissions are needed. Permit
   installation by other accounts if fork
   writeback is offered. Install it on the selected catalog repository. Fork
   owners separately authorize installation on their selected fork; enabling
   Actions write tokens/secrets for fork PRs is neither needed nor permitted.
2. Create environment **`pr-automation`** in repository Settings → Environments.
   Select **Selected branches and tags** and add exactly one **Branch** rule:
   **`master`**. Add no tag rule, wildcard or PR merge-ref rule. Do not use
   “Protected branches only” (it can permit all branches if none are protected).
   Set no required environment reviewers and no wait timer, and disable
   administrator bypass. Store **`PR_AUTOMATION_APP_PRIVATE_KEY`** only as an
   environment secret. Remove any broader copy of this key. Set repository
   Actions variable **`PR_AUTOMATION_APP_ID`** to the numeric App ID (not its
   installation ID). Keep ordinary fork approval/security policies unchanged.
3. Create a separate active branch ruleset **`PR automated validation`**, target
   **`refs/heads/master`**, with **no bypass actors**, including administrators
   and the App. Enable **Require status checks to pass** with context exactly
   **`PR validation`**, expected source **the dedicated App** (its integration
   ID), and **Require branches to be up to date before merging**. Set
   `do_not_enforce_on_create: false` if using the REST ruleset representation.
   Do not require individual model/release/native controller jobs.
4. Keep human review policy in a separate ruleset. A review bypass in that
   ruleset must not bypass the no-bypass automated-validation ruleset. Retain
   existing deletion/force-push protections. Inspect any legacy branch
   protection and remove obsolete path-filtered required checks only when
   replacing them with the stable App gate; do not weaken unrelated rules.

Inspect the App source and successful check in a test PR before making it
required; GitHub's selector requires a recently successful check. Bootstrap in
an isolated test repository whose **default branch is `master`** and contains
this implementation. `workflow_dispatch` and `workflow_run` require workflow
definitions on the default branch, so an implementation PR cannot exercise
the new controller end-to-end before that deployment.

For production rollout: obtain authorization, merge the reviewed implementation
under the current policy, configure the App/environment, run a controlled PR
through final validation, then activate and verify the required App check.
Do not merge other PRs during this controlled transition. Re-evaluate already
open PRs via manual recovery. Confirm both administrators and ordinary maintainers
are blocked by failing/pending automated checks. A missing App/configuration is
not a reason to merge without the gate.

### Configuration inspected for this change

At `master` commit `1e7149af010fb6a85c6928f54fcb5ad60e01d26f`, rechecked on
2026-09-01, visible active ruleset `21749910` (`master-1`) protects
deletion/non-fast-forward updates with
no bypass. Ruleset `21749911` (`master-2`) requires PRs with zero ordinary
approvals, enables extra approval for unattributed changes, and allows an
administrator-role bypass. Neither visible ruleset contains required status
checks. The classic branch-protection endpoint returned HTTP 403; its complete
configuration was not accessible and is not assumed absent. The unattributed
change approval setting is a human authorization concern, separate from an
Actions run's `action_required` state and the new automated gate.

## Regression evidence: PR #357

The [regression PR](https://github.com/OntoUML/ontouml-models/pull/357) used a
same-repository branch. Human source commit
`16548d285659c0b16b94379b505c7aa718cbb310` deliberately removed generated TKTOnto
artifacts. Both workflows started at 17:17:45 UTC on 2026-08-28.

The [failed release run](https://github.com/OntoUML/ontouml-models/actions/runs/33194012789)
passed dependency installation and ontology/catalog tests, then failed catalog
synchronization at 17:18:43; later release validation was skipped. Processing
run `33194012755` finished at 17:19:07 after writing bot commit
`238e6f827830f9a44cae63ef6c4343bc7e817baa` at 17:19:03. Thus the failing release
check evaluated a state the other workflow had not yet finished establishing.

Bot-head release run `33194119694`, attempt 1, concluded `action_required` with
`github-actions[bot]` as actor/triggering actor. Attempt 2 succeeded after
`pedropaulofb` triggered it. The existing workflow writes using checkout's
default `GITHUB_TOKEN`; GitHub's documented token-generated PR approval rule
explains this same-repository bot behavior without invoking first-time fork
approval as an explanation. The replacement explicitly validates the bot head
and does not need that approval-dependent follow-up path.

## Regression evidence: PR #360

[PR #360](https://github.com/OntoUML/ontouml-models/pull/360), merged as
`8a51a23312ca124e887fccb3eb76bf85584ed359`, changed 394 direct generated
metadata files across 42 model folders: 42 each of `metadata-json.ttl`,
`metadata-turtle.ttl`, `metadata-vpp.ttl`, and `metadata.ttl`, plus 226
`metadata-png-*.ttl` files. That is generated-only catalog maintenance, not 42
source submissions. The classifier accepts exactly those generated families
without invoking model generation; final validation checks the corresponding
six generators. Deletions and unrecognized metadata names still fail closed.

## Local validation and limits

`scripts/tests/test_pr_automation.py` covers classification, renames/pagination,
unsafe paths, PR #360 bulk metadata, missing outputs, generation failure,
atomic writeback ordering,
no-op generation, stale head/base/attempts/checks, result/source spoofing,
documentation/script cases, and workflow/container boundaries. Existing
generator tests continue to cover source conversion and metadata behavior.

From the repository root with Python 3.11+ and actionlint 1.7.12 on PATH:

```cmd
python -m pip install -r scripts/requirements.txt
```

```cmd
python -m pytest -q scripts/tests/test_pr_automation.py && actionlint -shellcheck= && git diff --check
```

```cmd
python -m pytest -q scripts/tests && python scripts/generate_catalog_file.py . --check
```

The container workflow runs actionlint with ShellCheck disabled explicitly;
it still validates workflow syntax, expressions, action inputs and dependencies.
These local tests do not prove GitHub event delivery, permissions, App check
association, Docker runtime behavior or actual merge denial. Verify those in
the live matrix after authorized deployment. Do not infer live success from an
API fake or from a previously completed run using an older implementation.

## Live GitHub regression matrix

Use separate disposable PRs and inspect check SHA/source and the merge box.
Leave other PRs unmerged until activation is verified.

| Scenario | Required observation |
| --- | --- |
| 1. Source-only model; derived files absent (PR #357 equivalent) | Pending gate before generation; derived files committed; head changes; no release validation before writeback; final head passes inventory, no-drift, catalog and release checks before merge is allowed |
| 2. Invalid source / generation failure | Generation fails, no final dispatch or success, merge blocked |
| 3. Valid generation plus failing applicable test/validation | Generated head exists but gate fails; merge blocked |
| 4. Documentation only | Generation skipped as not applicable; documentation validation completes; no required model workflow left pending |
| 5. Script/generator/workflow change | Candidate tests, catalog/release checks and applicable workflow lint run; no model generation without model/catalog input changes |
| 6. New commit after success (also during generation/validation) | Old result cannot authorize new SHA; atomic writer cannot overwrite it; new head must pass; base advancement requires updating the PR branch |
| 7. Bot-generated artifacts | Exactly the required writeback; explicit final-head validation; no recursive commits; no approval-required legacy PR workflow; same-repository and authorized-fork cases both exercised |
| 8. Multi-model generated distribution metadata (PR #360 equivalent) | No model generation/writeback; all six generator checks run against the final head; exact generated families pass while deletions/unknown names block |

Also verify fork models without an App installation fail closed, forks without
generation need no fork write token, fork code changes cannot run without a
maintainer-authorized controller dispatch, a PR-added job cannot access the environment
key or spoof the App gate, and cancelled/old attempts cannot produce success.
Prove admin review bypass cannot bypass pending/failed automated validation.

## Recovery

Resolve the actual generation, permission, configuration or validation error.
If the base advanced, merge/rebase the current `master` into the PR branch.
Then use Actions → **Orchestrate PR validation** → **Run workflow**, select
`master`, and enter the open PR number. This performs classification and
processing again, then validates the current head; idempotent generation does
not make another commit. Do not rerun an obsolete head to approve a new one.

Equivalent **authorized external action**, with `PR_NUMBER` replaced by the
actual open PR number:

```cmd
gh workflow run pr-validation.yml --repo OntoUML/ontouml-models --ref master -f pr_number=PR_NUMBER
```

This dispatch may commit generated files to that PR branch; it is not a
read-only local test. Do not bypass the check or grant fork secrets to recover.

## GitHub semantics used

- [Workflow-generated events and the GITHUB_TOKEN approval exception](https://docs.github.com/en/actions/using-workflows/triggering-a-workflow)
- [Authorization to run a workflow manually](https://docs.github.com/en/actions/managing-workflow-runs/manually-running-a-workflow)
- [Event refs, workflow_dispatch, pull_request_target and workflow_run](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
- [Required checks: current SHA, skipped jobs, path filters and expected source](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)
- [Checks API: check head_sha, external identity and results](https://docs.github.com/en/rest/checks/runs)
- [GraphQL commit operations and expectedHeadOid](https://docs.github.com/en/graphql/reference/commits)
- [Secure use of pull_request_target](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)
- [Environment branch restrictions and secret availability](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
- [Available repository rules and required-check source selection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)

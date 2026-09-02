"""Orchestration regressions; API fakes do not prove hosted event permissions."""
from __future__ import annotations

import base64
import copy
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import pr_automation as automation
import validate_pr_state as validation

HEAD, BASE, FINAL = "a" * 40, "b" * 40, "c" * 40
APP_ID = 42


def changed(*paths, status="modified"):
    return [{"filename": path, "status": status} for path in paths]


def plan_for(*paths):
    plan = automation.classify(changed(*paths))
    plan.update(pr=357, head=HEAD, base=BASE, controller=100, head_repo="OntoUML/ontouml-models", head_ref="submission")
    return plan


class FakeAPI:
    repo = "OntoUML/ontouml-models"

    def __init__(self):
        self.pr_data = {"number": 357, "state": "open", "changed_files": 1,
                        "head": {"sha": HEAD, "ref": "submission", "repo": {"full_name": self.repo}},
                        "base": {"sha": BASE, "ref": "master", "repo": {"full_name": self.repo}}}
        self.files_data = changed("README.md")
        self.events, self.check_store = [], {}
        self.check_counter, self.run_data = 1000, {}
        self.job = {"name": automation.VALIDATION_JOB, "status": "completed", "conclusion": "success"}
        self.reject_commit = self.reject_dispatch = False

    def pr(self, number):
        return automation.GitHub.pr(self, number)

    def files(self, pr):
        return automation.GitHub.files(self, pr)

    def start_check(self, plan, phase, check_id=None):
        return automation.GitHub.start_check(self, plan, phase, check_id)

    def finish_check(self, *args, **kwargs):
        return automation.GitHub.finish_check(self, *args, **kwargs)

    def check(self, check_id):
        return copy.deepcopy(self.check_store[check_id])

    def checks(self, head):
        return [copy.deepcopy(value) for value in self.check_store.values() if value["head_sha"] == head]

    def api(self, method, path, body=None):
        self.events.append((method, path, copy.deepcopy(body)))
        if path == "pulls/357":
            return copy.deepcopy(self.pr_data)
        if path.startswith("pulls/357/files?"):
            page = int(path.split("page=")[-1])
            return self.files_data[(page - 1) * 100:page * 100]
        if method == "POST" and path == "check-runs":
            self.check_counter += 1
            value = dict(body, id=self.check_counter, app={"id": APP_ID})
            self.check_store[value["id"]] = value
            return copy.deepcopy(value)
        if method == "PATCH" and path.startswith("check-runs/"):
            self.check_store[int(path.split("/")[-1])].update(body)
            return None
        if path.endswith("/jobs?per_page=100"):
            return {"total_count": 1, "jobs": [copy.deepcopy(self.job)]}
        if path.startswith("actions/runs/"):
            return copy.deepcopy(self.run_data)
        if method == "POST" and path.endswith("/dispatches"):
            if self.reject_dispatch:
                raise automation.AutomationError("Dispatch rejected")
            return None
        raise AssertionError((method, path, body))

    def request(self, method, path, body=None):
        assert method == "POST" and path == "/graphql"
        self.events.append((method, path, copy.deepcopy(body)))
        assert body["variables"]["input"]["expectedHeadOid"] == HEAD
        if self.reject_commit:
            return {"errors": [{"message": "Head changed"}]}
        self.pr_data["head"]["sha"] = FINAL
        return {"data": {"createCommitOnBranch": {"commit": {"oid": FINAL}}}}


def start(api, plan, phase="processing"):
    return api.start_check(plan, phase)


def completion(api, *, conclusion="success"):
    plan = plan_for("README.md")
    check_id = start(api, plan, "validation")
    run = {"id": 200, "run_attempt": 1, "status": "completed", "conclusion": conclusion,
           "display_title": f"PR 357 head {HEAD} base {BASE} check {check_id}",
           "event": "workflow_dispatch", "path": ".github/workflows/validate-pr-state.yml",
           "head_branch": "master", "head_sha": BASE, "html_url": "https://github.com/example/run/200"}
    api.run_data = run
    return check_id, copy.deepcopy(run)


@pytest.mark.parametrize("paths,mode,generate,code,catalog,workflows", [
    (["README.md"], "none", False, False, False, False),
    (["models/legacy/README.md"], "none", False, False, False, False),
    (["scripts/generate-catalog-file.md", "documentation/logo/logo.png"], "none", False, False, False, False),
    (["scripts/generate_catalog_file.py"], "none", False, True, True, False),
    (["scripts/requirements.txt"], "none", False, True, True, False),
    ([".github/workflows/publish-models-release.yml"], "none", False, True, True, True),
    (["models/new/ontology.json", "models/new/metadata.yaml"], "normal", True, False, True, False),
    (["models/new/ontology.json", "README.md", "scripts/validate_metadata_yaml.py"], "normal", True, True, True, False),
    (["catalog.yaml"], "none", True, False, True, False),
    (["catalog.ttl"], "none", False, False, True, False),
    (["shapes/shape.ttl"], "none", False, False, False, False),
    (["models/a/ontology.ttl", "models/a/metadata.ttl",
      "models/b/metadata-json.ttl", "models/b/metadata-turtle.ttl",
      "models/c/metadata-vpp.ttl", "models/d/metadata-png-o-main.ttl",
      "models/e/metadata-png-n-main.ttl"],
     "bulk-generated", False, False, True, False),
    ([".gitignore"], "none", False, True, True, False),
])
def test_applicability(paths, mode, generate, code, catalog, workflows):
    plan = automation.classify(changed(*paths))
    assert (plan["mode"], plan["generate"], plan["code"], plan["catalog"], plan["workflows"]) == (mode, generate, code, catalog, workflows)


def test_regression_357_sources_added_and_generated_files_removed():
    files = changed("models/bilal2026tktonto/ontology.json", "models/bilal2026tktonto/metadata.yaml", status="added")
    files += changed("models/bilal2026tktonto/ontology.ttl", "models/bilal2026tktonto/metadata.ttl", status="removed")
    assert automation.classify(files)["generate"]


def test_regression_360_bulk_distribution_metadata_is_applicable_without_generation():
    paths = []
    for index in range(42):
        model = f"models/model-{index:02d}"
        paths.extend(f"{model}/{name}" for name in (
            "metadata-json.ttl", "metadata-turtle.ttl",
            "metadata-vpp.ttl", "metadata.ttl"))
    paths.extend(
        f"models/model-{index % 42:02d}/metadata-png-o-diagram-{index:03d}.ttl"
        for index in range(226)
    )
    plan = automation.classify(changed(*paths))
    assert len(plan["paths"]) == 394
    assert len(plan["models"]) == 42
    assert plan["mode"] == "bulk-generated"
    assert plan["catalog"] and not plan["generate"]


def test_deleting_only_generated_file_of_existing_model_still_generates():
    assert automation.classify(changed("models/existing/ontology.ttl", status="removed"))["mode"] == "normal"


def test_rename_cannot_hide_script_change_as_documentation():
    files = [{"filename": "documentation/old-generator.md", "previous_filename": "scripts/generator.py", "status": "renamed"}]
    assert automation.classify(files)["code"]


@pytest.mark.parametrize("name", [
    "ontology.ttl", "metadata.ttl", "metadata-json.ttl",
    "metadata-turtle.ttl", "metadata-vpp.ttl", "metadata-png-o-main.ttl",
    "metadata-png-n-main.ttl",
])
def test_bulk_generated_metadata_deletion_fails_closed(name):
    files = changed(f"models/a/{name}", status="removed")
    files += changed("models/b/metadata.ttl")
    with pytest.raises(automation.AutomationError):
        automation.classify(files)


@pytest.mark.parametrize("paths", [
    ["models/a/ontology.json", "models/b/ontology.json"],
    ["models/a/metadata-custom.ttl", "models/b/metadata.ttl"],
    ["models/a/metadata-png-x-main.ttl", "models/b/metadata.ttl"],
    ["models/a/metadata-png-o-.ttl", "models/b/metadata.ttl"],
    ["models/a"],
    [],
])
def test_unsupported_changes_fail_closed(paths):
    with pytest.raises(automation.AutomationError):
        automation.classify(changed(*paths))


@pytest.mark.parametrize("path", ["../escape", "/tmp/escape", "models//a", "models/./a", "models/../a", "models\\a", "models/a\noutput=true", ".git/config"])
def test_paths_cannot_escape_or_inject_workflow_outputs(path):
    with pytest.raises(automation.AutomationError):
        automation.safe_path(path)


def test_complete_api_pagination_includes_late_model_file():
    api = FakeAPI()
    api.files_data = changed(*(f"documentation/{i}.md" for i in range(399)), "models/a/ontology.json")
    api.pr_data["changed_files"] = 400
    assert automation.classify(api.files(api.pr_data))["generate"]
    assert len([event for event in api.events if "/files?" in event[1]]) == 4


@pytest.mark.parametrize("count", [0, 3001, 2])
def test_incomplete_or_oversized_api_diff_is_not_docs_only(count):
    api = FakeAPI()
    api.pr_data["changed_files"] = count
    with pytest.raises(automation.AutomationError):
        api.files(api.pr_data)


def bundle_for(plan, path="models/new/ontology.ttl"):
    return {"head": plan["head"], "base": plan["base"], "additions": [{"path": path, "contents": base64.b64encode(b"generated").decode()}]}


@pytest.mark.parametrize("path", ["scripts/steal.py", ".github/workflows/steal.yml", "models/other/ontology.ttl", "models/new/ontology.json", "models/new/ontology.vpp", "../escape"])
def test_writeback_accepts_only_generated_files_in_target_model(path):
    plan = plan_for("models/new/ontology.json")
    with pytest.raises(automation.AutomationError):
        automation.validate_bundle(bundle_for(plan, path), plan)


@pytest.mark.parametrize("change", ["sha", "duplicate", "encoding", "deletions"])
def test_invalid_bundles_fail_closed(change):
    plan = plan_for("models/new/ontology.json")
    bundle = bundle_for(plan)
    if change == "sha":
        bundle["head"] = FINAL
    elif change == "duplicate":
        bundle["additions"] *= 2
    elif change == "encoding":
        bundle["additions"][0]["contents"] = "not-base64!"
    else:
        bundle["deletions"] = ["README.md"]
    with pytest.raises(automation.AutomationError):
        automation.validate_bundle(bundle, plan)


def test_new_model_writeback_precedes_dispatch_of_bot_head():
    api, plan = FakeAPI(), plan_for("models/new/ontology.json")
    first = start(api, plan)
    assert automation.publish(api, api, api, api, plan, first, bundle_for(plan)) == FINAL
    commit = next(i for i, event in enumerate(api.events) if event[1] == "/graphql")
    dispatch = next(i for i, event in enumerate(api.events) if event[1].endswith("/dispatches"))
    assert commit < dispatch
    inputs = api.events[dispatch][2]["inputs"]
    check = api.check_store[int(inputs["check_id"])]
    assert inputs["head_sha"] == check["head_sha"] == FINAL
    assert check["status"] == "in_progress"
    assert api.check_store[first]["conclusion"] == "failure"
    assert not any(check.get("conclusion") == "success" for check in api.check_store.values())


def test_documentation_dispatches_validation_without_generation_or_writeback():
    api, plan = FakeAPI(), plan_for("README.md")
    automation.publish(api, api, api, api, plan, start(api, plan))
    assert not any(event[1] == "/graphql" for event in api.events)
    assert any(event[1].endswith("/dispatches") for event in api.events)
    assert len(api.check_store) == 1
    assert list(api.check_store.values())[0]["status"] == "in_progress"


def test_validation_dispatch_uses_dedicated_app_client():
    api, dispatcher, plan = FakeAPI(), FakeAPI(), plan_for("README.md")
    automation.publish(api, api, api, dispatcher, plan, start(api, plan))
    assert not any(event[1].endswith("/dispatches") for event in api.events)
    dispatches = [event for event in dispatcher.events if event[1].endswith("/dispatches")]
    assert len(dispatches) == 1
    assert dispatches[0][2]["ref"] == automation.BASE_BRANCH


def test_validation_dispatch_failure_closes_gate():
    api, dispatcher, plan = FakeAPI(), FakeAPI(), plan_for("README.md")
    dispatcher.reject_dispatch = True
    check_id = start(api, plan)
    with pytest.raises(automation.AutomationError, match="Dispatch rejected"):
        automation.publish(api, api, api, dispatcher, plan, check_id)
    assert api.check_store[check_id]["conclusion"] == "failure"


def test_noop_generation_does_not_create_recursive_commits():
    api, plan = FakeAPI(), plan_for("models/new/ontology.json")
    automation.publish(api, api, api, api, plan, start(api, plan), dict(bundle_for(plan), additions=[]))
    assert not any(event[1] == "/graphql" for event in api.events)


def test_atomic_writeback_rejects_concurrent_human_commit():
    api, plan = FakeAPI(), plan_for("models/new/ontology.json")
    api.reject_commit = True
    check_id = start(api, plan)
    with pytest.raises(automation.AutomationError, match="Atomic"):
        automation.publish(api, api, api, api, plan, check_id, bundle_for(plan))
    assert api.check_store[check_id]["conclusion"] == "failure"
    assert not any(event[1].endswith("/dispatches") for event in api.events)


@pytest.mark.parametrize("mutation", ["head", "base", "closed"])
def test_stale_or_closed_pr_cannot_publish(mutation):
    api, plan = FakeAPI(), plan_for("README.md")
    check_id = start(api, plan)
    if mutation == "closed":
        api.pr_data["state"] = "closed"
    else:
        api.pr_data[mutation]["sha"] = FINAL
    with pytest.raises(automation.AutomationError):
        automation.publish(api, api, api, api, plan, check_id)
    assert api.check_store[check_id]["conclusion"] == "failure"


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "action_required", "skipped", "neutral", "timed_out"])
def test_non_successful_final_validation_blocks_merge(conclusion):
    api = FakeAPI()
    check_id, event = completion(api, conclusion=conclusion)
    automation.report(api, api, event, APP_ID)
    assert api.check_store[check_id]["conclusion"] == "failure"


def test_success_requires_actual_unskipped_validation_job():
    api = FakeAPI()
    check_id, event = completion(api)
    api.job["conclusion"] = "skipped"
    automation.report(api, api, event, APP_ID)
    assert api.check_store[check_id]["conclusion"] == "failure"


def test_final_validation_success_is_bound_to_current_head():
    api = FakeAPI()
    check_id, event = completion(api)
    automation.report(api, api, event, APP_ID)
    assert api.check_store[check_id]["conclusion"] == "success"
    api.pr_data["head"]["sha"] = FINAL
    automation.report(api, api, event, APP_ID)
    assert api.check_store[check_id]["conclusion"] == "failure"
    assert not api.checks(FINAL)


def test_pending_attempt_never_completes_gate():
    api = FakeAPI()
    check_id, event = completion(api)
    api.run_data["status"] = "in_progress"
    automation.report(api, api, event, APP_ID)
    assert api.check_store[check_id]["status"] == "in_progress"


def test_old_attempt_cannot_authorize_rerun():
    api = FakeAPI()
    check_id, event = completion(api)
    api.run_data["run_attempt"] = 2
    automation.report(api, api, event, APP_ID)
    assert api.check_store[check_id]["status"] == "in_progress"


def test_newer_check_for_same_head_supersedes_older_run():
    api = FakeAPI()
    check_id, event = completion(api)
    newer = start(api, plan_for("README.md"))
    automation.report(api, api, event, APP_ID)
    assert api.check_store[check_id]["status"] == api.check_store[newer]["status"] == "in_progress"


@pytest.mark.parametrize("field,value", [("event", "pull_request"), ("head_branch", "untrusted"), ("head_sha", HEAD), ("path", ".github/workflows/fake.yml")])
def test_spoofed_or_wrong_base_workflow_cannot_report(field, value):
    api = FakeAPI()
    check_id, event = completion(api)
    api.run_data[field] = value
    with pytest.raises(automation.AutomationError):
        automation.report(api, api, event, APP_ID)
    assert api.check_store[check_id]["status"] == "in_progress"


@pytest.mark.parametrize("change", ["app", "phase"])
def test_report_requires_app_owned_final_validation_check(change):
    api = FakeAPI()
    check_id, event = completion(api)
    if change == "app":
        api.check_store[check_id]["app"]["id"] += 1
    else:
        marker = json.loads(api.check_store[check_id]["external_id"])
        marker["phase"] = "processing"
        api.check_store[check_id]["external_id"] = json.dumps(marker)
    with pytest.raises(automation.AutomationError):
        automation.report(api, api, event, APP_ID)


def test_only_authenticated_app_actor_suppresses_duplicate_bot_processing():
    api = FakeAPI()
    completion(api)
    assert automation.already_dispatched(api.checks(HEAD), api.pr_data, APP_ID, "catalog-ci[bot]", "catalog-ci")
    assert not automation.already_dispatched(api.checks(HEAD), api.pr_data, APP_ID, "contributor", "catalog-ci")


def test_classification_failure_creates_a_failed_gate(tmp_path, monkeypatch):
    api = FakeAPI()
    api.pr_data["changed_files"] = 3001
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "outputs"))
    with pytest.raises(automation.AutomationError):
        automation.prepare(api, api, 357, controller=100, app_id=APP_ID,
                           actor="human", app_slug="catalog-ci", automatic=True)
    assert list(api.check_store.values())[0]["conclusion"] == "failure"


def test_manual_recovery_is_not_suppressed_for_app_actor(tmp_path, monkeypatch):
    api = FakeAPI()
    completion(api)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "outputs"))
    automation.prepare(api, api, 357, controller=101, app_id=APP_ID,
                       actor="catalog-ci[bot]", app_slug="catalog-ci", automatic=False)
    assert len(api.check_store) == 2


@pytest.mark.parametrize("automatic,manual_user,allowed", [(True,False,False),(False,False,False),(False,True,True)])
def test_fork_code_needs_maintainer_authorized_dispatch(tmp_path, monkeypatch, automatic, manual_user, allowed):
    api = FakeAPI()
    api.pr_data["head"]["repo"]["full_name"] = "contributor/ontouml-models"
    api.files_data = changed("scripts/generate_catalog_file.py")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "outputs"))
    kwargs = dict(controller=100, app_id=APP_ID, actor="human", app_slug="catalog-ci",
                  automatic=automatic, manual_user=manual_user)
    if allowed:
        automation.prepare(api, api, 357, **kwargs)
        assert list(api.check_store.values())[0]["status"] == "in_progress"
    else:
        with pytest.raises(automation.AutomationError, match="Fork code/dependency"):
            automation.prepare(api, api, 357, **kwargs)
        assert list(api.check_store.values())[0]["conclusion"] == "failure"


def test_missing_generated_files_fail_before_regeneration(tmp_path):
    from test_process_new_model_submission import make_model, make_repo
    root = make_repo(tmp_path)
    make_model(root, name="new", include_ontology_turtle=False)
    with pytest.raises(Exception, match="Expected generated file"):
        validation.require_generated_outputs(root, plan_for("models/new/ontology.json"))


def test_bulk_validation_covers_every_generated_metadata_family(tmp_path, monkeypatch):
    source, trusted = tmp_path / "source", tmp_path / "trusted"
    for root in (source / "models/a", source / "models/b", trusted / "scripts"):
        root.mkdir(parents=True)
    for path in (source / "models/a/metadata-json.ttl",
                 source / "models/b/metadata-png-o-main.ttl"):
        path.write_text("", encoding="utf-8")
    calls = []
    monkeypatch.setattr(validation.subprocess, "run",
                        lambda command, **kwargs: calls.append(command))
    monkeypatch.setattr(validation, "release_check", lambda root: None)
    plan = automation.classify(changed(
        "models/a/metadata-json.ttl", "models/b/metadata-png-o-main.ttl"))
    validation.validate_data(source, trusted, plan)
    assert [Path(command[1]).name for command in calls] == [
        check[0] for check in validation.BULK_GENERATOR_CHECKS]


def test_source_only_model_real_generation_and_final_state_validation(tmp_path):
    from test_generate_png_metadata import minimal_png
    from test_process_new_model_submission import make_model, make_repo
    from test_validate_metadata_yaml import VALID_METADATA
    root = make_repo(tmp_path)
    shutil.copytree(ROOT / "scripts", root / "scripts", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(ROOT / "catalog.yaml", root / "catalog.yaml")
    model = make_model(root, name="new", include_ontology_turtle=False)
    (model / "new-diagrams/main.png").write_bytes(minimal_png())
    (model / "metadata.yaml").write_text(VALID_METADATA, encoding="utf-8")
    shutil.copyfile(ROOT / "scripts/tests/fixtures/json2graph/minimal-single-language/ontology.json", model / "ontology.json")
    plan = plan_for("models/new/ontology.json", "models/new/metadata.yaml")
    with pytest.raises(Exception, match="Expected generated file"):
        validation.require_generated_outputs(root, plan)
    automation.process_data(root, plan)
    validation.require_generated_outputs(root, plan)
    before = automation.file_hashes(root)
    validation.validate_data(root, ROOT, plan)
    assert automation.file_hashes(root) == before


def test_check_listing_includes_new_pending_runs_not_only_latest_completion(monkeypatch):
    api = automation.GitHub("OntoUML/ontouml-models", "test-token")
    calls = []
    def fake_api(method, path):
        calls.append(path)
        assert "filter=all" in path
        page = int(path.split("page=")[-1])
        return {"total_count": 101, "check_runs": [{"id": index} for index in range(100)] if page == 1 else [{"id": 101, "status": "in_progress"}]}
    monkeypatch.setattr(api, "api", fake_api)
    assert api.checks(HEAD)[-1]["status"] == "in_progress"
    assert len(calls) == 2


def test_generation_failure_never_emits_partial_bundle(tmp_path, monkeypatch):
    plan = plan_for("models/new/ontology.json")
    monkeypatch.setattr(automation, "git", lambda root, *args: (HEAD if root.name == "candidate" else BASE).encode())
    monkeypatch.setattr(automation, "data_workspace", lambda *args: None)
    monkeypatch.setattr(automation, "file_hashes", lambda *args: {})
    def fail(*args):
        raise subprocess.CalledProcessError(1, "generator")
    monkeypatch.setattr(automation, "process_data", fail)
    output = tmp_path / "generated.json"
    with pytest.raises(subprocess.CalledProcessError):
        automation.generate(Path("trusted"), Path("candidate"), plan, output)
    assert not output.exists()


def test_export_rejects_symlinks_before_data_parsing(tmp_path, monkeypatch):
    monkeypatch.setattr(automation, "git", lambda *args: b"120000 blob deadbeef\tmodels/a/metadata.yaml\0")
    with pytest.raises(automation.AutomationError, match="Non-regular"):
        automation.copy_tracked(tmp_path / "source", tmp_path / "export", data_only=True)


def test_documentation_conflict_is_an_applicable_failure(tmp_path):
    (tmp_path / "README.md").write_text("<<<<<<< branch\nconflict\n")
    with pytest.raises(automation.AutomationError, match="conflict"):
        validation.validate_docs(tmp_path, plan_for("README.md"))


def test_container_does_not_mount_host_credentials_or_docker_socket(tmp_path):
    command = validation.container_command(tmp_path / "source", tmp_path / "trusted", tmp_path / "plan.json", "code")
    assert "--privileged" not in command and "--env" not in command and "-e" not in command
    assert "--read-only" in command and "--cap-drop=ALL" in command
    assert all("docker.sock" not in arg and ".git" not in arg for arg in command)
    assert command[-1].startswith("python -m venv /tmp/venv")
    assert "-r /repo/scripts/requirements.txt" in command[-1]


def test_docs_only_container_does_not_install_model_dependencies(tmp_path):
    command = validation.container_command(tmp_path / "source", tmp_path / "trusted", tmp_path / "plan.json", "data", dependencies=False)
    assert "pip install" not in command[-1]


def workflow(name):
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def test_workflow_dependencies_and_trust_boundaries():
    controller = workflow("pr-validation.yml")
    assert "paths" not in controller["on"]["pull_request_target"]
    assert controller["concurrency"]["cancel-in-progress"] == "false"
    jobs = controller["jobs"]
    assert jobs["publish"]["needs"] == ["prepare", "generate"]
    assert "always()" in jobs["publish"]["if"] and "needs.generate.result == 'success'" in jobs["publish"]["if"]
    assert jobs["generate"]["permissions"] == {"contents": "read"}
    assert "environment" not in jobs["generate"]
    assert jobs["publish"]["permissions"] == {"contents": "write", "pull-requests": "read"}
    publish_steps = {step.get("id"): step for step in jobs["publish"]["steps"] if step.get("id")}
    assert publish_steps["app"]["with"]["permission-checks"] == "write"
    assert "permission-actions" not in publish_steps["app"]["with"]
    assert publish_steps["dispatch"]["with"]["permission-actions"] == "write"
    assert "permission-checks" not in publish_steps["dispatch"]["with"]
    publish_command = next(step for step in jobs["publish"]["steps"]
                           if step.get("run") == "python scripts/pr_automation.py publish")
    assert publish_command["env"]["DISPATCH_TOKEN"] == "${{ steps.dispatch.outputs.token }}"
    for name in ("prepare", "publish", "failure", "report"):
        assert jobs[name]["environment"] == "pr-automation"
        for step in jobs[name]["steps"]:
            assert step.get("with", {}).get("path") != "candidate"
    validator = workflow("validate-pr-state.yml")
    assert set(validator["on"]) == {"workflow_dispatch"}
    assert len(validator["jobs"]) == 1
    job = validator["jobs"]["validate"]
    assert "if" not in job and "environment" not in job
    assert job["name"] == automation.VALIDATION_JOB
    assert "secrets." not in (ROOT / ".github/workflows/validate-pr-state.yml").read_text()
    for old in ("process-new-model-submission.yml", "publish-models-release.yml"):
        assert "pull_request" not in workflow(old)["on"]
    release = (ROOT / ".github/workflows/publish-models-release.yml").read_text()
    assert "git push" not in release
    assert "generate_catalog_file.py . --check" in release


def test_new_orchestration_actions_are_pinned_to_commits():
    for name in ("pr-validation.yml", "validate-pr-state.yml"):
        for job in workflow(name)["jobs"].values():
            for step in job.get("steps", []):
                if "uses" in step:
                    assert re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", step["uses"])

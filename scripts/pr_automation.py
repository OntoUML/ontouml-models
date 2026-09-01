"""Trusted PR controller. Never import or execute files from a PR checkout.

The dedicated App owns the required check; GitHub Actions job names are not
merge credentials. See pr-validation.md for the required environment/ruleset.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath

CHECK_NAME = "PR validation"
BASE_BRANCH = "master"
VALIDATION_WORKFLOW = "validate-pr-state.yml"
VALIDATION_JOB = "Validate applicable final state"
SHA = re.compile(r"[0-9a-f]{40}\Z")
RUN_TITLE = re.compile(r"PR ([1-9][0-9]*) head ([0-9a-f]{40}) base ([0-9a-f]{40}) check ([1-9][0-9]*)\Z")
BULK_FILES = {
    "ontology.ttl",
    "metadata.ttl",
    "metadata-json.ttl",
    "metadata-turtle.ttl",
    "metadata-vpp.ttl",
}
BULK_PNG_FILE = re.compile(r"metadata-png-(?:n|o)-.+\.ttl\Z")
MAX_BUNDLE_BYTES = 64 * 1024 * 1024


class AutomationError(RuntimeError):
    """A failure that must leave the merge gate closed."""


def require(condition, message):
    if not condition:
        raise AutomationError(message)


def safe_path(value):
    require(isinstance(value, str) and bool(value), "Empty or invalid path")
    path = PurePosixPath(value)
    require(not path.is_absolute() and str(path) == value and "\\" not in value
            and not re.search(r"[\x00-\x1f\x7f]", value)
            and not any(part in {"..", ".git"} for part in path.parts),
            f"Unsafe repository path: {value!r}")
    return value


def bulk_generated_file(name):
    """Return whether a direct model file is automation-generated bulk output."""
    return name in BULK_FILES or bool(BULK_PNG_FILE.fullmatch(name))


def classify(files):
    """Classify a complete diff, including both sides of renames.

    Preserve the existing one-model / bulk-generated boundary. Mixed changes
    take the union of applicable validation, not an exclusive first match.
    """
    paths, removed = set(), set()
    for item in files:
        path = safe_path(item["filename"])
        paths.add(path)
        if item["status"] == "removed":
            removed.add(path)
        if item.get("previous_filename"):
            previous = safe_path(item["previous_filename"])
            paths.add(previous)
            removed.add(previous)
    require(bool(paths), "No changed files; refusing an empty classification")
    model_paths = sorted(path for path in paths if path.startswith("models/") and not path.lower().endswith(".md"))
    require(all(len(PurePosixPath(path).parts) >= 3 for path in model_paths),
            "Model paths must be within a direct models/<slug> folder")
    folders = sorted({"/".join(path.split("/")[:2]) for path in model_paths})
    mode = "none"
    if len(folders) == 1:
        mode = "normal"
    elif folders:
        require(all(len(path.split("/")) == 3 and bulk_generated_file(path.split("/")[-1])
                    and path not in removed for path in model_paths),
                "Multiple models require generated-only maintenance; split source submissions")
        mode = "bulk-generated"
    docs = sorted(path for path in paths if path.lower().endswith(".md"))
    workflows = any(path.startswith(".github/workflows/") for path in paths)
    shapes = any(path.startswith("shapes/") for path in paths)
    code = any(not (path.startswith(("models/", "documentation/", "shapes/"))
                       or path.lower().endswith(".md")
                       or path in {"catalog.yaml", "catalog.ttl"}) for path in paths)
    catalog = bool(folders) or code or bool(paths & {"catalog.yaml", "catalog.ttl"})
    return {"mode": mode, "models": folders, "paths": sorted(paths), "removed": sorted(removed),
            "docs": docs, "code": code, "workflows": workflows, "shapes": shapes,
            "catalog": catalog, "generate": mode == "normal" or "catalog.yaml" in paths}


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def copy_tracked(source, destination, *, data_only=False):
    """Export only regular tracked files. Reject symlinks, submodules and traversal."""
    destination.mkdir(parents=True, exist_ok=True)
    for record in git(source, "ls-tree", "-rz", "HEAD").split(b"\0"):
        if not record:
            continue
        header, raw_path = record.split(b"\t", 1)
        mode, kind, _ = header.decode("ascii").split()
        path = safe_path(raw_path.decode("utf-8"))
        if data_only and not (path.startswith("models/") or path in {"catalog.yaml", "catalog.ttl"}):
            continue
        require(kind == "blob" and mode in {"100644", "100755"}, f"Non-regular tracked file: {path}")
        src = source / path
        require(src.is_file() and not src.is_symlink()
                and source.resolve() in src.resolve().parents, f"Unsafe checkout file: {path}")
        dest = destination / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)


def data_workspace(trusted, source, destination):
    copy_tracked(source, destination, data_only=True)
    shutil.copytree(trusted / "scripts", destination / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    (destination / "models").mkdir(exist_ok=True)


def file_hashes(root):
    result = {}
    for parent in (root / "models", root / "catalog.yaml", root / "catalog.ttl"):
        paths = parent.rglob("*") if parent.is_dir() else [parent]
        for path in paths:
            if path.is_file():
                require(not path.is_symlink(), "Generation produced a symlink")
                result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def process_data(root, plan):
    """Reuse the current generators, executing only the trusted scripts copy."""
    if plan["mode"] == "normal":
        model = plan["models"][0]
        if (root / model).is_dir():
            subprocess.run([sys.executable, "scripts/process_new_model_submission.py", model,
                            "--repository", "OntoUML/ontouml-models", "--branch", BASE_BRANCH],
                           cwd=root, check=True)
        else:
            require(all(path in plan["removed"] for path in plan["paths"]
                        if path.startswith(model + "/")), "Missing model folder is not a complete deletion")
    if plan["catalog"]:
        subprocess.run([sys.executable, "scripts/generate_catalog_file.py", "."], cwd=root, check=True)


def allowed_output(path, plan):
    if path == "catalog.ttl":
        return plan["catalog"]
    parts = path.split("/")
    return (plan["mode"] == "normal" and len(parts) == 3
            and "/".join(parts[:2]) == plan["models"][0]
            and (parts[2] in {"metadata.yaml", "ontology.ttl", "metadata.ttl"}
                 or (parts[2].startswith("metadata-") and parts[2].endswith(".ttl"))))


def validate_bundle(bundle, plan):
    require(bundle.get("head") == plan["head"] and bundle.get("base") == plan["base"], "Stale generation bundle")
    additions = bundle.get("additions", [])
    require(isinstance(additions, list), "Invalid bundle additions")
    seen, total = set(), 0
    for item in additions:
        require(set(item) == {"path", "contents"}, "Unexpected bundle fields")
        path = safe_path(item["path"])
        require(path not in seen and allowed_output(path, plan), f"Out-of-scope generated file: {path}")
        seen.add(path)
        try:
            contents = base64.b64decode(item["contents"], validate=True)
        except (ValueError, TypeError) as exc:
            raise AutomationError("Invalid generated file encoding") from exc
        total += len(contents)
        require(total <= MAX_BUNDLE_BYTES, "Generated bundle exceeds 64 MiB")
    require(set(bundle) == {"head", "base", "additions"}, "Unexpected generation bundle fields")
    return additions


def generate(trusted, candidate, plan, output):
    require(git(candidate, "rev-parse", "HEAD").decode().strip() == plan["head"], "Wrong generation head")
    require(git(trusted, "rev-parse", "HEAD").decode().strip() == plan["base"], "Wrong trusted base")
    with tempfile.TemporaryDirectory(prefix="ontouml-pr-generation-") as temp:
        root = Path(temp)
        data_workspace(trusted, candidate, root)
        before = file_hashes(root)
        process_data(root, plan)
        after = file_hashes(root)
        require(not (before.keys() - after.keys()), "Generators unexpectedly removed files")
        additions = [{"path": path, "contents": base64.b64encode((root / path).read_bytes()).decode("ascii")}
                     for path in sorted(after) if before.get(path) != after[path]]
        bundle = {"head": plan["head"], "base": plan["base"], "additions": additions}
        validate_bundle(bundle, plan)
        output.write_text(json.dumps(bundle), encoding="utf-8")
        return bundle


class GitHub:
    def __init__(self, repo, token):
        require(bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)), "Invalid repository")
        require(bool(token), "Missing GitHub token")
        self.repo, self.token = repo, token

    def request(self, method, path, body=None):
        url = "https://api.github.com" + path
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raise AutomationError(f"GitHub {method} {path} failed (HTTP {exc.code})") from exc

    def api(self, method, path, body=None):
        return self.request(method, f"/repos/{self.repo}/{path}", body)

    def pr(self, number):
        pr = self.api("GET", f"pulls/{int(number)}")
        require(pr["state"] == "open" and pr["base"]["ref"] == BASE_BRANCH
                and pr["base"]["repo"]["full_name"] == self.repo, "PR is closed or has an unsupported base")
        require(pr["head"]["repo"] is not None, "PR source repository is unavailable")
        require(not (pr["head"]["repo"]["full_name"] == self.repo and pr["head"]["ref"] == BASE_BRANCH),
                "Refusing to write to the protected base branch")
        require(SHA.fullmatch(pr["head"]["sha"]) and SHA.fullmatch(pr["base"]["sha"]), "Invalid GitHub SHA")
        return pr

    def files(self, pr):
        count = pr["changed_files"]
        require(0 < count <= 3000, "PR file list exceeds API coverage; split this PR")
        files = []
        for page in range(1, (count + 99) // 100 + 1):
            files.extend(self.api("GET", f"pulls/{pr['number']}/files?per_page=100&page={page}"))
        require(len(files) == count and len({item["filename"] for item in files}) == count,
                "Incomplete or changing PR file list")
        return files

    def check(self, check_id):
        return self.api("GET", f"check-runs/{int(check_id)}")

    def checks(self, head):
        # filter=latest is completion-time based. Inspect all matching runs so
        # an older completion cannot hide a newer pending check.
        result = []
        for page in range(1, 11):
            response = self.api("GET", f"commits/{head}/check-runs?check_name=PR%20validation&filter=all&per_page=100&page={page}")
            result.extend(response["check_runs"])
            if len(result) >= response["total_count"]:
                return result
        raise AutomationError("Too many matching checks to establish the newest check safely")

    def start_check(self, plan, phase, check_id=None):
        marker = {key: plan[key] for key in ("pr", "head", "base", "controller")}
        marker["phase"] = phase
        body = {
            "name": CHECK_NAME, "head_sha": plan["head"], "status": "in_progress",
            "external_id": json.dumps(marker, separators=(",", ":")),
            "details_url": f"https://github.com/{self.repo}/actions/runs/{plan['controller']}",
            "output": {"title": "Processing required" if phase == "processing" else "Final validation pending",
                       "summary": f"PR #{plan['pr']}; head `{plan['head']}`; base `{plan['base']}`. Merge remains blocked."}}
        if check_id is not None:
            del body["head_sha"]  # A check's SHA is immutable.
            self.api("PATCH", f"check-runs/{int(check_id)}", body)
            return int(check_id)
        return self.api("POST", "check-runs", body)["id"]

    def finish_check(self, check_id, success, summary, details_url=None):
        body = {"status": "completed", "conclusion": "success" if success else "failure",
                "output": {"title": "All applicable validations passed" if success else "PR validation blocked",
                           "summary": summary[:60000]}}
        if details_url:
            body["details_url"] = details_url
        self.api("PATCH", f"check-runs/{int(check_id)}", body)


def same_state(pr, plan):
    require(pr["head"]["sha"] == plan["head"] and pr["base"]["sha"] == plan["base"],
            "PR head or base changed; this run cannot authorize the new state")


def check_marker(check, app_id):
    require(check["name"] == CHECK_NAME and check["app"]["id"] == int(app_id), "Wrong check source")
    try:
        marker = json.loads(check["external_id"])
    except (TypeError, ValueError) as exc:
        raise AutomationError("Unrecognized check identity") from exc
    require(marker["head"] == check["head_sha"], "Check SHA identity mismatch")
    return marker


def already_dispatched(checks, pr, app_id, actor, app_slug):
    if actor != app_slug + "[bot]":
        return False
    owned = [check for check in checks if check.get("app", {}).get("id") == int(app_id)]
    for check in sorted(owned, key=lambda item: item["id"], reverse=True)[:1]:
        marker = check_marker(check, app_id)
        if (marker.get("phase") == "validation" and marker.get("pr") == pr["number"]
                and marker.get("head") == pr["head"]["sha"] and marker.get("base") == pr["base"]["sha"]
                and (check["status"] != "completed" or check.get("conclusion") == "success")):
            return True
    return False


def output_values(**values):
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        for key, value in values.items():
            text = json.dumps(value, separators=(",", ":")) if isinstance(value, (dict, list, bool)) else str(value)
            require("\n" not in text and "\r" not in text, "Unsafe workflow output")
            stream.write(f"{key}={text}\n")


def prepare(read_api, checks_api, number, *, controller, app_id, actor, app_slug, automatic, manual_user=False):
    pr = read_api.pr(number)
    if automatic and already_dispatched(checks_api.checks(pr["head"]["sha"]), pr, app_id, actor, app_slug):
        output_values(skip=True)
        return
    plan = {"pr": pr["number"], "head": pr["head"]["sha"], "base": pr["base"]["sha"],
            "controller": int(controller), "head_repo": pr["head"]["repo"]["full_name"], "head_ref": pr["head"]["ref"]}
    check_id = checks_api.start_check(plan, "processing")
    output_values(check_id=check_id)
    try:
        plan.update(classify(read_api.files(pr)))
        same_state(read_api.pr(number), plan)
        require(not (plan["code"] and plan["head_repo"] != read_api.repo)
                or (not automatic and manual_user),
                "Fork code/dependency changes require a maintainer to dispatch Orchestrate PR validation "
                "on master with this PR number. Automatic dispatch must not bypass fork code-execution approval.")
        owner, name = plan["head_repo"].split("/")
        output_values(plan=plan, head=plan["head"], base=plan["base"], generate=plan["generate"],
                      fork=plan["head_repo"] != read_api.repo, owner=owner, repository=name, skip=False)
        print("Applicable processing: " + json.dumps(plan, sort_keys=True))
    except Exception as exc:
        checks_api.finish_check(check_id, False, f"Processing cannot start: {exc}")
        raise


def create_commit(write_api, plan, additions):
    query = """mutation($input: CreateCommitOnBranchInput!) {
      createCommitOnBranch(input: $input) { commit { oid } }
    }"""
    result = write_api.request("POST", "/graphql", {"query": query, "variables": {"input": {
        "branch": {"repositoryNameWithOwner": plan["head_repo"], "branchName": plan["head_ref"]},
        "expectedHeadOid": plan["head"], "message": {"headline": "chore(metadata): synchronize PR generated artifacts"},
        "fileChanges": {"additions": additions}}}})
    require(not result.get("errors"), "Atomic generated commit rejected; branch may have changed")
    head = result["data"]["createCommitOnBranch"]["commit"]["oid"]
    require(bool(SHA.fullmatch(head)), "Commit API did not return a SHA")
    return head


def publish(read_api, checks_api, write_api, plan, check_id, bundle=None):
    active_check = check_id
    try:
        same_state(read_api.pr(plan["pr"]), plan)
        additions = validate_bundle(bundle, plan) if plan["generate"] else []
        final = dict(plan)
        if additions:
            final["head"] = create_commit(write_api, plan, additions)
        same_state(read_api.pr(plan["pr"]), final)
        if final["head"] == plan["head"]:
            active_check = checks_api.start_check(final, "validation", check_id)
        else:
            active_check = checks_api.start_check(final, "validation")
            checks_api.finish_check(check_id, False, f"Processing complete; superseded by final-head check #{active_check} on `{final['head']}`.")
        read_api.api("POST", f"actions/workflows/{VALIDATION_WORKFLOW}/dispatches", {
            "ref": BASE_BRANCH, "inputs": {"pr_number": str(plan["pr"]), "head_sha": final["head"],
                                           "base_sha": final["base"], "check_id": str(active_check)}})
        print(f"Final validation dispatched for PR #{plan['pr']} at {final['head']}; check {active_check}")
        return final["head"]
    except Exception:
        checks_api.finish_check(active_check, False, "Generation/writeback/dispatch failed. No success was granted; inspect the controller log.")
        raise


def report_identity(run, check, app_id):
    match = RUN_TITLE.fullmatch(run.get("display_title", ""))
    require(match is not None, "Unrecognized validation run title")
    number, head, base, check_id = match.groups()
    require(run["event"] == "workflow_dispatch" and run["path"] == f".github/workflows/{VALIDATION_WORKFLOW}"
            and run["head_branch"] == BASE_BRANCH and run["head_sha"] == base,
            "Validation was not dispatched from the expected trusted base")
    marker = check_marker(check, app_id)
    require(check["id"] == int(check_id) and marker.get("phase") == "validation"
            and marker.get("pr") == int(number) and marker.get("head") == head and marker.get("base") == base,
            "Validation run does not match the App-owned final-head check")
    return marker


def report(read_api, checks_api, event_run, app_id):
    # Reruns use the same run ID: never accept an older attempt's completion.
    run = read_api.api("GET", f"actions/runs/{event_run['id']}")
    if run["run_attempt"] != event_run["run_attempt"] or run["status"] != "completed":
        return
    match = RUN_TITLE.fullmatch(run.get("display_title", ""))
    require(match is not None, "Unrecognized validation run title")
    check_id = int(match[4])
    check = checks_api.check(check_id)
    plan = report_identity(run, check, app_id)
    newer = [item for item in checks_api.checks(plan["head"])
             if item.get("app", {}).get("id") == int(app_id) and item["id"] > check_id]
    if newer:
        return
    try:
        same_state(read_api.pr(plan["pr"]), plan)
    except AutomationError:
        checks_api.finish_check(check_id, False, "PR head/base changed after dispatch. This result is stale.")
        return
    jobs = read_api.api("GET", f"actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100")
    success = (run["conclusion"] == "success" and jobs["total_count"] == 1
               and len(jobs["jobs"]) == 1 and jobs["jobs"][0]["name"] == VALIDATION_JOB
               and jobs["jobs"][0]["status"] == "completed" and jobs["jobs"][0]["conclusion"] == "success")
    same_state(read_api.pr(plan["pr"]), plan)
    checks_api.finish_check(check_id, success,
                            f"Final head `{plan['head']}`; base `{plan['base']}`. "
                            + ("All applicable processing and validation succeeded." if success else "Applicable final validation failed, was skipped, or did not complete successfully."),
                            run["html_url"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["prepare", "generate", "publish", "fail", "report"])
    args = parser.parse_args()
    if args.operation == "generate":
        bundle = generate(Path("trusted"), Path("candidate"), json.loads(os.environ["PLAN"]), Path("generated.json"))
        output_values(changed=bool(bundle["additions"]))
        return
    read_api = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"])
    checks_api = GitHub(read_api.repo, os.environ["CHECK_TOKEN"])
    if args.operation == "prepare":
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        automatic = os.environ["GITHUB_EVENT_NAME"] == "pull_request_target"
        number = event["pull_request"]["number"] if automatic else int(os.environ["PR_NUMBER"])
        prepare(read_api, checks_api, number, controller=os.environ["GITHUB_RUN_ID"],
                app_id=os.environ["APP_ID"], actor=os.environ["GITHUB_ACTOR"],
                app_slug=os.environ["APP_SLUG"], automatic=automatic,
                manual_user=not automatic and event.get("sender", {}).get("type") == "User")
    elif args.operation == "publish":
        plan = json.loads(os.environ["PLAN"])
        bundle = json.loads(Path("bundle/generated.json").read_text()) if plan["generate"] else None
        write_api = GitHub(plan["head_repo"], os.environ.get("WRITE_TOKEN") or os.environ["GH_TOKEN"])
        publish(read_api, checks_api, write_api, plan, int(os.environ["CHECK_ID"]), bundle)
    elif args.operation == "fail":
        checks_api.finish_check(int(os.environ["CHECK_ID"]), False, "Required processing failed or was cancelled; inspect the controller run.")
    else:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        report(read_api, checks_api, event["workflow_run"], int(os.environ["APP_ID"]))


if __name__ == "__main__":
    main()

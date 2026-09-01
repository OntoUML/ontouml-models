"""Validate an immutable final PR snapshot using the trusted base's harness.

PR executables and dependencies run only inside disposable containers, never
in the controller or reporter. The containers receive no host credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Also works with python -I: do not search a PR's cwd for the trusted module.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_automation import (GitHub, SHA, classify, copy_tracked,
                           file_hashes, git, process_data, require, same_state)

BULK_GENERATOR_CHECKS = (
    ("generate_ontology_turtle.py", "--all", "--models-dir", "models",
     "--check", "--quiet"),
    ("generate_json_metadata.py", "--all", "--models-dir", "models",
     "--allow-missing-license", "--check", "--quiet"),
    ("generate_png_metadata.py", "--all", "--models-dir", "models",
     "--allow-missing-license", "--check", "--quiet"),
    ("generate_turtle_metadata.py", "--all", "--models-dir", "models",
     "--allow-missing-license", "--check", "--quiet"),
    ("generate_vpp_metadata.py", "--all", "--models-dir", "models",
     "--allow-missing-license", "--check", "--quiet"),
    ("metadata_yaml_to_ttl.py", "--all", "--models-dir", "models",
     "--allow-missing-license", "--check", "--quiet"),
)


def validate_docs(root, plan):
    for name in plan["docs"]:
        path = root / name
        if name in plan["removed"] and not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        require(not re.search(r"^(?:<<<<<<< |=======\s*$|>>>>>>> )", text, re.MULTILINE),
                f"Unresolved conflict marker in {name}")
    print(f"Checked {len(plan['docs'])} changed Markdown paths for UTF-8/conflict markers.")


def release_check(root):
    from rdflib import Graph
    subprocess.run([sys.executable, "scripts/generate_catalog_file.py", ".", "--check"], cwd=root, check=True)
    with tempfile.TemporaryDirectory(prefix="ontouml-pr-release-") as output:
        subprocess.run([sys.executable, "scripts/generate_release_file.py", ".", "--release-tag", "19700101",
                        "--output-dir", output], cwd=root, check=True)
        path = Path(output) / "ontouml-models-19700101.ttl"
        require(path.is_file() and path.stat().st_size > 0, "Release output is absent/empty")
        graph = Graph().parse(path, format="turtle")
        print(f"Parsed release graph: {len(graph)} triples.")


def require_generated_outputs(root, plan):
    import process_new_model_submission as submission
    if plan["mode"] != "normal":
        return
    model = root / plan["models"][0]
    if not model.exists():
        return  # process_data verifies complete model deletion below.
    diagrams = submission.validate_required_sources(model, root)
    outputs = submission.expected_generated_metadata_paths(model, diagrams)
    submission.ensure_expected_outputs_exist(outputs, root)
    submission.validate_all_turtle_files(model, root)


def validate_data(source, trusted, plan):
    """Check existing outputs BEFORE regeneration; regeneration must be a no-op."""
    validate_docs(source, plan)
    if plan["shapes"]:
        from rdflib import Graph
        for name in plan["paths"]:
            if name.startswith("shapes/") and name.endswith(".ttl") and (source / name).exists():
                Graph().parse(source / name, format="turtle")
    if not plan["catalog"]:
        return
    with tempfile.TemporaryDirectory(prefix="ontouml-final-state-") as temp:
        root = Path(temp)
        shutil.copytree(source / "models", root / "models")
        for name in ("catalog.yaml", "catalog.ttl"):
            if (source / name).is_file():
                shutil.copyfile(source / name, root / name)
        shutil.copytree(trusted / "scripts", root / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        require_generated_outputs(root, plan)
        if plan["generate"]:
            before = file_hashes(root)
            process_data(root, plan)
            require(before == file_hashes(root), "Final head is missing or has stale generated artifacts")
        if plan["mode"] == "bulk-generated":
            for script, *flags in BULK_GENERATOR_CHECKS:
                subprocess.run([sys.executable, "scripts/" + script, *flags], cwd=root, check=True)
        from rdflib import Graph
        paths = sorted((root / "models").glob("*/*.ttl"))
        require(bool(paths), "No model Turtle files found")
        for path in paths:
            Graph().parse(path, format="turtle")
        print(f"Parsed {len(paths)} model Turtle files.")
        release_check(root)


def validate_proposed_code(source, plan):
    if plan["code"]:
        subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "scripts/tests"], cwd=source, check=True)
        release_check(source)


def container_command(source, trusted, plan_file, phase, *, dependencies=True):
    require(phase in {"data", "code"}, "Unknown validation phase")
    requirements = "/trusted/scripts/requirements.txt" if phase == "data" else "/repo/scripts/requirements.txt"
    # Fixed shell source, never interpolated contributor input. pip also runs in
    # the container: a PR can change requirements/build hooks, not host access.
    command = " -I /trusted/scripts/validate_pr_state.py " + phase + " --source /repo --trusted /trusted --plan /plan.json"
    bootstrap = ("python -m venv /tmp/venv && /tmp/venv/bin/python -m pip install --disable-pip-version-check -r "
                 + requirements + " && /tmp/venv/bin/python" + command) if dependencies else "python" + command
    return ["docker", "run", "--rm", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--user", "65534:65534", "--tmpfs", "/tmp:rw,exec,nosuid,size=4g", "--workdir", "/repo",
            "--mount", f"type=bind,src={source.resolve()},dst=/repo,readonly",
            "--mount", f"type=bind,src={trusted.resolve()},dst=/trusted,readonly",
            "--mount", f"type=bind,src={plan_file.resolve()},dst=/plan.json,readonly",
            "python:3.11", "sh", "-c", bootstrap]


def prepare_snapshot(source, trusted, number, head, base, plan_file):
    require(SHA.fullmatch(head) and SHA.fullmatch(base), "Invalid dispatch SHA")
    api = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"])
    pr = api.pr(number)
    identity = {"head": head, "base": base}
    same_state(pr, identity)
    require(git(source, "rev-parse", "HEAD").decode().strip() == head, "Checkout is not the dispatched final head")
    require(git(trusted, "rev-parse", "HEAD").decode().strip() == base, "Trusted checkout is not the dispatched base")
    subprocess.run(["git", "-C", str(source), "merge-base", "--is-ancestor", base, head], check=True)
    subprocess.run(["git", "-C", str(source), "diff", "--check", f"{base}...{head}"], check=True)
    plan = classify(api.files(pr))
    plan.update(identity)
    same_state(api.pr(number), plan)
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    print("Final-head applicability: " + json.dumps(plan, sort_keys=True))


def run_containers(source, trusted, plan_file):
    plan = json.loads(plan_file.read_text())
    with tempfile.TemporaryDirectory(prefix="ontouml-isolated-validation-") as temp:
        root = Path(temp)
        root.chmod(0o755)
        snapshot = root / "source"
        copy_tracked(source, snapshot)
        harness = root / "trusted"
        shutil.copytree(trusted / "scripts", harness / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        # Neither .git nor host environment variables, credentials, runtime
        # tokens, artifact/cache credentials or the Docker socket are mounted.
        subprocess.run(container_command(snapshot, harness, plan_file, "data",
                                         dependencies=plan["catalog"] or plan["shapes"]), check=True)
        if plan["code"]:
            subprocess.run(container_command(snapshot, harness, plan_file, "code"), check=True)
        if plan["workflows"]:
            subprocess.run(["docker", "run", "--rm", "--network=none", "--read-only", "--cap-drop=ALL",
                            "--security-opt=no-new-privileges", "--user", "65534:65534",
                            "--workdir", "/repo", "--mount", f"type=bind,src={snapshot},dst=/repo,readonly",
                            "rhysd/actionlint:1.7.12", "-shellcheck="], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["prepare", "containers", "data", "code"])
    parser.add_argument("--source", type=Path, default=Path("candidate"))
    parser.add_argument("--trusted", type=Path, default=Path("trusted"))
    parser.add_argument("--plan", type=Path, default=Path("final-plan.json"))
    args = parser.parse_args()
    if args.operation == "prepare":
        prepare_snapshot(args.source, args.trusted, int(os.environ["PR_NUMBER"]),
                         os.environ["HEAD_SHA"], os.environ["BASE_SHA"], args.plan)
    elif args.operation == "containers":
        run_containers(args.source, args.trusted, args.plan)
    else:
        plan = json.loads(args.plan.read_text())
        if args.operation == "data":
            validate_data(args.source, args.trusted, plan)
        else:
            validate_proposed_code(args.source, plan)


if __name__ == "__main__":
    main()

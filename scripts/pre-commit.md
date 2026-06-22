# Pre-commit hooks

This repository uses [pre-commit](https://pre-commit.com/) to run lightweight checks before commits.

## Install

Install the repository automation dependencies, including the pre-commit CLI:

```bash
python -m pip install -r scripts/requirements.txt
```

Install the Git hook:

```bash
pre-commit install
```

## Run

Run the hooks on staged files:

```bash
pre-commit run
```

Run the hooks on the whole repository:

```bash
pre-commit run --all-files
```

Run the manual PNG metadata generator tests:

```bash
pre-commit run test-png-metadata-generator --hook-stage manual --all-files
```

Update pinned hook versions:

```bash
pre-commit autoupdate
```

## Included checks

The configuration includes:

- general repository hygiene checks from `pre-commit-hooks`;
- Python linting and formatting with Ruff;
- YAML, JSON, TOML, and Python syntax checks;
- merge-conflict and private-key detection;
- line-ending, trailing-whitespace, and final-newline normalization;
- Turtle syntax validation for changed `.ttl` files;
- a manual test hook for `scripts/generate_png_metadata.py`.

## Project-specific choices

The catalog intentionally contains binary and generated artifacts such as PNG diagrams and Visual Paradigm `.vpp` files. These files are excluded from text-oriented checks.

The `check-added-large-files` hook allows large catalog artifacts and uses a 10 MB threshold for other newly added files.

The Turtle hook checks only RDF/Turtle parseability. It does not replace SHACL validation.

The PNG metadata generator tests are configured as a manual pre-commit hook because running tests on every commit can be unnecessarily slow. Use the manual command above before opening a pull request that changes the generator.

## Dependency file

There is no separate `requirements-pre-commit.txt` file. The pre-commit CLI and the automation/test dependencies are listed together in:

```text
scripts/requirements.txt
```

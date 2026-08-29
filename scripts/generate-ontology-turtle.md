# Generate OntoUML Turtle distributions

[Script index and local setup](README.md)

This repository uses `scripts/generate_ontology_turtle.py` to generate each
catalog model's `ontology.ttl` from its canonical `ontology.json` source.

The generated Turtle file remains committed and published as a catalog
distribution. It must not be edited manually: normal generation may replace a
committed graph when it differs semantically from the JSON2Graph result.

## Requirements

Install the repository's script dependencies from the repository root:

```bat
python -m pip install -r scripts/requirements.txt
```

The wrapper requires exactly `ontouml-json2graph==2.0.1` and refuses to run with
a different installed converter version. JSON2Graph 2.0.1 declares Python
`>=3.10,<4.0`; the catalog workflow currently uses Python 3.11, and this
integration has also been validated with Python 3.13.

Each selected dataset folder must have a valid slug and contain:

```text
metadata.yaml
ontology.json
```

The slug must start with an ASCII letter or digit and contain only ASCII
letters, digits, `.`, `_`, or `-`. Paths containing `..` are rejected.

`metadata.yaml` must be UTF-8 YAML with exactly one `language` field and at
least one valid language tag. The field may be a scalar, a comma-separated
string, or a list. Duplicate language tags that differ only by case are treated
as one language.

`ontology.json` must be UTF-8 JSON with an object at its root and a non-empty
top-level project `id`.

## Source-of-truth and output policy

| File | Policy |
| --- | --- |
| `metadata.yaml` | Canonical source for the language-selection rule used during conversion. |
| `ontology.json` | Canonical source for the RDF graph. |
| `ontology.ttl` | Generated, committed, and published distribution. |

The wrapper always asks JSON2Graph to write into a temporary directory. It
requires the expected `ontology.ttl`, parses and validates the complete
candidate, and only then installs it in the dataset folder.

For a dataset with an existing `ontology.ttl`:

- normal generation compares the existing and candidate RDF graphs
  semantically;
- an isomorphic existing graph is preserved byte-for-byte;
- a semantically different graph is atomically replaced;
- `--force-materialization` instead compares bytes and installs every
  byte-different validated JSON2Graph candidate, including a candidate whose
  graph is isomorphic to the historical file.

The catalog-wide migration was completed in [PR #354](https://github.com/OntoUML/ontouml-models/pull/354)
and included in [release `20260827`](https://github.com/OntoUML/ontouml-models/releases/tag/20260827).
Force materialization remains available for separately approved rematerialization;
it is not an outstanding migration task or the normal maintenance mode.

The safe replacement applies per dataset. When several datasets are processed,
an error in a later dataset does not roll back successful writes already made
for earlier datasets.

## Transformation contract

For each dataset `<slug>`, the wrapper invokes the pinned JSON2Graph CLI with
the following effective contract:

```text
python -m json2graph.decode -i models/<slug>/ontology.json -o <temporary-directory> -f ttl --base-uri https://w3id.org/ontouml-models/model/<slug># [--language <tag>] --invalid-cardinality-policy preserve --invalid-stereotype-policy preserve --unresolved-model-element-policy omit --path-order-policy warn --property-assignment-policy warn --transformation-metadata none --silent
```

The optional `--language` argument follows this catalog rule:

- if `metadata.yaml` declares exactly one distinct language, that tag is passed
  to JSON2Graph and every generated `ontouml:name` literal must use it;
- if it declares more than one distinct language, `--language` is omitted and
  every generated `ontouml:name` literal must be untagged.

For example, `language: en` produces name literals tagged with `@en`, while
`language: [en, pt-br]` produces simple, untagged name literals.

The wrapper deliberately does not use:

- `--correct`, because generation must serialize the canonical JSON without a
  legacy correction pass;
- `--model_only`, because project and diagrammatic resources are retained;
- `--decode_all`, because the wrapper assigns a dataset-specific base URI and
  processes discovered datasets in deterministic sorted order;
- embedded or sidecar transformation metadata, because provenance timestamps
  would make output nondeterministic and no sidecar is required.

### Identity validation

Every generated subject IRI must use this hash namespace:

```text
https://w3id.org/ontouml-models/model/<slug>#
```

The graph must contain exactly one `ontouml:Project`, identified by the
namespace followed by the exact top-level project `id` from `ontology.json`:

```text
https://w3id.org/ontouml-models/model/<slug>#<project-id>
```

A foreign generated subject namespace, a missing or additional project, or a
different project IRI is fatal.

### Explicit warning policies

| Source condition | Policy | Result |
| --- | --- | --- |
| Invalid cardinality | `preserve` | Preserve the source `cardinalityValue`, omit derived bounds when invalid, and warn. |
| Invalid stereotype for its element type | `preserve` | Emit the normalized stereotype and warn. |
| Unresolved diagram `modelElement` reference | `omit` | Preserve the element view, omit the unresolved relation, and warn. |
| Ordered path points | `warn` | Emit point triples without representing their order and warn. |
| Non-empty `propertyAssignments` | `warn` | Omit the map from formal RDF and warn. |

These policy warnings are nonfatal. JSON2Graph's generic progress and legacy
validation messages are suppressed with `--silent`, but Python warnings remain
visible on standard error and are prefixed with the affected dataset slug by
the wrapper.

## Usage

Run commands from the repository root unless stated otherwise.

Generate or synchronize one dataset:

```bat
python scripts/generate_ontology_turtle.py models/example-model
```

Process several explicit datasets. Duplicate paths are removed and targets are
processed in deterministic sorted order:

```bat
python scripts/generate_ontology_turtle.py models/example-a models/example-b
```

Process every direct dataset folder below `models/` that contains
`metadata.yaml`:

```bat
python scripts/generate_ontology_turtle.py --all --models-dir models
```

When the current directory is itself a dataset folder containing
`metadata.yaml`, the dataset argument may be omitted:

```bat
python ../../scripts/generate_ontology_turtle.py
```

### Preview and synchronization checks

Validate and report what normal generation would change without writing:

```bat
python scripts/generate_ontology_turtle.py models/example-model --dry-run
```

Check synchronization without writing and return a failing exit code when the
committed graph needs an update:

```bat
python scripts/generate_ontology_turtle.py models/example-model --check
```

Check the complete catalog:

```bat
python scripts/generate_ontology_turtle.py --all --models-dir models --check
```

`--check` and `--dry-run` are mutually exclusive. Both still run JSON2Graph and
perform all candidate validations.

### Migration-only force materialization

The initial migration is complete. The following commands are retained as an
exceptional maintenance reference, not instructions to repeat it.

Preview a separately proposed rematerialization without retaining output changes:

```bat
python scripts/generate_ontology_turtle.py --all --models-dir models --force-materialization --dry-run
```

Only after that rematerialization has been separately reviewed and authorized,
install every byte-different validated candidate:

```bat
python scripts/generate_ontology_turtle.py --all --models-dir models --force-materialization
```

Force materialization does not bypass validation. A missing, malformed, or
otherwise invalid source, candidate, or existing Turtle file remains fatal.

### Reporting

Text output is the default. Each successful dataset reports the source, target,
language mode, comparison mode, and action, followed by a summary.

Use JSON for a machine-readable standard-output report:

```bat
python scripts/generate_ontology_turtle.py models/example-model --dry-run --format json
```

The JSON document contains:

- the exact converter version;
- overall `ok` status;
- whether force materialization was selected;
- one result per successful dataset, including paths, slug, base URI, declared
  and selected languages, triple counts, isomorphism/change/write status, and
  captured diagnostics;
- structured error records for failed datasets.

Warnings and error messages remain on standard error, so JSON written to
standard output stays parseable.

Use `--quiet` (also accepted as `-q` or `--silent`) to suppress progress and the
final text summary while retaining warnings and errors:

```bat
python scripts/generate_ontology_turtle.py models/example-model --check --quiet
```

JSON reporting is still emitted when `--quiet` and `--format json` are used
together.

## Exit codes

| Code | Meaning |
| ---: | --- |
| `0` | Every selected dataset converted and validated successfully, and `--check` found no semantic or requested force-materialization drift. |
| `1` | At least one dataset failed, or `--check` found an output requiring an update. |
| `2` | Command-line usage or generator setup failed, including a missing or incorrect JSON2Graph version. |

When several datasets are selected, the wrapper continues after a dataset-level
failure so the report can identify other affected datasets.

## Fatal validation and write behavior

The wrapper treats the following as fatal for the affected dataset:

- invalid dataset paths or slugs;
- missing or invalid `metadata.yaml` or language declarations;
- missing, unreadable, malformed, or non-object `ontology.json`;
- a missing top-level JSON project `id`;
- JSON2Graph execution failure, nonzero exit, missing output, invalid output, or
  empty output graph;
- a candidate with a wrong generated-subject namespace, project identity, or
  `ontouml:name` language policy;
- an existing `ontology.ttl` that is not a regular, readable, valid Turtle
  file;
- an atomic replacement failure.

The existing output is not overwritten when generation or validation fails.
Replacement uses a temporary file in the target directory followed by an
atomic filesystem operation. Temporary candidate directories are cleaned up
after each dataset.

Expected validation failures are reported with the dataset path, processing
stage, category, exact JSON2Graph version, and a bounded diagnostic message.

## Dependency upgrades

JSON2Graph upgrades are manual, reviewed catalog changes because a converter
release may change every committed RDF graph.

For an upgrade:

1. Review the JSON2Graph release, supported Python versions, dependency bounds,
   CLI options, policies, warnings, and output-affecting changes.
2. Update the exact pin in `scripts/requirements.txt` and the required version
   in `scripts/generate_ontology_turtle.py` together.
3. Update version-specific assertions and, only when behavior genuinely
   changed, the focused fixtures and tests.
4. Install the dependencies in a clean environment and run
   `scripts/tests/test_generate_ontology_turtle.py`, followed by the complete
   `scripts/tests` suite.
5. Run a full-catalog dry-run or check with JSON reporting. Review conversion
   failures, warning categories, namespace and project identities, language
   behavior, triple-count changes, and unexplained graph differences.
6. Do not enable `--correct`, add compatibility post-processing, or
   force-materialize changed output merely to make an upgrade pass. Resolve or
   explicitly approve behavioral differences before changing the catalog
   baseline.
7. Update this document if the tested contract or operational behavior changes.

The relevant JSON2Graph references are:

- <https://w3id.org/ontouml/json2graph/docs/guides/command-line.html>
- <https://w3id.org/ontouml/json2graph/docs/concepts/policies.html>
- <https://w3id.org/ontouml/json2graph/docs/reference/command-line.html>

# references.bib validation

This document describes `scripts/validate_references_bib.py`, a lightweight validator for optional `references.bib` files in OntoUML/UFO Catalog model folders.

The validator is intended for repository maintenance and CI/workflow preflight checks before metadata generation. It provides a basic BibTeX/BibLaTeX syntax check without introducing a new dependency.

## Why this validator exists

`references.bib` is optional in the catalog submission process. When present, however, it should at least be readable and structurally valid enough to avoid broken bibliographic metadata or failing downstream processing.

The validator is deliberately conservative in scope:

- it checks basic BibTeX/BibLaTeX structure;
- it detects common syntax errors;
- it accepts missing `references.bib` files by default because the file is optional;
- it does not enforce complete bibliographic semantics per entry type.

## Typical usage

Validate one dataset folder:

```bash
python scripts/validate_references_bib.py models/example-model
```

Validate several dataset folders:

```bash
python scripts/validate_references_bib.py models/example-a models/example-b
```

Validate a `references.bib` file directly:

```bash
python scripts/validate_references_bib.py models/example-model/references.bib
```

Validate all direct dataset folders under `models/`:

```bash
python scripts/validate_references_bib.py --all --models-dir models
```

Return machine-readable JSON:

```bash
python scripts/validate_references_bib.py models/example-model --format json
```

Require `references.bib` to exist:

```bash
python scripts/validate_references_bib.py models/example-model --require
```

Promote warnings to errors:

```bash
python scripts/validate_references_bib.py models/example-model --strict
```

Fail on warnings without changing their displayed severity:

```bash
python scripts/validate_references_bib.py models/example-model --fail-on-warning
```

## Exit codes

```text
0  no validation errors were found
1  validation errors were found
2  command-line or discovery problem prevented normal execution
```

Warnings do not affect the exit code unless `--strict` or `--fail-on-warning` is used.

## What is checked

The validator checks that a present `references.bib` file:

- is a regular file;
- is valid UTF-8 text;
- is not empty;
- contains at least one regular bibliographic entry;
- uses entries starting with `@`;
- has an entry type followed by `{...}` or `(...)`;
- has balanced entry delimiters;
- has citation keys for regular entries;
- has valid citation-key lexical form;
- has at least one field per regular entry;
- uses field assignments in the form `field = value`;
- has non-empty field values;
- accepts top-level `%` comments between fields;
- ignores `@` markers inside full-line `%` comments outside entries;
- accepts backslash-escaped literal braces such as `\{` and `\}` inside braced LaTeX values;
- does not reuse the same citation key twice.

The validator also recognizes `@string`, `@preamble`, and `@comment` as special entries. `@string` assignments are checked for a valid macro name and a basic value shape.

## Warning-level checks

The following are warnings by default:

- unknown entry types;
- duplicate fields inside the same entry;
- empty special entries.

Use `--strict` to promote these warnings to errors.

## What is intentionally not checked

The validator does not require specific mandatory fields per entry type. For example, it does not require every `@article` to include `author`, `title`, `journal`, and `year`.

This is intentional. Such semantic validation would require stronger policy decisions and might incorrectly reject existing or acceptable bibliography styles. The current validator is meant as a basic compliance check, not as a full BibTeX processor.

## Examples

Valid minimal entry:

```bibtex
@article{sales2023catalog,
  author = {Sales, Tiago Prince and Barcelos, Pedro Paulo F.},
  title = {A FAIR catalog of ontology-driven conceptual models},
  journal = {Data & Knowledge Engineering},
  year = {2023},
  doi = {10.1016/j.datak.2023.102210}
}
```

Valid entry with comments between fields:

```bibtex
@article{commented,
  title = {Commented entry}, % comment after a field
  % full-line comment between fields
  year = {2024}
}
```

Valid full-line comment outside entries:

```bibtex
% See also @not-an-entry in a comment.
@article{commented-outside,
  title = {Commented outside},
  year = {2024}
}
```

Invalid: missing `@`:

```bibtex
article{broken,
  title = {Wrong start}
}
```

Invalid: unclosed entry:

```bibtex
@article{broken,
  title = {Missing closing brace}
```

Invalid: missing field assignment:

```bibtex
@article{broken,
  title {Missing equals}
}
```

## Suggested use in future automation

Before running metadata generation for a new model folder, call:

```bash
python scripts/validate_references_bib.py models/example-model
```

This treats `references.bib` as optional but validates it when present.

For a stricter future mode in which new submissions must always include references:

```bash
python scripts/validate_references_bib.py models/example-model --require
```

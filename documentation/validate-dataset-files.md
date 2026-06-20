# Dataset mandatory file validator

This validator checks only whether the mandatory files of an OntoUML/UFO Catalog dataset folder are present.
It does not parse or validate the contents of model, metadata, or diagram files.

## Scope

For each dataset/model folder, the validator requires:

- `ontology.vpp`
- `ontology.json`
- `metadata.yaml`
- at least one lower-case `.png` file directly inside either:
  - `new-diagrams/`
  - `original-diagrams/`

The diagram check is satisfied when at least one file ending exactly in `.png` exists in either accepted diagram directory.
The check is not recursive.

## Run from the repository root

Validate one dataset folder:

```bash
python tools/validate_dataset_files.py models/example-model
```

Validate multiple dataset folders:

```bash
python tools/validate_dataset_files.py models/model-a models/model-b
```

Validate all direct child directories of `models/`:

```bash
python tools/validate_dataset_files.py --models-dir models
```

If no path is provided and a `models/` directory exists in the current working directory, the validator validates all direct child directories of `models/`.

## JSON output

```bash
python tools/validate_dataset_files.py --models-dir models --format json
```

The JSON output includes:

- global valid/invalid status;
- number of checked datasets;
- required files;
- required diagram PNG locations;
- per-dataset results;
- missing files;
- missing diagram PNG availability;
- discovered diagram PNGs.

## Exit codes

- `0`: all checked dataset folders are valid.
- `1`: at least one checked dataset folder is invalid.
- `2`: command-line usage or input path error.

## Run tests

```bash
python -m unittest discover -s tests
```

The test suite uses only the Python standard library.

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.validate_dataset_files import (
    REQUIRED_FILES,
    build_summary,
    discover_dataset_folders,
    validate_dataset_folder,
)


def make_dataset(root: Path, name: str, *, diagram_dir: str | None = "new-diagrams") -> Path:
    dataset = root / name
    dataset.mkdir(parents=True)

    for filename in REQUIRED_FILES:
        (dataset / filename).write_text("placeholder\n", encoding="utf-8")

    if diagram_dir is not None:
        png_dir = dataset / diagram_dir
        png_dir.mkdir()
        (png_dir / "diagram-1.png").write_bytes(b"not a real png; content is not validated")

    return dataset


class DatasetFileValidationTests(unittest.TestCase):
    def test_valid_dataset_with_new_diagram_png(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            dataset = make_dataset(Path(tempdir), "valid-model", diagram_dir="new-diagrams")

            result = validate_dataset_folder(dataset)

            self.assertTrue(result.valid)
            self.assertEqual(result.missing_files, [])
            self.assertEqual(result.missing_diagram_pngs, [])
            self.assertEqual(result.present_diagram_pngs, ["new-diagrams/diagram-1.png"])

    def test_valid_dataset_with_original_diagram_png(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            dataset = make_dataset(
                Path(tempdir), "valid-model", diagram_dir="original-diagrams"
            )

            result = validate_dataset_folder(dataset)

            self.assertTrue(result.valid)
            self.assertEqual(result.present_diagram_pngs, ["original-diagrams/diagram-1.png"])

    def test_invalid_dataset_reports_missing_required_file_and_diagrams(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            dataset = make_dataset(Path(tempdir), "invalid-model", diagram_dir=None)
            (dataset / "metadata.yaml").unlink()

            result = validate_dataset_folder(dataset)

            self.assertFalse(result.valid)
            self.assertEqual(result.missing_files, ["metadata.yaml"])
            self.assertEqual(
                result.missing_diagram_pngs,
                ["new-diagrams/*.png", "original-diagrams/*.png"],
            )

    def test_png_check_is_not_recursive(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            dataset = make_dataset(Path(tempdir), "invalid-model", diagram_dir=None)
            nested = dataset / "new-diagrams" / "nested"
            nested.mkdir(parents=True)
            (nested / "diagram-1.png").write_bytes(b"placeholder")

            result = validate_dataset_folder(dataset)

            self.assertFalse(result.valid)
            self.assertEqual(result.present_diagram_pngs, [])

    def test_discover_dataset_folders_returns_direct_child_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            models = root / "models"
            models.mkdir()
            (models / "b-model").mkdir()
            (models / "a-model").mkdir()
            (models / "README.md").write_text("not a dataset folder", encoding="utf-8")

            discovered = discover_dataset_folders(models)

            self.assertEqual([path.name for path in discovered], ["a-model", "b-model"])

    def test_build_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            valid = make_dataset(root, "valid-model")
            invalid = make_dataset(root, "invalid-model", diagram_dir=None)
            (invalid / "ontology.vpp").unlink()

            summary = build_summary(
                [validate_dataset_folder(valid), validate_dataset_folder(invalid)]
            )

            self.assertFalse(summary["valid"])
            self.assertEqual(summary["total"], 2)
            self.assertEqual(summary["valid_count"], 1)
            self.assertEqual(summary["invalid_count"], 1)

    def test_cli_json_output_and_exit_code_for_invalid_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            dataset = make_dataset(Path(tempdir), "invalid-model", diagram_dir=None)
            script = Path(__file__).resolve().parents[1] / "tools" / "validate_dataset_files.py"

            completed = subprocess.run(
                [sys.executable, str(script), str(dataset), "--format", "json"],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 1)
            payload = json.loads(completed.stdout)
            self.assertFalse(payload["valid"])
            self.assertEqual(payload["invalid_count"], 1)
            self.assertIn("new-diagrams/*.png", payload["results"][0]["missing_diagram_pngs"])


if __name__ == "__main__":
    unittest.main()

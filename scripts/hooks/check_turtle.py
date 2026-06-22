"""Pre-commit hook for validating Turtle syntax with RDFLib.

The hook receives changed ``.ttl`` files from pre-commit and parses each one as
Turtle. It does not validate catalog-specific SHACL constraints; it only checks
that the RDF serialization is syntactically parseable.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rdflib import Graph


def check_turtle_file(path: Path) -> tuple[bool, str | None]:
    """Return whether ``path`` is parseable Turtle, plus an optional error."""

    try:
        Graph().parse(path, format="turtle")
    except Exception as exc:  # noqa: BLE001 - pre-commit should display parser details.
        return False, str(exc)
    return True, None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Turtle syntax for .ttl files."
    )
    parser.add_argument("files", nargs="*", type=Path, help="Turtle files to validate.")
    args = parser.parse_args()

    failed = False
    for path in args.files:
        if not path.exists():
            # The file may have been deleted in the current commit.
            continue
        ok, error = check_turtle_file(path)
        if not ok:
            failed = True
            print(f"{path}: invalid Turtle")
            print(f"  {error}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from oakn.validation import (  # noqa: E402
    ClaimValidator,
    ValidationError,
    validate_contribution_paths,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("contribution", type=Path)
    parser.add_argument("--changes", type=Path, required=True)
    arguments = parser.parse_args()
    changes = []
    for line in arguments.changes.read_text().splitlines():
        status, path = line.split("\t", maxsplit=1)
        changes.append((status, path))
    path = validate_contribution_paths(changes)
    claim_path = arguments.contribution / path
    if not claim_path.is_file():
        raise ValidationError("added claim file is absent from contribution")
    ClaimValidator().validate(json.loads(claim_path.read_text()))
    print("valid contribution")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from oakn.client import build_bundle  # noqa: E402
from oakn.index import build_index  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    parser.add_argument("release", type=Path)
    arguments = parser.parse_args()
    index = arguments.release / "index.sqlite"
    count = build_index(arguments.repository / "knowledge" / "claims", index)
    manifest = build_bundle(index, arguments.release)
    print(f"built {count} claims: {manifest}")


if __name__ == "__main__":
    main()

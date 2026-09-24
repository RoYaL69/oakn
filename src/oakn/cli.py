from __future__ import annotations

import argparse
import json
from pathlib import Path

from .client import KnowledgeClient, build_bundle
from .dependencies import resolve_project
from .index import build_index
from .validation import ClaimValidator


def main() -> None:
    parser = argparse.ArgumentParser(prog="oakn")
    subcommands = parser.add_subparsers(dest="command", required=True)
    resolve = subcommands.add_parser("resolve-project")
    resolve.add_argument("project", type=Path)
    validate = subcommands.add_parser("validate")
    validate.add_argument("claim", type=Path)
    build = subcommands.add_parser("build-index")
    build.add_argument("claims", type=Path)
    build.add_argument("index", type=Path)
    release = subcommands.add_parser("build-bundle")
    release.add_argument("index", type=Path)
    release.add_argument("output", type=Path)
    sync = subcommands.add_parser("sync")
    sync.add_argument("manifest_url")
    sync.add_argument("--index", type=Path, required=True)
    metrics = subcommands.add_parser("metrics")
    metrics.add_argument("--index", type=Path, required=True)
    outcome = subcommands.add_parser("record-outcome")
    outcome.add_argument("claim_id")
    outcome.add_argument("--index", type=Path, required=True)
    outcome_group = outcome.add_mutually_exclusive_group(required=True)
    outcome_group.add_argument("--accepted", action="store_true")
    outcome_group.add_argument("--rejected", action="store_true")
    arguments = parser.parse_args()
    if arguments.command == "resolve-project":
        print(json.dumps(resolve_project(arguments.project), indent=2))
    elif arguments.command == "validate":
        ClaimValidator().validate(json.loads(arguments.claim.read_text()))
        print("valid")
    elif arguments.command == "build-index":
        print(build_index(arguments.claims, arguments.index))
    elif arguments.command == "build-bundle":
        print(build_bundle(arguments.index, arguments.output))
    elif arguments.command == "sync":
        KnowledgeClient(arguments.index).sync(arguments.manifest_url)
    elif arguments.command == "metrics":
        print(json.dumps(KnowledgeClient(arguments.index).metrics(), indent=2, sort_keys=True))
    elif arguments.command == "record-outcome":
        outcome_metrics = KnowledgeClient(arguments.index).record_outcome(
            arguments.claim_id, accepted=arguments.accepted
        )
        print(json.dumps(outcome_metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

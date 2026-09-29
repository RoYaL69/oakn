#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load(path: Path) -> Any:
    return json.loads(path.read_text())


def approved_maintainers(
    reviews: list[dict[str, Any]],
    collaborators: list[dict[str, Any]],
    head_sha: str,
) -> set[str]:
    trusted = {
        collaborator["login"]
        for collaborator in collaborators
        if any(
            collaborator.get("permissions", {}).get(permission)
            for permission in ("admin", "maintain", "push")
        )
    }
    latest: dict[str, dict[str, Any]] = {}
    for review in reviews:
        login = review.get("user", {}).get("login")
        submitted_at = review.get("submitted_at")
        if login in trusted and isinstance(submitted_at, str):
            previous = latest.get(login)
            if previous is None or submitted_at > previous["submitted_at"]:
                latest[login] = {
                    "state": review.get("state"),
                    "commit_id": review.get("commit_id"),
                    "submitted_at": submitted_at,
                }
    return {
        login
        for login, review in latest.items()
        if review["state"] == "APPROVED" and review["commit_id"] == head_sha
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--collaborators", type=Path, required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--minimum", type=int, default=2)
    arguments = parser.parse_args()

    reviewers = approved_maintainers(
        _load(arguments.reviews), _load(arguments.collaborators), arguments.head_sha
    )
    if len(reviewers) < arguments.minimum:
        print(
            f"control-plane changes require {arguments.minimum} independent maintainer "
            f"approvals for the current commit; found {len(reviewers)}",
            file=sys.stderr,
        )
        return 1
    print(f"trusted approvals: {', '.join(sorted(reviewers))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

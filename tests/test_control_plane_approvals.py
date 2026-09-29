import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "check_control_plane_approvals.py"
HEAD = "a" * 40


def run_check(
    reviews: list[dict], collaborators: list[dict], *extra: str
) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        reviews_path = root / "reviews.json"
        collaborators_path = root / "collaborators.json"
        reviews_path.write_text(json.dumps(reviews))
        collaborators_path.write_text(json.dumps(collaborators))
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--reviews",
                str(reviews_path),
                "--collaborators",
                str(collaborators_path),
                "--head-sha",
                HEAD,
                *extra,
            ],
            capture_output=True,
            text=True,
            check=False,
        )


class ControlPlaneApprovalTests(unittest.TestCase):
    def test_requires_two_distinct_trusted_approvals_for_current_head(self) -> None:
        result = run_check(
            [
                {
                    "id": 1,
                    "user": {"login": "owner"},
                    "state": "APPROVED",
                    "commit_id": HEAD,
                    "submitted_at": "2026-01-01T00:00:00Z",
                },
                {
                    "id": 2,
                    "user": {"login": "maintainer"},
                    "state": "APPROVED",
                    "commit_id": HEAD,
                    "submitted_at": "2026-01-01T00:01:00Z",
                },
            ],
            [
                {"login": "owner", "permissions": {"admin": True}},
                {"login": "maintainer", "permissions": {"maintain": True}},
            ],
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_old_approval_and_untrusted_reviewer(self) -> None:
        result = run_check(
            [
                {
                    "id": 1,
                    "user": {"login": "owner"},
                    "state": "APPROVED",
                    "commit_id": "b" * 40,
                    "submitted_at": "2026-01-01T00:00:00Z",
                },
                {
                    "id": 2,
                    "user": {"login": "random"},
                    "state": "APPROVED",
                    "commit_id": HEAD,
                    "submitted_at": "2026-01-01T00:01:00Z",
                },
            ],
            [
                {"login": "owner", "permissions": {"admin": True}},
                {"login": "random", "permissions": {"pull": True}},
            ],
        )
        self.assertNotEqual(result.returncode, 0)

    def test_latest_review_for_a_maintainer_must_be_approval(self) -> None:
        result = run_check(
            [
                {
                    "id": 1,
                    "user": {"login": "owner"},
                    "state": "APPROVED",
                    "commit_id": HEAD,
                    "submitted_at": "2026-01-01T00:00:00Z",
                },
                {
                    "id": 2,
                    "user": {"login": "maintainer"},
                    "state": "APPROVED",
                    "commit_id": HEAD,
                    "submitted_at": "2026-01-01T00:01:00Z",
                },
                {
                    "id": 3,
                    "user": {"login": "maintainer"},
                    "state": "CHANGES_REQUESTED",
                    "commit_id": HEAD,
                    "submitted_at": "2026-01-01T00:02:00Z",
                },
            ],
            [
                {"login": "owner", "permissions": {"admin": True}},
                {"login": "maintainer", "permissions": {"push": True}},
            ],
        )
        self.assertNotEqual(result.returncode, 0)

    def test_review_id_breaks_timestamp_ties(self) -> None:
        timestamp = "2026-01-01T00:00:00Z"
        result = run_check(
            [
                {
                    "id": 1,
                    "user": {"login": "owner"},
                    "state": "APPROVED",
                    "commit_id": HEAD,
                    "submitted_at": timestamp,
                },
                {
                    "id": 2,
                    "user": {"login": "owner"},
                    "state": "CHANGES_REQUESTED",
                    "commit_id": HEAD,
                    "submitted_at": timestamp,
                },
                {
                    "id": 3,
                    "user": {"login": "maintainer"},
                    "state": "APPROVED",
                    "commit_id": HEAD,
                    "submitted_at": timestamp,
                },
            ],
            [
                {"login": "owner", "permissions": {"admin": True}},
                {"login": "maintainer", "permissions": {"push": True}},
            ],
        )
        self.assertNotEqual(result.returncode, 0)

    def test_skips_reviews_without_a_user(self) -> None:
        result = run_check(
            [
                {
                    "user": None,
                    "state": "APPROVED",
                    "commit_id": HEAD,
                    "submitted_at": "2026-01-01T00:00:00Z",
                },
                {
                    "id": 1,
                    "user": {"login": "owner"},
                    "state": "APPROVED",
                    "commit_id": HEAD,
                    "submitted_at": "2026-01-01T00:01:00Z",
                },
                {
                    "id": 2,
                    "user": {"login": "maintainer"},
                    "state": "APPROVED",
                    "commit_id": HEAD,
                    "submitted_at": "2026-01-01T00:02:00Z",
                },
            ],
            [
                {"login": "owner", "permissions": {"admin": True}},
                {"login": "maintainer", "permissions": {"maintain": True}},
            ],
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

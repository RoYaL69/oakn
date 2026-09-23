from __future__ import annotations

import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .client import KnowledgeClient


class PublicationError(RuntimeError):
    """An explicit draft-PR publication could not be completed safely."""


Runner = Callable[[list[str], Path], str]
StageClaim = Callable[[dict[str, Any], Path], Path]


def _run(command: list[str], cwd: Path) -> str:
    try:
        completed = subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        raise PublicationError(f"publication command failed: {command[0]} {command[1]}") from error
    return completed.stdout


def _github_repository(remote: str) -> str | None:
    remote = remote.strip()
    ssh_match = re.fullmatch(r"git@github\.com:([^/\s]+)/([^/\s]+?)(?:\.git)?", remote)
    if ssh_match:
        return f"{ssh_match.group(1)}/{ssh_match.group(2)}"
    parsed = urlparse(remote)
    if parsed.hostname != "github.com":
        return None
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if re.fullmatch(r"[^/\s]+/[^/\s]+", path):
        return path
    return None


def _default_stage_claim(candidate: dict[str, Any], claims_directory: Path) -> Path:
    metrics_path = claims_directory.parent.parent / ".oakn" / "publisher.metrics.json"
    return KnowledgeClient(metrics_path.with_suffix(".sqlite"), metrics_path).contribute(
        candidate, claims_directory
    )


class DraftPullRequestPublisher:
    """Creates an explicit draft PR through an isolated Git worktree."""

    def __init__(self, runner: Runner | None = None, stage_claim: StageClaim | None = None) -> None:
        self._runner = runner or _run
        self._stage_claim = stage_claim or _default_stage_claim

    def publish(
        self,
        candidate: dict[str, Any],
        repository_path: str | Path,
        github_repository: str,
        base_branch: str = "main",
    ) -> dict[str, str]:
        repository = Path(repository_path).resolve()
        if not re.fullmatch(r"[^/\s]+/[^/\s]+", github_repository):
            raise PublicationError("github_repository must be an explicit owner/repository value")
        remote = _github_repository(
            self._runner(["git", "remote", "get-url", "origin"], repository)
        )
        if remote != github_repository:
            raise PublicationError("local origin does not match the explicit GitHub repository")
        claim_id = candidate.get("id")
        if not isinstance(claim_id, str) or not re.fullmatch(r"[0-9a-f-]{36}", claim_id):
            raise PublicationError("candidate id must be a UUID before publication")
        branch = f"oakn/claim-{claim_id}"
        self._runner(["git", "fetch", "--no-tags", "origin", base_branch], repository)
        scratch = repository / ".oakn"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="publish-", dir=scratch) as temporary:
            worktree = Path(temporary) / "worktree"
            added = False
            try:
                self._runner(
                    [
                        "git",
                        "worktree",
                        "add",
                        "-b",
                        branch,
                        str(worktree),
                        f"origin/{base_branch}",
                    ],
                    repository,
                )
                added = True
                claim_path = self._stage_claim(candidate, worktree / "knowledge" / "claims")
                relative_claim_path = claim_path.relative_to(worktree).as_posix()
                self._runner(["git", "add", "--", relative_claim_path], worktree)
                self._runner(
                    ["git", "commit", "-m", f"knowledge: add claim {claim_id}"],
                    worktree,
                )
                self._runner(["git", "push", "-u", "origin", branch], worktree)
                url = self._runner(
                    [
                        "gh",
                        "pr",
                        "create",
                        "--repo",
                        github_repository,
                        "--base",
                        base_branch,
                        "--head",
                        branch,
                        "--draft",
                        "--title",
                        f"knowledge: add claim {claim_id}",
                        "--body",
                        "Public-evidence OAKN claim. Contributions are untrusted data and require CI validation.",
                    ],
                    worktree,
                ).strip()
            finally:
                if added:
                    self._runner(
                        ["git", "worktree", "remove", "--force", str(worktree)], repository
                    )
        if not re.fullmatch(rf"https://github\.com/{re.escape(github_repository)}/pull/\d+", url):
            raise PublicationError("GitHub did not return a draft pull request URL")
        return {"status": "draft_pr_created", "url": url, "branch": branch}

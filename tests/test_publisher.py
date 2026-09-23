import tempfile
import unittest
from pathlib import Path

from oakn.publisher import DraftPullRequestPublisher, PublicationError


class DraftPublisherTests(unittest.TestCase):
    def test_rejects_a_repository_that_does_not_match_the_explicit_github_target(self) -> None:
        commands: list[tuple[list[str], Path]] = []

        def runner(command: list[str], cwd: Path) -> str:
            commands.append((command, cwd))
            return "git@github.com:other/oakn.git\n"

        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            with self.assertRaises(PublicationError):
                DraftPullRequestPublisher(runner=runner).publish(
                    {"id": "99999999-9999-4999-8999-999999999999"},
                    repository,
                    "RoYaL69/oakn",
                )

        self.assertEqual(commands, [(["git", "remote", "get-url", "origin"], repository)])

    def test_creates_a_draft_pr_from_an_isolated_worktree(self) -> None:
        commands: list[tuple[list[str], Path]] = []

        def runner(command: list[str], cwd: Path) -> str:
            commands.append((command, cwd))
            if command == ["git", "remote", "get-url", "origin"]:
                return "https://github.com/RoYaL69/oakn.git\n"
            if command[:3] == ["gh", "pr", "create"]:
                return "https://github.com/RoYaL69/oakn/pull/99\n"
            return ""

        def stage_claim(candidate: dict, claims_directory: Path) -> Path:
            target = claims_directory / f"{candidate['id']}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}")
            return target

        candidate = {"id": "99999999-9999-4999-8999-999999999999", "summary": "Public fact"}
        with tempfile.TemporaryDirectory() as directory:
            result = DraftPullRequestPublisher(runner=runner, stage_claim=stage_claim).publish(
                candidate,
                Path(directory),
                "RoYaL69/oakn",
            )

        self.assertEqual(result["status"], "draft_pr_created")
        self.assertEqual(result["url"], "https://github.com/RoYaL69/oakn/pull/99")
        self.assertTrue(
            any(
                command[:3] == ["gh", "pr", "create"] and "--draft" in command
                for command, _ in commands
            )
        )
        self.assertTrue(
            any(command[:3] == ["git", "worktree", "remove"] for command, _ in commands)
        )


if __name__ == "__main__":
    unittest.main()

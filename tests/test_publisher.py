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

    def test_rejects_a_pushurl_that_does_not_match_the_explicit_github_target(self) -> None:
        commands: list[tuple[list[str], Path]] = []

        def runner(command: list[str], cwd: Path) -> str:
            commands.append((command, cwd))
            if command == ["git", "remote", "get-url", "origin"]:
                return "https://github.com/RoYaL69/oakn.git\n"
            if command == ["git", "remote", "get-url", "--push", "--all", "origin"]:
                return "git@github.com:other/oakn.git\n"
            return ""

        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            with self.assertRaises(PublicationError):
                DraftPullRequestPublisher(runner=runner).publish(
                    {"id": "99999999-9999-4999-8999-999999999999"},
                    repository,
                    "RoYaL69/oakn",
                )

        self.assertEqual(
            [command for command, _ in commands],
            [
                ["git", "remote", "get-url", "origin"],
                ["git", "remote", "get-url", "--push", "--all", "origin"],
            ],
        )

    def test_removes_the_worktree_when_staging_fails(self) -> None:
        commands: list[tuple[list[str], Path]] = []

        def runner(command: list[str], cwd: Path) -> str:
            commands.append((command, cwd))
            if command in (
                ["git", "remote", "get-url", "origin"],
                ["git", "remote", "get-url", "--push", "--all", "origin"],
            ):
                return "https://github.com/RoYaL69/oakn.git\n"
            return ""

        def fail_stage(candidate: dict, claims_directory: Path) -> Path:
            raise RuntimeError("staging failed")

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "staging failed"):
                DraftPullRequestPublisher(runner=runner, stage_claim=fail_stage).publish(
                    {"id": "99999999-9999-4999-8999-999999999999"},
                    Path(directory),
                    "RoYaL69/oakn",
                )

        self.assertTrue(
            any(command[:3] == ["git", "worktree", "remove"] for command, _ in commands)
        )
        self.assertFalse(any(command[:2] == ["git", "push"] for command, _ in commands))

    def test_removes_the_worktree_when_push_or_pr_creation_fails(self) -> None:
        def stage_claim(candidate: dict, claims_directory: Path) -> Path:
            target = claims_directory / f"{candidate['id']}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}")
            return target

        for failing_prefix in (["git", "push"], ["gh", "pr", "create"]):
            with self.subTest(failing_prefix=failing_prefix):
                commands: list[tuple[list[str], Path]] = []

                def runner(
                    command: list[str],
                    cwd: Path,
                    expected: list[str] = failing_prefix,
                    recorded: list[tuple[list[str], Path]] = commands,
                ) -> str:
                    recorded.append((command, cwd))
                    if command in (
                        ["git", "remote", "get-url", "origin"],
                        ["git", "remote", "get-url", "--push", "--all", "origin"],
                    ):
                        return "https://github.com/RoYaL69/oakn.git\n"
                    if command[: len(expected)] == expected:
                        raise PublicationError("command failed")
                    return ""

                with tempfile.TemporaryDirectory() as directory:
                    with self.assertRaisesRegex(PublicationError, "command failed"):
                        DraftPullRequestPublisher(runner=runner, stage_claim=stage_claim).publish(
                            {"id": "99999999-9999-4999-8999-999999999999"},
                            Path(directory),
                            "RoYaL69/oakn",
                        )

                self.assertTrue(
                    any(command[:3] == ["git", "worktree", "remove"] for command, _ in commands)
                )

    def test_creates_a_draft_pr_from_an_isolated_worktree(self) -> None:
        commands: list[tuple[list[str], Path]] = []

        def runner(command: list[str], cwd: Path) -> str:
            commands.append((command, cwd))
            if command in (
                ["git", "remote", "get-url", "origin"],
                ["git", "remote", "get-url", "--push", "--all", "origin"],
            ):
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

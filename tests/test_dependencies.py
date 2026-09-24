import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from oakn.dependencies import resolve_project


class DependencyResolutionTests(unittest.TestCase):
    def test_resolves_exact_npm_package_version_from_package_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "package.json").write_text(
                json.dumps({"dependencies": {"left-pad": "^1.3.0"}})
            )
            (project / "package-lock.json").write_text(
                json.dumps(
                    {
                        "lockfileVersion": 3,
                        "packages": {"node_modules/left-pad": {"version": "1.3.0"}},
                    }
                )
            )

            dependencies = resolve_project(project)

        self.assertEqual(dependencies, [{"purl": "pkg:npm/left-pad@1.3.0", "version": "1.3.0"}])

    def test_discovers_a_nested_supported_project_when_the_repository_root_has_no_manifest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            frontend = repository / "frontend"
            frontend.mkdir()
            (frontend / "package.json").write_text(
                json.dumps({"dependencies": {"p-limit": "^3.1.0"}})
            )
            (frontend / "package-lock.json").write_text(
                json.dumps(
                    {
                        "lockfileVersion": 3,
                        "packages": {"node_modules/p-limit": {"version": "3.1.0"}},
                    }
                )
            )

            dependencies = resolve_project(repository)

        self.assertEqual(dependencies, [{"purl": "pkg:npm/p-limit@3.1.0", "version": "3.1.0"}])

    def test_prunes_ignored_directories_before_descending(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            frontend = repository / "frontend"
            frontend.mkdir()
            (frontend / "package.json").write_text(
                json.dumps({"dependencies": {"p-limit": "^3.1.0"}})
            )
            (frontend / "package-lock.json").write_text(
                json.dumps(
                    {
                        "lockfileVersion": 3,
                        "packages": {"node_modules/p-limit": {"version": "3.1.0"}},
                    }
                )
            )
            remaining_directories: list[list[str]] = []

            def walk(_: Path) -> object:
                child_directories = ["node_modules", "frontend"]
                yield str(repository), child_directories, []
                remaining_directories.append(child_directories)
                yield str(frontend), [], ["package.json", "package-lock.json"]

            with mock.patch("oakn.dependencies.os.walk", walk):
                dependencies = resolve_project(repository)

        self.assertEqual(remaining_directories, [["frontend"]])
        self.assertEqual(dependencies, [{"purl": "pkg:npm/p-limit@3.1.0", "version": "3.1.0"}])

    def test_skips_gradle_dependencies_without_an_exact_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "build.gradle.kts").write_text(
                'implementation("androidx.appcompat:appcompat:$androidxAppCompatVersion")\n'
                'implementation("androidx.health.connect:connect-client:1.1.0")\n'
            )

            dependencies = resolve_project(project)

        self.assertEqual(
            dependencies,
            [
                {
                    "purl": "pkg:maven/androidx.health.connect/connect-client@1.1.0",
                    "version": "1.1.0",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()

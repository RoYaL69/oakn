import json
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()

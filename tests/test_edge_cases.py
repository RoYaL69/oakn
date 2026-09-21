import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from oakn.client import KnowledgeClient, _fetch
from oakn.dependencies import resolve_project
from oakn.index import IndexError
from oakn.validation import ValidationError


class EdgeCaseTests(unittest.TestCase):
    def test_resolves_maven_gradle_pnpm_and_yarn_exact_versions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            maven = root / "maven"
            maven.mkdir()
            (maven / "pom.xml").write_text(
                """<project xmlns='http://maven.apache.org/POM/4.0.0'><modelVersion>4.0.0</modelVersion><dependencies><dependency><groupId>org.example</groupId><artifactId>demo</artifactId><version>2.0.0</version></dependency></dependencies></project>"""
            )
            gradle = root / "gradle"
            gradle.mkdir()
            (gradle / "build.gradle.kts").write_text(
                'dependencies { implementation("org.example:demo:3.0.0") }'
            )
            pnpm = root / "pnpm"
            pnpm.mkdir()
            (pnpm / "package.json").write_text(json.dumps({"dependencies": {"left-pad": "^1"}}))
            (pnpm / "pnpm-lock.yaml").write_text("packages:\n  left-pad@1.3.0:\n")
            yarn = root / "yarn"
            yarn.mkdir()
            (yarn / "package.json").write_text(json.dumps({"dependencies": {"left-pad": "^1"}}))
            (yarn / "yarn.lock").write_text('left-pad@^1:\n  version "1.3.0"\n')
            self.assertEqual(resolve_project(maven)[0]["purl"], "pkg:maven/org.example/demo@2.0.0")
            self.assertEqual(resolve_project(gradle)[0]["purl"], "pkg:maven/org.example/demo@3.0.0")
            self.assertEqual(resolve_project(pnpm)[0]["purl"], "pkg:npm/left-pad@1.3.0")
            self.assertEqual(resolve_project(yarn)[0]["purl"], "pkg:npm/left-pad@1.3.0")

    def test_allows_github_release_asset_redirects(self) -> None:
        class Response:
            def __init__(
                self, status_code: int, content: bytes = b"", location: str | None = None
            ) -> None:
                self.status_code = status_code
                self.content = content
                self.is_redirect = location is not None
                self.headers = {"Location": location} if location else {}

        with patch(
            "oakn.client.requests.get",
            side_effect=[
                Response(302, location="https://release-assets.githubusercontent.com/download"),
                Response(200, content=b"bundle"),
            ],
        ):
            self.assertEqual(
                _fetch("https://github.com/owner/repo/releases/download/tag/manifest.json"),
                b"bundle",
            )

    def test_rejects_duplicate_claim_and_corrupt_signed_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            claims = root / "knowledge" / "claims"
            claims.mkdir(parents=True)
            existing = {
                "id": "55555555-5555-4555-8555-555555555555",
                "package": {"purl": "pkg:npm/left-pad@1.3.0", "version": "1.3.0"},
                "summary": "left-pad pads text to requested width",
                "verification": {"source_binding": "verified"},
            }
            (claims / f"{existing['id']}.json").write_text(json.dumps(existing))
            client = KnowledgeClient(root / "local.sqlite")
            candidate = {
                "package": existing["package"],
                "summary": "left-pad pads text to requested width",
            }
            with self.assertRaises(ValidationError):
                client._reject_duplicate(candidate, claims)
            (root / "local.sqlite").write_bytes(b"not sqlite")
            with self.assertRaises(IndexError):
                client.search("pads", "pkg:npm/left-pad@1.3.0", "1.3.0")


if __name__ == "__main__":
    unittest.main()

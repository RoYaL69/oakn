import hashlib
import tempfile
import unittest
from datetime import date
from pathlib import Path

from oakn.client import KnowledgeClient, build_bundle
from oakn.index import build_index


def candidate() -> tuple[dict, bytes, bytes]:
    manifest = b'{"name":"left-pad","version":"1.3.0"}'
    source = b"left-pad documented behavior"
    return (
        {
            "schema_version": 1,
            "id": "99999999-9999-4999-8999-999999999999",
            "package": {"purl": "pkg:npm/left-pad@1.3.0", "version": "1.3.0"},
            "claim_type": "API_BEHAVIOR",
            "summary": "left-pad 1.3.0 pads text to a requested width.",
            "conditions": ["The package version is exactly 1.3.0."],
            "evidence": [
                {
                    "kind": "git",
                    "repository": "https://github.com/stevemao/left-pad",
                    "commit_sha": "a" * 40,
                    "path": "README.md",
                    "content_sha256": hashlib.sha256(source).hexdigest(),
                    "package_manifest": {
                        "path": "package.json",
                        "content_sha256": hashlib.sha256(manifest).hexdigest(),
                    },
                }
            ],
            "provenance": {
                "source_url": "https://github.com/stevemao/left-pad/blob/"
                + "a" * 40
                + "/README.md",
                "retrieved_at": str(date.today()),
                "source_authority": "maintainer",
            },
            "verification": {
                "source_binding": "verified",
                "source_authority": "asserted",
                "semantic_support": "asserted",
                "executable_verification": "not_run",
                "freshness": "current_at_creation",
                "contradictions": "none_known",
            },
            "license": {"source_license": "MIT", "verbatim": False},
            "lifecycle": {"state": "active", "created_at": str(date.today())},
        },
        manifest,
        source,
    )


class EndToEndTests(unittest.TestCase):
    def test_empty_repository_contribution_index_sync_and_hit(self) -> None:
        claim, manifest, source = candidate()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = root / "canonical" / "knowledge" / "claims"
            canonical.mkdir(parents=True)
            release_index = root / "release.sqlite"
            build_index(canonical, release_index)
            client = KnowledgeClient(root / "local.sqlite", allow_file_urls=True)

            miss = client.search("pad width", "pkg:npm/left-pad@1.3.0", "1.3.0")
            self.assertEqual(miss["status"], "true_miss")
            staged = client.contribute(
                claim,
                canonical,
                fetch=lambda url: manifest if url.endswith("package.json") else source,
            )
            self.assertTrue(staged.exists())

            build_index(canonical, release_index)
            manifest_path = build_bundle(release_index, root / "release")
            client.sync(manifest_path.as_uri())
            hit = client.search("pad width", "pkg:npm/left-pad@1.3.0", "1.3.0")

        self.assertEqual(hit["status"], "hit")
        self.assertEqual(hit["results"][0]["claim_id"], claim["id"])
        self.assertGreaterEqual(hit["metrics"]["research_tokens_avoided"], 1)


if __name__ == "__main__":
    unittest.main()

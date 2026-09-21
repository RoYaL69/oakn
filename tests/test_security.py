import hashlib
import unittest
from datetime import date

from oakn.validation import ClaimValidator, ValidationError, validate_contribution_paths


def claim() -> tuple[dict, bytes, bytes]:
    manifest = b'{"name":"left-pad","version":"1.3.0"}'
    source = b"public evidence"
    return (
        {
            "schema_version": 1,
            "id": "33333333-3333-4333-8333-333333333333",
            "package": {"purl": "pkg:npm/left-pad@1.3.0", "version": "1.3.0"},
            "claim_type": "API_BEHAVIOR",
            "summary": "left-pad pads text to a width.",
            "conditions": [],
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
            "license": {"source_license": "unknown", "verbatim": False},
            "lifecycle": {"state": "active", "created_at": str(date.today())},
        },
        manifest,
        source,
    )


class ContributionSecurityTests(unittest.TestCase):
    def test_rejects_nonexistent_or_tampered_source_binding_as_validation_error(self) -> None:
        candidate, manifest, _ = claim()
        with self.assertRaises(ValidationError):
            ClaimValidator(
                fetch=lambda url: (
                    manifest
                    if url.endswith("package.json")
                    else (_ for _ in ()).throw(FileNotFoundError())
                )
            ).validate(candidate)

    def test_rejects_wrong_manifest_package_version_and_verbatim_unknown_license(self) -> None:
        candidate, manifest, source = claim()
        candidate["package"]["version"] = "1.3.1"
        candidate["license"]["verbatim"] = True
        with self.assertRaises(ValidationError):
            ClaimValidator(
                fetch=lambda url: manifest if url.endswith("package.json") else source
            ).validate(candidate)

    def test_rejects_unsafe_package_manifest_path(self) -> None:
        candidate, manifest, source = claim()
        candidate["evidence"][0]["package_manifest"]["path"] = "../package.json"
        with self.assertRaises(ValidationError):
            ClaimValidator(
                fetch=lambda url: manifest if url.endswith("package.json") else source
            ).validate(candidate)

    def test_allows_only_one_added_claim_data_path(self) -> None:
        self.assertEqual(
            validate_contribution_paths(
                [("A", "knowledge/claims/33333333-3333-4333-8333-333333333333.json")]
            ),
            "knowledge/claims/33333333-3333-4333-8333-333333333333.json",
        )
        with self.assertRaises(ValidationError):
            validate_contribution_paths([("A", ".github/workflows/validate.yml")])


if __name__ == "__main__":
    unittest.main()

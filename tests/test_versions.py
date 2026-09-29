import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from oakn.client import KnowledgeClient
from oakn.index import ClaimIndex, IndexError, build_index
from oakn.validation import ClaimValidator, ValidationError
from oakn.versions import applies_to, parse_affected, split_purl

TEXT4SHELL = "07e1c244-2289-4d06-8846-0fc22d828ad2"
OTHER = "11111111-1111-4111-8111-111111111111"


def write_claims(directory: Path) -> None:
    for identifier, purl, version, affected, summary in [
        (
            TEXT4SHELL,
            "pkg:maven/org.apache.commons/commons-text@1.10.0",
            "1.10.0",
            "vers:maven/>=1.5|<1.10.0",
            "StringSubstitutor script interpolation enables remote code execution",
        ),
        (
            OTHER,
            "pkg:maven/org.apache.commons/commons-text@1.12.0",
            "1.12.0",
            None,
            "WordUtils is deprecated in favor of commons-text CaseUtils",
        ),
    ]:
        package = {"purl": purl, "version": version}
        if affected:
            package["affected"] = affected
        (directory / f"{identifier}.json").write_text(
            json.dumps(
                {
                    "id": identifier,
                    "package": package,
                    "summary": summary,
                    "verification": {"source_binding": "verified"},
                }
            )
        )


class VersionHelperTests(unittest.TestCase):
    def test_split_purl_separates_type_base_and_optional_version(self) -> None:
        self.assertEqual(
            split_purl("pkg:maven/org.apache.commons/commons-text@1.10.0?type=jar"),
            (
                "maven",
                "pkg:maven/org.apache.commons/commons-text?type=jar",
                "1.10.0",
            ),
        )
        self.assertEqual(split_purl("pkg:npm/p-limit"), ("npm", "pkg:npm/p-limit", None))
        self.assertEqual(
            split_purl("pkg:npm/p-limit@4.0.0#dist"),
            ("npm", "pkg:npm/p-limit#dist", "4.0.0"),
        )
        with self.assertRaises(ValueError):
            split_purl("p-limit@4.0.0")

    def test_parse_affected_requires_the_purl_scheme(self) -> None:
        self.assertEqual(parse_affected("npm", "vers:npm/<1.2.6").scheme, "npm")
        with self.assertRaises(ValueError):
            parse_affected("pypi", "vers:npm/<1.2.6")

    def test_applies_to_uses_each_ecosystem_ordering(self) -> None:
        text4shell = "vers:maven/>=1.5|<1.10.0"
        self.assertTrue(applies_to("maven", "1.10.0", text4shell, "1.9"))
        self.assertTrue(applies_to("maven", "1.10.0", text4shell, "1.10.0"))
        self.assertFalse(applies_to("maven", "1.10.0", text4shell, "1.4"))
        self.assertTrue(applies_to("golang", "v4.5.2", "vers:golang/<v4.5.2", "v4.5.1"))
        self.assertTrue(applies_to("pypi", "44.0.1", "vers:pypi/<44.0.1", "44.0.1rc1"))
        self.assertFalse(applies_to("npm", "1.2.6", None, "1.2.5"))

    def test_applies_to_is_false_for_an_unparseable_version_or_range(self) -> None:
        self.assertFalse(applies_to("npm", "1.2.6", "vers:npm/<1.2.6", "banana"))
        self.assertFalse(applies_to("npm", "1.2.6", "vers:npm/<<1", "1.0.0"))


class RangeRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        root = Path(self._directory.name)
        claims = root / "claims"
        claims.mkdir()
        write_claims(claims)
        self.index_path = root / "index.sqlite"
        build_index(claims, self.index_path)

    def tearDown(self) -> None:
        self._directory.cleanup()

    def test_vulnerable_version_finds_the_claim_recorded_against_the_fix(self) -> None:
        results = ClaimIndex(self.index_path).search(
            "script interpolation", "pkg:maven/org.apache.commons/commons-text@1.9", "1.9"
        )

        self.assertEqual([result["claim_id"] for result in results], [TEXT4SHELL])
        self.assertTrue(results[0]["applies_to_version"])
        self.assertEqual(results[0]["affected"], "vers:maven/>=1.5|<1.10.0")

    def test_bare_purl_matches_and_a_disagreeing_suffix_does_not(self) -> None:
        index = ClaimIndex(self.index_path)

        bare = index.search("script", "pkg:maven/org.apache.commons/commons-text", "1.9")
        disagreeing = index.search(
            "script", "pkg:maven/org.apache.commons/commons-text@1.10.0", "1.9"
        )

        self.assertEqual([result["claim_id"] for result in bare], [TEXT4SHELL])
        self.assertEqual(disagreeing, [])

    def test_qualifiers_and_subpaths_do_not_match_another_package_identity(self) -> None:
        index = ClaimIndex(self.index_path)

        qualified = index.search(
            "script",
            "pkg:maven/org.apache.commons/commons-text@1.9?classifier=sources",
            "1.9",
        )
        subpath = index.search(
            "script",
            "pkg:maven/org.apache.commons/commons-text@1.9#nested",
            "1.9",
        )

        self.assertEqual(qualified, [])
        self.assertEqual(subpath, [])

    def test_version_outside_every_range_misses_with_other_version_hints(self) -> None:
        client = KnowledgeClient(self.index_path)

        response = client.search("script", "pkg:maven/org.apache.commons/commons-text@1.4", "1.4")

        self.assertEqual(response["status"], "true_miss")
        self.assertEqual(
            {candidate["claim_id"] for candidate in response["package_candidates"]},
            {TEXT4SHELL, OTHER},
        )
        self.assertFalse(
            any(candidate["applies_to_version"] for candidate in response["package_candidates"])
        )
        self.assertEqual(
            response["checked"],
            ["version_and_range", "query_variants", "package_only", "other_versions"],
        )

    def test_package_candidates_list_applying_claims_first(self) -> None:
        candidates = ClaimIndex(self.index_path).package_claims(
            "pkg:maven/org.apache.commons/commons-text", "1.12.0"
        )

        self.assertEqual(
            [(c["claim_id"], c["applies_to_version"]) for c in candidates],
            [(OTHER, True), (TEXT4SHELL, False)],
        )

    def test_hit_records_estimated_retrieval_tokens(self) -> None:
        client = KnowledgeClient(self.index_path)

        hit = client.search("script", "pkg:maven/org.apache.commons/commons-text@1.9", "1.9")

        expected = -(-len(json.dumps(hit["results"], sort_keys=True)) // 4)
        self.assertEqual(hit["metrics"]["retrieval_tokens"], expected)
        self.assertNotIn("estimated_research_tokens_avoided", client.metrics())

    def test_index_without_range_columns_asks_for_a_sync(self) -> None:
        legacy = Path(self._directory.name) / "legacy.sqlite"
        connection = sqlite3.connect(legacy)
        connection.executescript(
            """
            CREATE TABLE claims (id TEXT, purl TEXT, version TEXT, summary TEXT,
                                 evidence_state TEXT, claim_json TEXT);
            CREATE VIRTUAL TABLE claims_fts USING fts5(id UNINDEXED, summary);
            """
        )
        connection.close()

        with self.assertRaisesRegex(IndexError, "sync it again"):
            ClaimIndex(legacy).search("script", "pkg:npm/p-limit", "4.0.0")


class AffectedValidationTests(unittest.TestCase):
    manifest = b'{"name":"minimist","version":"1.2.6"}'
    evidence = b"documented behavior"

    def claim(self, **package_fields: object) -> dict:
        return {
            "schema_version": 1,
            "id": "8c9a17e3-8173-4863-9539-e7aa9fa7467c",
            "package": {"purl": "pkg:npm/minimist@1.2.6", "version": "1.2.6", **package_fields},
            "claim_type": "DOCUMENTED_BUG",
            "summary": "minimist before 1.2.6 allows prototype pollution through constructor keys.",
            "conditions": ["This is a fix-version claim."],
            "evidence": [
                {
                    "kind": "git",
                    "repository": "https://github.com/minimistjs/minimist",
                    "commit_sha": "a" * 40,
                    "path": "CHANGELOG.md",
                    "content_sha256": hashlib.sha256(self.evidence).hexdigest(),
                    "package_manifest": {
                        "path": "package.json",
                        "content_sha256": hashlib.sha256(self.manifest).hexdigest(),
                    },
                }
            ],
            "provenance": {
                "source_url": "https://github.com/advisories/GHSA-xvch-5gv4-984h",
                "retrieved_at": str(date.today()),
                "source_authority": "official",
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
        }

    def validate(self, claim: dict) -> None:
        ClaimValidator(
            fetch=lambda url: self.manifest if url.endswith("package.json") else self.evidence
        ).validate(copy.deepcopy(claim))

    def test_accepts_a_claim_with_or_without_a_matching_vers_range(self) -> None:
        self.validate(self.claim())
        self.validate(self.claim(affected="vers:npm/<1.2.6"))

    def test_rejects_a_bad_range_a_foreign_scheme_and_unknown_package_fields(self) -> None:
        for fields, message in [
            ({"affected": "vers:npm/<<1"}, "not a valid VERS range"),
            ({"affected": "vers:pypi/<1.2.6"}, "does not match purl type"),
            ({"affected": 126}, "must be a VERS string"),
            ({"affected": None}, "must be a VERS string"),
            ({"affected": "vers:npm/<" + "1" * 200}, "must be a VERS string"),
            ({"ranges": []}, "only purl, version and affected"),
        ]:
            with self.subTest(fields=fields), self.assertRaisesRegex(ValidationError, message):
                self.validate(self.claim(**fields))


if __name__ == "__main__":
    unittest.main()

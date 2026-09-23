import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from oakn.index import ClaimIndex, IndexError, build_index


class IndexRetrievalTests(unittest.TestCase):
    def test_search_filters_exact_package_version_before_bm25(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            claims = root / "knowledge" / "claims"
            claims.mkdir(parents=True)
            for identifier, version, summary in [
                (
                    "11111111-1111-4111-8111-111111111111",
                    "1.3.0",
                    "left-pad pads text to a requested width",
                ),
                (
                    "22222222-2222-4222-8222-222222222222",
                    "1.3.1",
                    "left-pad has unrelated migration behavior",
                ),
            ]:
                (claims / f"{identifier}.json").write_text(
                    json.dumps(
                        {
                            "id": identifier,
                            "package": {"purl": f"pkg:npm/left-pad@{version}", "version": version},
                            "summary": summary,
                            "verification": {"source_binding": "verified"},
                        }
                    )
                )
            index_path = root / "index.sqlite"
            build_index(claims, index_path)

            results = ClaimIndex(index_path).search("pads width", "pkg:npm/left-pad@1.3.0", "1.3.0")

        self.assertEqual(
            [result["claim_id"] for result in results], ["11111111-1111-4111-8111-111111111111"]
        )
        self.assertEqual(results[0]["untrusted_reference_data"], True)

    def test_count_rejects_sqlite_without_oakn_claim_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index_path = Path(directory) / "not-oakn.sqlite"
            connection = sqlite3.connect(index_path)
            connection.execute("CREATE TABLE unrelated (value TEXT)")
            connection.commit()
            connection.close()

            with self.assertRaises(IndexError):
                ClaimIndex(index_path).count()


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from oakn.client import KnowledgeClient
from oakn.index import build_index


class MetricsTests(unittest.TestCase):
    def test_summarizes_local_hit_miss_and_index_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            claims = root / "knowledge" / "claims"
            claims.mkdir(parents=True)
            (claims / "11111111-1111-4111-8111-111111111111.json").write_text(
                json.dumps(
                    {
                        "id": "11111111-1111-4111-8111-111111111111",
                        "package": {"purl": "pkg:npm/left-pad@1.3.0", "version": "1.3.0"},
                        "summary": "left-pad pads text to width",
                        "verification": {"source_binding": "verified"},
                    }
                )
            )
            index = root / "index.sqlite"
            build_index(claims, index)
            client = KnowledgeClient(index)

            client.search("pads text", "pkg:npm/left-pad@1.3.0", "1.3.0")
            client.search("unrelated", "pkg:npm/other@1.0.0", "1.0.0")
            metrics = client.metrics()

        self.assertEqual(metrics["claim_count"], 1)
        self.assertEqual(metrics["search_count"], 2)
        self.assertEqual(metrics["knowledge_hits"], 1)
        self.assertEqual(metrics["true_misses"], 1)
        self.assertEqual(metrics["knowledge_hit_rate"], 0.5)
        self.assertEqual(metrics["true_miss_rate"], 0.5)
        self.assertIsNone(metrics["retrieval_precision"])
        self.assertEqual(metrics["retrieval_precision_feedback_count"], 0)
        self.assertGreater(metrics["index_size_bytes"], 0)

    def test_outcome_feedback_calculates_precision_from_accepted_and_rejected_claims(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            claims = root / "knowledge" / "claims"
            claims.mkdir(parents=True)
            (claims / "22222222-2222-4222-8222-222222222222.json").write_text(
                json.dumps(
                    {
                        "id": "22222222-2222-4222-8222-222222222222",
                        "package": {"purl": "pkg:npm/left-pad@1.3.0", "version": "1.3.0"},
                        "summary": "left-pad pads text to width",
                        "verification": {"source_binding": "verified"},
                    }
                )
            )
            index = root / "index.sqlite"
            build_index(claims, index)
            client = KnowledgeClient(index)

            client.record_outcome("22222222-2222-4222-8222-222222222222", accepted=True)
            client.record_outcome("22222222-2222-4222-8222-222222222222", accepted=False)
            metrics = client.metrics()

        self.assertEqual(metrics["accepted_outcome_count"], 1)
        self.assertEqual(metrics["rejected_outcome_count"], 1)
        self.assertEqual(metrics["retrieval_precision_feedback_count"], 2)
        self.assertEqual(metrics["retrieval_precision"], 0.5)


if __name__ == "__main__":
    unittest.main()

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from oakn.cli import main
from oakn.index import build_index


class CliTests(unittest.TestCase):
    def test_record_outcome_writes_local_feedback_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            claims = root / "knowledge" / "claims"
            claims.mkdir(parents=True)
            claim_id = "33333333-3333-4333-8333-333333333333"
            (claims / f"{claim_id}.json").write_text(
                json.dumps(
                    {
                        "id": claim_id,
                        "package": {"purl": "pkg:npm/left-pad@1.3.0", "version": "1.3.0"},
                        "summary": "left-pad pads text to width",
                        "verification": {"source_binding": "verified"},
                    }
                )
            )
            index = root / "index.sqlite"
            build_index(claims, index)
            output = io.StringIO()

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "oakn",
                        "record-outcome",
                        claim_id,
                        "--index",
                        str(index),
                        "--accepted",
                    ],
                ),
                contextlib.redirect_stdout(output),
            ):
                main()

        metrics = json.loads(output.getvalue())
        self.assertEqual(metrics["accepted_outcome_count"], 1)
        self.assertEqual(metrics["retrieval_precision"], 1.0)

    def test_record_outcome_rejects_unknown_claim_without_creating_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            claims = root / "knowledge" / "claims"
            claims.mkdir(parents=True)
            index = root / "index.sqlite"
            build_index(claims, index)
            error = io.StringIO()

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "oakn",
                        "record-outcome",
                        "33333333-3333-4333-8333-333333333333",
                        "--index",
                        str(index),
                        "--accepted",
                    ],
                ),
                contextlib.redirect_stderr(error),
                self.assertRaises(SystemExit) as raised,
            ):
                main()

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("outcome feedback requires an indexed claim", error.getvalue())
        self.assertNotIn("Traceback", error.getvalue())
        self.assertFalse(index.with_suffix(".metrics.json").exists())


if __name__ == "__main__":
    unittest.main()

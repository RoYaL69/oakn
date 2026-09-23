import unittest
from types import SimpleNamespace

from oakn.demo import DemoError, parse_tool_payload


class DemoTests(unittest.TestCase):
    def test_parses_untrusted_search_hit_with_expected_claim(self) -> None:
        result = SimpleNamespace(
            content=[
                SimpleNamespace(
                    text=(
                        '{"status":"hit","results":[{"claim_id":"claim-1"}],'
                        '"untrusted_reference_data":true}'
                    )
                )
            ]
        )

        payload = parse_tool_payload(result, expected_claim_id="claim-1")

        self.assertEqual(payload["status"], "hit")
        self.assertTrue(payload["untrusted_reference_data"])

    def test_rejects_a_result_that_is_not_untrusted_reference_data(self) -> None:
        result = SimpleNamespace(content=[SimpleNamespace(text='{"status":"hit","results":[]}')])

        with self.assertRaises(DemoError):
            parse_tool_payload(result)

    def test_rejects_a_missing_expected_claim(self) -> None:
        result = SimpleNamespace(
            content=[
                SimpleNamespace(
                    text='{"status":"hit","results":[],"untrusted_reference_data":true}'
                )
            ]
        )

        with self.assertRaises(DemoError):
            parse_tool_payload(result, expected_claim_id="claim-1")


if __name__ == "__main__":
    unittest.main()

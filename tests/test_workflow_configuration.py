import unittest
from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "validate-contribution.yml"


class WorkflowConfigurationTests(unittest.TestCase):
    def test_validation_workflow_is_pr_only_and_keeps_required_check_name(self) -> None:
        workflow = WORKFLOW.read_text()

        self.assertIn("name: Validate pull request boundary", workflow)
        self.assertIn("  pull_request_target:", workflow)
        self.assertIn("  pull_request_review:", workflow)
        self.assertNotIn("\n  push:", workflow)
        self.assertNotIn("ignore-push:", workflow)

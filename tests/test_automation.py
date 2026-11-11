"""Pipeline regression tests. No live Trello/GitHub calls or model invocations."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation import runner

ROOT = Path(__file__).resolve().parents[1]
CARD = "ari:cloud:trello::card/workspace/60cd46fcc5cbc205d26e948c/6af424a8d0a3efc91141c4a9"
HEAD = "a" * 40
BASE = "b" * 40


def result(outcome="complete", checks=None):
    return {"outcome": outcome, "summary": "Проверено", "findings": ["Исправить ошибку"] if outcome == "rework" else [], "checks": checks or []}


class Agent:
    def __init__(self, config):
        self.config = config
        self.card = {"id": CARD, "url": "https://trello.com/c/DL9DuUF6", "name": "Task", "description": "Criteria", "comments": "", "list_id": config["lists"]["testing"]}
        self.results = []
        self.calls = []

    def trello(self, operation, **args):
        self.calls.append((operation, args))
        if operation == "move":
            self.card["list_id"] = args["destination"]
        if operation == "select" and self.card["list_id"] != self.config["lists"]["ready"]:
            return {**self.card, "id": ""}
        return deepcopy(self.card)

    def worker(self, role, task):
        self.calls.append((role, {}))
        value = self.results.pop(0)
        if isinstance(value, Exception):
            raise value
        return deepcopy(value)


class GitHub:
    def __init__(self):
        self.head, self.base, self.ci_status = HEAD, BASE, "pass"
        self.comments = []

    def inspect(self, task):
        return {"head": {"sha": self.head}, "base": {"sha": self.base}}

    def ci(self, sha):
        return self.ci_status

    def comment(self, number, text, marker):
        self.comments.append((number, text, marker))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.config = json.loads((ROOT / "automation/config.json").read_text())
        self.agent, self.github = Agent(self.config), GitHub()
        self.pipeline = runner.Pipeline(self.config, self.state, self.agent, self.github)
        self.task = {**self.agent.card, "stage": "tester", "attempts": 1, "branch": "agents/trello-6af424a8d0a3efc91141c4a9", "worktree": str(self.state / "worktree"), "pr_number": 1, "head_sha": HEAD, "base_sha": BASE, "visual_change": False}
        self.pipeline.data["active"] = self.task
        self.patches = [patch.object(runner, "git", return_value=HEAD), patch.object(runner, "changed_paths", return_value=[]), patch.object(self.pipeline, "run_checks")]
        self.checks = None
        for item in self.patches:
            mock = item.start()
            self.addCleanup(item.stop)
            self.checks = mock

    def test_tester_pass_keeps_card_in_testing_and_binds_qa(self):
        self.agent.results = [result()]
        self.assertEqual(self.pipeline.tick(), "reviewer")
        self.assertEqual(self.agent.card["list_id"], self.config["lists"]["testing"])
        self.assertEqual(self.task["qa"]["head_sha"], HEAD)
        self.assertEqual(self.task["qa"]["base_sha"], BASE)

    def test_reviewer_pass_moves_done_without_merge(self):
        self.task.update(stage="reviewer", qa={"head_sha": HEAD, "base_sha": BASE})
        self.agent.results = [result()]
        self.assertEqual(self.pipeline.tick(), "done")
        self.assertEqual(self.agent.card["list_id"], self.config["lists"]["done"])
        completed = list((self.state / "completed").glob("*.json"))
        self.assertEqual(len(completed), 1)
        self.assertFalse(json.loads(completed[0].read_text())["merged_by_agent"])

    def test_failed_test_returns_in_progress(self):
        self.agent.results = [result("rework")]
        self.assertEqual(self.pipeline.tick(), "developer")
        self.assertEqual(self.agent.card["list_id"], self.config["lists"]["in_progress"])
        self.assertIn("Исправить", self.task["feedback"])
        self.assertIsNone(self.task["qa"])

    def test_reviewer_rework_returns_to_developer(self):
        self.task.update(stage="reviewer", qa={"head_sha": HEAD, "base_sha": BASE})
        self.agent.results = [result("rework")]
        self.assertEqual(self.pipeline.tick(), "developer")
        self.assertEqual(self.agent.card["list_id"], self.config["lists"]["in_progress"])

    def test_running_ci_does_not_launch_worker(self):
        self.github.ci_status = "pending"
        self.assertEqual(self.pipeline.tick(), "tester")
        self.assertFalse(any(role in runner.ROLES for role, _ in self.agent.calls))
        self.assertIsNone(self.pipeline.data["pending"])

    def test_failed_ci_returns_to_developer(self):
        self.github.ci_status = "fail"
        self.assertEqual(self.pipeline.tick(), "developer")
        self.assertEqual(self.agent.card["list_id"], self.config["lists"]["in_progress"])

    def test_failed_local_tests_return_to_developer(self):
        self.checks.side_effect = RuntimeError("project_checks_failed")
        self.assertEqual(self.pipeline.tick(), "developer")
        self.assertEqual(self.agent.card["list_id"], self.config["lists"]["in_progress"])

    def test_timeout_latches_and_never_automatically_retries(self):
        self.agent.results = [RuntimeError("process_timeout_or_interruption")]
        self.assertEqual(self.pipeline.tick(), "halted")
        calls = len(self.agent.calls)
        self.assertIsNotNone(self.pipeline.data["pending"])
        self.assertEqual(self.pipeline.tick(), "halted")
        self.assertEqual(len(self.agent.calls), calls)
        persisted = runner.read_json(self.pipeline.path)
        self.assertIsNotNone(persisted["halted"])

    def test_head_change_invalidates_qa(self):
        self.github.head = "c" * 40
        self.assertEqual(self.pipeline.tick(), "halted")
        self.assertEqual(self.agent.card["list_id"], self.config["lists"]["testing"])

    def test_base_change_invalidates_qa(self):
        self.github.base = "c" * 40
        self.assertEqual(self.pipeline.tick(), "halted")

    def test_reviewer_cannot_skip_qa(self):
        self.task["stage"] = "reviewer"
        self.agent.results = [result()]
        self.assertEqual(self.pipeline.tick(), "halted")
        self.assertFalse(any(role == "reviewer" for role, _ in self.agent.calls))

    def test_visual_pass_without_browser_evidence_is_rejected(self):
        self.task["visual_change"] = True
        self.agent.results = [result()]
        self.assertEqual(self.pipeline.tick(), "halted")
        self.assertEqual(self.agent.card["list_id"], self.config["lists"]["testing"])

    def test_visual_pass_requires_all_three_widths(self):
        self.task["visual_change"] = True
        checks = [{"name": f"browser-{width}", "status": "pass", "evidence": "Проверены layout и клавиатура"} for width in (360, 768, 1440)]
        self.agent.results = [result(checks=checks)]
        self.assertEqual(self.pipeline.tick(), "reviewer")

    def test_human_move_is_respected(self):
        self.agent.card["list_id"] = self.config["lists"]["backlog"]
        self.assertEqual(self.pipeline.tick(), "halted")
        self.assertFalse(any(operation == "move" for operation, _ in self.agent.calls))

    def test_idle_queue_does_not_touch_backlog(self):
        self.pipeline.data["active"] = None
        self.assertEqual(self.pipeline.tick(), "idle")
        self.assertEqual([operation for operation, _ in self.agent.calls], ["select"])

    def test_code_change_by_tester_cannot_advance(self):
        self.agent.results = [result()]
        with patch.object(runner, "changed_paths", side_effect=[[], ["src/app.js"]]):
            self.assertEqual(self.pipeline.tick(), "halted")
        self.assertEqual(self.agent.card["list_id"], self.config["lists"]["testing"])


class PolicyTests(unittest.TestCase):
    def test_protected_infrastructure_cannot_be_published(self):
        for path in ("automation/runner.py", "AGENTS.md", ".github/workflows/ci.yml", ".codex/config.toml", "tests/test_automation.py"):
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                runner.assert_allowed_changes([path])
        runner.assert_allowed_changes(["src/app.js", "docs/content.md"])

    def test_card_ids_cannot_escape_worktree_directory(self):
        with self.assertRaises(ValueError):
            runner.card_key("../../main")

    def test_worker_environment_drops_service_credentials(self):
        with patch.dict(runner.os.environ, {"GH_TOKEN": "fake", "GITHUB_TOKEN": "fake", "CODEX_API_KEY": "fake", "TRELLO_TOKEN": "fake"}):
            environment = runner.clean_environment()
        self.assertFalse(set(environment) & {"GH_TOKEN", "GITHUB_TOKEN", "CODEX_API_KEY", "TRELLO_TOKEN"})

    def test_rework_requires_actionable_findings(self):
        report = result("rework")
        report["findings"] = []
        with self.assertRaises(ValueError):
            runner.validate_transition("tester", report, {})

    def test_malformed_role_report_is_rejected(self):
        with self.assertRaises(ValueError):
            runner.validate_schema({"outcome": "complete"}, runner.RESULT_SCHEMA)

    def test_cron_update_preserves_other_jobs_and_is_idempotent(self):
        spec = importlib.util.spec_from_file_location("install_cron", ROOT / "automation/install-cron.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        other = "0 8 * * * /some/unrelated/job\n"
        block = module.BEGIN + "\n*/5 * * * * command\n" + module.END + "\n"
        combined = module.replace_block(other, block)
        self.assertTrue(combined.startswith(other))
        self.assertEqual(module.replace_block(combined, block), combined)
        self.assertEqual(module.replace_block(combined, ""), other)

    def test_incomplete_cron_marker_is_not_overwritten(self):
        spec = importlib.util.spec_from_file_location("install_cron", ROOT / "automation/install-cron.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with self.assertRaises(ValueError):
            module.replace_block(module.BEGIN + "\n", "")


if __name__ == "__main__":
    unittest.main()

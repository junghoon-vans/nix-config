import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parent
PLUGIN_NAME = "hermes_omp_worker_approval"
SPEC = importlib.util.spec_from_file_location(
    PLUGIN_NAME,
    ROOT / "omp-worker/__init__.py",
    submodule_search_locations=[str(ROOT / "omp-worker")],
)
PLUGIN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PLUGIN
SPEC.loader.exec_module(PLUGIN)


class NativeApprovalGateSubstitute:
    """Small native-gate model: once, session, and permanent grants have distinct lifetimes."""

    def __init__(self, harness, choices=(), permanent_grants=None):
        self.harness = harness
        self.choices = list(choices)
        self.permanent_grants = permanent_grants if permanent_grants is not None else set()
        self.session_grants = set()
        self.prompts = []

    def request(self, tool_name, reason, *, rule_key):
        if len(self.harness.messages) <= self.harness.messages_before_call:
            raise AssertionError("the complete action must be delivered before native approval")

        session_grant = (self.harness.context["session_key"], rule_key)
        if rule_key in self.permanent_grants or session_grant in self.session_grants:
            return {"approved": True}

        self.prompts.append((rule_key, reason))
        choice = self.choices.pop(0) if self.choices else "deny"
        if choice == "session":
            self.session_grants.add(session_grant)
        elif choice == "always":
            self.permanent_grants.add(rule_key)
        return {"approved": choice in ("once", "session", "always")}


class ApprovalHarness:
    def __init__(self, choices=(), permanent_grants=None):
        self.context = {
            "HERMES_SESSION_PLATFORM": "slack",
            "HERMES_SESSION_CHAT_ID": "C-workspace",
            "HERMES_SESSION_THREAD_ID": "thread-1",
            "HERMES_SESSION_SCOPE_ID": "workspace-1",
            "HERMES_SESSION_USER_ID": "user-1",
            "session_key": "hermes-session-1",
        }
        self.bypass = False
        self.interrupted = False
        self.fail_delivery = False
        self.interrupt_on_delivery = False
        self.interrupt_after_decision = False
        self.messages = []
        self.messages_before_call = 0
        self.gate = NativeApprovalGateSubstitute(self, choices, permanent_grants)

    def run(self, params):
        self.messages_before_call = len(self.messages)
        harness = self

        class SlackClient:
            def __init__(self, **_):
                pass

            def chat_postMessage(self, **message):
                if harness.fail_delivery:
                    raise OSError("Slack delivery failed")
                harness.messages.append(message)
                if harness.interrupt_on_delivery:
                    harness.interrupted = True

        gateway = types.ModuleType("gateway")
        gateway.__path__ = []
        session_context = types.ModuleType("gateway.session_context")
        session_context.get_session_env = lambda key: harness.context.get(key)
        tools = types.ModuleType("tools")
        tools.__path__ = []
        approval = types.ModuleType("tools.approval")
        approval.get_current_session_key = lambda default="": harness.context["session_key"]
        approval.is_approval_bypass_active_for_session = lambda _session: harness.bypass

        def request_tool_approval(tool_name, reason, *, rule_key):
            decision = harness.gate.request(tool_name, reason, rule_key=rule_key)
            if harness.interrupt_after_decision:
                harness.interrupted = True
            return decision

        approval.request_tool_approval = request_tool_approval
        interrupt = types.ModuleType("tools.interrupt")
        interrupt.is_interrupted = lambda: harness.interrupted
        slack_sdk = types.ModuleType("slack_sdk")
        slack_sdk.WebClient = SlackClient
        modules = {
            "gateway": gateway,
            "gateway.session_context": session_context,
            "tools": tools,
            "tools.approval": approval,
            "tools.interrupt": interrupt,
            "slack_sdk": slack_sdk,
        }
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {"SLACK_BOT_TOKEN": "test-token"}):
            return PLUGIN._approve(params)


class ApprovalBehavior(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self.repository_other = self.root / "other-repository"
        self.repository_other.mkdir()
        self.worktree_a = self.root / "worktree-a"
        self.worktree_a.mkdir()
        (self.worktree_a / "src").mkdir()
        self.worktree_b = self.root / "worktree-b"
        self.worktree_b.mkdir()
        (self.worktree_b / "src").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def action(self, *, repository=None, worktree=None, raw_input=None, kind="edit", task="task-a", head="head-a", call_id="call-a"):
        repository = repository or self.repository
        worktree = worktree or self.worktree_a
        if raw_input is None:
            raw_input = {
                "path": str(worktree / "src" / "file.py"),
                "cwd": str(worktree),
                "content": "unchanged contents\n",
            }
        return {
            "sessionId": "acp-session",
            "toolCall": {
                "toolCallId": call_id,
                "kind": kind,
                "title": "Write file",
                "status": "pending",
                "rawInput": raw_input,
                "hermes_worker": {
                    "task_id": task,
                    "repository": str(repository),
                    "worktree": str(worktree),
                    "head": head,
                },
            },
        }

    def test_session_grant_reuses_exact_action_across_worktrees_not_transport_metadata(self):
        harness = ApprovalHarness(["session"])
        original = self.action()
        self.assertTrue(harness.run(original))

        repeated = self.action(
            worktree=self.worktree_b,
            task="different-task",
            head="different-head",
            call_id="different-call",
        )
        repeated["toolCall"]["title"] = "Different transport title"
        repeated["toolCall"]["status"] = "in_progress"
        self.assertTrue(harness.run(repeated))

        self.assertEqual(len(harness.gate.prompts), 1)
        self.assertEqual(len(harness.messages), 2)

    def test_user_workspace_repository_kind_and_input_changes_need_new_prompts(self):
        harness = ApprovalHarness(["session"] + ["once"] * 5)
        original = self.action()
        self.assertTrue(harness.run(original))

        cases = [
            ("user", lambda: harness.context.__setitem__("HERMES_SESSION_USER_ID", "user-2"), original),
            ("workspace", lambda: harness.context.__setitem__("HERMES_SESSION_SCOPE_ID", "workspace-2"), original),
            ("repository", lambda: None, self.action(repository=self.repository_other)),
            ("kind", lambda: None, self.action(kind="execute")),
            ("input", lambda: None, self.action(raw_input={
                "path": str(self.worktree_a / "src" / "file.py"),
                "cwd": str(self.worktree_a),
                "content": "different contents\n",
            })),
        ]
        for label, alter_context, params in cases:
            with self.subTest(label=label):
                alter_context()
                self.assertTrue(harness.run(params))
                if label == "user":
                    harness.context["HERMES_SESSION_USER_ID"] = "user-1"
                elif label == "workspace":
                    harness.context["HERMES_SESSION_SCOPE_ID"] = "workspace-1"

        self.assertEqual(len(harness.gate.prompts), 6)

    def test_only_explicit_paths_are_normalized_not_content_commands_patches_or_text(self):
        harness = ApprovalHarness(["session"] + ["once"] * 4)
        base_input = {
            "path": str(self.worktree_a / "src" / "file.py"),
            "cwd": str(self.worktree_a),
            "content": "same content",
            "command": "python script.py --path /tmp/original",
            "patch": "--- a/file.py\n+++ b/file.py\n",
            "note": "text /tmp/original",
        }
        self.assertTrue(harness.run(self.action(raw_input=base_input)))

        other_worktree_input = {
            **base_input,
            "path": str(self.worktree_b / "src" / "file.py"),
            "cwd": str(self.worktree_b),
        }
        self.assertTrue(harness.run(self.action(worktree=self.worktree_b, raw_input=other_worktree_input)))
        self.assertEqual(len(harness.gate.prompts), 1)

        for field, changed in (
            ("content", "same content\n"),
            ("command", "python script.py --path /tmp/changed"),
            ("patch", "--- a/file.py\n+++ b/file.py\n+changed\n"),
            ("note", "text /tmp/changed"),
        ):
            with self.subTest(field=field):
                changed_input = {**base_input, field: changed}
                self.assertTrue(harness.run(self.action(raw_input=changed_input)))

        self.assertEqual(len(harness.gate.prompts), 5)

    def test_session_and_always_choices_keep_native_lifetimes(self):
        session = ApprovalHarness(["session", "once", "once"])
        params = self.action()
        self.assertTrue(session.run(params))
        self.assertTrue(session.run(params))
        self.assertEqual(len(session.gate.prompts), 1)
        session.context["session_key"] = "hermes-session-2"
        self.assertTrue(session.run(params))
        self.assertTrue(session.run(params))
        self.assertEqual(len(session.gate.prompts), 3)

        permanent = set()
        always = ApprovalHarness(["always"], permanent)
        self.assertTrue(always.run(params))
        self.assertEqual(len(always.gate.prompts), 1)
        next_process = ApprovalHarness([], permanent)
        next_process.context["session_key"] = "hermes-session-3"
        self.assertTrue(next_process.run(params))
        self.assertEqual(len(next_process.gate.prompts), 0)

    def test_path_marker_cannot_collide_with_literal_action_text(self):
        harness = ApprovalHarness(["session", "once"])
        normalized_path = self.action()
        self.assertTrue(harness.run(normalized_path))

        literal_text = self.action(raw_input={
            "path": '{"$omp:v2:path":"src/file.py"}',
            "cwd": str(self.worktree_a),
            "content": "unchanged contents\n",
        })
        self.assertTrue(harness.run(literal_text))
        self.assertEqual(len(harness.gate.prompts), 2)

    def test_missing_or_malformed_identity_and_action_fail_closed(self):
        harness = ApprovalHarness(["session"])
        malformed = self.action()
        del malformed["toolCall"]["rawInput"]
        self.assertFalse(harness.run(malformed))

        malformed = self.action()
        malformed["toolCall"]["hermes_worker"]["worktree"] = "relative/worktree"
        self.assertFalse(harness.run(malformed))

        malformed = self.action()
        malformed["toolCall"]["hermes_worker"]["repository"] = "relative/repository"
        self.assertFalse(harness.run(malformed))

        malformed = self.action()
        malformed["toolCall"]["rawInput"] = []
        self.assertFalse(harness.run(malformed))

        malformed = self.action()
        malformed["toolCall"]["rawInput"] = {}
        self.assertFalse(harness.run(malformed))

        malformed = self.action()
        del malformed["toolCall"]["kind"]
        self.assertFalse(harness.run(malformed))

        harness.context["session_key"] = ""
        self.assertFalse(harness.run(self.action()))
        harness.context["session_key"] = "hermes-session-1"

        harness.context["HERMES_SESSION_USER_ID"] = None
        self.assertFalse(harness.run(self.action()))
        self.assertEqual(harness.messages, [])
        self.assertEqual(harness.gate.prompts, [])

    def test_bypass_cancellation_and_delivery_failure_do_not_reach_gate(self):
        params = self.action()
        harness = ApprovalHarness(["session"])
        harness.bypass = True
        self.assertFalse(harness.run(params))
        self.assertEqual(harness.messages, [])

        harness.bypass = False
        harness.interrupted = True
        self.assertFalse(harness.run(params))
        self.assertEqual(harness.messages, [])

        harness.interrupted = False
        harness.fail_delivery = True
        with self.assertRaisesRegex(RuntimeError, "Cannot deliver complete OMP approval details"):
            harness.run(params)
        self.assertEqual(harness.gate.prompts, [])

    def test_interruption_during_delivery_or_native_decision_fails_closed(self):
        params = self.action()
        during_delivery = ApprovalHarness(["session"])
        during_delivery.interrupt_on_delivery = True
        self.assertFalse(during_delivery.run(params))
        self.assertEqual(during_delivery.gate.prompts, [])

        during_decision = ApprovalHarness(["session"])
        during_decision.interrupt_after_decision = True
        self.assertFalse(during_decision.run(params))
        self.assertEqual(len(during_decision.gate.prompts), 1)


if __name__ == "__main__":
    unittest.main()

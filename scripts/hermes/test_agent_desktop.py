import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


REPOSITORY = Path(__file__).resolve().parents[2]
PLUGIN_FILE = REPOSITORY / "home/.hermes/plugins/agent-desktop/__init__.py"
PNG_DATA = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/S8sAAAAASUVORK5CYII="
)
COMMANDS = {
    "status",
    "version",
    "help",
    "list-apps",
    "list-windows",
    "list-displays",
    "list-surfaces",
    "snapshot",
    "find",
    "get",
    "is",
    "screenshot",
    "click",
    "right-click",
    "double-click",
    "type",
    "set-value",
    "clear",
    "select",
    "toggle",
    "check",
    "uncheck",
    "expand",
    "collapse",
    "scroll",
    "scroll-to",
}
READ_COMMANDS = {
    "status",
    "version",
    "help",
    "list-apps",
    "list-windows",
    "list-displays",
    "list-surfaces",
    "snapshot",
    "find",
    "get",
    "is",
    "screenshot",
}
MUTATING_COMMANDS = COMMANDS - READ_COMMANDS


def load_plugin():
    spec = importlib.util.spec_from_file_location("agent_desktop_test_plugin", PLUGIN_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load desktop plugin from {PLUGIN_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakePluginContext:
    def __init__(self, command, settings=None):
        self.settings = {"command": str(command), **(settings or {})}
        self.tools = []
        self.hooks = {}

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def register_tool(self, **registration):
        self.tools.append(registration)

    def register_hook(self, name, callback):
        self.hooks.setdefault(name, []).append(callback)


class AgentDesktopPlugin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The fixture tests run outside the packaged Hermes interpreter. Keep the
        # documented helper import shape while resolving its active profile from
        # the same HERMES_HOME that Hermes supplies in production.
        constants = types.ModuleType("hermes_constants")
        constants.get_hermes_home = lambda: Path(os.environ["HERMES_HOME"])
        with patch.dict(sys.modules, {"hermes_constants": constants}):
            cls.plugin = load_plugin()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="agent-desktop-plugin-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.command = self.root / "agent-desktop-fixture"
        self.argv_log = self.root / "invocation.json"
        self.command.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['AGENT_DESKTOP_TEST_LOG']).write_text(json.dumps({\n"
            "    'argv': sys.argv[1:],\n"
            "    'agent_desktop_home': os.environ.get('AGENT_DESKTOP_HOME'),\n"
            "    'tmpdir': os.environ.get('TMPDIR'),\n"
            "}))\n"
            "if '--help' in sys.argv[1:]:\n"
            "    print('Agent Desktop fixture help')\n"
            "    raise SystemExit(0)\n"
            "response = os.environ.get('AGENT_DESKTOP_TEST_RESPONSE')\n"
            "if response is None:\n"
            "    response = json.dumps({'version': '2.5', 'ok': True, 'command': sys.argv[1], 'data': {'fixture': True}})\n"
            "sys.stdout.write(response)\n"
            "sys.stderr.write(os.environ.get('AGENT_DESKTOP_TEST_STDERR', ''))\n"
            "raise SystemExit(int(os.environ.get('AGENT_DESKTOP_TEST_EXIT', '0')))\n"
        )
        self.command.chmod(0o700)
        self.context = FakePluginContext(self.command)
        self.plugin.register(self.context)
        self.assertEqual(len(self.context.tools), 1)
        self.registration = self.context.tools[0]
        self.handler = self.registration["handler"]
        self.hook = self.context.hooks["pre_tool_call"][0]

    def invoke(self, command, args=None, **kwargs):
        payload = {"command": command}
        if args is not None:
            payload["args"] = args
        with patch.dict(
            os.environ,
            {
                "AGENT_DESKTOP_TEST_LOG": str(self.argv_log),
                "HERMES_HOME": str(self.root / ".hermes" / "profiles" / "omp-worker"),
            },
        ):
            result = self.handler(payload, **kwargs)
            return json.loads(result) if isinstance(result, str) else result

    def last_invocation(self):
        return json.loads(self.argv_log.read_text())

    def assert_rejected_without_launch(self, command, args):
        self.argv_log.unlink(missing_ok=True)
        result = self.invoke(command, args)
        self.assertFalse(result.get("ok", True), result)
        self.assertFalse(self.argv_log.exists(), f"unsafe request launched CLI: {command} {args!r}")

    def test_registers_one_fixed_model_tool_and_actual_pre_tool_hook(self):
        self.assertEqual(self.registration["name"], "agent_desktop")
        self.assertEqual(self.registration["toolset"], "agent_desktop")
        schema = self.registration["schema"]
        self.assertEqual(schema["name"], "agent_desktop")
        parameters = schema["parameters"]
        self.assertEqual(parameters["required"], ["command"])
        self.assertFalse(parameters["additionalProperties"])
        self.assertEqual(set(parameters["properties"]["command"]["enum"]), COMMANDS)
        self.assertEqual(parameters["properties"]["args"]["type"], "array")
        self.assertEqual(parameters["properties"]["args"]["items"]["type"], "string")
        self.assertEqual(parameters["properties"]["args"]["default"], [])
        self.assertEqual(set(self.context.hooks), {"pre_tool_call"})

    def test_registry_style_handler_accepts_dict_and_runtime_kwargs(self):
        result = self.invoke("status", task_id="task-1", session_id="session-1")
        self.assertEqual(result["ok"], True)
        self.assertEqual(self.last_invocation()["argv"], ["status"])

    def test_literal_shell_metacharacters_are_one_unchanged_cli_argument(self):
        ref = "@s8f3k2p9:e8"
        text = 'literal ; $(touch /tmp/should-not-exist) "quoted" `echo no`'
        result = self.invoke("type", [ref, text])
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.last_invocation()["argv"], ["type", ref, text])

    def test_safe_help_is_a_fixed_read_only_cli_request(self):
        result = self.invoke("help", ["snapshot"])
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.last_invocation()["argv"], ["snapshot", "--help"])
        self.assertIn("fixture help", str(result).lower())
        self.assertIsNone(
            self.hook(tool_name="agent_desktop", args={"command": "help", "args": ["snapshot"]})
        )

    def test_unknown_commands_and_unapproved_cli_surfaces_never_launch(self):
        for command in ("exec", "shell", "batch", "session", "trace", "permissions", "open-system-surface"):
            with self.subTest(command=command):
                self.assert_rejected_without_launch(command, [])

    def test_unsafe_options_and_arbitrary_output_paths_never_launch(self):
        requests = (
            ("status", ["--headed"]),
            ("snapshot", ["--headed"]),
            ("snapshot", ["--output", "/tmp/private.png"]),
            ("snapshot", ["--output-file=/tmp/private.png"]),
            ("screenshot", ["/tmp/private.png"]),
            ("screenshot", ["--output", "/tmp/private.png"]),
            ("screenshot", ["--output=/tmp/private.png"]),
            ("help", ["permissions"]),
            ("help", ["--headed"]),
            ("status", ["--help"]),
            ("get", ["/tmp/private.png"]),
            ("click", ["@e1"]),
        )
        for command, args in requests:
            with self.subTest(command=command, args=args):
                self.assert_rejected_without_launch(command, args)

    def test_command_error_envelope_and_retry_disposition_are_preserved(self):
        envelope = {
            "version": "2.5",
            "ok": False,
            "command": "click",
            "error": {
                "code": "STALE_REF",
                "message": "Take a fresh snapshot.",
                "disposition": {"delivery": "not_delivered", "retry": "safe"},
                "recovery": {"strategy": "fresh_snapshot"},
            },
        }
        with patch.dict(os.environ, {"AGENT_DESKTOP_TEST_RESPONSE": json.dumps(envelope), "AGENT_DESKTOP_TEST_EXIT": "1"}):
            result = self.invoke("click", ["@s8f3k2p9:e8"])
        self.assertEqual(result, envelope)
        self.assertEqual(
            result["error"]["disposition"],
            {"delivery": "not_delivered", "retry": "safe"},
        )

    def test_malformed_json_and_invalid_envelopes_are_sanitized(self):
        private_stdout = "PRIVATE-CLI-OUTPUT-" + ("x" * 96)
        for response in (private_stdout, "[]", '{"ok": "yes", "data": {}}'):
            with self.subTest(response=response[:12]):
                with patch.dict(os.environ, {"AGENT_DESKTOP_TEST_RESPONSE": response}):
                    result = self.invoke("status")
                self.assertFalse(result.get("ok", True), result)
                self.assertNotIn(private_stdout, json.dumps(result))

    def test_timeout_is_unknown_delivery_and_is_never_automatically_retried(self):
        with patch.object(
            self.plugin.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired([str(self.command), "click"], 0.01),
        ) as run:
            result = self.invoke("click", ["@s8f3k2p9:e8"])
        run.assert_called_once()
        disposition = result["error"]["disposition"]
        self.assertEqual(disposition["delivery"], "unknown")
        self.assertEqual(disposition["retry"], "unsafe")
        self.assertIn("unknown", result["error"]["message"].lower())

    def test_screenshot_base64_becomes_a_model_visible_image_not_text(self):
        envelope = {
            "version": "2.5",
            "ok": True,
            "command": "screenshot",
            "data": {"data": PNG_DATA, "format": "png", "width": 1, "height": 1, "scale_factor": 1.0},
        }
        with patch.dict(os.environ, {"AGENT_DESKTOP_TEST_RESPONSE": json.dumps(envelope)}):
            result = self.invoke("screenshot")
        url = "data:image/png;base64," + PNG_DATA
        self.assertIs(result["_multimodal"], True)
        self.assertEqual(result["content"][0]["type"], "text")
        self.assertEqual(result["content"][1], {"type": "image_url", "image_url": {"url": url}})
        self.assertEqual(result["text_summary"], result["content"][0]["text"])
        self.assertNotIn(PNG_DATA, result["text_summary"])

    def test_malformed_screenshot_images_are_not_forwarded_or_leaked_as_text(self):
        malformed = "this-is-not-valid-base64!"
        wrong_png = base64.b64encode(b"not a PNG image").decode("ascii")
        for image in (malformed, wrong_png):
            envelope = {
                "version": "2.5",
                "ok": True,
                "command": "screenshot",
                "data": {"data": image, "format": "png", "width": 1, "height": 1, "scale_factor": 1.0},
            }
            with self.subTest(image=image[:12]):
                with patch.dict(os.environ, {"AGENT_DESKTOP_TEST_RESPONSE": json.dumps(envelope)}):
                    result = self.invoke("screenshot")
                self.assertFalse(result.get("_multimodal", False))
                self.assertNotIn(image, json.dumps(result))

    def test_unsupported_screenshot_format_is_not_mislabeled_as_png(self):
        envelope = {
            "version": "2.5",
            "ok": True,
            "command": "screenshot",
            "data": {"data": PNG_DATA, "format": "jpeg", "width": 1, "height": 1, "scale_factor": 1.0},
        }
        with patch.dict(os.environ, {"AGENT_DESKTOP_TEST_RESPONSE": json.dumps(envelope)}):
            result = self.invoke("screenshot")
        self.assertFalse(result.get("_multimodal", False))
        self.assertNotIn(PNG_DATA, json.dumps(result))

    def test_action_hook_requests_approval_with_exact_json_escaped_arguments(self):
        text = 'Enter "OK"; $(echo should-not-run)\nthen continue'
        args = {"command": "type", "args": ["@s8f3k2p9:e8", text]}
        result = self.hook(tool_name="agent_desktop", args=args, task_id="task-1")
        self.assertEqual(result["action"], "approve")
        self.assertIn(json.dumps(args, ensure_ascii=False, separators=(",", ":")), result["message"])
        self.assertNotIn("\nthen continue", result["message"])

    def test_read_hook_does_not_request_approval_and_other_tools_are_untouched(self):
        self.assertIsNone(self.hook(tool_name="agent_desktop", args={"command": "snapshot", "args": []}))
        self.assertIsNone(self.hook(tool_name="terminal", args={"command": "rm -rf /"}))

    def test_actual_hermes_approval_resolver_fails_closed_for_plugin_directive(self):
        try:
            hermes_plugins = __import__("hermes_cli.plugins", fromlist=["resolve_pre_tool_block"])
            approval = __import__("tools.approval", fromlist=["request_tool_approval"])
        except ImportError:
            self.skipTest("Hermes runtime is only available in the packaged Hermes integration environment")

        args = {"command": "click", "args": ["@s8f3k2p9:e8"]}
        directive = self.hook(tool_name="agent_desktop", args=args)
        self.assertEqual(directive["action"], "approve")
        with patch.object(hermes_plugins, "invoke_hook", return_value=[directive]), patch.object(
            approval, "request_tool_approval", return_value={"approved": False, "message": "human denied"}
        ) as gate:
            blocked = hermes_plugins.resolve_pre_tool_block("agent_desktop", args)
        self.assertEqual(blocked, "human denied")
        gate.assert_called_once()

        with patch.object(hermes_plugins, "invoke_hook", return_value=[directive]), patch.object(
            approval, "request_tool_approval", side_effect=RuntimeError("approval transport unavailable")
        ):
            blocked = hermes_plugins.resolve_pre_tool_block("agent_desktop", args)
        self.assertIn("approval gate failed", blocked)

    def test_active_hermes_profile_controls_agent_desktop_state_without_changing_tmpdir(self):
        private_tmp = self.root / "private-short-tmp"
        private_tmp.mkdir(mode=0o700)
        for profile in ("omp-worker", "default"):
            profile_home = self.root / ".hermes" / "profiles" / profile
            with self.subTest(profile=profile), patch.dict(
                os.environ,
                {
                    "HERMES_HOME": str(profile_home),
                    "AGENT_DESKTOP_TEST_LOG": str(self.argv_log),
                    "AGENT_DESKTOP_HOME": str(self.root / "wrong-global-agent-desktop-home"),
                    "TMPDIR": str(private_tmp),
                },
            ):
                self.argv_log.unlink(missing_ok=True)
                result = self.handler({"command": "status", "args": []})
                result = json.loads(result) if isinstance(result, str) else result
                self.assertTrue(result["ok"], result)
                invocation = self.last_invocation()
                self.assertEqual(
                    invocation["agent_desktop_home"],
                    str(profile_home / "agent-desktop"),
                )
                self.assertEqual(invocation["tmpdir"], str(private_tmp))


if __name__ == "__main__":
    unittest.main()

"""Profile-scoped, headless Agent Desktop tools for Hermes 0.22.5."""
import base64
import binascii
import json
import os
import re
import subprocess

from hermes_constants import get_hermes_home

READ_COMMANDS = {
    "status", "version", "help", "list-apps", "list-windows", "list-displays",
    "list-surfaces", "snapshot", "find", "get", "is", "screenshot",
}
ACTION_COMMANDS = {
    "click", "right-click", "double-click", "type", "set-value", "clear", "select",
    "toggle", "check", "uncheck", "expand", "collapse", "scroll", "scroll-to",
}
COMMANDS = READ_COMMANDS | ACTION_COMMANDS
REF = re.compile(r"@s[a-zA-Z0-9]+:e[0-9]+\Z")
SCOPE = {"--app", "--window-id"}
# No global flags, paths, physical-input switches, or command forwarding.
VALUE_OPTIONS = {
    "list-apps": {"--app"}, "list-windows": {"--app"}, "list-surfaces": {"--app"},
    "snapshot": SCOPE | {"--max-depth", "--surface", "--root", "--timeout-ms"},
    "find": SCOPE | {"--role", "--name", "--value", "--text", "--description", "--native-id",
                       "--root", "--surface", "--state", "--timeout-ms", "--nth", "--limit"},
    "screenshot": SCOPE | {"--screen"}, "get": {"--property"}, "is": {"--property"},
    **{name: {"--timeout-ms"} for name in ACTION_COMMANDS},
    "scroll": {"--timeout-ms", "--direction", "--amount"},
}
BOOL_OPTIONS = {
    "snapshot": {"-i", "--interactive-only", "--compact", "--skeleton", "--include-bounds"},
    "find": {"--exact", "--count", "--first", "--last"},
}


def failure(code, message, delivery="not_delivered"):
    return {"ok": False, "error": {"code": code, "message": message,
            "disposition": {"delivery": delivery, "retry": "unsafe"}}}


def argv_for(payload):
    if not isinstance(payload, dict) or set(payload) - {"command", "args"}:
        raise ValueError("Expected only command and args")
    command, args = payload.get("command"), payload.get("args", [])
    if not isinstance(command, str) or command not in COMMANDS:
        raise ValueError("Command is not exposed")
    if not isinstance(args, list) or not all(isinstance(arg, str) and "\0" not in arg for arg in args):
        raise ValueError("args must be strings without NUL")
    if command == "help":
        if len(args) > 1 or (args and args[0] not in COMMANDS - {"help"}):
            raise ValueError("help accepts one exposed command")
        return [*args, "--help"]
    positional = 2 if command in {"type", "set-value", "select"} else (
        1 if command in ACTION_COMMANDS | {"get", "is"} else 0)
    if len(args) < positional or (positional and not REF.fullmatch(args[0])):
        raise ValueError("A qualified snapshot ref is required")
    # Leading '-' values could be interpreted as CLI flags. Keep literal text otherwise.
    if positional == 2 and args[1].startswith("-"):
        raise ValueError("Text/value must not start with a CLI option prefix")
    index = positional
    while index < len(args):
        option = args[index]
        if option in BOOL_OPTIONS.get(command, set()):
            index += 1
        elif option in VALUE_OPTIONS.get(command, set()) and index + 1 < len(args):
            value = args[index + 1]
            if value.startswith("-") or (option == "--root" and not REF.fullmatch(value)):
                raise ValueError("Invalid option value")
            index += 2
        else:
            raise ValueError("Unsupported argument or option")
    return [command, *args]


def pre_tool_call(tool_name, args, **kwargs):
    if tool_name != "agent_desktop":
        return None
    try:
        argv_for(args)
    except ValueError as error:
        return {"action": "block", "message": str(error)}
    if args["command"] in ACTION_COMMANDS:
        return {"action": "approve", "message": "Agent Desktop mutation: " +
                json.dumps(args, ensure_ascii=False, separators=(",", ":"))}
    return None


def register(ctx):
    command = ctx.get_config("command", "")
    timeout = ctx.get_config("timeout", 30)
    if not isinstance(command, str) or not os.path.isabs(command):
        raise ValueError("agent-desktop settings.command must be an absolute executable path")
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= 120:
        raise ValueError("agent-desktop timeout must be between 0 and 120 seconds")

    def execute(payload):
        try:
            argv = argv_for(payload)
        except ValueError as error:
            return failure("INVALID_ARGUMENT", str(error))
        env = os.environ.copy()
        env["AGENT_DESKTOP_HOME"] = str(get_hermes_home() / "agent-desktop")
        # Ignore ambient sessions/traces; state follows the active Hermes profile.
        for key in ("AGENT_DESKTOP_SESSION", "AGENT_DESKTOP_AGENT_ID"):
            env.pop(key, None)
        try:
            result = subprocess.run([command, *argv], capture_output=True, text=True,
                                    timeout=timeout, env=env, shell=False)
        except subprocess.TimeoutExpired:
            return failure("TIMEOUT", "Delivery unknown after timeout; observe before any retry.", "unknown")
        except OSError:
            return failure("LAUNCH_FAILED", "Agent Desktop could not be launched.")
        if payload["command"] == "help":
            if result.returncode:
                return failure("CLI_FAILED", "Agent Desktop help failed.")
            return {"ok": True, "data": {"help": result.stdout}}
        try:
            envelope = json.loads(result.stdout)
            if not isinstance(envelope, dict) or type(envelope.get("ok")) is not bool:
                raise ValueError("Invalid envelope")
            if envelope["ok"] and (result.returncode or "data" not in envelope):
                raise ValueError("Inconsistent success envelope")
            if not envelope["ok"] and not isinstance(envelope.get("error"), dict):
                raise ValueError("Missing error")
        except (ValueError, TypeError):
            return failure("INVALID_RESPONSE", "Invalid Agent Desktop response; delivery unknown.", "unknown")
        if payload["command"] != "screenshot" or not envelope["ok"]:
            return envelope
        data = envelope.get("data")
        try:
            if not isinstance(data, dict) or data.get("format") != "png":
                raise ValueError("Unsupported image format")
            encoded = data["data"]
            image = base64.b64decode(encoded, validate=True)
            if not image.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Invalid PNG")
        except (KeyError, ValueError, TypeError, binascii.Error):
            return failure("INVALID_IMAGE", "Agent Desktop did not return a valid PNG screenshot.")
        summary = json.dumps({**envelope, "data": {key: value for key, value in data.items() if key != "data"}})
        return {"_multimodal": True, "content": [
            {"type": "text", "text": summary},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + encoded}},
        ], "text_summary": summary}

    def handler(payload, **kwargs):
        result = execute(payload)
        # Hermes registry accepts JSON strings or its explicit multimodal dict.
        return result if result.get("_multimodal") is True else json.dumps(result)

    ctx.register_tool(name="agent_desktop", toolset="agent_desktop", handler=handler,
        schema={"name": "agent_desktop", "description":
            "Observe native macOS apps and perform approved semantic ref actions. Start with status, then snapshot. "
            "Use help with one exposed command for CLI arguments. No shell, permission changes or output paths. "
            "After each action observe again; never retry unknown delivery.",
            "parameters": {"type": "object", "required": ["command"], "additionalProperties": False,
                "properties": {"command": {"type": "string", "enum": sorted(COMMANDS)},
                    "args": {"type": "array", "items": {"type": "string"}, "default": []}}}})
    ctx.register_hook("pre_tool_call", pre_tool_call)

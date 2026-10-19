"""Hermes tools driving a real, local OMP ACP coding session."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

from .worker import Worker


def _conversation(session_id):
    from tools.approval import get_current_session_key

    if not session_id:
        raise ValueError("Missing trusted Hermes session identity.")
    routing = get_current_session_key(default="")
    if not routing:
        raise ValueError("Missing bound Hermes approval context.")
    # Compression rotates transcript IDs; only compression children inherit the
    # coding task. A reset/fork must never attach to an older OMP conversation.
    home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    with closing(sqlite3.connect((home / "state.db").as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
        seen = set()
        while session_id not in seen and len(seen) < 128:
            seen.add(session_id)
            row = db.execute(
                "SELECT p.id, p.end_reason FROM sessions s "
                "JOIN sessions p ON p.id = s.parent_session_id WHERE s.id = ?",
                (session_id,),
            ).fetchone()
            if not row or row[1] != "compression":
                return f"{routing}\0{session_id}"
            session_id = row[0]
    raise RuntimeError("Invalid or excessive Hermes compression lineage.")

def _required_string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing or malformed {name}.")
    return value


def _canonical_directory(value, name):
    value = _required_string(value, name)
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"Malformed {name}.")
    path = path.resolve(strict=True)
    if not path.is_dir():
        raise ValueError(f"Malformed {name}.")
    return path


def _normalize_action_input(value, worktree_paths, ancestors=None):
    if isinstance(value, (dict, list)):
        ancestors = ancestors if ancestors is not None else set()
        marker = id(value)
        if marker in ancestors:
            raise ValueError("Malformed OMP action input.")
        ancestors.add(marker)
        try:
            if isinstance(value, dict):
                normalized = {}
                for key, item in value.items():
                    if not isinstance(key, str):
                        raise ValueError("Malformed OMP action input.")
                    if key in ("path", "cwd"):
                        if not isinstance(item, str) or not item.strip() or "\0" in item:
                            raise ValueError("Malformed OMP action path.")
                        path = Path(item)
                        if not path.is_absolute():
                            path = worktree_paths[0] / path
                        lexical = Path(os.path.normpath(str(path)))
                        resolved = lexical.resolve(strict=False)
                        root = next((root for root in worktree_paths if lexical.is_relative_to(root)), None)
                        if root is not None and resolved.is_relative_to(worktree_paths[0]):
                            relative = lexical.relative_to(root).as_posix() or "."
                            # This tagged value cannot collide with a literal
                            # path input: path/cwd fields must contain strings.
                            normalized[key] = {"$omp:v2:path": relative}
                        else:
                            normalized[key] = item
                    else:
                        normalized[key] = _normalize_action_input(item, worktree_paths, ancestors)
                return normalized
            return [_normalize_action_input(item, worktree_paths, ancestors) for item in value]
        finally:
            ancestors.remove(marker)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("Malformed OMP action input.")


def _approval_identity(tool_call, get_session_env):
    workspace = _required_string(get_session_env("HERMES_SESSION_SCOPE_ID"), "Slack workspace identity")
    user = _required_string(get_session_env("HERMES_SESSION_USER_ID"), "Slack user identity")
    if not isinstance(tool_call, dict):
        raise ValueError("Missing OMP action.")
    kind = _required_string(tool_call.get("kind"), "OMP operation kind")
    if not isinstance(tool_call.get("rawInput"), dict) or not tool_call["rawInput"]:
        raise ValueError("Missing or malformed complete OMP action input.")
    worker = tool_call.get("hermes_worker")
    if not isinstance(worker, dict):
        raise ValueError("Missing trusted OMP worker identity.")
    repository = _canonical_directory(worker.get("repository"), "canonical repository")
    worktree = _canonical_directory(worker.get("worktree"), "OMP worktree")
    if worktree == repository:
        raise ValueError("Malformed OMP worktree.")

    identity = {
        "platform": "slack",
        "workspace": workspace,
        "user": user,
        "repository": str(repository),
        "kind": kind,
        "rawInput": _normalize_action_input(
            tool_call["rawInput"], (worktree, Path(os.path.abspath(worker["worktree"])))
        ),
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    rule_key = f"omp:v2:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"
    return identity, rule_key


def _approve(params):
    from gateway.session_context import get_session_env
    from slack_sdk import WebClient
    from tools.approval import get_current_session_key, is_approval_bypass_active_for_session, request_tool_approval
    from tools.interrupt import is_interrupted

    if not isinstance(params, dict):
        return False
    session_key = get_current_session_key(default="")
    if not isinstance(session_key, str) or not session_key.strip():
        return False
    if is_approval_bypass_active_for_session(session_key) or is_interrupted():
        return False
    try:
        if get_session_env("HERMES_SESSION_PLATFORM") != "slack":
            return False
        channel = get_session_env("HERMES_SESSION_CHAT_ID")
        thread = get_session_env("HERMES_SESSION_THREAD_ID")
        if not isinstance(channel, str) or not channel.strip() or (thread is not None and not isinstance(thread, str)):
            return False
        tool_call = params.get("toolCall")
        identity, rule_key = _approval_identity(tool_call, get_session_env)
    except (KeyError, LookupError, OSError, RuntimeError, TypeError, ValueError):
        return False
    detail_data = {
        "scope": {
            "platform": identity["platform"],
            "workspace": identity["workspace"],
            "user": identity["user"],
            "repository": identity["repository"],
        },
        "toolCall": tool_call,
    }
    try:
        detail = json.dumps(detail_data, ensure_ascii=False, indent=2, allow_nan=False)
    except (TypeError, ValueError):
        return False
    if len(detail) > 60000:
        return False
    digest = hashlib.sha256(detail.encode()).hexdigest()
    nonce = uuid.uuid4().hex
    # The native approval card truncates its reason to 500 characters. Post
    # the complete action as non-markup text first; the nonce and digest are
    # audit labels only and do not identify the native approval rule.
    try:
        slack = WebClient(token=os.environ["SLACK_BOT_TOKEN"], timeout=15)
        chunks = [detail[offset:offset + 2800] for offset in range(0, len(detail), 2800)]
        for index, chunk in enumerate(chunks, 1):
            if is_interrupted():
                return False
            slack.chat_postMessage(
                channel=channel, thread_ts=thread or None,
                text=f"OMP action {nonce} ({index}/{len(chunks)}); SHA-256 {digest}",
                blocks=[
                    {"type": "section", "text": {"type": "plain_text", "text": f"OMP action {nonce} ({index}/{len(chunks)})"}},
                    {"type": "section", "text": {"type": "plain_text", "text": chunk}},
                ],
                unfurl_links=False, unfurl_media=False,
            )
    except Exception as error:
        raise RuntimeError("Cannot deliver complete OMP approval details to Slack; no action authorized.") from error
    if is_interrupted():
        return False
    reason = (
        f"OMP request {nonce}; audit SHA-256 {digest}. "
        "Allow once approves this request only. "
        "Session/Always grant this exact operation kind and complete raw input for the same Slack workspace, "
        "user, and canonical repository shown above; changed inputs or scope require approval."
    )
    decision = request_tool_approval("omp_task", reason, rule_key=rule_key)
    return (
        not is_interrupted()
        and isinstance(decision, dict)
        and decision.get("approved") is True
    )

def _handle(args, *, session_id=None, status=False, **_):
    from tools.interrupt import is_interrupted

    try:
        config = json.loads(Path(os.environ["OMP_WORKER_CONFIG"]).read_text())
        worker = Worker(config)
        conversation = _conversation(session_id)
        repository = args["repository"]
        if status:
            result = worker.status(conversation, repository)
        else:
            result = worker.run(
                conversation, repository, args["prompt"], approve=_approve,
                cancelled=is_interrupted, resume_interrupted=args.get("resume_interrupted") is True,
            )
        return json.dumps(result, ensure_ascii=False)
    except (OSError, ValueError, KeyError, RuntimeError, sqlite3.Error) as error:
        return json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False)


def register(ctx):
    repository = {"type": "string", "description": "Absolute path to the allowed Git repository root."}
    for name, description, properties, required in (
        (
            "omp_task",
            "Run or continue coding through local OMP. OMP owns tools and works in a retained isolated Git worktree. Return real changes, tool outcomes and verification. Follow-ups reuse this conversation's worktree and OMP session. Do not automatically retry interrupted/failed changes.",
            {
                "repository": repository,
                "prompt": {"type": "string", "description": "Task or follow-up instruction for OMP."},
                "resume_interrupted": {"type": "boolean", "description": "Only after inspecting omp_status and an explicit user continuation of a failed/interrupted task."},
            },
            ["repository", "prompt"],
        ),
        (
            "omp_status",
            "Inspect this conversation's retained OMP task, worktree and prior result without executing another task.",
            {"repository": repository},
            ["repository"],
        ),
    ):
        ctx.register_tool(
            name=name, toolset="omp-worker",
            schema={"type": "function", "function": {
                "name": name, "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
            }},
            handler=(lambda args, **kwargs: _handle(args, status=True, **kwargs)) if name == "omp_status" else _handle,
        )

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


def _approve(params):
    from gateway.session_context import get_session_env
    from slack_sdk import WebClient
    from tools.approval import get_current_session_key, is_approval_bypass_active_for_session, request_tool_approval
    from tools.interrupt import is_interrupted

    if is_approval_bypass_active_for_session(get_current_session_key()) or is_interrupted():
        return False
    if get_session_env("HERMES_SESSION_PLATFORM") != "slack":
        return False
    channel = get_session_env("HERMES_SESSION_CHAT_ID")
    thread = get_session_env("HERMES_SESSION_THREAD_ID")
    if not channel:
        return False
    detail = json.dumps(params.get("toolCall") or {}, ensure_ascii=False, indent=2)
    if len(detail) > 60000:
        return False
    digest = hashlib.sha256(detail.encode()).hexdigest()
    nonce = uuid.uuid4().hex
    # The native approval card truncates its reason to 500 characters. Post
    # the complete action as non-markup text first, then bind the card to its
    # digest. Do not silently approve an operation the user could not inspect.
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
    reason = (
        f"Approve only OMP action {nonce}, displayed above. SHA-256 {digest}. "
        "Session/Always choices do not authorize later OMP actions."
    )
    decision = request_tool_approval("omp_task", reason, rule_key=f"omp:{nonce}")
    return not is_interrupted() and decision.get("approved") is True


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

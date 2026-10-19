#!/usr/bin/env python3
"""Deterministic ACP peer exercising real mutation, persistence and cancellation."""

import json
from pathlib import Path
import subprocess
import sys
import time
import uuid


def send(value):
    print(json.dumps({"jsonrpc": "2.0", **value}), flush=True)


def update(session_id, value):
    send({"method": "session/update", "params": {"sessionId": session_id, "update": value}})


def main():
    sessions = Path.cwd().parent.parent / "peer-sessions" / Path.cwd().name
    sessions.mkdir(parents=True, exist_ok=True)
    session_id = None
    for line in sys.stdin:
        message = json.loads(line)
        method = message.get("method")
        params = message.get("params", {})
        if method == "initialize":
            result = {"protocolVersion": 1, "agentCapabilities": {"loadSession": True}}
        elif method == "session/new":
            session_id = uuid.uuid4().hex
            (sessions / session_id).write_text("0")
            result = {"sessionId": session_id}
        elif method == "session/load":
            session_id = params["sessionId"]
            if not (sessions / session_id).exists():
                send({"id": message["id"], "error": {"code": -32001, "message": "Unknown session"}})
                continue
            result = {}
        elif method == "session/prompt":
            instruction = params["prompt"][0]["text"].splitlines()[0]
            if instruction == "crash":
                sys.exit(17)
            if instruction == "bad-stop":
                send({"id": message["id"], "result": {"stopReason": "max_tokens"}})
                continue
            if instruction == "history-limit":
                for number in range(205):
                    update(session_id, {"sessionUpdate": "tool_call", "toolCallId": f"read-{number}", "status": "completed", "rawInput": {"path": "original.txt"}})
            if instruction == "sleep":
                send({"id": "permission", "method": "session/request_permission", "params": {
                    "sessionId": session_id,
                    "toolCall": {"toolCallId": "mutate", "kind": "execute", "title": "Run shell child"},
                    "options": [{"optionId": "once", "kind": "allow_once", "name": "Allow once"}],
                }})
                permission = json.loads(next(sys.stdin))["result"]["outcome"]
                approved = permission.get("outcome") == "selected"
            else:
                update(session_id, {
                    "sessionUpdate": "tool_call", "toolCallId": "mutate",
                    "status": "pending", "kind": "edit", "rawInput": {"content": instruction},
                })
                if instruction == "ambiguous":
                    update(session_id, {"sessionUpdate": "tool_call", "toolCallId": "other", "status": "pending", "rawInput": {"content": "unrelated operation"}})
                send({"id": "form", "method": "elicitation/create", "params": {
                    "sessionId": session_id, "mode": "form", "message": f"Allow tool: write\n{instruction}",
                    "requestedSchema": {"type": "object", "properties": {
                        "value": {"type": "string", "enum": ["Proceed", "Abort"] if instruction == "unknown-form" else ["Approve", "Deny"]},
                    }},
                }})
                permission = json.loads(next(sys.stdin))["result"]
                approved = permission.get("action") == "accept" and permission.get("content", {}).get("value") == "Approve"
            if not approved:
                text = "Permission denied; no mutation performed."
            elif instruction == "sleep":
                subprocess.Popen([sys.executable, "-c", "import os, signal, time; from pathlib import Path; signal.signal(signal.SIGTERM, signal.SIG_IGN); Path('child.pid').write_text(str(os.getpid())); time.sleep(30); Path('escaped').write_text('unsafe')"])
                while True:
                    time.sleep(1)
            else:
                count = int((sessions / session_id).read_text()) + 1
                (sessions / session_id).write_text(str(count))
                with Path("result.txt").open("a") as output:
                    output.write(f"{count}:{instruction}\n")
                check = subprocess.run([sys.executable, "-c", "from pathlib import Path; assert Path('result.txt').read_text().endswith('\\n')"], check=False)
                update(session_id, {"sessionUpdate": "tool_call_update", "toolCallId": "mutate", "status": "completed", "rawOutput": {"exit_code": check.returncode}})
                text = f"Updated result.txt; verification exit code {check.returncode}."
            update(session_id, {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}})
            result = {"stopReason": "end_turn"}
        else:
            continue
        send({"id": message["id"], "result": result})


if __name__ == "__main__":
    main()

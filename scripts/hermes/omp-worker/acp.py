"""Bounded stdio ACP client. OMP owns tools; no filesystem/terminal bridge."""

from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import select
import signal
import subprocess
import time


class Cancelled(RuntimeError):
    pass


class ACPClient:
    def __init__(self, command, *, cwd, log, cancelled, approve, timeout=1800):
        self.cancelled = cancelled
        self.approve = approve
        self.deadline = time.monotonic() + timeout
        self.session_id = None
        self.next_id = 0
        self.active_prompt = None
        self.closed = False
        self.buffer = bytearray()
        self.text = []
        self.text_size = 0
        self.tool_calls = {}
        self.log = Path(log).open("ab", buffering=0)
        try:
            self.process = subprocess.Popen(
                command, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self.log, start_new_session=True, bufsize=0,
            )
        except Exception:
            self.log.close()
            raise
        os.set_blocking(self.process.stdin.fileno(), False)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def _receive(self, timeout=0.1):
        until = time.monotonic() + timeout
        while True:
            newline = self.buffer.find(b"\n")
            if newline >= 0:
                line = bytes(self.buffer[:newline])
                del self.buffer[:newline + 1]
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise RuntimeError("OMP sent a non-object ACP message.")
                return message
            remaining = until - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                return None
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("OMP exited before completing the ACP request.")
            self.buffer.extend(chunk)
            if len(self.buffer) > 4 * 1024 * 1024:
                raise RuntimeError("OMP exceeded the ACP message size limit.")

    def _send(self, message, *, closing=False):
        data = (json.dumps(message, ensure_ascii=False) + "\n").encode()
        view = memoryview(data)
        until = time.monotonic() + 0.2 if closing else self.deadline
        while view:
            if not closing:
                self._check()
            if time.monotonic() >= until:
                raise TimeoutError("OMP stopped reading its ACP input.")
            try:
                count = os.write(self.process.stdin.fileno(), view)
            except BlockingIOError:
                select.select([], [self.process.stdin], [], 0.1)
                continue
            if not count:
                raise RuntimeError("OMP closed its ACP input.")
            view = view[count:]

    def _check(self):
        if self.cancelled():
            raise Cancelled("OMP task cancelled; partial changes remain in its worktree.")
        if time.monotonic() >= self.deadline:
            raise TimeoutError("OMP task timed out; inspect its retained worktree before continuing.")

    def _permission(self, params):
        once = next((o for o in params.get("options", []) if o.get("kind") == "allow_once"), None)
        if once is None:
            return {"outcome": {"outcome": "cancelled"}}
        # The native Slack gate must stay on Hermes' tracked tool-worker thread
        # so its thread-local interruption signal remains visible while waiting.
        approved = bool(self.approve(params))
        self._check()
        if approved:
            return {"outcome": {"outcome": "selected", "optionId": once["optionId"]}}
        return {"outcome": {"outcome": "cancelled"}}

    def _elicitation(self, params):
        schema = params.get("requestedSchema") or {}
        properties = schema.get("properties") or {}
        value = properties.get("value") or {}
        if (
            params.get("mode") != "form"
            or set(properties) != {"value"}
            or set(value.get("enum") or []) != {"Approve", "Deny"}
        ):
            return {"action": "decline"}
        pending = [
            call for call in self.tool_calls.values()
            if call.get("status") in ("pending", "in_progress") and call.get("rawInput")
        ]
        # Generic OMP forms omit the tool ID and sometimes the proposed patch.
        # Never authorize an ambiguous operation or show only its filename.
        if len(pending) != 1:
            return {"action": "decline"}
        approved = self.approve({
            "sessionId": self.session_id,
            "toolCall": {**pending[0], "approval_message": params.get("message", ""), "requestedSchema": schema},
        })
        self._check()
        if approved:
            return {"action": "accept", "content": {"value": "Approve"}}
        return {"action": "decline"}

    def _update(self, params):
        if params.get("sessionId") != self.session_id:
            return
        update = params.get("update") or {}
        kind = update.get("sessionUpdate")
        if kind == "agent_message_chunk":
            content = update.get("content") or {}
            if content.get("type") == "text":
                text = content.get("text", "")
                self.text.append(text)
                self.text_size += len(text)
                if self.text_size > 64000:
                    self.text = ["".join(self.text)[-64000:]]
                    self.text_size = len(self.text[0])
        elif kind in ("tool_call", "tool_call_update"):
            key = str(update.get("toolCallId", ""))
            if key not in self.tool_calls and len(self.tool_calls) >= 200:
                completed = next((key for key, call in self.tool_calls.items() if call.get("status") in ("completed", "failed")), None)
                if completed is None:
                    raise RuntimeError("OMP exceeded the concurrent tool-call limit.")
                del self.tool_calls[completed]
            self.tool_calls.setdefault(key, {}).update(update)

    def request(self, method, params):
        self._check()
        self.next_id += 1
        request_id = self.next_id
        if method == "session/prompt":
            self.active_prompt = request_id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            self._check()
            message = self._receive()
            if message is None:
                continue
            if message.get("id") == request_id and "method" not in message:
                self.active_prompt = None
                if "error" in message:
                    error = message["error"]
                    raise RuntimeError(f"ACP {method} failed ({error.get('code')}): {error.get('message')}")
                return message.get("result") or {}
            incoming = message.get("method")
            if incoming == "session/update":
                self._update(message.get("params") or {})
            elif "id" in message and incoming:
                params = message.get("params") or {}
                if incoming == "session/request_permission" and params.get("sessionId") == self.session_id:
                    response = {"result": self._permission(params)}
                elif incoming == "elicitation/create" and params.get("sessionId") == self.session_id:
                    response = {"result": self._elicitation(params)}
                else:
                    response = {"error": {"code": -32601, "message": "Client capability not advertised"}}
                self._send({"jsonrpc": "2.0", "id": message["id"], **response})

    def initialize(self):
        return self.request("initialize", {
            "protocolVersion": 1,
            "clientCapabilities": {"elicitation": {"form": {}}},
            "clientInfo": {"name": "hermes-omp-worker", "version": "1.0.0"},
        })

    def _signal_group(self, sig):
        try:
            os.killpg(self.process.pid, sig)
        except ProcessLookupError:
            pass

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.active_prompt and self.session_id and self.process.poll() is None:
            try:
                self._send({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": self.session_id}}, closing=True)
                until = time.monotonic() + 1
                while time.monotonic() < until:
                    message = self._receive()
                    if message and message.get("id") == self.active_prompt and "method" not in message:
                        break
            except (OSError, ValueError, RuntimeError):
                pass
        # EOF lets OMP dispose its own tools/process groups before forced exit.
        self.process.stdin.close()
        try:
            self.process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass
        self._signal_group(signal.SIGTERM)
        try:
            self.process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass
        # The ACP parent may already have exited while a shell child ignores
        # TERM. Escalate the remaining group independently of the parent's exit.
        self._signal_group(signal.SIGKILL)
        self.process.wait(timeout=2)
        self.selector.close()
        self.process.stdout.close()
        self.log.close()

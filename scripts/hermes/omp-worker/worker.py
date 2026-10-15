"""One retained OMP session/worktree per Hermes conversation and repository."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

from .acp import ACPClient, Cancelled


class Worker:
    def __init__(self, config):
        self.config = config
        self.root = Path(config["state_dir"]).expanduser().resolve()
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.git = config["git"]

    def _git(self, cwd, *args):
        result = subprocess.run(
            [self.git, "-C", str(cwd), "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", *args],
            text=True, capture_output=True,
            timeout=30, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        if result.returncode:
            raise RuntimeError(f"Git {' '.join(args[:2])} failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def _repository(self, value):
        repository = Path(value).expanduser().resolve(strict=True)
        roots = [Path(root).expanduser().resolve() for root in self.config["allowed_roots"]]
        if not any(repository.is_relative_to(root) for root in roots):
            raise ValueError("Repository is outside the Nix-declared repository roots.")
        top = Path(self._git(repository, "rev-parse", "--show-toplevel")).resolve()
        if top != repository:
            raise ValueError("Specify the repository root, not a subdirectory.")
        return repository

    @contextmanager
    def _task(self, conversation, repository):
        if not conversation:
            raise ValueError("A trusted Hermes session identity is required.")
        key = hashlib.sha256(f"{conversation}\0{repository}".encode()).hexdigest()
        state_path = self.root / f"{key}.json"
        fd = os.open(self.root / f"{key}.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("This conversation already has an OMP task running in this repository.") from None
            state = json.loads(state_path.read_text()) if state_path.exists() else None
            if state and (state.get("conversation") != conversation or state.get("repository") != str(repository)):
                raise RuntimeError("Retained task ownership does not match the caller.")
            yield state_path, state
        finally:
            os.close(fd)

    def _save(self, path, state):
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump(state, stream, ensure_ascii=False)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def _create(self, conversation, repository):
        task_id = uuid.uuid4().hex
        worktree = self.root / "worktrees" / task_id
        worktree.parent.mkdir(mode=0o700, exist_ok=True)
        base = self._git(repository, "rev-parse", "HEAD")
        branch = f"hermes/{task_id}"
        self._git(repository, "worktree", "add", "-b", branch, str(worktree), base)
        return {
            "task_id": task_id, "conversation": conversation,
            "repository": str(repository), "worktree": str(worktree),
            "base_commit": base, "branch": branch, "session_id": None,
            "status": "created", "response": "", "tool_calls": [],
        }

    def status(self, conversation, repository):
        repository = self._repository(repository)
        with self._task(conversation, repository) as (_, state):
            if not state:
                return {"status": "not_started", "repository": str(repository)}
            return self._result(state)

    @staticmethod
    def _result(state):
        return {key: value for key, value in state.items() if key != "conversation"}

    def run(self, conversation, repository, prompt, *, approve, cancelled, resume_interrupted=False):
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("A non-empty task or follow-up instruction is required.")
        repository = self._repository(repository)
        with self._task(conversation, repository) as (path, state):
            if state is None:
                state = self._create(conversation, repository)
                self._save(path, state)
            elif state["status"] in ("running", "failed", "cancelled") and not resume_interrupted:
                raise RuntimeError(
                    f"Previous run is {state['status']}; inspect omp_status and obtain an explicit "
                    "user continuation before setting resume_interrupted. Never blindly retry."
                )
            worktree = Path(state["worktree"])
            if self._git(worktree, "rev-parse", "--show-toplevel") != str(worktree):
                raise RuntimeError("The retained worktree is missing or no longer valid.")
            # The restricted OMP SDK entrypoint excludes executable ambient
            # custom tools before import; CLI --tools is not an admission gate.
            command = [self.config["command"], "--policy", self.config["approval_config"]]
            state.update(status="running", response="", tool_calls=[])
            state.pop("error", None)
            self._save(path, state)
            client = None
            try:
                client = ACPClient(
                    command, cwd=worktree, log=self.root / f"{state['task_id']}.stderr.log",
                    approve=lambda params: approve({
                        **params, "toolCall": {
                            **(params.get("toolCall") or {}),
                            "hermes_worker": {
                                "task_id": state["task_id"], "repository": str(repository),
                                "worktree": str(worktree),
                                "head": self._git(worktree, "rev-parse", "HEAD"),
                            },
                        },
                    }),
                    cancelled=cancelled, timeout=self.config.get("timeout", 1800),
                )
                client.initialize()
                params = {"cwd": str(worktree), "mcpServers": []}
                if state["session_id"]:
                    params["sessionId"] = state["session_id"]
                    client.session_id = state["session_id"]
                    client.request("session/load", params)
                else:
                    session = client.request("session/new", params)
                    client.session_id = session.get("sessionId")
                    if not client.session_id:
                        raise RuntimeError("OMP did not return an ACP session ID.")
                    state["session_id"] = client.session_id
                    self._save(path, state)
                # session/load replays previous updates; retain only this turn.
                client.text.clear()
                client.tool_calls.clear()
                result = client.request("session/prompt", {
                    "sessionId": client.session_id,
                    "prompt": [{"type": "text", "text": prompt + "\n\nWork only in the current worktree. Do not push, deploy or change permissions without a separate explicit human approval. Report actual changes and verification commands with exit codes; never invent evidence."}],
                })
                state["stop_reason"] = result.get("stopReason")
                if result.get("stopReason") != "end_turn":
                    raise RuntimeError(f"OMP did not finish normally: {result.get('stopReason')}")
                state["status"] = "completed"
            except Exception as error:
                state["status"] = "cancelled" if isinstance(error, Cancelled) else "failed"
                state["error"] = str(error)
            finally:
                if client:
                    state["response"] = "".join(client.text)[-64000:]
                    state["tool_calls"] = list(client.tool_calls.values())
                try:
                    if client:
                        client.close()
                    state["changes"] = self._git(worktree, "status", "--short")
                    state["diff_stat"] = self._git(worktree, "diff", "--no-ext-diff", "--no-textconv", "--stat", state["base_commit"])
                    state["head"] = self._git(worktree, "rev-parse", "HEAD")
                except Exception as error:
                    state["status"] = "failed"
                    state["error"] = f"{state.get('error', '')} Finalization: {error}".strip()
                self._save(path, state)
            return self._result(state)

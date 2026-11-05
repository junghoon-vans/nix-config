#!/usr/bin/env python3
"""Exercise the packaged Hermes gateway host with isolated synthetic children."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


HOST_EXECUTABLE, PYTHON_EXECUTABLE = None, None


def _python_child_command(python_executable, code, *arguments):
    return [python_executable, "-B", "-c", code, *arguments]


def _signal_if_running(pid, sig):
    if pid is None:
        return
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass


_SIGNAL_GROUP_CHILD = """\
import json, os, signal, sys, time
state_path, events_dir, ready_path, release_path, signal_text = sys.argv[1:]
target_signal = int(signal_text)
received = []
def record(signum, frame):
    if not received:
        received.append(signum)
        with open(os.path.join(events_dir, str(os.getpid())), "w") as event:
            event.write(str(signum))
grandchild_pid = os.fork()
if grandchild_pid == 0:
    signal.signal(target_signal, record)
    with open(ready_path, "w") as ready:
        ready.write(str(os.getpid()))
    while not received and not os.path.exists(release_path):
        time.sleep(0.01)
    os._exit(0)
signal.signal(target_signal, record)
deadline = time.monotonic() + 10
while not os.path.exists(ready_path) and time.monotonic() < deadline:
    time.sleep(0.01)
if not os.path.exists(ready_path):
    os._exit(2)
with open(state_path, "w") as state:
    json.dump({"child_pid": os.getpid(), "parent_pid": os.getppid(), "grandchild_pid": grandchild_pid}, state)
while not received and not os.path.exists(release_path):
    time.sleep(0.01)
if not received:
    try:
        os.kill(grandchild_pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
os.waitpid(grandchild_pid, 0)
"""


_DIRECT_CHILD_SIGNAL = """\
import json, os, signal, sys, time
state_path, events_dir, ready_path, release_path, signal_text = sys.argv[1:]
target_signal = int(signal_text)
received = []
def record(signum, frame):
    if not received:
        received.append(signum)
        with open(os.path.join(events_dir, str(os.getpid())), "w") as event:
            event.write(str(signum))
grandchild_pid = os.fork()
if grandchild_pid == 0:
    signal.signal(target_signal, record)
    signal.signal(signal.SIGTERM, lambda signum, frame: os._exit(0))
    with open(ready_path, "w") as ready:
        ready.write(str(os.getpid()))
    while not os.path.exists(release_path):
        time.sleep(0.01)
    os._exit(0)
signal.signal(target_signal, record)
deadline = time.monotonic() + 10
while not os.path.exists(ready_path) and time.monotonic() < deadline:
    time.sleep(0.01)
if not os.path.exists(ready_path):
    os._exit(2)
with open(state_path, "w") as state:
    json.dump({"child_pid": os.getpid(), "parent_pid": os.getppid(), "grandchild_pid": grandchild_pid}, state)
while not os.path.exists(release_path):
    time.sleep(0.01)
try:
    os.kill(grandchild_pid, signal.SIGTERM)
except ProcessLookupError:
    pass
os.waitpid(grandchild_pid, 0)
"""


class GatewayHostLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if HOST_EXECUTABLE is None or PYTHON_EXECUTABLE is None:
            raise AssertionError("test_gateway_host.py requires HOST_EXECUTABLE PYTHON_EXECUTABLE")
        cls.host_executable = HOST_EXECUTABLE
        cls.python_executable = PYTHON_EXECUTABLE

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hermes gateway host ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        home = self.root / "home directory"
        home.mkdir()
        hermes_home = self.root / "worker profile"
        hermes_home.mkdir()
        tmpdir = self.root / "scratch directory"
        tmpdir.mkdir()
        self.environment = os.environ.copy()
        self.environment.update(
            HOME=str(home),
            HERMES_HOME=str(hermes_home),
            PATH=os.pathsep.join((str(self.root / "path with spaces"), str(self.root / "second path"))),
            TMPDIR=str(tmpdir),
            GATEWAY_HOST_SENTINEL='spaces, quotes \'" and café',
        )

    def _start_host(self, code, *arguments):
        return subprocess.Popen(
            [self.host_executable, *_python_child_command(self.python_executable, code, *arguments)],
            env=self.environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

    def _run_host(self, code, *arguments, input_text=None, child_pid_path=None):
        process = subprocess.Popen(
            [self.host_executable, *_python_child_command(self.python_executable, code, *arguments)],
            env=self.environment,
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = process.communicate(input=input_text, timeout=15)
        except subprocess.TimeoutExpired:
            child_pid = None
            if child_pid_path is not None:
                try:
                    child_pid = int(child_pid_path.read_text())
                except (OSError, ValueError):
                    pass
            _signal_if_running(child_pid, signal.SIGKILL)
            if process.poll() is None:
                _signal_if_running(process.pid, signal.SIGKILL)
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            raise
        return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)

    def _wait_for_json(self, path, process, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists():
                try:
                    return json.loads(path.read_text())
                except (OSError, json.JSONDecodeError):
                    pass
            if process.poll() is not None:
                self.fail(f"gateway host exited before child readiness with status {process.returncode}")
            time.sleep(0.01)
        self.fail(f"synthetic child did not become ready at {path}")

    def _wait_for_event(self, path, expected, process, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if path.read_text() == expected:
                    return
            except OSError:
                pass
            if process.poll() is not None:
                self.fail(f"gateway host exited before child signal delivery with status {process.returncode}")
            time.sleep(0.01)
        self.fail(f"synthetic child did not record {expected!r} at {path}")

    def _assert_pid_gone(self, pid, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.01)
        self.fail(f"process {pid} remained after gateway host shutdown")

    def _stop_host(self, process, state_path=None, release_path=None):
        if release_path is not None:
            release_path.touch(exist_ok=True)
        if process.poll() is None:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                _signal_if_running(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        state = {}
        if state_path is not None and state_path.exists():
            try:
                state = json.loads(state_path.read_text())
            except (OSError, json.JSONDecodeError):
                pass
        for key in ("child_pid", "grandchild_pid"):
            _signal_if_running(state.get(key), signal.SIGKILL)
        if process.poll() is None:
            _signal_if_running(process.pid, signal.SIGKILL)
            process.wait(timeout=2)

    def test_child_receives_exact_arguments_environment_and_standard_streams(self):
        arguments = ["", "two words", "single'quote", 'double"quote', "line\nbreak", "café"]
        input_text = "gateway input with spaces and café\n"
        child_pid_path = self.root / "stdio-child.pid"
        code = """\
import json, os, sys, tempfile
with open(sys.argv[1], "w") as state:
    state.write(str(os.getpid()))
names = ("HOME", "HERMES_HOME", "PATH", "TMPDIR", "GATEWAY_HOST_SENTINEL")
print(json.dumps({
    "argv": sys.argv,
    "environment": {name: os.environ.get(name) for name in names},
    "stdin": sys.stdin.read(),
    "tempfile_tmpdir": tempfile.gettempdir(),
}, ensure_ascii=False))
print("synthetic Hermes diagnostic", file=sys.stderr)
"""
        result = self._run_host(
            code,
            str(child_pid_path),
            *arguments,
            input_text=input_text,
            child_pid_path=child_pid_path,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(observed["argv"], ["-c", str(child_pid_path), *arguments])
        self.assertEqual(
            observed["environment"],
            {name: self.environment[name] for name in ("HOME", "HERMES_HOME", "PATH", "TMPDIR", "GATEWAY_HOST_SENTINEL")},
        )
        self.assertEqual(observed["stdin"], input_text)
        self.assertEqual(observed["tempfile_tmpdir"], self.environment["TMPDIR"])
        self.assertEqual(result.stderr, "synthetic Hermes diagnostic\n")

    def test_exit_75_is_preserved_and_exit_78_is_parked_for_launchd(self):
        for child_status, host_status in ((75, 75), (78, 0)):
            with self.subTest(child_status=child_status):
                result = self._run_host(f"raise SystemExit({child_status})\n")
                self.assertEqual(result.returncode, host_status, result.stdout + result.stderr)

    def test_term_int_and_hup_reach_process_group_and_reap_descendants(self):
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            with self.subTest(signal=signal.Signals(sig).name):
                state_path = self.root / f"state-{sig}.json"
                events_dir = self.root / f"events-{sig}"
                events_dir.mkdir()
                ready_path = self.root / f"grandchild-ready-{sig}"
                release_path = self.root / f"release-{sig}"
                process = self._start_host(
                    _SIGNAL_GROUP_CHILD,
                    str(state_path), str(events_dir), str(ready_path), str(release_path), str(sig),
                )
                self.addCleanup(self._stop_host, process, state_path, release_path)
                state = self._wait_for_json(state_path, process)
                self.assertEqual(state["parent_pid"], process.pid)
                process.send_signal(sig)
                self.assertEqual(process.wait(timeout=10), 0)
                self.assertEqual((events_dir / str(state["child_pid"])).read_text(), str(sig))
                self.assertEqual((events_dir / str(state["grandchild_pid"])).read_text(), str(sig))
                self._assert_pid_gone(state["child_pid"])
                self._assert_pid_gone(state["grandchild_pid"])

    def test_usr1_and_usr2_reach_only_direct_child(self):
        for sig in (signal.SIGUSR1, signal.SIGUSR2):
            with self.subTest(signal=signal.Signals(sig).name):
                state_path = self.root / f"state-{sig}.json"
                events_dir = self.root / f"events-{sig}"
                events_dir.mkdir()
                ready_path = self.root / f"grandchild-ready-{sig}"
                release_path = self.root / f"release-{sig}"
                process = self._start_host(
                    _DIRECT_CHILD_SIGNAL,
                    str(state_path), str(events_dir), str(ready_path), str(release_path), str(sig),
                )
                self.addCleanup(self._stop_host, process, state_path, release_path)
                state = self._wait_for_json(state_path, process)
                self.assertEqual(state["parent_pid"], process.pid)
                process.send_signal(sig)
                direct_event = events_dir / str(state["child_pid"])
                self._wait_for_event(direct_event, str(sig), process)
                descendant_event = events_dir / str(state["grandchild_pid"])
                deadline = time.monotonic() + 0.25
                while time.monotonic() < deadline:
                    self.assertFalse(descendant_event.exists(), "USR signal reached a descendant")
                    self.assertIsNone(process.poll(), "supervisor exited before signal scope was checked")
                    time.sleep(0.01)
                release_path.touch()
                self.assertEqual(process.wait(timeout=10), 0)
                self._assert_pid_gone(state["child_pid"])
                self._assert_pid_gone(state["grandchild_pid"])

    def test_child_terminated_by_signal_returns_128_plus_signal(self):
        state_path = self.root / "signal-death.json"
        code = """\
import json, os, sys, time
with open(sys.argv[1], "w") as state:
    json.dump({"child_pid": os.getpid(), "parent_pid": os.getppid()}, state)
while True:
    time.sleep(0.1)
"""
        process = self._start_host(code, str(state_path))
        self.addCleanup(self._stop_host, process, state_path)
        state = self._wait_for_json(state_path, process)
        self.assertEqual(state["parent_pid"], process.pid)
        os.kill(state["child_pid"], signal.SIGTERM)
        self.assertEqual(process.wait(timeout=10), 128 + signal.SIGTERM)
        self._assert_pid_gone(state["child_pid"])


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: test_gateway_host.py HOST_EXECUTABLE PYTHON_EXECUTABLE")
    HOST_EXECUTABLE, PYTHON_EXECUTABLE = sys.argv[1:]
    unittest.main(argv=[sys.argv[0]], verbosity=2)

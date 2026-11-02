#!/usr/bin/env python3
"""Exercise a packaged Hermes gateway host with isolated synthetic children."""

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


def _send_signal_if_running(pid, sig):
    if pid is None:
        return
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass


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
        self.tmpdir = self.root / "scratch tmp"
        self.tmpdir.mkdir()
        self.hermes_home = self.root / "hermes profile"
        self.hermes_home.mkdir()
        home = self.root / "home"
        home.mkdir()
        self.environment = {
            "HOME": str(home),
            "HERMES_HOME": str(self.hermes_home),
            "PATH": os.pathsep.join((str(self.root / "path with spaces"), str(self.root / "second path"))),
            "TMPDIR": str(self.tmpdir),
        }

    def _start_host(self, code, *arguments, env=None):
        return subprocess.Popen(
            [self.host_executable, *_python_child_command(self.python_executable, code, *arguments)],
            env=self.environment if env is None else env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

    def _run_host(self, code, *arguments):
        process = subprocess.Popen(
            [self.host_executable, *_python_child_command(self.python_executable, code, *arguments)],
            env=self.environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            close_fds=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
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

    def _wait_for_contents(self, path, expected, process, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists():
                try:
                    if path.read_text() == expected:
                        return
                except OSError:
                    pass
            if process.poll() is not None:
                self.fail(f"gateway host exited before child event was written with status {process.returncode}")
            time.sleep(0.01)
        self.fail(f"synthetic child did not write {expected!r} to {path}")

    def _assert_path_absent_for(self, path, process, duration=0.25):
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            self.assertFalse(path.exists(), f"signal unexpectedly reached descendant: {path}")
            self.assertIsNone(process.poll(), "supervisor exited before signal scope was checked")
            time.sleep(0.01)

    def _stop_host(self, process, release_path=None, state_path=None):
        state = {}
        if state_path is not None and state_path.exists():
            try:
                state = json.loads(state_path.read_text())
            except (OSError, json.JSONDecodeError):
                pass
        if process.poll() is None:
            if release_path is not None:
                release_path.touch(exist_ok=True)
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                for pid in (state.get("child_pid"), state.get("grandchild_pid")):
                    _send_signal_if_running(pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    for pid in (state.get("child_pid"), state.get("grandchild_pid")):
                        _send_signal_if_running(pid, signal.SIGKILL)
                    process.kill()
                    process.wait(timeout=2)

    def _simple_child(self, result_path, exit_code=0, release_path=None):
        wait_for_release = ""
        if release_path is not None:
            wait_for_release = (
                f"while not os.path.exists({str(release_path)!r}):\n"
                "    time.sleep(0.01)\n"
            )
        return (
            "import json, os, sys, tempfile, time\n"
            f"with open({str(result_path)!r}, 'w', encoding='utf-8') as result:\n"
            "    json.dump({\n"
            "        'argv': sys.argv,\n"
            "        'hermes_home': os.environ.get('HERMES_HOME'),\n"
            "        'path': os.environ.get('PATH'),\n"
            "        'tmpdir': os.environ.get('TMPDIR'),\n"
            "        'tempfile_tmpdir': tempfile.gettempdir(),\n"
            "        'child_pid': os.getpid(),\n"
            "        'parent_pid': os.getppid(),\n"
            "    }, result)\n"
            f"{wait_for_release}"
            f"raise SystemExit({exit_code})\n"
        )

    def _waiting_child(self, state_path, release_path):
        return (
            "import json, os, sys, time\n"
            f"with open({str(state_path)!r}, 'w', encoding='utf-8') as result:\n"
            "    json.dump({'child_pid': os.getpid(), 'parent_pid': os.getppid()}, result)\n"
            f"while not os.path.exists({str(release_path)!r}):\n"
            "    time.sleep(0.01)\n"
        )

    def _signal_group_child(self, state_path, events_dir, grandchild_ready, release_path, sig):
        return (
            "import json, os, signal, sys, time\n"
            f"state_path = {str(state_path)!r}\n"
            f"events_dir = {str(events_dir)!r}\n"
            f"grandchild_ready = {str(grandchild_ready)!r}\n"
            f"release_path = {str(release_path)!r}\n"
            f"target_signal = {int(sig)}\n"
            "received = []\n"
            "def record(signum, frame):\n"
            "    if not received:\n"
            "        received.append(signum)\n"
            "        with open(os.path.join(events_dir, str(os.getpid())), 'w') as event:\n"
            "            event.write(str(signum))\n"
            "grandchild_pid = os.fork()\n"
            "if grandchild_pid == 0:\n"
            "    signal.signal(target_signal, record)\n"
            "    with open(grandchild_ready, 'w') as ready:\n"
            "        ready.write(str(os.getpid()))\n"
            "    while not received and not os.path.exists(release_path):\n"
            "        time.sleep(0.01)\n"
            "    os._exit(0)\n"
            "signal.signal(target_signal, record)\n"
            "while not os.path.exists(grandchild_ready):\n"
            "    time.sleep(0.01)\n"
            "with open(state_path, 'w') as result:\n"
            "    json.dump({'child_pid': os.getpid(), 'parent_pid': os.getppid(), "
            "'grandchild_pid': grandchild_pid}, result)\n"
            "while not received and not os.path.exists(release_path):\n"
            "    time.sleep(0.01)\n"
            "if not received:\n"
            "    try:\n"
            "        os.kill(grandchild_pid, signal.SIGTERM)\n"
            "    except ProcessLookupError:\n"
            "        pass\n"
            "os.waitpid(grandchild_pid, 0)\n"
        )

    def _signal_direct_child(self, state_path, events_dir, grandchild_ready, release_path, sig):
        return (
            "import json, os, signal, time\n"
            f"state_path = {str(state_path)!r}\n"
            f"events_dir = {str(events_dir)!r}\n"
            f"grandchild_ready = {str(grandchild_ready)!r}\n"
            f"release_path = {str(release_path)!r}\n"
            f"target_signal = {int(sig)}\n"
            "def record(signum, frame):\n"
            "    with open(os.path.join(events_dir, str(os.getpid())), 'w') as event:\n"
            "        event.write(str(signum))\n"
            "grandchild_pid = os.fork()\n"
            "if grandchild_pid == 0:\n"
            "    signal.signal(target_signal, record)\n"
            "    with open(grandchild_ready, 'w') as ready:\n"
            "        ready.write(str(os.getpid()))\n"
            "    while not os.path.exists(release_path):\n"
            "        time.sleep(0.01)\n"
            "    os._exit(0)\n"
            "signal.signal(target_signal, record)\n"
            "while not os.path.exists(grandchild_ready):\n"
            "    time.sleep(0.01)\n"
            "with open(state_path, 'w') as result:\n"
            "    json.dump({'child_pid': os.getpid(), 'parent_pid': os.getppid(), "
            "'grandchild_pid': grandchild_pid}, result)\n"
            "while not os.path.exists(release_path):\n"
            "    time.sleep(0.01)\n"
            "try:\n"
            "    os.kill(grandchild_pid, signal.SIGTERM)\n"
            "except ProcessLookupError:\n"
            "    pass\n"
            "os.waitpid(grandchild_pid, 0)\n"
        )

    def test_child_is_live_parent_and_receives_exact_argv_and_environment(self):
        result_path = self.root / "child.json"
        release_path = self.root / "release-child"
        arguments = ["", "two words", "single'quote", 'double"quote', "--profile", "line\nbreak", "café"]
        process = self._start_host(
            self._simple_child(result_path, release_path=release_path),
            *arguments,
        )
        self.addCleanup(self._stop_host, process, release_path, result_path)
        child = self._wait_for_json(result_path, process)
        self.assertIsNone(process.poll(), "supervisor exited while synthetic gateway was waiting")
        self.assertEqual(child["parent_pid"], process.pid)
        self.assertEqual(child["argv"], ["-c", *arguments])
        self.assertEqual(child["hermes_home"], self.environment["HERMES_HOME"])
        self.assertEqual(child["path"], self.environment["PATH"])
        self.assertEqual(child["tmpdir"], self.environment["TMPDIR"])
        self.assertEqual(child["tempfile_tmpdir"], self.environment["TMPDIR"])
        release_path.touch()
        self.assertEqual(process.wait(timeout=10), 0)

    def test_child_exit_status_is_preserved_or_parked_for_launchd(self):
        for child_status, host_status in ((0, 0), (75, 75), (78, 0)):
            with self.subTest(child_status=child_status):
                result = self._run_host(f"raise SystemExit({child_status})\n")
                self.assertEqual(result.returncode, host_status, result.stdout + result.stderr)

    def test_spawn_failure_is_reported_without_running_child(self):
        missing_child = self.root / "no-such-child-executable"
        result = subprocess.run(
            [self.host_executable, str(missing_child)],
            env=self.environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(result.returncode, 127, result.stdout + result.stderr)
        self.assertIn("starting Hermes:", result.stderr)

    def test_term_int_and_hup_reach_the_child_process_group_and_leave_no_orphan(self):
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            with self.subTest(signal=signal.Signals(sig).name):
                state_path = self.root / f"state-{sig}.json"
                events_dir = self.root / f"events-{sig}"
                events_dir.mkdir()
                ready_path = self.root / f"grandchild-ready-{sig}"
                release_path = self.root / f"release-{sig}"
                code = self._signal_group_child(state_path, events_dir, ready_path, release_path, sig)
                process = self._start_host(code)
                try:
                    state = self._wait_for_json(state_path, process)
                    self.assertIsNone(process.poll(), "supervisor exited while synthetic gateway was waiting")
                    self.assertEqual(state["parent_pid"], process.pid)
                    process.send_signal(sig)
                    self.assertEqual(process.wait(timeout=10), 0)
                    self.assertEqual((events_dir / str(state["child_pid"])).read_text(), str(sig))
                    self.assertEqual((events_dir / str(state["grandchild_pid"])).read_text(), str(sig))
                    self.assertFalse(release_path.exists())
                    self._assert_pid_gone(state["child_pid"])
                    self._assert_pid_gone(state["grandchild_pid"])
                finally:
                    self._stop_host(process, release_path, state_path)

    def test_usr1_and_usr2_reach_only_the_direct_child_and_shutdown_cleanly(self):
        for sig in (signal.SIGUSR1, signal.SIGUSR2):
            with self.subTest(signal=signal.Signals(sig).name):
                state_path = self.root / f"state-{sig}.json"
                events_dir = self.root / f"events-{sig}"
                events_dir.mkdir()
                ready_path = self.root / f"grandchild-ready-{sig}"
                release_path = self.root / f"release-{sig}"
                code = self._signal_direct_child(state_path, events_dir, ready_path, release_path, sig)
                process = self._start_host(code)
                try:
                    state = self._wait_for_json(state_path, process)
                    self.assertEqual(state["parent_pid"], process.pid)
                    process.send_signal(sig)
                    self._wait_for_contents(events_dir / str(state["child_pid"]), str(sig), process)
                    self._assert_path_absent_for(
                        events_dir / str(state["grandchild_pid"]),
                        process,
                    )
                    release_path.touch()
                    self.assertEqual(process.wait(timeout=10), 0)
                    self._assert_pid_gone(state["child_pid"])
                    self._assert_pid_gone(state["grandchild_pid"])
                finally:
                    self._stop_host(process, release_path, state_path)

    def test_child_signal_death_is_reported_as_128_plus_signal(self):
        state_path = self.root / "signal-death.json"
        process = self._start_host(self._waiting_child(state_path, self.root / "release-signal-death"))
        self.addCleanup(self._stop_host, process, self.root / "release-signal-death", state_path)
        state = self._wait_for_json(state_path, process)
        self.assertEqual(state["parent_pid"], process.pid)
        os.kill(state["child_pid"], signal.SIGTERM)
        self.assertEqual(process.wait(timeout=10), 128 + signal.SIGTERM)
        self._assert_pid_gone(state["child_pid"])

    def _assert_pid_gone(self, pid, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.01)
        self.fail(f"process {pid} remained after gateway host shutdown")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: test_gateway_host.py HOST_EXECUTABLE PYTHON_EXECUTABLE")
    HOST_EXECUTABLE, PYTHON_EXECUTABLE = sys.argv[1:]
    unittest.main(argv=[sys.argv[0]], verbosity=2)

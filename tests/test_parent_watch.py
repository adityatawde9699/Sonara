import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from parent_watch import PARENT_WATCH_ENV, start_parent_watch

ROOT = Path(__file__).resolve().parents[1]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie still answers signal 0; treat an unreaped exit as gone.
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as stat:
            return stat.read().split(") ", 1)[1].split()[0] != "Z"
    except OSError:
        return True


class ParentWatchTests(unittest.TestCase):
    def test_disabled_unless_the_desktop_app_asks(self):
        self.assertFalse(start_parent_watch(environ={}))
        self.assertFalse(start_parent_watch(environ={PARENT_WATCH_ENV: "0"}))

    @unittest.skipUnless(hasattr(os, "killpg"), "Windows uses Job Objects instead")
    def test_worker_and_its_children_stop_when_the_parent_dies_without_cleanup(self):
        # The "app" starts a worker that leads its own process group (as the
        # Tauri side does) and that starts a long-running child (as Piper is),
        # reports both pids, then dies without stopping either.
        worker = textwrap.dedent(
            """
            import subprocess, sys, time
            from parent_watch import start_parent_watch
            assert start_parent_watch(interval=0.05)
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            print(child.pid, flush=True)
            time.sleep(60)
            """
        )
        app = textwrap.dedent(
            f"""
            import os, subprocess, sys
            env = dict(os.environ, {PARENT_WATCH_ENV}="1")
            worker = subprocess.Popen(
                [sys.executable, "-c", {worker!r}],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, process_group=0,
            )
            print(worker.pid, worker.stdout.readline().strip(), flush=True)
            os._exit(0)
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, PYTHONPATH=str(ROOT))
            result = subprocess.run(
                [sys.executable, "-c", app], env=env, cwd=directory,
                capture_output=True, text=True, timeout=30,
            )
        worker_pid, child_pid = (int(value) for value in result.stdout.split())
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and (_alive(worker_pid) or _alive(child_pid)):
            time.sleep(0.05)
        try:
            self.assertFalse(_alive(worker_pid), "the orphaned worker kept running")
            self.assertFalse(_alive(child_pid), "the worker's child kept running")
        finally:
            for pid in (worker_pid, child_pid):
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass


if __name__ == "__main__":
    unittest.main()

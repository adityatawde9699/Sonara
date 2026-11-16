"""Stop a Sonara worker when the desktop app that started it is gone.

The desktop app starts its Python workers with ``SONARA_PARENT_WATCH=1``.
A worker that calls :func:`start_parent_watch` then checks once a second
whether its parent process has changed. On Unix an orphaned process is
re-parented (to init or a subreaper), so a changed parent means Sonara exited
without stopping the worker: a crash, ``panic = "abort"``, or being killed.
The worker then kills its own process group, which takes Piper with it, or
just exits when it does not lead a group.

On Windows the parent id does not change when the parent dies, so this check
never fires there; Job Objects with kill-on-close (``process_tree.rs``) stop
the tree instead. Run from a terminal without the variable, nothing changes.
"""

from __future__ import annotations

import os
import signal
import threading
import time

PARENT_WATCH_ENV = "SONARA_PARENT_WATCH"
PARENT_GONE_EXIT_CODE = 75  # EX_TEMPFAIL: nobody is left to read it anyway


def _stop_this_worker() -> None:
    killpg = getattr(os, "killpg", None)
    if killpg is not None and os.getpgrp() == os.getpid():
        # Leading a group: everything the worker started dies with it.
        killpg(os.getpgrp(), signal.SIGKILL)
    os._exit(PARENT_GONE_EXIT_CODE)


def start_parent_watch(interval: float = 1.0, *, environ: dict[str, str] | None = None) -> bool:
    """Watch the parent in a daemon thread if the desktop app asked for it."""
    if (os.environ if environ is None else environ).get(PARENT_WATCH_ENV) != "1":
        return False
    parent = os.getppid()

    def watch() -> None:
        while True:
            time.sleep(interval)
            if os.getppid() != parent:
                _stop_this_worker()

    threading.Thread(target=watch, name="sonara-parent-watch", daemon=True).start()
    return True

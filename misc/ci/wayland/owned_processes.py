"""Reap detached descendants created by the engine's setsid-based launcher (Linux)."""

import ctypes
import errno
import os
import signal
import time
from pathlib import Path


def allow_parent_debugger():
    # Yama permits this runner and its debugger children to inspect only the
    # process that opts in. The permission survives exec; no sysctl is changed.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(0x59616D61, os.getppid(), 0, 0, 0) != 0 and ctypes.get_errno() != errno.EINVAL:
        raise OSError(ctypes.get_errno(), "PR_SET_PTRACER")


def adopt_descendants():
    # PR_SET_CHILD_SUBREAPER: detached test games return to this runner if their
    # editor/server exits before reaping them. This does not affect other apps.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_CHILD_SUBREAPER")


def reap_adopted():
    """Call after all directly managed Popen children have been waited on."""
    leftovers = []
    children = Path(f"/proc/self/task/{os.getpid()}/children")
    deadline = time.monotonic() + 2
    while True:
        pids = [int(pid) for pid in children.read_text().split()]
        if not pids:
            return leftovers
        for pid in pids:
            reaped, _ = os.waitpid(pid, os.WNOHANG)
            if reaped:
                continue
            if pid not in leftovers:
                leftovers.append(pid)
                os.kill(pid, signal.SIGTERM)
            if time.monotonic() >= deadline:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
        time.sleep(0.02)

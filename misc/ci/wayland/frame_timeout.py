"""GDB probe, sourced at entry to wait_frame_suspend_ms with owned Weston paused."""

import json
import os
import signal
import time
from pathlib import Path

import gdb

output = Path(os.environ["REDOT_WAYLAND_TEST_OUTPUT"])
compositor = int(os.environ["REDOT_WAYLAND_TEST_COMPOSITOR"])
result = {"frame_timeout_verified": False, "frame_recovered": False, "poll_calls": 0}


class PollBreakpoint(gdb.Breakpoint):
    def stop(self):
        frame = gdb.newest_frame().older()
        while frame:
            if "WaylandThread::wait_frame_suspend_ms" in (frame.name() or ""):
                result["poll_calls"] += 1
                break
            frame = frame.older()
        return False


class WaitFinished(gdb.FinishBreakpoint):
    def stop(self):
        result["frame_wait_seconds"] = time.monotonic() - started
        result["frame_wait_return"] = bool(self.return_value) if self.return_value is not None else None
        return True


try:
    # Read debug information rather than relying on CPU-specific argument/return registers.
    timeout_ms = int(gdb.parse_and_eval("p_timeout"))
    result["frame_timeout_ms"] = timeout_ms
    if timeout_ms <= 0:
        raise gdb.GdbError("The frame probe requires a positive timeout")
    state = gdb.parse_and_eval("this")
    window = state["windows"]["head_element"]
    active_windows = 0
    while window:
        active_windows += not bool(window["data"]["value"]["suspended"])
        window = window["next"]
    if not active_windows:
        raise gdb.GdbError("The frame probe requires a non-suspended window")
    result["active_windows"] = active_windows
    gdb.set_convenience_variable("probe_wayland", state)
    gdb.execute("set variable $probe_wayland->frame = false")

    # Already-buffered callbacks must finish their normal proxy cleanup. Suppress
    # only their readiness flag while the compositor cannot produce fresh frames.
    watch = gdb.Breakpoint("$probe_wayland->frame", type=gdb.BP_WATCHPOINT)
    gdb.execute(f"commands {watch.number}\nsilent\nset variable $probe_wayland->frame = false\ncontinue\nend")
    poll = PollBreakpoint("poll", internal=True)
    finished = WaitFinished(gdb.newest_frame(), internal=True)
    started = time.monotonic()
    gdb.execute("continue")
    watch.delete()
    poll.delete()
    elapsed = result.get("frame_wait_seconds", 0)
    # Allow scheduling/debugger overhead, but reject an immediate return and a
    # wait exceeding the requested budget by more than one second.
    if (
        result.get("frame_wait_return") is not False
        or not result["poll_calls"]
        or elapsed < timeout_ms / 1000 * 0.9
        or elapsed > timeout_ms / 1000 + 1
    ):
        raise gdb.GdbError("Frame timeout did not meet its return, polling and elapsed-time assertions")
    result["frame_timeout_verified"] = True

    # Require a real frame callback after resuming, then let the process exit
    # normally. A leaked prepare_read must not strand either display reader.
    recovered = gdb.Breakpoint("WaylandThread::_frame_wl_callback_on_done", temporary=True, internal=True)
    os.kill(compositor, signal.SIGCONT)
    gdb.execute("continue")
    if "WaylandThread::_frame_wl_callback_on_done" not in (gdb.newest_frame().name() or ""):
        raise gdb.GdbError("No frame callback after compositor recovery")
    result["frame_recovered"] = True
    (output / "frame.json").write_text(json.dumps(result, indent=2))
    gdb.execute("continue")
finally:
    (output / "frame.json").write_text(json.dumps(result, indent=2))

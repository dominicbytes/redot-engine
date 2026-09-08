#!/usr/bin/env python3
"""Pause an owned compositor at a precise client lifecycle breakpoint."""

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from owned_processes import adopt_descendants, reap_adopted

p = argparse.ArgumentParser()
p.add_argument("binary", type=Path)
p.add_argument("--output", required=True, type=Path)
p.add_argument("--phase", choices=["destroy", "window_destroy", "wait_frame_suspend_ms"], default="destroy")
p.add_argument("--deadline", type=float, default=5)
p.add_argument("--exit-timeout", type=float, default=30, help="Normal-exit deadline after verified frame recovery")
init_mode = p.add_mutually_exclusive_group()
init_mode.add_argument("--serialize-init", action="store_true", help="Serialize baseline initialization under GDB")
init_mode.add_argument(
    "--fail-cursor-init", action="store_true", help="Force cursor initialization to fail before thread startup"
)
a = p.parse_args()
if a.fail_cursor_init and a.phase != "destroy":
    p.error("--fail-cursor-init requires --phase destroy")
symbols = subprocess.run(
    ["nm", "--defined-only", "--demangle", str(a.binary.resolve())], capture_output=True, text=True, timeout=15
)
if symbols.returncode or f" WaylandThread::{a.phase}(" not in symbols.stdout:
    p.error("The test binary needs Wayland function symbols; build with debug_symbols=yes before stripping it")
if a.phase == "wait_frame_suspend_ms":
    sections = subprocess.check_output(["readelf", "--section-headers", str(a.binary.resolve())], text=True, timeout=15)
    if ".debug_info" not in sections and ".zdebug_info" not in sections:
        p.error("The frame-timeout test needs retained DWARF debug information; do not strip this test binary")
adopt_descendants()
a.output = a.output.resolve()
a.output.mkdir(parents=True, exist_ok=True)
# Unix socket paths are short even when the checkout or output directory is long.
runtime_directory = tempfile.TemporaryDirectory(prefix="redot-wayland-")
runtime = Path(runtime_directory.name)
env = os.environ.copy()
env.update(XDG_RUNTIME_DIR=str(runtime), WAYLAND_DISPLAY="redot-test", LIBGL_ALWAYS_SOFTWARE="1", DRI_PRIME="0")
env.pop("DISPLAY", None)
env["REDOT_WAYLAND_TEST_OUTPUT"] = str(a.output)
for kind in ["CONFIG", "DATA", "CACHE"]:
    path = a.output / kind.lower()
    path.mkdir(exist_ok=True)
    env[f"XDG_{kind}_HOME"] = str(path)
weston_log = (a.output / "weston-stderr.log").open("w")
weston = subprocess.Popen(
    [
        "weston",
        "--backend=headless",
        "--renderer=pixman",
        "--socket=redot-test",
        "--no-config",
        "--idle-time=0",
        "--width=1280",
        "--height=720",
        f"--log={a.output / 'weston.log'}",
    ],
    env=env,
    stdout=weston_log,
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
gdb = None
env["REDOT_WAYLAND_TEST_COMPOSITOR"] = str(weston.pid)
result = {
    "phase": a.phase,
    "binary": str(a.binary.resolve()),
    "timed_out": False,
    "reached_breakpoint": False,
    "serialized_init": a.serialize_init,
    "failed_cursor_init": a.fail_cursor_init,
}
try:
    deadline = time.monotonic() + 10
    while not (runtime / "redot-test").exists():
        if weston.poll() is not None or time.monotonic() >= deadline:
            raise RuntimeError("Owned Weston failed to become ready")
        time.sleep(0.05)
    marker = a.output / "breakpoint.json"
    if marker.exists():
        raise RuntimeError("Use a fresh output directory")
    commands = a.output / "probe.gdb"
    commands.write_text(
        "\n".join(
            [
                "set pagination off",
                "set confirm off",
                "set debuginfod enabled off",
                "set auto-solib-add off",
                "set disable-randomization off",
                "set print thread-events off",
                "python",
                "import gdb, json",
                "stop_signal = None",
                'gdb.events.stop.connect(lambda event: globals().update(stop_signal=getattr(event, "stop_signal", None)))',
                f'gdb.events.new_thread.connect(lambda event: open({str(a.output / "startup.json")!r}, "w").write(json.dumps({{"pid": gdb.selected_inferior().pid}})))',
                f'gdb.events.exited.connect(lambda event: open({str(a.output / "exit.json")!r}, "w").write(json.dumps({{"exit_code": getattr(event, "exit_code", None)}})))',
                "end",
                f"break WaylandThread::{a.phase}",
                *(
                    [
                        "break WaylandThread::init",
                        "run",
                        "set scheduler-locking on",
                        "finish",
                        "set scheduler-locking off",
                        "delete 2",
                        "continue",
                    ]
                    if a.serialize_init
                    else ["break WaylandThread::_load_cursor_theme", "run", "return (int)0", "delete 2", "continue"]
                    if a.fail_cursor_init
                    else ["run"]
                ),
                "disable breakpoints",
                "python",
                "import gdb, json, os, signal",
                f'if "WaylandThread::{a.phase}" not in (gdb.newest_frame().name() or ""):',
                '    gdb.execute("thread apply all bt")',
                '    gdb.execute("kill")',
                '    gdb.execute("quit 2")',
                f"os.kill({weston.pid}, signal.SIGSTOP)",
                f'open({str(marker)!r}, "w").write(json.dumps({{"pid": gdb.selected_inferior().pid}}))',
                "end",
                f"source {Path(__file__).with_name('frame_timeout.py').resolve()}"
                if a.phase == "wait_frame_suspend_ms"
                else "finish"
                if a.fail_cursor_init
                else "continue",
                "thread apply all bt",
                "python",
                f'open({str(a.output / "completed.json")!r}, "w").write(json.dumps({{"inferior_alive": bool(gdb.selected_inferior().pid), "stop_signal": stop_signal, "function_returned": bool(gdb.selected_inferior().pid) and stop_signal is None and gdb.newest_frame().name() != "WaylandThread::{a.phase}"}}))',
                'if gdb.selected_inferior().pid: gdb.execute("kill")',
                "end",
                "quit",
                "",
            ]
        )
    )
    with (a.output / "gdb.log").open("w") as log:
        gdb = subprocess.Popen(
            [
                "gdb",
                "-q",
                "-batch",
                "-x",
                str(commands),
                "--args",
                str(a.binary.resolve()),
                "--display-driver",
                "wayland",
                "--rendering-method",
                "gl_compatibility",
                "--audio-driver",
                "Dummy",
                "--disable-crash-handler",
                "--verbose",
                "--project-manager",
                "--quit-after",
                "20",
            ],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.monotonic() + 30
        while not marker.exists() and gdb.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if not marker.exists():
            result["startup_timeout"] = gdb.poll() is None
            startup = a.output / "startup.json"
            if gdb.poll() is None and startup.exists():
                os.kill(json.loads(startup.read_text())["pid"], signal.SIGINT)
                try:
                    gdb.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            raise RuntimeError("Client never reached the requested breakpoint; inspect gdb.log")
        result["reached_breakpoint"] = True
        inferior = json.loads(marker.read_text())["pid"]
        started = time.monotonic()
        try:
            try:
                gdb.wait(timeout=a.deadline)
            except subprocess.TimeoutExpired:
                progress_file = a.output / "frame.json"
                progress = json.loads(progress_file.read_text()) if progress_file.exists() else {}
                if progress.get("frame_timeout_verified") and progress.get("frame_recovered"):
                    gdb.wait(timeout=a.exit_timeout)
                else:
                    raise
        except subprocess.TimeoutExpired:
            result["timed_out"] = True
            os.kill(inferior, signal.SIGINT)
            try:
                gdb.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(gdb.pid, signal.SIGKILL)
                gdb.wait()
        result["seconds_after_pause"] = time.monotonic() - started
        result["gdb_exit_code"] = gdb.returncode
        if (a.output / "completed.json").exists():
            result.update(json.loads((a.output / "completed.json").read_text()))
        if (a.output / "exit.json").exists():
            result.update(json.loads((a.output / "exit.json").read_text()))
        if (a.output / "frame.json").exists():
            result.update(json.loads((a.output / "frame.json").read_text()))
finally:
    if gdb is not None and gdb.poll() is None:
        os.killpg(gdb.pid, signal.SIGKILL)
        gdb.wait()
    if weston.poll() is None:
        os.kill(weston.pid, signal.SIGCONT)
        os.killpg(weston.pid, signal.SIGTERM)
        try:
            weston.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(weston.pid, signal.SIGKILL)
            weston.wait()
    weston_log.close()
    result["leftovers"] = reap_adopted()
    runtime_directory.cleanup()
    (a.output / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
passed = result["reached_breakpoint"] and not result["timed_out"] and result.get("gdb_exit_code") == 0
if a.phase == "wait_frame_suspend_ms":
    passed = passed and result.get("frame_timeout_verified") is True and result.get("frame_recovered") is True
    passed = passed and result.get("exit_code") == 0 and result.get("inferior_alive") is False
elif a.fail_cursor_init:
    passed = passed and result.get("function_returned") is True
else:
    passed = passed and result.get("exit_code") == 0 and result.get("inferior_alive") is False
sys.exit(0 if passed else 1)

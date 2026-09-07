#!/usr/bin/env python3
"""Local before/after probe; logs each owned process and bounds cleanup."""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from owned_processes import adopt_descendants, allow_parent_debugger, reap_adopted

p = argparse.ArgumentParser()
p.add_argument("binary", type=Path)
p.add_argument("--backend", choices=["wayland", "x11"], default="wayland")
p.add_argument("--iterations", type=int, default=5)
p.add_argument("--timeout", type=float, default=60, help="Startup deadline in seconds")
p.add_argument("--shutdown-timeout", type=float, default=15)
p.add_argument("--output", required=True, type=Path)
p.add_argument("--mode", choices=["project-manager", "editor", "runtime"], default="project-manager")
p.add_argument("--project", type=Path)
p.add_argument("--software", action="store_true")
p.add_argument("--close", choices=["smoke", "hyprland"], default="smoke")
p.add_argument("--editor-game", action="store_true")
args = p.parse_args()
adopt_descendants()
args.output.mkdir(parents=True, exist_ok=True)
env = os.environ.copy()
for kind in ["CONFIG", "DATA", "CACHE"]:
    folder = args.output.resolve() / kind.lower()
    folder.mkdir(exist_ok=True)
    env[f"XDG_{kind}_HOME"] = str(folder)
if args.software:
    env["LIBGL_ALWAYS_SOFTWARE"] = "1"
    env["DRI_PRIME"] = "0"
command = [
    str(args.binary.resolve()),
    "--display-driver",
    args.backend,
    "--rendering-method",
    "gl_compatibility",
    "--audio-driver",
    "Dummy",
    "--disable-crash-handler",
    "--verbose",
]
if args.close == "smoke":
    command += ["--quit-after", "20"]
if args.mode != "runtime":
    command.append("--" + args.mode)
if args.project:
    command += ["--path", str(args.project.resolve())]
if args.editor_game:
    command += ["--", "--lifecycle-editor-cycle"]
results = []
for iteration in range(args.iterations):
    log_path = args.output / f"{iteration:03}.log"
    start = time.monotonic()
    with log_path.open("w") as log:
        proc = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
            preexec_fn=allow_parent_debugger,
        )
        observed_backend = None
        mapped = False
        close_seconds = None
        try:
            if args.close == "hyprland":
                deadline = start + args.timeout
                while time.monotonic() < deadline and proc.poll() is None:
                    try:
                        clients = json.loads(subprocess.check_output(["hyprctl", "-j", "clients"], timeout=2))
                    except subprocess.TimeoutExpired:
                        # A slow compositor query is not an engine shutdown timeout.
                        continue
                    owned = [w for w in clients if w["pid"] == proc.pid and w.get("mapped")]
                    ready = True
                    if args.mode == "editor":
                        marker = "LIFECYCLE_EDITOR_GAME_STOPPED" if args.editor_game else "LIFECYCLE_EDITOR_READY"
                        ready = marker in log_path.read_text()
                    elif args.mode == "project-manager":
                        ready = "EditorTheme: Generating new styles." in log_path.read_text()
                    elif args.mode == "runtime":
                        ready = "LIFECYCLE_READY" in log_path.read_text()
                    if owned and ready:
                        window = owned[0]
                        observed_backend = "x11" if window["xwayland"] else "wayland"
                        mapped = True
                        time.sleep(0.5)
                        address = window["address"]
                        subprocess.run(
                            ["hyprctl", "dispatch", f'hl.dsp.window.close({{ window = "address:{address}" }})'],
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            timeout=2,
                            check=True,
                        )
                        close_seconds = time.monotonic() - start
                        deadline = time.monotonic() + args.shutdown_timeout
                        break
                    time.sleep(0.05)
                code = proc.wait(timeout=max(0.01, deadline - time.monotonic()))
            else:
                code = proc.wait(timeout=args.timeout)
            status = "exited"
        except subprocess.TimeoutExpired:
            with (args.output / f"{iteration:03}.backtrace").open("w") as bt:
                try:
                    subprocess.run(
                        [
                            "gdb",
                            "--batch",
                            "-iex",
                            "set debuginfod enabled off",
                            "-p",
                            str(proc.pid),
                            "-ex",
                            "set pagination off",
                            "-ex",
                            "thread apply all bt",
                        ],
                        stdout=bt,
                        stderr=subprocess.STDOUT,
                        timeout=8,
                    )
                except subprocess.TimeoutExpired:
                    bt.write("Debugger timed out.\n")
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            code = proc.returncode
            status = "timeout"
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
            leftovers = reap_adopted()
    if leftovers:
        status = "leftover-processes"
    if status == "exited" and args.close == "hyprland" and (not mapped or observed_backend != args.backend):
        status = "backend-or-mapping-failure"
    if status == "exited" and args.mode == "runtime" and "LIFECYCLE_BACKEND=" in log_path.read_text():
        expected = "Wayland" if args.backend == "wayland" else "X11"
        if f"LIFECYCLE_BACKEND={expected}" not in log_path.read_text():
            status = "backend-failure"
    game_report = None
    if args.editor_game:
        for line in log_path.read_text().splitlines():
            if line.startswith("LIFECYCLE_EDITOR_GAME_REPORT="):
                game_report = json.loads(line.split("=", 1)[1])
        expected = "Wayland" if args.backend == "wayland" else "X11"
        if status == "exited" and (not game_report or game_report["backend"] != expected or game_report["frames"] < 2):
            status = "game-render-or-backend-failure"
    result = {
        "iteration": iteration,
        "pid": proc.pid,
        "status": status,
        "observed_backend": observed_backend,
        "mapped": mapped,
        "close_seconds": round(close_seconds, 3) if close_seconds is not None else None,
        "shutdown_seconds": round(time.monotonic() - start - close_seconds, 3) if close_seconds is not None else None,
        "game_report": game_report,
        "leftovers": leftovers,
        "returncode": code,
        "seconds": round(time.monotonic() - start, 3),
        "log": str(log_path),
    }
    results.append(result)
    print(json.dumps(result), flush=True)
    (args.output / "results.json").write_text(json.dumps({"command": command, "results": results}, indent=2))
    if status != "exited" or code != 0:
        break
sys.exit(
    0
    if len(results) == args.iterations and all(r["status"] == "exited" and r["returncode"] == 0 for r in results)
    else 1
)

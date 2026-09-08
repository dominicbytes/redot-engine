#!/usr/bin/env python3
"""Failed GUI initialization must report an error without crashing during cleanup."""

import argparse
import json
import os
import resource
import signal
import subprocess
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("binary", type=Path)
p.add_argument("--output", required=True, type=Path)
a = p.parse_args()
a.output = a.output.resolve()
a.output.mkdir(parents=True, exist_ok=True)
env = os.environ.copy()
env.pop("DISPLAY", None)
env["WAYLAND_DISPLAY"] = str(a.output / "absent-wayland-socket")
for kind in ["RUNTIME", "CONFIG", "DATA", "CACHE"]:
    directory = a.output / kind.lower()
    directory.mkdir(mode=0o700, exist_ok=True)
    env[f"XDG_{kind}_HOME" if kind != "RUNTIME" else "XDG_RUNTIME_DIR"] = str(directory)
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
results = []
for backend in ["x11", "wayland"]:
    log_path = a.output / f"{backend}.log"
    with log_path.open("w") as log:
        proc = subprocess.Popen(
            [
                str(a.binary.resolve()),
                "--display-driver",
                backend,
                "--rendering-method",
                "gl_compatibility",
                "--audio-driver",
                "Dummy",
                "--disable-crash-handler",
                "--project-manager",
            ],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            code = proc.wait(timeout=20)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
    text = log_path.read_text()
    passed = (
        code == 1
        and "X11 Display is not available" in text
        and "all display drivers failed" in text
        and "never started" not in text
    )
    results.append({"backend": backend, "returncode": code, "passed": passed})
    (a.output / "result.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results[-1]))
raise SystemExit(0 if all(row["passed"] for row in results) else 1)

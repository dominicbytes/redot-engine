# Wayland lifecycle regression checks

These Linux integration checks exercise a real display connection. They complement
the headless unit suite, which does not create a Wayland display server.

## Isolated compositor failures

Install Python 3, GDB, binutils, Weston, Mesa's software OpenGL driver, and libdecor with its
Cairo plugin. The runner uses Weston's headless backend and Pixman renderer,
an isolated runtime directory, and software OpenGL for Redot. It unsets `DISPLAY`
so a successful X11 fallback cannot hide a Wayland failure.

Run from the repository root, using an editor executable built with
`debug_symbols=yes`. The frame test also requires retained DWARF debug information.
`dev_mode=yes` alone does not preserve symbols. The runner checks these requirements
before starting the compositor:

```sh
python3 misc/ci/wayland/paused_compositor.py bin/redot.linuxbsd.editor.x86_64 \
    --phase destroy --output /tmp/redot-wayland-destroy
python3 misc/ci/wayland/paused_compositor.py bin/redot.linuxbsd.editor.x86_64 \
    --phase window_destroy --output /tmp/redot-wayland-window-destroy
python3 misc/ci/wayland/paused_compositor.py bin/redot.linuxbsd.editor.x86_64 \
    --phase wait_frame_suspend_ms --output /tmp/redot-wayland-frame
```

Each command starts its own compositor, waits for its socket, starts the project
manager under GDB, and pauses only that compositor at the selected engine
function. The destruction checks require normal process exit while the compositor
remains paused. The frame check asserts a non-suspended window, clears any pending
frame, and suppresses readiness from already-buffered callbacks with a watchpoint
while their normal proxy cleanup runs. It requires entry into polling, a false
return, and elapsed time between 90% of the requested timeout and that timeout
plus one second of scheduling/debugger allowance. It then resumes its compositor,
requires a fresh frame callback, and requires normal process exit. Startup failure,
missing breakpoints, crashes, early returns, and failed recovery fail the check.

For an unpatched baseline that stalls during concurrent initialization, add
`--serialize-init` to make GDB run `WaylandThread::init()` with only the calling
thread scheduled. Other threads resume before the selected fault checkpoint.
This diagnostic workaround isolates teardown from the separate startup race;
it must not be counted as a successful normal-startup test. Test the patched
binary without this option.

To test partial initialization cleanup, run the destruction check with
`--fail-cursor-init`. GDB forces cursor-theme initialization to return failure
after registry, seat and libdecor setup but before event-thread creation. The
check then pauses the compositor at destruction and requires that function to
return without a hang or crash, then deliberately terminates the process. This
isolates Wayland cleanup from subsequent fallback to another display backend.

The startup deadline is 30 seconds; the post-breakpoint deadline defaults to
5 seconds. After verified frame recovery, normal startup/exit has an additional
30-second deadline (`--exit-timeout`). The frame budget is asserted independently
inside GDB. Logs, backtraces, and machine-readable results go in `--output`. Use a
fresh output directory for each invocation. Detached compositor children are
cleaned up by the runner and may appear in the `leftovers` diagnostic.

On memory-constrained hosts, preserve the original debug executable and create a
probe copy for the destruction checks using `objcopy --strip-debug INPUT OUTPUT`. This retains function
symbols and unwind information while avoiding GDB loading the engine's large
DWARF data. Use the original executable for the frame test, and cap the test
process group's memory with a local resource manager. Do not run multiple
full-symbol debuggers or automatic crash symbolizers alongside a linker.

Linux CI runs all three phases in the Mono editor and ThreadSanitizer editor
jobs before stripping artifacts. The sanitizer job therefore exercises native
Wayland display lifecycle in addition to its headless unit tests.

## Normal close in Hyprland

`run_lifecycle.py` can verify the actual mapped backend using Hyprland's client
list and request a normal close of the window belonging to the test process.
It requires Hyprland's Lua `hl.dsp.window.close` dispatcher. It does not change
the compositor configuration or close unrelated windows.

```sh
python3 misc/ci/wayland/run_lifecycle.py /path/to/redot-probe \
    --backend wayland --mode project-manager --close hyprland --software \
    --iterations 100 --output /tmp/redot-pm-cycles
cp -R misc/ci/wayland/project /tmp/redot-lifecycle-project
python3 misc/ci/wayland/run_lifecycle.py /path/to/redot-probe \
    --backend wayland --mode editor --editor-game --close hyprland --software \
    --project /tmp/redot-lifecycle-project --timeout 40 \
    --iterations 100 --output /tmp/redot-editor-cycles
```

The disposable project's editor plugin launches its main scene, waits for the
game to report its backend and at least two rendered frames, and stops it through
the editor. The runner then closes the editor and requires exit status zero with
no live detached children. Run these tests sequentially; each creates visible
windows. First-time project imports can take longer than later cycles. `--timeout` bounds
startup (60 seconds by default); `--shutdown-timeout` bounds exit after the close
request (15 seconds by default). Results record both phases. Project-manager
checks wait for theme generation after the splash; game checks require the
fixture to report rendered frames. Slow client-list queries are retried only
within the startup deadline.

For the Xwayland control, set `display/display_server/driver.linuxbsd` in the
disposable project to `x11` and pass `--backend x11`. The child's project setting
matters independently of the editor's command-line backend.

`--software` explicitly sets `LIBGL_ALWAYS_SOFTWARE=1` and `DRI_PRIME=0` to isolate
display lifecycle from GPU probing. Repeat selected checks without that option
for the machine's normal renderer. Software results do not establish physical
GPU, mixed-DPI, input, hotplug, or embedding compatibility.

The default `--close smoke` uses `--quit-after` and is only a startup/exit smoke
check. Use `--close hyprland` for mapped-backend and normal-close evidence.

The runners adopt and reap their own detached descendants. On Hyprland, the test
child opts into tracing by its parent and the parent's debugger children so
timeout backtraces work with Yama enabled. No system-wide ptrace setting is changed.

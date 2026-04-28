# winvision-mcp

**Glance for Windows desktop apps.** A production-ready MCP server that lets opencode, Claude Code, Cursor, and any other MCP-aware client take screenshots, walk the UI Automation tree, drive native Windows applications, and run vision-LLM-powered QA assertions against any Win32, WinForms, WPF, WinUI, UWP, Electron, or Chromium-based desktop app — without baking an API key into the server (assertions use **MCP sampling** so the connected client's LLM does the grading).

```
opencode "take an annotated screenshot of Calculator and click the 7 button"
        ↓
        winvision-mcp (stdio)
        ├─ screenshot_annotated  →  numbered marks over Buttons/Edits/...
        ├─ invoke_element        →  UIA InvokePattern on the picked mark
        └─ assert_visual         →  client LLM grades the result
```

---

## Install

```sh
git clone https://github.com/winvision/winvision-mcp.git
cd winvision-mcp
uv sync                    # or: pip install -e ".[dev]"
winvision-mcp --help
winvision-mcp doctor       # sanity check (DPI, COM, admin, monitors, ...)
```

`winvision-mcp` is a console script. By default (no subcommand) it runs over **stdio**, which is what every MCP client expects. The `http` subcommand exposes Streamable HTTP for remote/WSL2 use.

### Requirements

- Windows 11 (Windows 10 22H2 should also work; not the focus).
- Python 3.11+.
- Optional but recommended: `uv` for dependency management.
- Optional: signed UIAccess install (see below) to drive elevated windows.

---

## Wire it up

### opencode (`~/.config/opencode/opencode.json`)

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "winvision": {
      "type": "local",
      "command": ["winvision-mcp", "stdio"],
      "enabled": true,
      "timeout": 30000
    }
  }
}
```

### Claude Desktop (`%APPDATA%\Claude\claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "winvision": {
      "command": "winvision-mcp",
      "args": ["stdio"]
    }
  }
}
```

### Cursor (Settings → MCP)

Add a stdio server: command `winvision-mcp`, args `stdio`.

### WSL2 / remote — Streamable HTTP

Run on the Windows host:

```powershell
winvision-mcp http --host 0.0.0.0 --port 8787
```

From WSL2, point your client at `http://<windows-host-ip>:8787`. (Use `(Get-NetIPAddress -InterfaceAlias 'vEthernet (WSL)').IPAddress` from PowerShell to find the right address.)

> **Security note:** Streamable HTTP has no auth in v1. Bind to `127.0.0.1` unless you own the network, and prefer `strict` allowlist mode (see [Security](#security)).

---

## UIAccess (optional)

By default, Windows lets non-elevated processes drive their own windows but blocks `SetForegroundWindow` against elevated apps. To automate elevated targets (e.g. Task Manager, an installer running as admin), the server binary must:

1. Be **signed** by a cert in `LocalMachine\TrustedPublisher`.
2. Live under `%ProgramFiles%\` (or `%SystemRoot%\System32\`).
3. Embed a manifest with `uiAccess="true"`.

`scripts/sign_and_install.ps1` does all three:

```powershell
# Run from an elevated PowerShell prompt:
powershell -ExecutionPolicy Bypass -File scripts\sign_and_install.ps1
```

This bundles the package via `pyinstaller`, generates a self-signed code-signing cert, trusts it on the local machine, signs the binary, and copies it to `C:\Program Files\WinVision\winvision-mcp.exe`. Update your MCP client config to point at that path instead of the PATH-resolved console script.

> **You don't need this for normal apps** (Notepad, Calc, Chromium-based editors, etc.) — UIAccess is only required when the target window has higher integrity than your shell.

---

## Tool catalog

All tools accept Pydantic-validated args and return either an MCP `Image`, a structured JSON dict, or a `ToolError` envelope (`{error, message, details}`). Tools never raise unhandled exceptions out of the server.

### Capture (`capture_tools.py`)

| Tool | Purpose |
|---|---|
| `screenshot_desktop(monitor=0)` | Capture a monitor or the virtual desktop. |
| `screenshot_window(hwnd, title_regex, process_name)` | Capture one window via WGC, falling back to PrintWindow. |
| `screenshot_region(x, y, w, h, monitor=0)` | Capture an arbitrary rectangle. |
| `screenshot_element(automation_id, name, window_title)` | Resolve an element → BoundingRectangle → crop. |
| `screenshot_annotated(window_title, filter_types, max_elements=60)` | **The flagship.** Numbered Set-of-Marks overlay on every interactable UIA element + a legend mapping each mark to `{automation_id, name, control_type, rect, handle}`. |
| `tile_screenshot(window_title, tile_size=1072)` | Vision-model-friendly chunking for high-DPI captures. |
| `list_monitors()` | Enumerate monitors with rects. |

### UI Automation (`uia_tools.py`)

| Tool | Purpose |
|---|---|
| `get_ui_tree(window_title, depth=8, visible_only, interactable_only, max_nodes=500)` | Pruned JSON tree. |
| `get_ui_tree_text(window_title, depth=6)` | ASCII tree, cheap for LLMs. |
| `find_elements(query, limit=50)` | Composable `ElementQuery` (`name`, `name_regex`, `automation_id`, `control_type`, `class_name`, `window_title`, `ancestor_*`, `descendant_*`). |
| `get_element(ref)` | Resolve `ElementRef` (handle or query). |
| `get_focused_element()` | Currently-focused control. |
| `list_windows(visible_only=True)` | Enumerate top-level windows. |

### Interaction (`input_tools.py`)

UIA-first, SendInput-fallback. Every interaction focuses the target window first.

| Tool | Notes |
|---|---|
| `invoke_element(ref)` | InvokePattern → SelectionItem → Toggle → click_at(center). |
| `set_value(ref, value)` | ValuePattern.SetValue → focus + Ctrl+A + type. |
| `toggle_element(ref)` | TogglePattern. |
| `select_item(ref)` | SelectionItemPattern. |
| `expand_collapse(ref, action)` | ExpandCollapsePattern. |
| `scroll_element(ref, direction, amount)` | ScrollPattern. |
| `click_at(x, y, button, count)` | SendInput, normalized 0–65535 absolute coords + `MOUSEEVENTF_VIRTUALDESK`. Multi-monitor safe. |
| `drag(from_x, from_y, to_x, to_y, duration_ms=300)` | Smoothed drag. |
| `type_text(text, interval_ms=5)` | KEYEVENTF_UNICODE — full Unicode. |
| `send_keys(keys)` | pywinauto sequence (`"^a{DEL}Hello{ENTER}"`). |
| `focus_window(title_regex \| hwnd)` | AttachThreadInput trick + ALT-press. |
| `wait_for_element(query, timeout_s=10)` | Self-healing poll. |
| `wait_for_idle(window_title, timeout_s=5)` | WaitForInputIdle + CPU quiescence. |

### App lifecycle (`app_tools.py`)

| Tool | Notes |
|---|---|
| `launch_app(path \| AUMID, args, cwd, wait_for_window_s=5)` | Returns `{pid, hwnd}`. |
| `kill_process(pid \| process_name, force, dry_run)` | **Allowlist-gated.** |
| `list_processes()` | Snapshot via psutil. |
| `is_running(process_name)` | Quick check + matching PIDs. |

### QA (`qa_tools.py`)

| Tool | Notes |
|---|---|
| `assert_visual(description, window_title, model_hint)` | LLM-judged via **MCP sampling** — no API key in the server. Returns `{passed, confidence, reasoning}`. |
| `assert_element_visible(query)` | Deterministic, free. |
| `assert_text_present(text, window_title, use_ocr=False)` | Walks UIA Name/Value; optional Tesseract fallback. |
| `baseline_capture(name, window_title, notes)` | Save PNG + metadata; content-hashed in SQLite. |
| `baseline_compare(name, window_title, threshold_ssim=0.98, mask_regions)` | SSIM + connected-component diff. Returns annotated diff PNG. |
| `list_baselines()` | All stored baselines. |
| `start_recording(name)` / `stop_recording()` | Append every tool invocation to a JSONL script. |
| `replay_script(path, speed, strict)` | **Zero LLM cost** — replays deterministically. |

### System (`system_tools.py`)

| Tool | Notes |
|---|---|
| `get_system_info()` | OS, monitors, DPI, user, admin status, UIAccess flag. |
| `read_clipboard()` | Text or image. |
| `write_clipboard(content)` | Allowlist-gated. |
| `get_process_memory(pid)` | `{working_set, private, handles, threads}` — catch Electron leaks. |
| `get_allowlist_policy()` | Read-only snapshot. |

---

## Recipe cookbook

### 1. Take an annotated screenshot of Notepad and click File → Save As

```text
> open Notepad
> tools/call screenshot_annotated {"window_title": "Untitled - Notepad"}
↳ legend: {"3": {"automation_id":"FileMenuItem", ...}, ...}
> tools/call invoke_element {"ref": {"handle": "<from legend>"}}
> tools/call invoke_element {"ref": {"automation_id": "SaveAsMenuItem"}}
```

### 2. Regression-test Calculator: type 2+2, assert result == 4

```text
> tools/call launch_app  {"path": "calc.exe"}
> tools/call wait_for_element {"query": {"automation_id": "num2Button", "window_title_regex":"Calculator"}}
> tools/call invoke_element  {"ref": {"automation_id": "num2Button"}}
> tools/call invoke_element  {"ref": {"automation_id": "plusButton"}}
> tools/call invoke_element  {"ref": {"automation_id": "num2Button"}}
> tools/call invoke_element  {"ref": {"automation_id": "equalButton"}}
> tools/call assert_text_present {"text": "4", "window_title_regex": "Calculator"}
```

### 3. Monitor Electron memory leak over 1 hour

```python
# Driving from a notebook / loop client:
import time
from anthropic_mcp_client import client  # any MCP client
pid = client.call("is_running", {"process_name": "MyElectronApp.exe"})["pids"][0]
samples = []
for _ in range(60):
    samples.append(client.call("get_process_memory", {"pid": pid}))
    time.sleep(60)
print("WS growth:", samples[-1]["working_set"] - samples[0]["working_set"])
```

### 4. Record a 10-step session manually, then replay in CI with zero LLM cost

```text
> tools/call start_recording {"session_name": "save-as-flow"}
… (drive the app via tools/call invoke_element / type_text / …)
> tools/call stop_recording
↳ {"path": "%LOCALAPPDATA%\\WinVision\\recordings\\save-as-flow.jsonl"}

# In CI:
> tools/call replay_script {"path": "<above>", "speed": 4, "strict": true}
```

`replay_script` invokes tools by name — it never calls the LLM. It also skips `assert_visual` (which needs a live MCP context); use `assert_element_visible` / `assert_text_present` / `baseline_compare` for replay-safe assertions.

### 5. Visual assertion: no red error toast

```text
> tools/call assert_visual {"description": "no red error toast is visible anywhere on screen", "window_title": "MyApp"}
↳ {"passed": true, "confidence": 0.93, "reasoning": "no red toast or error banner present"}
```

### 6. Multi-app: Outlook → Notepad copy

```text
> tools/call launch_app {"path": "outlook.exe"}
> tools/call wait_for_element {"query": {"control_type": "Window", "window_title_regex": "Outlook"}}
> tools/call find_elements {"query": {"control_type": "Document", "window_title_regex": "Outlook"}}
> tools/call send_keys {"keys": "^a^c"}
> tools/call launch_app {"path": "notepad.exe"}
> tools/call focus_window {"title_regex": "Untitled - Notepad"}
> tools/call send_keys {"keys": "^v"}
```

---

## Security

WinVision uses a layered policy:

- **Hard block list** (always enforced): `lsass.exe`, `winlogon.exe`, `csrss.exe`, `smss.exe`, `services.exe`, `wininit.exe`, ... cannot be killed via `kill_process` regardless of mode.
- **Allowlist mode** (configurable, default `permissive_with_confirm`):
  - `strict` — only entities on `WINVISION_ALLOWLIST_PROCESSES` / `_WINDOW_TITLES` are allowed.
  - `permissive_with_confirm` — destructive operations are allowed but logged to SQLite (one row per invocation) so you have a complete audit trail.
  - `off` — nothing is gated; the server prints a loud warning at startup.
- **Dry-run** flag on every destructive tool — returns "would do X" without doing X.
- **Invocation log** — every tool call (args hash, outcome, duration) is written to `${data_dir}/winvision.sqlite`.

Configure via env vars or `~/.winvision/config.toml`:

```toml
allowlist_mode = "strict"

[allowlist]
processes = ["notepad.exe", "calc.exe", "MyApp.exe"]
window_titles = ["MyApp", "Calculator", "Notepad"]
```

---

## Configuration reference

| Env var | Default | Purpose |
|---|---|---|
| `WINVISION_DATA_DIR` | `%LOCALAPPDATA%\WinVision` | DB + baselines + recordings + screenshots. |
| `WINVISION_ALLOWLIST_MODE` | `permissive_with_confirm` | `strict` \| `permissive_with_confirm` \| `off`. |
| `WINVISION_ALLOWLIST_PROCESSES` | `[]` | JSON array of allowed process names (strict mode). |
| `WINVISION_ALLOWLIST_WINDOW_TITLES` | `[]` | JSON array of allowed window-title substrings. |
| `WINVISION_CAPTURE_MAX_EDGE` | `1600` | Downsample longest edge to this many px. |
| `WINVISION_INPUT_SETTLE_MS` | `50` | Sleep after focus before sending input. |
| `WINVISION_LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR. |
| `WINVISION_UIA_WALK_TIMEOUT_S` | `8.0` | Wall-clock cap on any single UIA tree walk. Prevents accessibility-rich apps (VS Code, Office) from outliving the MCP client's request timeout. |
| `WINVISION_HTTP_HOST` | `127.0.0.1` | Bind host for HTTP transport. |
| `WINVISION_HTTP_PORT` | `8787` | Bind port for HTTP transport. |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Clicks land at the wrong pixel on a multi-monitor setup | The process isn't per-monitor-DPI-aware | We call `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` at startup; if you're running via a wrapper that ignores manifest hints, embed `manifest/winvision.manifest` (`<dpiAwareness>PerMonitorV2</dpiAwareness>`). |
| `focus_window` returns success but the window doesn't come forward | Target window has higher integrity than the server | Run `scripts/sign_and_install.ps1` and use the UIAccess binary from `C:\Program Files\WinVision\`. |
| Chromium / Electron windows return all-black screenshots | PrintWindow can't capture GPU-composited DWM surfaces | This is exactly why we use WGC by default (via the `windows-capture` Rust-backed binding). If you see this anyway, run `winvision-mcp doctor` to confirm WGC is enabled, and check `pip show windows-capture`. WGC requires Windows 10 1903+. |
| `get_ui_tree` returns one `region` node with no children for an Electron / Chromium / Skia / Flutter app | The app doesn't expose accessibility properties via UIA | Drop one rung: use `screenshot_window` (WGC handles these correctly) + the vision LLM to identify targets visually + `click_at(x, y)` + `assert_visual` for verdicts. UIA-based tools (`find_elements`, `invoke_element`) cannot help here — there are literally no accessible elements. |
| `get_ui_tree` for a WinForms app returns 2-3 nodes | Some legacy WinForms apps don't expose UIA reflection by default | Try driving them with WinAppDriver as a fallback (see `scripts/install_wad.ps1`), or set `backend="win32"` in pywinauto-direct flows. |
| First tool call after starting opencode times out (`MCP error -32001: Request timed out`), then every subsequent winvision tool returns `Not connected` | Your MCP client (opencode/Claude Desktop) severed the stdio session after the timeout. There is no in-session reconnect for stdio MCP — once severed it stays severed. | (1) Restart the MCP client. (2) Bump the client `timeout` to ≥ 60000 ms. (3) Always pass an explicit `window_title` / `window_title_regex` to `screenshot_annotated` — never let it default to "the foreground window," because the foreground when you're chatting *is* the MCP client. As of v1.0.1 the server refuses to walk known IDE/terminal foregrounds and every UIA walk is wall-clock-bounded by `WINVISION_UIA_WALK_TIMEOUT_S` (default 8 s). |
| `assert_visual` returns `passed=false` with `"sampling unavailable"` | Your MCP client doesn't support sampling | Use `assert_element_visible` / `assert_text_present` / `baseline_compare` for structural / visual-regression checks instead. |
| `screenshot_annotated` returns `error=ide_foreground_refused` | You called it with no `window_title` while opencode/Claude Desktop/VS Code/Terminal was the foreground window. Walking those is what timed out earlier versions. | Pass `window_title` (exact title) or `window_title_regex` (regex). E.g. `{"window_title_regex": "^OpMed CDP$"}`. |

---

## Layout

```
winvision-mcp/
├── pyproject.toml
├── README.md
├── LICENSE
├── manifest/winvision.manifest         # uiAccess=true template
├── scripts/                            # PS install scripts + smoke client
└── src/winvision_mcp/
    ├── __main__.py                     # Typer CLI (stdio | http | doctor | version)
    ├── server.py                       # FastMCP app + tool dispatch
    ├── config.py                       # Pydantic settings + TOML overlay
    ├── dpi.py                          # PER_MONITOR_AWARE_V2
    ├── diagnostics.py                  # `winvision-mcp doctor`
    ├── models.py                       # Shared Pydantic models
    ├── logging_setup.py                # structlog (pretty for stdio, JSON for HTTP)
    ├── capture/                        # mss + WGC + PrintWindow backends
    ├── uia/                            # tree, finder, patterns, cache
    ├── input/                          # SendInput, AttachThreadInput focus
    ├── annotate/                       # Set-of-Marks overlay
    ├── qa/                             # assertions, baselines, recorder, replayer
    ├── storage/                        # SQLite schema + access
    ├── security/                       # allowlist + dry-run
    └── tools/                          # MCP tool wrappers (capture/uia/input/app/qa/system)
```

## Non-goals (v1)

- No web/Electron frontend (separate project).
- No cloud sync of baselines.
- No support for games / Direct3D exclusive fullscreen — WGC declines those.
- No macOS / Linux desktop targets.

## License

MIT.

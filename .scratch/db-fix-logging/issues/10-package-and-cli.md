# Package layout & render CLI

Type: grilling
Status: resolved
Assignee: MyNameIs-13
Blocked by:

## Question

What is the package called (import name, distribution name, logger name: `dbfixlog` has been used only as a placeholder), which Python versions does it support, and which runtime dependencies (if any) does it allow? What does the `render` command look like: invocation (`python -m <pkg> render` and/or a console script), output path default, `--title` override, opening a browser, rendering an unfinished Log File (no `run_end`) or one still being written, and the exit codes and messages for an unknown major format or malformed lines?

Context: see the Answer of 08-logger-api.md (the package exposes `run()`, `get_logger()`, `scope`; no dependencies for the console handler) and of 06-run-header.md (format major/minor acceptance rules; title falls back to the Log File's name).

## Answer

Not an installable package after all: two plain Python files, kept in this repo and copied together next to the scripts (or onto `PYTHONPATH`). No pip, no `setup.py`, no runtime dependencies. Wrapping them in a package later stays possible.

**Files and names**

- `dbfixlog.py`: the module scripts import (`run()`, `get_logger()`, `scope`). Import name and logger name are `dbfixlog`.
- `dbfixlog_render.py`: the render script. It does **not** import `dbfixlog.py`, so it can be copied alone to wherever Reports are read.
- `report.js` and `report.css`: the Report's viewer code, hand-written plain JS/CSS with no build step and no vendored libraries. They sit next to the render script, which reads them at render time and inlines them into each Report. If copying three files proves annoying, a later step can inline them into the script.
- Each Python file carries a version string. The renderer states which format majors it reads (currently `1`).

**Python and dependencies**

- Both files target **Python 3.6.3+**, so a Report can be rendered on the same machine that wrote the Log File. Only the stdlib is used (`json`, `gzip`, `base64`, `argparse`, `webbrowser`).
- Because `contextvars` is 3.7+, Scope state lives in `threading.local`. Each thread keeps its own Scope path, but `asyncio` scripts are unsupported. No `dataclasses`, no `datetime.fromisoformat`.
- Tests run on 3.6 (e.g. the `python:3.6` Docker image) and on a current Python.

**Render command**

```
python dbfixlog_render.py LOG [-o PATH|-] [--title TEXT] [--open] [--strict]
```

- **Output:** the same stem with `.html`, next to the Log File, overwritten silently (a Report is regenerable). `-o PATH` overrides; `-o -` writes to stdout.
- **Title:** `--title`, then `run_start.title`, then the Log File's name.
- **`--open`:** opens the Report in the default browser via `webbrowser`. Off by default.
- **No auto-render:** `run()` does not render. Rendering is always a separate step.
- **Unfinished Log File** (no `run_end`): rendered normally and shown as *unfinished*; exit 0.
- **File still being written:** render is a snapshot to EOF with no follow/watch mode. A partial last line (no trailing newline) is skipped, with a notice in the Report: "last line incomplete, file may still be written".
- **Malformed lines** (not JSON, not an object): skipped by default. The Report shows a notice with their line numbers and the first few bad lines verbatim, and stderr gets a warning. `--strict` aborts instead.
- **Unknown `type`** (e.g. from a newer minor version): shown as a generic row, not dropped.
- **Known `type` with missing or odd fields:** shown as well as possible, with a warning, like the mode-mismatch warning.

**Exit codes** (documented in `--help`; every fatal error is one stderr line prefixed `dbfixlog_render:`)

| Code | Meaning |
|---|---|
| 0 | Report written. Includes unfinished Runs, skipped lines and newer-minor notices. |
| 1 | Log File unreadable, or its first line isn't a `run_start` (not a Log File) |
| 2 | Usage error |
| 3 | Unknown major format. The message names the file's format, the majors this renderer reads, and says to update `dbfixlog_render.py`. |
| 4 | `--strict` and malformed lines found |

**Deferred:** an lnav format file for reading Log Files in a terminal (suggested by Prior-art survey).

No glossary change.

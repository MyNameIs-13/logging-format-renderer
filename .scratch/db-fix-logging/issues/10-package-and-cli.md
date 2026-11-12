# Package layout & render CLI

Type: grilling
Status: open
Blocked by:

## Question

What is the package called (import name, distribution name, logger name: `dbfixlog` has been used only as a placeholder), which Python versions does it support, and which runtime dependencies (if any) does it allow? What does the `render` command look like: invocation (`python -m <pkg> render` and/or a console script), output path default, `--title` override, opening a browser, rendering an unfinished Log File (no `run_end`) or one still being written, and the exit codes and messages for an unknown major format or malformed lines?

Context: see the Answer of 08-logger-api.md (the package exposes `run()`, `get_logger()`, `scope`; no dependencies for the console handler) and of 06-run-header.md (format major/minor acceptance rules; title falls back to the Log File's name).

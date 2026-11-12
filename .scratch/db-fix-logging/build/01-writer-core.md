# Writer core and Run lifecycle

Status: open
Blocked by:

## What to build

Create `dbfixlog.py` with `run()` and the JSONL handler, writing Messages and the Run bracket. Do not build value encoding (02), Scopes (03), typed calls (04) or the console (05). Leave clear seams for them: one function that turns a value into JSON-safe form, and one place that builds a record dict.

Spec: §2 (files, version string, stdlib only), §3.1 (common fields, `exc` shape), §3.2 (`run_start`/`run_end`), §4.1 (`run()` signature and behaviour; accept and store `encoders`, `strict`, `max_text` and `console` for later tickets), §4.2 (root handler, stdlib Messages, `fields=`; `log` adapter for `__main__` with `dry_run`/`write_run`), §4.6 (one namespaced LogRecord attribute).

## Acceptance

- `with dbfixlog.run(path, mode=...) as log:` writes `run_start` first and `run_end` last, with every outcome: `ok`, `error` (with `exc`), `interrupted`, and `SystemExit` (with `exit_code`). The exception re-raises. Handlers are removed on exit, and pre-existing root handlers stay.
- `{ts}` in the path, refusal of an existing file unless `overwrite=True`, and refusal of an invalid `mode` or a nested `run()`.
- Plain `logging.getLogger("x").info(...)` and `log.info("m", fields={...})` become Messages with `ts`, `level`, `logger`, `type`, `src` and `msg`.
- Records below `level=` are dropped, but run records are always written.
- `tests/test_py36_compat.py` exists (see README conventions).

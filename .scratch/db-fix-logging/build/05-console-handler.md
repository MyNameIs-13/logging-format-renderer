# Console handler

Status: resolved
Blocked by: 04

## What to build

The terse stderr console view controlled by `run(console=...)`.

Spec: §4.5.

## Acceptance

- On by default at INFO on stderr. `console=logging.WARNING` raises the level, and `console=False` turns it off.
- Changes and Findings print one line prefixed by the Scope label, matching the §4.5 example.
- Scope starts print a line. Scope ends print only on `error`. Messages use the stdlib format.
- No colours.

## Done

- Commits: 9a72e7e (merge of ticket/05-console-handler into build/db-fix-logging), 38ad034 (Console handler prints Changes prefixed by the Scope label on stderr), e723bc0 (Test console levels: off, raised, below the file level, removed on exit), ad412a0 (Test console lines for Findings, failed Changes, Messages and Scope ends), a66327a (merge of build/db-fix-logging into the ticket branch).
- 133 Python + 13 JS tests passed on the ticket branch; after the merge 138 Python + 13 JS tests pass (`python3 -m unittest discover -s tests`, `node --test tests/js/*.test.js`).
- Line format matches the §4.5 example: `HH:MM:SS LEVEL<pad to 5> [<innermost Scope label> › ]<body>`.
- Seams in dbfixlog.py:
  - `ConsoleHandler(stream, run, level)`: a logging.Handler on the root logger with its own `ScopeFilter()`. `_Run.__enter__` creates it from `sys.stderr` as it is at enter time (tests swap `sys.stderr` before `run()`), keeps it in `run.console_handler` (None when off) and `_teardown` removes it.
  - `console=`: False/None = off, True = INFO, otherwise an int level.
  - `run.scope_labels` (Scope id -> label), filled in `_Scope.__enter__` via `scope_label(kind, key, label)` -> e.g. "customer 42 ACME" (kind, key values, label values, space-joined).
  - Scope start/end bypass logging, so `_Scope._write` calls `run.console_handler.write_scope(rec, levelno)` after the JSONL write. Start prints at INFO; end prints only for outcome error (ERROR), as `end <label> error: ErrType: message` without traceback.
  - Bodies: Change `op table {k:v} labelvalues status[: ErrType: message] [- msg]`; Finding `check [table] [{k:v}] [labelvalues] [- msg]`; Scope start `start <label> [- msg]`; Message `record.getMessage()` plus the traceback when exc_info is set.
  - Console errors are swallowed (handleError) unless `strict`.
- Choices beyond the spec:
  - Console time is local time (stdlib default converter); the Report uses UTC.
  - Only the innermost Scope label is used as the prefix.
  - run_start/run_end print no console line.
  - Messages omit fields.
  - The root logger is lowered to min(level, console) during the Run, so `console=INFO` with `level=WARNING` still prints INFO lines (the JSONL handler's own level keeps them out of the file).

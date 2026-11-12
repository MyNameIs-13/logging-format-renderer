# Scopes in the writer

Status: resolved
Blocked by: 01

## What to build

`dbfixlog.scope(kind, *, key=None, label=None, msg=None, fields=None)` as a context manager and as a decorator (static arguments only). Scope state lives in `threading.local`. A `logging.Filter` stamps the `scope` path onto every record.

Spec: §3.4 (records, ids, parent path on start/end, outcome, re-raise, levels), §4.3 (the scope signature; `log.scope` on the adapter comes in ticket 04 and delegates here), §4.6 (`threading.local`, Filter).

## Acceptance

- Nested Scopes produce the paths and start/end placement shown in the §3.6 example.
- An escaping exception gives an `outcome: error` end with `exc` at ERROR, and the exception re-raises.
- Start and end records are written even when `level` is above INFO.
- Two threads keep separate Scope paths.
- Ids come from a per-Run counter.

## Done

- Commits: d0132e6 (merge of ticket/03-scopes into build/db-fix-logging), 2400824 (Add dbfixlog.scope with thread-local path and ScopeFilter), aa0d7a0 (Scope tests: nesting, errors, levels, threads, decorator form).
- 37 tests pass on Python 3.13 (`python3 -m unittest discover -s tests`).
- Choices beyond the spec:
  - `SystemExit` with code 0/None leaves a Scope `ok`; `KeyboardInterrupt` ends it as `error` (the spec lists only ok/error).
  - `scope()` outside a Run is a transparent no-op (no records, no path, exceptions pass through).
- Seams for later tickets:
  - Ticket 04: `log.scope` should build `_Scope(kind, key, label, msg, fields, src, logger)` directly with `src` from `_caller(1)` and `logger=self.logger.name`; calling `dbfixlog.scope()` from the adapter would stamp dbfixlog.py as src/logger.
  - Ticket 05: the console handler should add its own `ScopeFilter()` (handler order is not guaranteed). The label prefix needs id -> kind/key/label, which is not stored yet; add a per-Run dict in `_Scope.__enter__` if needed.
  - Thread-local path: `_scope_state.path`, read via `_scope_path()`. Ids: `_Run.next_scope_id()` (lock-guarded, per Run, starts at 1).
  - `ScopeFilter` is attached to the JsonlHandler in `_Run.__enter__`; it sets ATTR `"scope"` with setdefault. `_build_record(..., scope=...)` field order: ts, level, logger, type, src, scope, msg, extra..., exc.
  - start/end are written via `run.handler.write_dict` (level bypassed); write errors are swallowed unless `run.strict`.

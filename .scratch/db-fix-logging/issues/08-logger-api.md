# Logger API ergonomics

Type: grilling
Status: resolved
Assignee: MyNameIs-13
Blocked by:

## Question

Which calls does a script author actually write? Covers: setup (opening the Log File, writing the Run Header, choosing Dry Run vs Write Run, the optional console handler), `log.message`/`log.finding`/`log.change` signatures, and how a Change's status is set in each mode. Also `scope(kind, key=..., label=...)` as a context manager (and decorator?), the custom type → encoder mapping, the `strict` flag and the truncation limit. How does the API keep a Dry Run from writing, or is that left entirely to the script?

Context: see the Answer of 03-record-schema.md (record fields), 04-value-serialization.md (encoder mapping, `strict`, truncation; logging never raises) and 05-scope-model.md (`scope_start`/`scope_end`, ids, re-raise on error, written regardless of level).

Context: see the Answer of 06-run-header.md (`run_start` fields the API must accept: `mode` required, optional `title`/`description`/`target`/`fields`; `run_end` with `outcome` ok/error/interrupted, `exit_code`, `duration_ms`, written even on exceptions; both written regardless of level).

Context: see the Answer of 07-report-layout.md (a Dry Run with any `applied`/`failed` Change gets a red "the script may have written to the database" strip; the Report only knows what was logged, so whether the API itself guards a Dry Run against writes matters here).

## Answer

The script opens a Run with a context manager, logs through stdlib-compatible adapters, and does its own database writes. The API never guards them.

**Setup**

```python
with dbfixlog.run("fix-{ts}.jsonl", mode="dry", title="Orphaned orders cleanup",
                  target={"database": "shop_prod"}) as log:
    ...
```

- `run(path, *, mode, title=None, description=None, target=None, fields=None, level=logging.DEBUG, console=logging.INFO, encoders=None, strict=False, max_text=1000, overwrite=False)`. All configuration lives here. There is no config file and no environment variables.
- On entry it writes `run_start`. On exit it writes `run_end` with `outcome` `ok`/`error`/`interrupted` (`exit_code` for `SystemExit`, as in 06-run-header.md), then re-raises. Its handlers are removed on exit. Pre-existing root handlers (e.g. from `basicConfig`) are left alone.
- `path` is required and may contain `{ts}` (the Run's start time, `20261112T200100Z`). An existing Log File is refused unless `overwrite=True`.
- `run()` is setup, so it may raise: for an existing file, a path it can't open, an invalid `mode`, or a nested `run()`. Logging calls never raise (04-value-serialization.md), except under `strict=True`.
- `encoders={Type: fn}`, `strict` and `max_text` are the knobs from 04-value-serialization.md.

**Loggers**

- The JSONL handler is attached to the **root logger**, so plain `logging.getLogger(__name__).info(...)` calls from the script, its helpers and libraries become Messages with their real `logger` name.
- `log` (returned by `run()`, logger `__main__`) and `dbfixlog.get_logger(__name__)` (for helper modules) are stdlib adapters that add `finding`, `change` and `scope`. Helpers find the active Run without `log` being passed in. Outside a Run, typed calls fall back to plain stdlib logging.
- Messages use the stdlib methods plus an optional `fields=` dict: `log.info("connected", fields={"rows": 12})`.

**Typed calls** (keyword-only after the positionals; free key/values only via `fields=`, never `**kwargs`)

```python
log.change(table, op, *, key=None, label=None, changes=None,
           msg=None, status=None, error=None, level=None, fields=None)
log.finding(check, msg=None, *, table=None, key=None, label=None,
            level=logging.WARNING, fields=None)
with log.scope(kind, *, key=None, label=None, msg=None, fields=None): ...
@dbfixlog.scope("orphan-check")          # decorator form: static arguments only
def orphan_check(): ...
```

- **Change status:** with no `status`, it is `planned` in a Dry Run and `applied` in a Write Run. `error=exc` makes it `failed` (with `error` `{type, message}`) at level ERROR. An explicit `status=` overrides both.
- **`changes`:** `{"field": (old, new)}` tuples or `{"old": …, "new": …}` dicts, written as given. Entries where old == new are not dropped.
- **Misuse** (unknown `op`, `update` without `changes`, missing `key` on a non-insert, a bare scalar `key`): the record is written as given, plus a WARNING Message `invalid change call: …`. Under `strict=True` it raises instead. Scalar keys are never auto-wrapped, because the column name is unknown.

**Dry Run guard and commit**

```python
if log.write_run:
    cur.execute("DELETE FROM orders WHERE id = %s", (156,))
log.change("orders", "delete", key={"id": 156}, label={"no": "A88f"})
```

- The API does not prevent writes in a Dry Run. Scripts branch on `log.dry_run` / `log.write_run`, and the Report's red strip (07-report-layout.md) catches `applied`/`failed` Changes in a Dry Run.
- `applied` means *the statement executed without error*. Commit and rollback are not tracked per Change. A script that rolls back says so with a Message, or the escaping exception ends the Scope as `error`. Rejected: a `do=` callable that the logger runs only in Write Runs (it turns the logger into a framework and still can't see commits); a `rolled_back` status or commit marker records.

**Console handler**

- On by default at INFO, writing to stderr. Set `console=logging.WARNING` to raise its level, or `console=False` to turn it off. No colours, no dependencies.
- One terse line per record, prefixed by the Scope label: `20:01:03 INFO  customer 42 ACME › delete orders {id:156} planned`. Scope starts get a line; Scope ends get one only on `error`. Messages use the stdlib format.

**Concurrency:** one Run per process with a single writer (03-record-schema.md). Scope state lives in a ContextVar, so threads keep separate Scope paths, but there is no further thread or process support. *(Superseded by Package layout & render CLI (10-package-and-cli.md): Python 3.6.3 has no `contextvars`, so Scope state lives in `threading.local`; threads still keep separate paths, `asyncio` is unsupported.)*

No new glossary terms: `dry_run`/`write_run` are API spellings of Dry Run / Write Run.

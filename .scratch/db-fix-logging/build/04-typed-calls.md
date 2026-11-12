# Typed calls: change, finding, get_logger

Status: resolved
Blocked by: 02, 03

## What to build

The stdlib adapter behind `log` and `dbfixlog.get_logger(name)`, with `change`, `finding` and `scope`.

Spec: §3.3 (Change/Finding fields and rules), §4.2 (adapters find the active Run; typed calls fall back to plain logging outside a Run), §4.3 (signatures, status defaults, `changes` input forms, misuse handling), §4.4.

## Acceptance

- Change status defaults: `planned` in a Dry Run, `applied` in a Write Run. `error=exc` gives `failed` with `error` `{type, message}` at ERROR. An explicit `status=` wins.
- `changes` accepts both tuple and dict forms, writes `{field: {old, new}}`, and keeps entries where old equals new.
- Each misuse case writes the record plus a WARNING `invalid change call: …`, or raises under `strict=True`.
- Finding defaults to WARNING. `check` is required.
- `get_logger(__name__)` in a helper module logs into the active Run without being passed `log`.

## Done

- Commits: c585959 (merge of ticket/04-typed-calls into build/db-fix-logging), 11812e5 (log.change writes a planned Change in a Dry Run with the caller's src), 1db1845 (Change status defaults, error= makes failed at ERROR, explicit status and level win), c952b18 (Change accepts (old, new) tuples and {old, new} dicts in changes), 0df178c (Misused change calls write the record plus an invalid-change WARNING, or raise under strict), 58d62d5 (Add log.finding, log.scope and dbfixlog.get_logger for helper modules), 960494b (Test that typed calls outside a Run fall back to plain stdlib logging).
- 118 Python tests + 1 JS test pass after the merge (`python3 -m unittest discover -s tests`, `node --test tests/js/*.test.js`).
- Choices beyond the spec:
  - Typed calls carry the caller's `src` in the ATTR dict (`_caller(1)[0]`); `_record_from_logrecord` pops ATTR `"src"` and falls back to pathname:lineno only when absent. Any future typed helper in dbfixlog.py must do the same.
  - Misuse (`_change_misuse(op, key, changes)`): unknown op, update with falsy `changes` (so `changes={}` counts as misuse), missing key on non-insert, non-dict key. The change is written, then a WARNING Message `invalid change call: <reason>` with the same src and logger. Under `strict=True`, `ValueError("invalid change call: ...")` is raised before anything is written.
  - `error=exc` gives `{"type": ExcName, "message": exc}`; `error.message` is stringified by `_encode` at write time (a raising `__str__` gives `$unencodable`; a custom encoder registered for the exception type also applies).
  - `changes`: a 2-item tuple/list becomes `{"old", "new"}`; anything else is written as given (entry shape not validated).
  - Outside a Run: same code path, plain stdlib logging; status is omitted (no mode); misuse warns but never raises (strict belongs to a Run). `log.scope` outside a Run is the ticket 03 no-op.
  - The level argument is passed straight to `Logger.log`, so it must be an int (no level-name strings).
  - Change field order: ts, level, logger, type, src, scope, msg, table, op, key, label, changes, status, error, fields.
- Seams for later tickets:
  - Typed calls go through `RunLogger._typed(level, text, data, src)` -> `self.logger.log(level, "%s", text, extra={ATTR: data})`. `text` is a plain summary for non-JSONL handlers ("delete orders", "orphan-order: no customer"); the JSONL `msg` comes from ATTR `"msg"` (None -> no msg slot).
  - Ticket 05: build the console handler's terse line from the ATTR dict (type/op/table/key/status/check), not from `getMessage()`. ATTR `"type"` is `"change"`/`"finding"`; plain messages have no `"type"` key.
  - `dbfixlog.get_logger(name)` = `RunLogger(logging.getLogger(name))`, safe at import time; the Run is looked up per call.

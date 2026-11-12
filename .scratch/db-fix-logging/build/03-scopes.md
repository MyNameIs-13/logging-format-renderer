# Scopes in the writer

Status: open
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

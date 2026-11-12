# Typed calls: change, finding, get_logger

Status: open
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

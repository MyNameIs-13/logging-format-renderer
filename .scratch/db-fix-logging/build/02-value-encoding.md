# Value encoding

Status: resolved
Blocked by: 01

## What to build

The value encoder for `key`, `label`, `fields` and `changes`, wired into the writer through the seam from ticket 01. Includes the `encoders=` mapping, `strict=True` and `max_text`.

Spec: §3.5 (the full table and the rules below it). Logging never raises unless `strict=True`.

## Acceptance

- One test per table row of §3.5, including NaN/±Infinity with `allow_nan=False`, Decimal scale, aware and naive datetimes, sorted sets, `$truncated`, `$bytes` and `$unencodable`.
- Custom `encoders` take precedence. `None`-valued keys are never dropped.
- A `str()` that raises gives `$unencodable` by default and raises under `strict=True`.

## Done

- Commits: abbd50f (merge of ticket/02-value-encoding into build/db-fix-logging), 896f889 (Encode NaN/Infinity, Decimal and date/time values), 95959d2 (Encode sets, long text ($truncated) and bytes ($bytes); only value slots truncate), c314aa2 (Encode Enum as .value, failing str() as $unencodable; strict=True raises), fdde386 (Custom encoders= take precedence over built-in value rules), 3990c6d (merge of build/db-fix-logging into the ticket branch), 29b8c0b (Test that scope_start value slots are encoded).
- 64 tests passed on the ticket branch; 99 Python tests + 1 JS test pass after the merge (`python3 -m unittest discover -s tests`, `node --test tests/js/*.test.js`).
- Choices beyond the spec:
  - Only `key`/`label`/`fields`/`changes` (`VALUE_SLOTS`) are truncated at `max_text`; other top-level slots (msg, target, exc, scope, ...) are made JSON-safe only (`_encode(..., truncate=False)`).
  - Enum is written as its encoded `.value`.
  - Custom `encoders={Type: fn}` match along `type(value).__mro__` and win over built-in rules; the result is encoded again (built-in rules only if it has the same type). A raising encoder gives `$unencodable` (raises under strict).
  - `$unencodable` text is `repr(value)`, or `"<ExcType>: <msg>"` if repr also raises. Non-str dict keys become `str(k)`.
  - Under `strict=True`, `JsonlHandler.emit` re-raises instead of `handleError`, so a bad value raises at the call site.
- Known gaps (record is lost via handleError, nothing raises): self-containing containers (RecursionError), dict keys whose `str()` raises.
- Seams for later tickets:
  - `_encode(value, run=None, truncate=True)`; `_encode_record(rec, run)` is applied in `write_dict`. Ticket 04 only needs to put key/label/changes/fields in the ATTR dict.
  - Ticket 04: `changes` given as `{"field": (old, new)}` are encoded as `[old, new]` arrays; normalising to `{"old": ..., "new": ...}` is 04's job, before the record reaches `write_dict`.

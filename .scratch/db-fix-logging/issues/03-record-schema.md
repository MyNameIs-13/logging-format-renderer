# Record schema for Message, Finding, Change

Type: grilling
Status: resolved
Assignee: MyNameIs-13
Blocked by:

## Question

What exact fields does each record type carry in the Log File? Common fields (timestamp, level, logger, record type, Scope reference, source location?), Message (text, free key/value fields), Finding (rule/check name, table, key, severity, details), Change (table, key, field, old, new, status `planned`/`applied`/`failed`, error on failure). How is a row key represented, including composite keys? One Change per field, or one per row with several fields? How are exceptions/tracebacks recorded?

## Answer

Every record is one flat JSON object. A Change covers one row operation, not one field. Rows are identified by `key` (database key columns) plus an optional human-recognisable `label`.

| Field | All records | Message | Finding | Change |
|---|---|---|---|---|
| `ts` (ISO 8601 UTC, ms), `level` (stdlib name), `logger`, `type` (`message`/`finding`/`change`), `src` (`file.py:123`) | required | | | |
| `msg` | | required | optional | optional |
| `scope` | slot; shape decided in 05-scope-model.md | | | |
| `fields` (free key/values) | optional | | | |
| `exc` `{type, message, traceback}` (traceback as one string) | optional | | | |
| `check` (stable rule name) | | | required | |
| `table` (string, optionally schema-qualified), `key`, `label` | | | optional | `table` required; `key` required except for planned inserts; `label` optional |
| `op` `update`/`insert`/`delete` | | | | required |
| `changes` `{field: {old, new}}` | | | | `update` only |
| `status` `planned`/`applied`/`failed` | | | | required |
| `error` `{type, message}` | | | | when `failed` |

- **Row identity:** `key` is always an object of column → value (`{"id": 156}`, `{"order_id": 7, "line_no": 3}`). `label` is an object of values chosen by the script author so a human can recognise the row (`{"barcode": "A88f"}`). It is searchable and shown beside the key.
- **Change:** one per row operation. An update carries all of that row's field changes. Insert and delete carry only `table`, `key` and `label`, never row contents. A planned insert may have no `key` because the database hasn't generated it yet. Status and error apply to the whole Change. Each Change is written once, with its final status. There is no planned/applied pair and no `skipped` status (log a Message or Finding instead). Level defaults to INFO, or ERROR when failed; the author can override it.
- **Finding:** severity is the logging level; there is no separate field. Each Finding covers one row (or none, for table-level checks).
- **Message:** `msg` plus optional `fields`.
- **Ordering and ids:** a record's line position in the Log File gives its order and its id. There is no sequence number (the Log File has a single writer) and no function, thread or process fields.
- **Display:** the renderer builds a summary from the structured fields. `msg` on a Finding or Change is supplementary.
- Value encoding inside `old`/`new`/`key`/`label`/`fields` is left to 04-value-serialization.md.

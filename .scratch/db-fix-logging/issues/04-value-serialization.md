# Serialization of database values

Type: grilling
Status: resolved
Assignee: MyNameIs-13
Blocked by: 03

## Question

How are database values written into JSON Lines so values (Change `changes` old/new, `key`, `label`, `fields`) round-trip faithfully and display unambiguously in the Report? Cover None/NULL vs missing, Decimal, datetime/date/time with timezones, bytes/blobs, large text, JSON/array columns, UUIDs, and unknown types (fallback to `repr`?). Is a type tag needed alongside the value?

Context: see the Answer of 01-prior-art-survey.md (python-json-logger's str() fallback loses type information).

Context: see the Answer of 03-record-schema.md (where values appear in a record).

## Answer

Values are written for **display, not typed round-trip**: readable JSON, with no declared column type. Any rollback relies on domain knowledge. The same encoding applies to `key`, `label`, `fields` and `changes.old`/`new`.

| Python value | Written as |
|---|---|
| `None` | `null` |
| int, float, bool, str | native JSON |
| float NaN / ±Infinity | strings `"NaN"`, `"Infinity"`, `"-Infinity"`; the writer uses `allow_nan=False` so invalid JSON can never reach the Log File |
| Decimal | string with its scale kept (`"12.30"`) |
| datetime / date / time objects | ISO 8601 as returned by the source, offset kept if aware, never converted to UTC (only the record's `ts` is UTC) |
| date/time already given as strings (Uniface: `20261122053550`) | written as received |
| dict / list / tuple / set | nested JSON; tuple → array, set → array (sorted where possible) |
| text longer than N chars (default 1000, configurable) | `{"$truncated": "<first N chars>", "length": <full length>}` |
| bytes | `{"$bytes": "<hex of first 64 bytes>", "length": <byte count>}` |
| UUID, Enum (`.value`), IP addresses, any other type | `str(value)` |
| `str()` raises | `{"$unencodable": "<repr or error text>"}` |

- **Missing vs null:** a missing key means "not logged" (in `changes`: "field not changed"). The logger never drops `None`-valued keys. There is **no NULL-vs-empty guarantee**: the Uniface database loader doesn't reliably tell `null` from `""` apart.
- **`$`-prefixed objects** mark values the logger altered. The Report displays them as such (e.g. a "truncated" badge), never as real data.
- **Never crash the Run:** by default, logging never raises. Logger setup takes a type → encoder mapping and an opt-in `strict=True` (for tests) that raises instead of writing `$unencodable`.
- **Report display:** values are shown as logged. `null` and `""` are shown distinctly (a dim `NULL` badge / a dim `(empty)`), with the Uniface caveat in the help text. No guessing: compact date strings are not reformatted.
- Rejected: typed values with type tags (unneeded, since domain knowledge covers rollback, and switching later only adds fields); merging null/empty in the Report.

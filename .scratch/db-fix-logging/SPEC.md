# Spec: Database Fix Logging → HTML Reports

Hand-off spec for the builder. It brings together the decisions on the [map](map.md) and adds none of its own. Each section links the ticket that holds the full reasoning. Where a later ticket replaced an earlier answer, only the later answer appears here.

**What gets built:**

1. `dbfixlog.py`: a Python stdlib-`logging`-based writer for **Log Files**, used by database check/fix scripts in **Dry Runs** and **Write Runs**.
2. `dbfixlog_render.py` (with `report.js` and `report.css`): one general renderer that turns any Log File (up to ~100k records) into a self-contained, readable, searchable HTML **Report**.

Terms in **bold** are defined in [GLOSSARY.md](../../GLOSSARY.md), and this spec uses only those terms. Run, Dry Run, Write Run, Log File, Run Header, Report, Message, Finding, Change, Scope, Key and Label mean exactly what the glossary says.

---

## 1. Ground rules

_Source: the map's Notes (settled while charting)._

- One **Run** produces one **Log File**, which renders to one **Report**.
- The Report is a single static HTML file with inline JS and CSS and no server. It is opened locally or shared as an attachment or CI artifact.
- The Log File is JSON Lines: one JSON object per line. Its first line is the **Run Header**, which carries a format version.
- An optional console handler gives a terse live view. It is not a second record of the Run.
- There are three typed records: **Message**, **Finding** and **Change**. A Change has a status: `planned` in a Dry Run, `applied` or `failed` in a Write Run. It always records old and new values.
- Work across connected tables is grouped into **Scopes**, which nest.
- Scripts log explicitly (`log.change(...)` and so on). The design is database-agnostic.
- Keeping sensitive values out of Log Files is the developer's responsibility.

## 2. Files, Python version, dependencies

_Source: [Package layout & render CLI](issues/10-package-and-cli.md)._

This is not an installable package. The files live in this repo and are copied together next to the scripts, or onto `PYTHONPATH`. There is no pip, no `setup.py` and no runtime dependency. Wrapping them in a package later stays possible.

| File | Role |
|---|---|
| `dbfixlog.py` | The module scripts import: `run()`, `get_logger()`, `scope`. Its import name and logger name are both `dbfixlog`. |
| `dbfixlog_render.py` | The render script. It does **not** import `dbfixlog.py`, so it can be copied on its own to wherever Reports are read. |
| `report.js`, `report.css` | The Report's viewer code: hand-written plain JS and CSS, with no build step and no vendored libraries. They sit next to the render script, which reads them at render time and inlines them into each Report. If copying three files proves annoying, a later step can inline them into the script. |

- Each Python file carries a version string. The renderer states which format majors it reads (currently `1`).
- Both Python files target **Python 3.6.3+**, so a Report can be rendered on the same machine that wrote the Log File. They use only the stdlib (`json`, `gzip`, `base64`, `argparse`, `webbrowser`). No `contextvars`, no `dataclasses`, no `datetime.fromisoformat`.
- Tests run on Python 3.6 (for example the `python:3.6` Docker image) and on a current Python.

## 3. Log File format

### 3.1 Records, order, identity

_Source: [Record schema for Message, Finding, Change](issues/03-record-schema.md)._

- Every record is one flat JSON object on one line.
- A record's line position in the Log File is its order and its id. There is no sequence number (each Log File has a single writer) and there are no function, thread or process fields.

Common fields:

| Field | Presence | Content |
|---|---|---|
| `ts` | required | ISO 8601, UTC, millisecond precision (`"2026-11-12T20:01:00.000Z"`) |
| `level` | required | stdlib level name (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) |
| `logger` | required | logger name, without the `dbfixlog.` prefix (4.2) |
| `type` | required | `message`, `finding`, `change`, `scope_start`, `scope_end`, `run_start`, `run_end` |
| `src` | required, except on `run_start` / `run_end` | `file.py:123` |
| `scope` | absent outside any Scope | the Scope path, see 3.4 |
| `fields` | optional | free key/value object |
| `exc` | optional | `{type, message, traceback}`, with the traceback as one string |

Row identity, used by Findings, Changes and Scopes:

- `key` is always an object mapping column name to value, e.g. `{"id": 156}` or `{"order_id": 7, "line_no": 3}`.
- `label` is an object of values the script author chooses so a human can recognise the row, e.g. `{"barcode": "A88f"}`. It is searchable and shown beside the key.

### 3.2 Run Header (`run_start`) and `run_end`

_Source: [Run Header contents](issues/06-run-header.md)._

A Run is bracketed by two records. `run_start` (the Run Header) is always the first line and `run_end` is the last line. Both are written whatever the configured level. Nothing about the environment is captured automatically: no run id, host, user, argv or git sha.

**`run_start`**

- `ts` is the Run's start time. `level` is `INFO`, `logger` is `dbfixlog`, and there is no `src`.
- `format`: `"1.0"`, as major.minor. A minor bump only adds optional fields. The renderer accepts any minor of a major it knows, and shows a notice when the minor is newer than the ones it knows. It refuses an unknown major with a clear message (see 5.4).
- `mode`: `"dry"` or `"write"`, required. A Change whose status doesn't fit the mode (`planned` in a Write Run, `applied` or `failed` in a Dry Run) is shown as a warning in the Report, not rejected.
- Optional fields supplied by the author:
  - `title`: the Report title. Falls back to the Log File's name.
  - `description`: free text, for example a ticket reference.
  - `target`: a free-form object describing the database. Keeping credentials out of it is the developer's responsibility.
  - `fields`.

**`run_end`**

- `ts` is the Run's end time. There is no `src`.
- `duration_ms`.
- `outcome`:
  - `ok`.
  - `error`: an exception escaped the Run, and `exc` is attached.
  - `interrupted`: `KeyboardInterrupt`.
- For a `SystemExit`, the record carries `exit_code`. The outcome is `ok` for code 0 or `None` and `error` otherwise.
- `level` is `INFO`, or `ERROR` for `error` and `interrupted`.
- There are no totals. The renderer derives them from the records.
- A Log File without `run_end` is **unfinished** (the process was killed or crashed hard). It renders like an unfinished Scope.

### 3.3 Message, Finding, Change

_Source: [Record schema for Message, Finding, Change](issues/03-record-schema.md)._

| Field | Message | Finding | Change |
|---|---|---|---|
| `msg` | required | optional | optional |
| `check` (stable rule name) | | required | |
| `table` (string, optionally schema-qualified) | | optional | required |
| `key` | | optional | required, except for a planned insert |
| `label` | | optional | optional |
| `op`: `update` / `insert` / `delete` | | | required |
| `changes`: `{field: {"old": …, "new": …}}` | | | `update` only |
| `status`: `planned` / `applied` / `failed` | | | required |
| `error`: `{type, message}` | | | when `failed` |

- **Message:** `msg` plus optional `fields`.
- **Finding:**
  - Severity is the logging level. There is no separate severity field.
  - Each Finding covers one row, or no row for a table-level check.
- **Change:**
  - One Change covers one row operation, not one field. An update carries all of that row's field changes.
  - Insert and delete carry only `table`, `key` and `label`, never the row's contents.
  - A planned insert may have no `key`, because the database hasn't generated it yet.
  - Status and error apply to the whole Change.
  - Each Change is written once, with its final status. There is no planned/applied pair and no `skipped` status (log a Message or Finding instead).
  - Level defaults to `INFO`, or `ERROR` when failed. The author can override it.
- **Display:** the renderer builds each row's summary from the structured fields. A `msg` on a Finding or Change is supplementary.

### 3.4 Scopes

_Source: [Scope model](issues/05-scope-model.md)._

A Scope is written as a `scope_start` and a `scope_end` record. Every record inside the Scope carries the Scope's path. A Scope is shaped around either an entity or a phase, and Scopes nest.

- **`scope_start`:**
  - `id`: an integer from a per-Run counter, assigned when the Scope opens.
  - `kind`: free-form, e.g. `"customer"` or `"orphan-check"`.
  - Optional `key` and `label`, in the same shapes as row identity (3.1). A Scope without `key` is a named phase of the Run.
  - Optional `msg` and `fields`.
- **`scope` slot:** the path of Scope ids, outermost first (`[1, 2]`). It is absent outside any Scope. A Scope's own start and end records carry their *parent's* path, so they sit at the level of the Scope they open or close.
- **Records outside any Scope** are valid and shown at Run level.
- **Same entity twice:** each `scope(...)` call is a separate Scope. The Report does not merge them, and a key filter finds both.
- **`scope_end`:**
  - `id` and `duration_ms`.
  - `outcome`: `ok` or `error`. `error` means an exception escaped the Scope. The record then carries `exc` and the helper re-raises the exception.
  - Richer outcomes (changed, had failed Changes, had Findings) are not recorded. The renderer derives them from the Scope's contents.
  - A failed Change that the script caught leaves the Scope `ok`.
- **Levels:** start and end records are always written, whatever the configured level. They are stamped `INFO`, or `ERROR` for an `error` end.
- **Crash:** a Scope with no end record is **unfinished**. It closes at the last record in the file and has no duration.

### 3.5 Values

_Source: [Serialization of database values](issues/04-value-serialization.md)._

Values are written **for display, not for typed round-trip**. The JSON is readable and declares no column type, so any rollback relies on domain knowledge. The same encoding applies to `key`, `label`, `fields` and `changes.old` / `new`.

| Python value | Written as |
|---|---|
| `None` | `null` |
| int, float, bool, str | native JSON |
| float NaN / ±Infinity | strings `"NaN"`, `"Infinity"`, `"-Infinity"`. The writer uses `allow_nan=False`, so invalid JSON can never reach the Log File. |
| Decimal | string with its scale kept (`"12.30"`) |
| datetime / date / time objects | ISO 8601 as returned by the source. The offset is kept if the value is timezone-aware, and nothing is converted to UTC (only the record's `ts` is UTC). |
| date/time already given as strings (Uniface: `20261122053550`) | as received |
| dict / list / tuple / set | nested JSON. A tuple becomes an array, and a set becomes an array, sorted where possible. |
| text longer than `max_text` chars (default 1000) | `{"$truncated": "<first N chars>", "length": <full length>}` |
| bytes | `{"$bytes": "<hex of first 64 bytes>", "length": <byte count>}` |
| UUID, Enum (`.value`), IP addresses, any other type | `str(value)` |
| `str()` raises | `{"$unencodable": "<repr or error text>"}` |

- **Missing vs null:** a missing key means "not logged". In `changes`, it means "field not changed". The logger never drops keys whose value is `None`.
- **No NULL-vs-empty guarantee:** the Uniface database loader doesn't reliably tell `null` and `""` apart.
- **`$`-prefixed objects** mark values the logger altered. The Report shows them as markers (e.g. a "truncated" badge), never as real data.
- **Logging never raises.** A value that can't be encoded (including a cycle, a dict key whose `str()` raises, or an exception whose `__str__` raises) becomes `$unencodable`, and the record is still written. A type → encoder mapping is set up in `run()` (see 4.1).

### 3.6 Example Log File

Assembled from the examples in the Scope model and Run Header tickets (fields abbreviated with `...`):

```jsonl
{"ts":"2026-11-12T20:01:00.000Z","level":"INFO","logger":"dbfixlog","type":"run_start","format":"1.0","mode":"dry","title":"Orphaned orders cleanup","target":{"database":"shop_prod"}}
{"type":"message","msg":"connected", ...}
{"type":"scope_start","id":1,"kind":"orphan-check","msg":"pass 1", ...}
{"type":"scope_start","id":2,"kind":"customer","key":{"id":42},"label":{"name":"ACME"},"scope":[1], ...}
{"type":"change","op":"delete","table":"orders","key":{"id":156},"status":"planned","scope":[1,2], ...}
{"type":"scope_end","id":2,"outcome":"ok","duration_ms":38,"scope":[1], ...}
{"type":"scope_end","id":1,"outcome":"ok","duration_ms":120, ...}
{"ts":"2026-11-12T20:03:12.418Z","level":"INFO","logger":"dbfixlog","type":"run_end","outcome":"ok","duration_ms":132418}
```

## 4. Logger API (`dbfixlog.py`)

_Source: [Logger API ergonomics](issues/08-logger-api.md), with Scope state per [Package layout & render CLI](issues/10-package-and-cli.md)._

The script opens a Run with a context manager and logs through stdlib-compatible adapters. It does its own database writes, and the API never guards them.

### 4.1 Setup

```python
with dbfixlog.run("fix-{ts}.jsonl", mode="dry", title="Orphaned orders cleanup",
                  target={"database": "shop_prod"}) as log:
    ...
```

```python
run(path, *, mode, title=None, description=None, target=None, fields=None,
    level=logging.DEBUG, console=logging.INFO, encoders=None,
    max_text=1000, overwrite=False)
```

- All configuration lives in these arguments. There is no config file and no environment variables.
- On entry, `run()` writes `run_start`. On exit it writes `run_end` (outcome and `exit_code` as in 3.2), then re-raises any exception. Its handlers are removed on exit. The root logger (its handlers, e.g. from `basicConfig`, and its level) is never touched.
- `path` is required. It may contain `{ts}`, which becomes the Run's start time (`20261112T200100Z`). An existing Log File is refused unless `overwrite=True`.
- `run()` is setup, so it may raise: for an existing file, a path it can't open, an invalid `mode` or a nested `run()`. Logging calls never raise.
- `encoders={Type: fn}` and `max_text` control value encoding (3.5).
- `level` is the Log File's threshold and `console` the terminal's. During a Run, dbfixlog's own logger namespace is set to the lower of the two; nothing outside it changes.

### 4.2 Loggers

- **Opt-in:** only records logged through `log` (from `run()`), a `dbfixlog.get_logger(...)` adapter or `dbfixlog.scope(...)` reach the Log File and the console. A module-level `dbfixlog.scope()` belongs to the calling module's logger in the namespace (`dbfixlog.<__name__>`). Plain `logging.getLogger(...)` calls from the script, its helpers and libraries never do, even under the same name.
  - These loggers live in dbfixlog's own namespace (`get_logger("orders")` is the stdlib logger `dbfixlog.orders`). Log File records show the name without the prefix: `"logger": "orders"`.
  - `get_logger(None)` and `get_logger("")` return the `__main__` logger, the one `log` uses.
  - `dbfixlog` and `dbfixlog.*` are reserved logger names. A plain `logging.getLogger("dbfixlog.x")` is inside the namespace and reaches the Log File as `x`; nothing guards against it.
  - The Run's handlers are attached to that namespace, not the root logger. During a Run its records don't propagate to the root logger, so the script's own logging setup doesn't print them a second time.
- `log` (returned by `run()`, stdlib logger `dbfixlog.__main__`, shown as `__main__`) and `dbfixlog.get_logger(__name__)` (for helper modules) are stdlib adapters that add `finding`, `change` and `scope`.
  - Helpers' records reach the active Run without `log` being passed in.
  - Only `log` has `dry_run` / `write_run`. `get_logger()` adapters don't know the Run's mode, so a helper that writes takes the script's `log` (or the mode) as an argument.
  - Outside a Run, their records (typed calls included) propagate to the root logger under their full stdlib name (`dbfixlog.orders`), so the script's own logging setup decides what is shown. Scope start and end records skip the loggers' level checks, as during a Run, so a root handler sees them at INFO even when the root level is higher.
- Messages use the stdlib methods plus an optional `fields=` dict: `log.info("connected", fields={"rows": 12})`.

### 4.3 Typed calls

Arguments after the positionals are keyword-only. Free key/values go only through `fields=`, never `**kwargs`.

```python
log.change(table, op, *, key=None, label=None, changes=None,
           msg=None, status=None, error=None, level=None, fields=None)
log.finding(check, msg=None, *, table=None, key=None, label=None,
            level=logging.WARNING, fields=None)
with log.scope(kind, *, key=None, label=None, msg=None, fields=None): ...
@dbfixlog.scope("orphan-check")          # decorator form: static arguments only
def orphan_check(): ...
```

- **Change status:**
  - With no `status`, it is `planned` in a Dry Run and `applied` in a Write Run.
  - `error=exc` makes it `failed`, with `error` `{type, message}`, at level ERROR.
  - An explicit `status=` decides the status only. A Change with `error=` is still logged at ERROR unless `level=` is given.
- **`changes`:** accepts `{"field": (old, new)}` tuples or `{"field": {"old": …, "new": …}}` dicts, written as given. Entries where old equals new are not dropped.
- **Misuse:** an unknown `op`, an `update` without `changes`, a missing `key` on a non-insert, or a bare scalar `key`.
  - The record is written as given, followed by a WARNING Message `invalid change call: …`. The call never raises.
  - A scalar key is never wrapped automatically, because the column name is unknown.

### 4.4 Dry Run guard and commit

```python
if log.write_run:
    cur.execute("DELETE FROM orders WHERE id = %s", (156,))
log.change("orders", "delete", key={"id": 156}, label={"no": "A88f"})
```

- The API does not prevent writes in a Dry Run. Scripts branch on `log.dry_run` / `log.write_run` (only on `run()`'s `log`; see 4.2). The Report's red strip (6.2) catches `applied` or `failed` Changes in a Dry Run.
- `applied` means *the statement executed without error*. Commit and rollback are not tracked per Change.
  - A script that rolls back says so with a Message.
  - An exception that escapes a Scope ends it as `error`.

### 4.5 Console handler

- On by default at INFO, writing to stderr. Set `console=logging.WARNING` to raise its level, or `console=False` to turn it off. No colours, no dependencies.
- One terse line per record, prefixed by the Scope label:

  ```
  20:01:03 INFO  customer 42 ACME › delete orders {id:156} planned
  ```

  - Scope starts get a line. Scope ends get one only on `error`.
  - Messages use the stdlib format.

### 4.6 Concurrency and implementation notes

- One Run per process, with a single writer. Nothing guards against two threads calling `run()` at once; that is unsupported.
- Scope state lives in **`threading.local`**, because `contextvars` needs 3.7+. Each thread keeps its own Scope path. `asyncio` scripts are unsupported, and there is no further thread or process support.
- No mutable module-level state in `dbfixlog.py` or `dbfixlog_render.py` (no `global`, no module-level locks, thread-locals or mutated containers): no code looks up an active Run. Adapters and `scope()` only emit LogRecords; everything that depends on the Run (default Change status, Scope ids and the per-thread Scope path, value encoding) happens in the Run's own handlers and their shared filter.
- Build on stdlib `logging` only (_source: [Prior-art survey for structured logs → HTML](issues/01-prior-art-survey.md)_):
  - Stamp the Scope path onto every record with a `logging.Filter` that reads the thread-local Scope state. This is the cookbook pattern, with `threading.local` in place of `ContextVar`.
  - Put typed fields under **one namespaced LogRecord attribute**, because `extra` keys that clash with LogRecord attributes raise `KeyError`. python-json-logger's reserved-attribute list is a useful reference.
  - Learn from Eliot's start/end records and tree path (already reflected in 3.4) and from structlog's token-reset binding. Don't depend on either.

## 5. Renderer (`dbfixlog_render.py`)

### 5.1 Command

_Source: [Package layout & render CLI](issues/10-package-and-cli.md)._

```
python dbfixlog_render.py LOG [-o PATH|-] [--title TEXT] [--open] [--strict]
```

- **Output:**
  - By default, the Log File's stem with `.html`, next to the Log File. An existing Report is overwritten silently, because a Report can always be regenerated.
  - `-o PATH` overrides the path, and `-o -` writes to stdout.
- **Title:** `--title`, then `run_start.title`, then the Log File's name.
- **`--open`:** opens the Report in the default browser via `webbrowser`. Off by default.
- **No auto-render:** `run()` does not render. Rendering is always a separate step.

### 5.2 Input handling

_Source: [Package layout & render CLI](issues/10-package-and-cli.md)._

- **Unfinished Log File** (no `run_end`): rendered normally and shown as *unfinished*. Exit 0.
- **File still being written:** rendering takes a snapshot to EOF. There is no follow or watch mode. A partial last line (no trailing newline) is skipped, and the Report shows a notice: "last line incomplete, file may still be written".
- **Malformed lines** (not JSON, or not an object):
  - Skipped by default. The Report shows a notice with their line numbers and the first few bad lines verbatim, and stderr gets a warning.
  - With `--strict`, the render aborts instead.
- **Unknown `type`** (e.g. from a newer minor version): shown as a generic row, not dropped.
- **Known `type` with missing or odd fields:** shown as well as possible, with a warning, like the mode-mismatch warning.

### 5.3 Output and size

_Source: [Report size budget](issues/11-report-size-budget.md)._

- There is no size check, warning or refusal, and no record cap. Log Files above 100k records render in full and no records are ever dropped. The budgets in section 7 are guaranteed only up to 100k records.
- On success the renderer prints one summary line: the record count and the Report size.

### 5.4 Exit codes

_Source: [Package layout & render CLI](issues/10-package-and-cli.md)._

The exit codes are documented in `--help`. Every fatal error is one stderr line prefixed `dbfixlog_render:`.

| Code | Meaning |
|---|---|
| 0 | Report written. This includes unfinished Runs, skipped lines and newer-minor notices. |
| 1 | Log File unreadable, or its first line isn't a `run_start` (not a Log File). |
| 2 | Usage error. |
| 3 | Unknown major format. The message names the file's format and the majors this renderer reads, and says to update `dbfixlog_render.py`. |
| 4 | `--strict` and malformed lines found. |

## 6. Report

### 6.1 Technique

_Source: [Making 100k records usable in one HTML file](issues/02-large-single-file-html.md), constrained by [Package layout & render CLI](issues/10-package-and-cli.md) (no libraries) and [Report layout](issues/07-report-layout.md) (details in a panel, not inline)._

- **Embedding:**
  - The records are gzipped, then base64-encoded, inside a `<script type="application/json">` block.
  - The browser decodes them with `DecompressionStream("gzip")` and `JSON.parse`.
  - This works from `file://` in Chrome 80+, Firefox 113+ and Safari 16.4+.
  - Whatever is embedded must not be able to close the script block early. Base64 text contains no `<`; raw JSON would need `<` escaped.
- **Rendering:** plain JS that renders only the visible rows, each of fixed height (~100 lines of code in the research). 100k rows at 24–28 px is ~2.8M px, well under the binding browser limit (Firefox's maximum element height, ~17M px).
- **Search:**
  - No Web Worker. A search index is built at idle time right after data ready (~200 ms at 100k), and the search box debounces input by 150 ms. Only a search started within about 50 ms of data ready pays for part of the build.
  - Ctrl+F can't see unrendered rows, so the Report has its own search box.
- **Inside the Report**, the renderer may reshape the embedded data (e.g. into columnar arrays) if the builder needs that to meet the budgets. This is internal and not a format change (_source: [Report size budget](issues/11-report-size-budget.md)_).

### 6.2 Layout

_Source: [Report layout](issues/07-report-layout.md). Primary source: the prototype on branch `prototype/report-layout` (commit a4cd752), `.scratch/db-fix-logging/prototypes/report-layout/`. Run `python build.py` and open the output with `?variant=E`._

The Report shows a run summary on top, then one list with fixed, resizable columns, in which Scopes form a tree. From top to bottom:

1. **Run Header block:** title, description, mode badge, `target`, `fields`, start time, outcome (with exit code) and duration, or *unfinished*.
2. **Mode strip and notices** (full width):
   - **Dry Run:** an amber strip, *"Dry Run: the Changes below are planned, not applied."* If any Change has status `applied` or `failed`, a **red** strip replaces it: *"Dry Run, but N Changes were logged as applied or failed: the script may have written to the database. Show them."* The strip only claims what the Log File shows, never "nothing was written".
   - **Write Run with `planned` Changes:** an amber notice, *"logged as planned in a Write Run: they were not carried out"*.
   - Other notices:
     - Run unfinished (no `run_end`).
     - Run outcome `error` or `interrupted`.
     - Newer-minor format.
     - Unfinished Scopes.
     - Skipped malformed lines, or an incomplete last line (5.2).
3. **Summary cards**, foldable and open by default. Clicking any number filters the list.
   - Changes per table × op (update/insert/delete) and status (planned/applied/failed). Applied and failed stay visible in Dry Runs, shown red there when non-zero.
   - Findings per check × level.
   - Scopes per kind, with error and unfinished counts. Clicking the unfinished count filters to the unfinished Scopes.
4. **Filter bar:**
   - **View buttons with counts:** All · Changes · Findings · Errors.
     - *Errors* is level ≥ ERROR: failed Changes, error Findings, error Messages and Scopes that raised.
     - The Errors button is red when its count is non-zero.
   - One **search box** (6.4).
   - A **level ≥** dropdown.
   - A **Tree / Flat** switch, plus expand all / fold to phases / fold all.
   - There is no logger dropdown and no time-range input. Both stay available in the query syntax.
5. **The list**, with a details panel that opens on demand.

**Columns:** Time · Scope · Status · Op · Table · Key · Label · Details.

- The header row stays in place.
- Columns resize by dragging a header edge, and a double-click resets them. Widths are remembered per browser.
- The list scrolls sideways when the columns are wider than the window.
- **Status:**
  - For Changes it shows the Change's status. For everything else it shows the **level** (`debug`/`info`/`warning`/`error`).
  - A Scope that ended with an exception shows `scope error`.
  - There is no Level column and there are no record-type symbols. A Finding is recognisable by its check name in Details and its filled table/key/label.
  - DEBUG rows are dimmed.
  - In a Dry Run, the status badge of an `applied` or `failed` Change is red with ⚠.
- **Details:**
  - Change: each changed field as `field: old → new`, then `error` and `msg`.
  - Finding: check name and `msg`.
  - Message: `msg` and `fields`.
- **Value display:**
  - Values are shown as logged.
  - `null` and `""` are shown distinctly, as a dim `NULL` badge and a dim `(empty)`. The help text explains the Uniface caveat (3.5).
  - `$truncated`, `$bytes` and `$unencodable` are shown as markers.
  - Compact date strings are not reformatted.

**Tree mode** (the default, with everything expanded):

- The Scope column holds guide lines, a fold caret and the Scope's `kind`.
- Scope header rows use the same columns:
  - Time: the start time.
  - Status: an outcome badge when the outcome isn't ok.
  - Key: the `key`, or "phase" for a Scope without one.
  - Label: the `label`.
  - Details: `msg` plus derived totals (records, planned/applied/failed, Findings, duration).
- **Sticky Scopes:** the Scopes enclosing the top visible row stay pinned above the list. Clicking one jumps to it.

**Flat mode:** a plain list. The Scope column shows the Scope path, with the full path on hover.

**Details panel:** opens on row click and closes with ✕, so the Details column normally gets the full width. For a record it shows:

- every field
- a field-changes table
- the traceback
- the raw JSON
- the Scope path, with each Scope clickable to reveal it in the tree

For a Scope row it instead shows the Scope's totals and a "show only this Scope" link.

### 6.3 Filters and Scope headers

_Source: [Scope headers under filters](issues/09-scope-headers-under-filters.md)._

Every filter follows one pruning rule.

- **When a filter is active:** a view other than All, a search query, a level ≥ setting above DEBUG, or a clicked summary number.
- **Tree mode with a filter active:**
  - A Scope header shows only if it matches the filter itself or contains a visible row.
  - Every Scope enclosing a visible row stays visible, so the tree path is never broken.
  - Without a filter, everything shows. The Run's full structure stays reachable through the unfiltered All view, "fold to phases" and the Scopes-per-kind card.
- **A Scope header matches on its own fields:** `kind`, `key`, `label`, `msg`, its Status (`info`, or `scope error`) and its start time.
  - A matching header shows even if nothing inside it matches. Its records are still filtered one by one.
  - Example: `acme` shows the ACME Scope and everything in it, even when it is empty.
  - Example: the Errors view shows a Scope that raised, but inside it only the records that are errors themselves.
- **Totals:** a header's derived totals always cover the whole Scope. While a filter is active, the header adds "k of n shown".
- **Flat mode:** Scope rows are ordinary rows. They show only when they match the filter themselves, and enclosing Scopes are not kept.
- **Unfinished Scopes** are not errors. The Errors view and `level>=error` don't match them. `is:unfinished` does, and so does the unfinished count on the Scopes card. The Run-level notice still reports them.

### 6.4 Search syntax

_Source: [Report layout](issues/07-report-layout.md), plus `is:unfinished` from [Scope headers under filters](issues/09-scope-headers-under-filters.md)._

- **Plain words** match the record's own text and the kind/key/label of the **Scopes it sits in**. So `acme status:failed` finds failed Changes under ACME customers. `key:` matches the same way.
- **Terms:**

  | Term | Matches |
  |---|---|
  | `level>=warning`, `level:error` | level |
  | `type:change,finding` | record type |
  | `table:`, `op:`, `status:`, `check:` | the field of that name |
  | `logger:` | logger name |
  | `key:` | key, including the keys of enclosing Scopes |
  | `kind:` | Scope kind |
  | `in:<scope id>` | records inside that Scope |
  | `after:`, `before:` | time, as hh:mm:ss |
  | `f.<field>=<value>` | `fields` and changed fields |
  | `is:warn` | status/mode mismatch |
  | `is:unfinished` | unfinished Scopes |

## 7. Budgets and verification

_Source: [Report size budget](issues/11-report-size-budget.md)._

Acceptance criteria at 100k records, opened from `file://` in a current desktop browser:

| Measure | Budget | Prototype measurement (synthetic data, fast desktop) | Build measurement (budget fixture, 100,011 records, headless Firefox) |
|---|---|---|---|
| Data ready | ≤ 0.5 s | 310–365 ms (decode ~110, parse ~140, model ~80) | 446 ms median (432/446/453), from navigation start to the first list rows |
| Filter / search | ≤ 50 ms | 1–25 ms | worst 41 ms median |
| Report size | none | | 11.9 MB, gzip ratio 4.27x |
| First real Log File ≥ 10k records | (to be measured) | | |

- **Measurement method:** the build measures from outside the page. Data ready is timed from navigation start, so it includes parsing the ~12 MB HTML (the prototype timed from script start). Each search, view click and level change is timed around the control that applies it, after waiting 1 s for the idle-time search index.

- **There is no file-size budget.** Size follows the data. Expect about 3–7 MB at 100k records, depending on how well the values compress (the synthetic data compresses ~9.5x, real data likely 4–6x). This figure is information only.
- **Load time** depends mainly on raw record bytes (parse and model building), so less compressible data barely affects it.
- **The Record schema stays unchanged** for size reasons: no short keys or string tables in the Log File.
- **Verification:**
  - The build includes a fixture generator with realistic entropy: random ids, names, free-text values and mixed field counts, with a gzip ratio ≤ 5x.
  - A test renders 100k records, checks both budgets and reports the size.
  - The first real Log File of ≥ 10k records is measured, and its numbers are added to the table above.

## 8. Out of scope

_Source: the map's Out of scope section._

- Searching or aggregating across multiple Runs: one Report per Log File.
- Generating rollback scripts from a Write Run's Log File. Old values are recorded, so this stays possible later.
- Automatic capture at the database/driver layer (SQLAlchemy hooks, statement interception).
- Redaction or masking of sensitive values: the developer's responsibility.
- Comparing a Dry Run with a Write Run (did everything planned get applied?). That relates two Runs. Matching by `table` + `key` + `op` stays possible later.
- Rich content in records (tables, links, SQL blocks). The Report layout work found no need. If real scripts miss it, it is a fresh effort.
- An lnav format file for reading Log Files in a terminal. Deferred by Package layout & render CLI.

## 9. Gaps noticed while assembling

These points are not decided by any ticket. They are listed so the builder asks instead of guessing:

- **Time zone of the Time column and of `after:`/`before:`.** `ts` is UTC. The prototype shows the UTC `hh:mm:ss.mmm` slice of `ts`. Whether the Report shows UTC or local time, and how `after:`/`before:` behave for a Run that crosses midnight, isn't specified.
- **Where the renderer's success summary line goes.** Under `-o -` the Report itself goes to stdout, so the stream for the summary line (5.3) matters.

## Traceability

Each map decision appears once, in the section listed below.

| Decision (ticket) | Section |
|---|---|
| [Prior-art survey for structured logs → HTML](issues/01-prior-art-survey.md) | 4.6 |
| [Making 100k records usable in one HTML file](issues/02-large-single-file-html.md) | 6.1 |
| [Record schema for Message, Finding, Change](issues/03-record-schema.md) | 3.1, 3.3 |
| [Serialization of database values](issues/04-value-serialization.md) | 3.5 (Report display in 6.2) |
| [Scope model](issues/05-scope-model.md) | 3.4 |
| [Run Header contents](issues/06-run-header.md) | 3.2 |
| [Report layout](issues/07-report-layout.md) | 6.2, 6.4 |
| [Logger API ergonomics](issues/08-logger-api.md) | 4.1–4.5 |
| [Scope headers under filters](issues/09-scope-headers-under-filters.md) | 6.3 |
| [Package layout & render CLI](issues/10-package-and-cli.md) | 2, 4.6 (`threading.local`), 5.1, 5.2, 5.4 |
| [Report size budget](issues/11-report-size-budget.md) | 5.3, 7 |

Replaced along the way (only the later answer appears above):

- `ContextVar` → `threading.local`: Prior-art survey and Logger API ergonomics, replaced by Package layout & render CLI.
- "The level filter never hides Scope headers": Scope model, replaced by Scope headers under filters.
- The 5 MB file-size budget: Making 100k records usable and Report layout, replaced by Report size budget.
- The optional `@tanstack/virtual-core` dependency: Making 100k records usable, ruled out by Package layout & render CLI (no vendored libraries) and Report layout (details panel instead of inline expansion).
- A pip-installable package: the map's charting notes, replaced by Package layout & render CLI (plain copied files).

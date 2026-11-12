# Run Header contents

Type: grilling
Status: resolved
Assignee: MyNameIs-13
Blocked by:

## Question

What does the Run Header (first record of every Log File) contain? Candidates: format version, run id, mode (Dry Run / Write Run), script name and arguments, start time, host/user, database target (without credentials), git sha of the script, free-form description. Is there a matching run-end record (end time, totals, exit status) so a Report can tell a completed Run from a crashed one?

Context: see the Answer of 05-scope-model.md (a `scope_end` record carries `duration_ms`, `outcome` `ok`/`error` and `exc`; a run-end record could mirror it. Scope records are written regardless of level, and the Run's records probably should be too).

## Answer

A Run is bracketed by two records: `run_start` (the Run Header, always the first line) and `run_end` (the last line). Both are always written regardless of the configured level. Nothing is captured automatically about the environment (no run id, host, user, argv or git); each record's `src` already says which line produced it.

**`run_start`**

- Common fields: `ts` (the Run's start time), `level` INFO, `logger` (this package's logger name), `type: "run_start"`. No `src`.
- `format`: `"1.0"`, as major.minor. A minor bump only adds optional fields. The renderer accepts any minor of a major it knows (showing a notice when the minor is newer than it knows) and refuses an unknown major with a clear message.
- `mode`: `"dry"` / `"write"`, required. A Change whose status doesn't fit the mode (`planned` in a Write Run, `applied`/`failed` in a Dry Run) is shown as a warning in the Report, not rejected.
- Optional, author-supplied: `title` (the Report title; falls back to the Log File's name), `description` (free text, e.g. a ticket reference), `target` (free-form object describing the database; credentials are the developer's responsibility), `fields`.

**`run_end`**

- Common fields: `ts` (the Run's end time), `level`, `logger`, `type: "run_end"`. No `src`.
- `duration_ms` and `outcome`: `ok`, `error` (an exception escaped; `exc` attached, record-schema shape) or `interrupted` (KeyboardInterrupt).
- A `SystemExit` records `exit_code`; it counts as `ok` for code 0/None, `error` otherwise.
- Level INFO, or ERROR for `error`/`interrupted`.
- No totals: the renderer derives them from the records.
- A Log File without `run_end` is shown as **unfinished** (the process was killed or crashed hard), like an unfinished Scope.

Example:

```jsonl
{"ts":"2026-11-12T20:01:00.000Z","level":"INFO","logger":"dbfixlog","type":"run_start","format":"1.0","mode":"dry","title":"Orphaned orders cleanup","target":{"database":"shop_prod"}}
...
{"ts":"2026-11-12T20:03:12.418Z","level":"INFO","logger":"dbfixlog","type":"run_end","outcome":"ok","duration_ms":132418}
```

Glossary: the Run Header definition now says it states whether the Run is a Dry Run or a Write Run. `run_end` is a structural marker with no term.

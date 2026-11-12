# Scope model

Type: grilling
Status: resolved
Assignee: MyNameIs-13
Blocked by: 03

## Question

How do Scopes work in the Log File? How is a Scope opened/closed (start/end records vs a scope path on every record), how does nesting work, what identifies the root entity (kind + key), and does a Scope record an outcome (ok / changed / failed) and duration? What happens to records logged outside any Scope, and to a Scope left open by a crash?

Context: see the Answer of 01-prior-art-survey.md (Eliot's start/end records and tree path; ContextVar + Filter pattern).

Context: see the Answer of 03-record-schema.md (the `scope` slot on every record; rows identified by `key` + `label`, which may suit a Scope's root entity too).

## Answer

Scopes appear in the Log File as `scope_start`/`scope_end` records, and every record inside a Scope carries its Scope path. Scopes are entity-shaped or phase-shaped, and they nest.

- **Identity:** the start record carries `id` (an integer from a per-Run counter, assigned when the Scope opens), `kind` (free-form, e.g. `"customer"` or `"orphan-check"`), an optional `key` object and an optional `label` object (same shapes as row identity in 03-record-schema.md), plus optional `msg`/`fields`. A Scope without `key` is a named phase of the Run.
- **`scope` slot:** the path of Scope ids, outermost first (`[1, 2]`). It is absent outside any Scope. Start and end records carry their *parent's* path, so they sit at the level of the Scope they open or close.
- **Records outside any Scope** are valid and shown at Run level.
- **Same entity twice:** each `scope(...)` call is a separate Scope. The Report does not merge them. A key filter finds both.
- **End record:** `id`, `duration_ms`, `outcome` `ok`/`error`. `error` means an exception escaped the Scope. The record then carries `exc` (record-schema shape), and the helper re-raises the exception. Richer outcomes (changed, had failed Changes, had Findings) are not recorded; the renderer derives them from the Scope's contents. A failed Change that the script caught leaves the Scope `ok`.
- **Levels:** start/end records are always written regardless of the configured logging level. They are stamped INFO, or ERROR for an `error` end. The Report's level filter never hides Scope headers, only their contents.
- **Crash:** a Scope with no end record is shown as *unfinished*. It closes at the last record in the file and has no duration. Telling a crashed Run from a completed one is left to 06-run-header.md.
- No new glossary term: start/end records are structural markers. The Scope definition in GLOSSARY.md was widened to cover phases and repeated entities.

Example:

```jsonl
{"type":"message","msg":"connected", ...}
{"type":"scope_start","id":1,"kind":"orphan-check","msg":"pass 1", ...}
{"type":"scope_start","id":2,"kind":"customer","key":{"id":42},"label":{"name":"ACME"},"scope":[1], ...}
{"type":"change","op":"delete","table":"orders","key":{"id":156},"status":"planned","scope":[1,2], ...}
{"type":"scope_end","id":2,"outcome":"ok","duration_ms":38,"scope":[1], ...}
{"type":"scope_end","id":1,"outcome":"ok","duration_ms":120, ...}
```

# Report layout

Type: prototype
Status: resolved
Assignee: MyNameIs-13
Blocked by: 01, 02, 03, 05

## Question

What does the Report look like and how does it behave? What is shown first (Run Header summary, totals of Changes per table and status, Findings per rule), how are Scopes and their records displayed (collapsible tree vs flat list with breadcrumbs), how are Changes shown (old → new), and how do free-text search and filters (level, logger, time, record type, table, key, fields) look and interact? Build a rough throwaway HTML prototype on sample data to react to.

Context: see the Answer of 02-large-single-file-html.md (fixed-height virtual rows, details in a side panel, own search box, Scope headers kept visible for matches).

Context: see the Answer of 03-record-schema.md (record fields, per-row Changes with a `changes` map, `key` + `label`). Re-measure the 02 budgets with records of that shape.

Context: see the Answer of 04-value-serialization.md (`$truncated`/`$bytes`/`$unencodable` markers, `null` vs `""` shown distinctly, values displayed as logged).

Context: see the Answer of 05-scope-model.md (`scope_start`/`scope_end` records, `scope` id path on every record, outcome `ok`/`error`/unfinished, derived per-Scope summaries, Scope headers never hidden by the level filter).

Context: see the Answer of 06-run-header.md (Run Header fields to summarise: `mode`, `title`, `description`, `target`, `fields`; `run_end` outcome/duration or *unfinished*; warnings for Change statuses that don't fit the mode; newer-minor-format notice).

## Answer

The Report is **variant E** of the prototype: a run summary on top, then one list with fixed, resizable columns, in which Scopes form a tree. Prototype (primary source): branch `prototype/report-layout` (commit a4cd752), `.scratch/db-fix-logging/prototypes/report-layout/`. Run `python build.py`, then open the output with `?variant=E`. Variants A–D were rejected along the way (see below).

**Page, top to bottom**

1. **Run Header block:** title, description, mode badge, `target`, `fields`, start time, outcome (with exit code) and duration, or *unfinished*.
2. **Mode strip and notices** (full width):
   - Dry Run: an amber strip, *"Dry Run: the Changes below are planned, not applied."* If any Change has status `applied` or `failed`, a **red** strip replaces it: *"Dry Run, but N Changes were logged as applied or failed: the script may have written to the database. Show them."* The strip only claims what the Log File shows, never "nothing was written".
   - Write Run with `planned` Changes: an amber notice, *"logged as planned in a Write Run: they were not carried out"*.
   - Also: Run unfinished (no `run_end`), Run outcome `error`/`interrupted`, newer-minor format, unfinished Scopes.
3. **Summary cards**, foldable and open by default. Every number filters the list when clicked:
   - Changes per table × op (update/insert/delete) and status (planned/applied/failed). Applied and failed stay in Dry Runs, shown red there when non-zero.
   - Findings per check × level.
   - Scopes per kind, with error/unfinished counts.
4. **Filter bar:**
   - **View buttons with counts:** All · Changes · Findings · Errors. *Errors* is level ≥ ERROR: failed Changes, error Findings, error Messages and Scopes that raised. The button is red when the count is non-zero. Views hide Scopes that contain no match.
   - One **search box** (syntax below).
   - **level ≥** dropdown.
   - **Tree / Flat** switch, and expand all / fold to phases / fold all.
   - No logger dropdown and no time-range inputs: nobody filters on those. Both stay available in the query syntax.
5. **The list**, with a details panel that opens on demand (see below).

**Columns:** Time · Scope · Status · Op · Table · Key · Label · Details.

- Header row stays in place. Columns resize by dragging a header edge, double-click resets, and widths are remembered per browser. The list scrolls sideways when the columns are wider than the window.
- **Status** shows a Change's status for Changes, and the **level** (`debug`/`info`/`warning`/`error`) for everything else. A Scope that ended with an exception shows `scope error`. There is no Level column and no record-type symbols. A Finding is recognisable by its check name in Details and its filled table/key/label. DEBUG rows are dimmed.
- **Details:**
  - Change: each changed field as `field: old → new`, displayed per Serialization of database values (`NULL` / `(empty)` badges, `$truncated` / `$bytes` / `$unencodable` markers), then `error` and `msg`.
  - Finding: check name and `msg`.
  - Message: `msg` and `fields`.
- In a Dry Run, an `applied`/`failed` Change's status badge is red with ⚠.

**Tree mode** (default, everything expanded)

- The Scope column holds guide lines, a fold caret and the Scope's `kind`.
- Scope header rows use the same columns: start time, outcome badge when not ok, `key` (or "phase"), `label`, and in Details `msg` plus derived totals (records, planned/applied/failed, Findings, duration).
- **Sticky Scopes:** the Scopes enclosing the top visible row stay pinned above the list. Clicking one jumps to it.

**Flat mode:** a plain list. The Scope column shows the Scope path, full path on hover.

**Details panel:** opens on row click and closes with ✕, so the Details column normally has the full width. It shows:
- every field of the record
- a field-changes table
- the traceback
- the raw JSON
- the Scope path, each Scope clickable to reveal it in the tree. For a Scope row, it instead shows the Scope's totals and a "show only this Scope" link.

**Search**

- Plain words match the record's text and the kind/key/label of the **Scopes it sits in**. So `acme status:failed` finds failed Changes under ACME customers. `key:` matches the same way.
- Query syntax: `level>=warning`, `level:error`, `type:change,finding`, `table:`, `op:`, `status:`, `check:`, `logger:`, `key:`, `kind:`, `in:<scope id>`, `after:`/`before:` (hh:mm:ss), `f.<field>=<value>` (fields and changed fields), `is:warn` (status/mode mismatch).

**Budgets, re-measured** with records of the Record schema shape: 100k records at ~272 B. Headless Firefox, file://, fast desktop.

| Measure | Budget | Measured |
|---|---|---|
| File size | ≤ 5 MB | 2.9 MB |
| Data ready | ≤ 0.5 s | 310–365 ms (decode ~110, parse ~140, model ~80) |
| Filter / search | ≤ 50 ms | 1–25 ms |

The synthetic values compress ~9.5x. Real data at 4–6x would give 5–7 MB, so the size budget is at risk (see the map's Not yet specified).

**Rejected**

- A as built: no column headers, fixed widths, truncated Scope breadcrumbs.
- B: facet sidebar, overloaded.
- C: tabs per record type, overloaded.
- D: columns, but Scope headers spanning the row and a wasteful Level column.
- Also rejected: a logger filter, a time-range filter, record-type symbols, a separate Level column, and a "nothing was written" claim in Dry Runs.

**Open:** the *Errors* view hides Scopes without errors, while Scope model says the level filter never hides Scope headers. Whether every filter should prune empty Scopes is its own ticket: Scope headers under filters. *(Resolved there: every filter prunes Scopes the same way, and `is:unfinished` joins the query syntax.)*

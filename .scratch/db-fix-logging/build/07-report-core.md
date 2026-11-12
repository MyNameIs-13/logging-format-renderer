# Report core: model, header, list

Status: resolved
Blocked by: 06

## What to build

The `report.js`/`report.css` base:

- the decode
- the data model: Scope tree, derived Scope totals, unfinished Scopes and Run, mode-mismatch warnings
- the Run Header block, the mode strip and all notices
- the fixed-height virtual list with its columns in Tree and Flat mode, with Scope header rows and value display

Not included: the filter bar and search (08), summary cards (09), the details panel, resizing, sticky Scopes and folding beyond a basic caret (10).

Spec: §6.1, §6.2 items 1, 2 and 5, the Columns, Tree mode (except sticky Scopes) and Flat mode, Value display. Times are shown in UTC (build README).

## Acceptance

- Node tests cover the model:
  - Scope tree from paths
  - totals
  - unfinished detection
  - `is:warn`-style mismatch flags
  - unknown `type` handled as a generic row
- In headless Firefox, a rendered Dry Run fixture with applied Changes shows the red strip. A clean Dry Run shows the amber strip. A Write Run with planned Changes shows the amber notice.
- NULL, `(empty)` and `$`-marker values display as specified.

## Done

- Commits: f681d86 (merge of ticket/07-report-core into build/db-fix-logging), 25f9ffb (Report model: Scope tree, totals, unfinished, mode mismatches, notices), 94ad432 (Report rows and cells: Tree/Flat lists, columns, value display), 718862a (Report core DOM: Run Header, mode strip, notices, virtual list), 41a76b3 (merge of build/db-fix-logging into the ticket branch), e4bf942 (Document the window.dbfixlogReport seam in report.js).
- 123 Python tests (including the headless Firefox checks, none skipped) + 13 JS tests pass after the merge (`python3 -m unittest discover -s tests`, `node --test tests/js/*.test.js`).
- The payload is unchanged (version 1). The model is derived in the browser and exported via `module.exports` for Node (`buildModel`, `treeRows`, `flatRows`, `modeStrip`, `runNotices`, `rowCells`, `rowClass`, `isHeader`, `isEntry`, helpers `valueHTML`, `scopeName`, `hms`, `duration`, `esc`, `LEVELS`).
- Model: `buildModel(payload)` gives `records`, `lines`, `payload`, `header`, `end`, `mode`, `unfinished`, `outcome` (`ok`|`error`|`interrupted`|`unfinished`), `scopes` (Map, start order), `unfinishedScopes`, `warn[i]` (reason or null; the `is:warn` flag) and `warnings`. A Scope is `{id, kind, start, end, last, parent, path, depth, children, outcome, totals}`; `totals` = `{records, planned, applied, failed, findings, duration_ms}` always covers the whole Scope (08's "k of n shown" uses `totals.records` as n).
- Row identity: a row is a record index; a Scope header row is its `scope_start` index. Entries are everything except run_start, run_end, scope_start and ok scope_ends. Error scope_ends are rows (Status "scope error", carry `exc`). Unknown types are generic rows. `totals.records` counts entries, not headers.
- Seams for later tickets:
  - `window.dbfixlogReport = {model, list, onQuery(q)}`. `onQuery` is called for every `[data-q]` link click (strip "Show them", notice "show"); it currently only scrolls to the first match. 08 replaces `report.onQuery` to set the search box/filter; 09 can reuse `data-q` on card numbers.
  - `list`: `mode`, `collapsed` (Set), `rows`, `refresh()`, `setMode(m)`, `toggle(id)`, `scrollToRecord(i)`, `setWidths([8 px])`, `draw()`. 08 sets `list.rowSource = (model, mode, collapsed) => rows` then `refresh()` (`treeRows`/`flatRows` are unfiltered). 10 uses `setWidths` (defaults `DEFAULT_WIDTHS`).
  - Empty `<div id="bar">` (08) and `<div id="cards">` (09) slots sit between the notices and the list. No Tree/Flat switch in the UI yet (08 owns the filter bar); use `list.setMode`.
  - Markup: `.lhead .grid .hc[data-col]` header; `.list > .sizer + .rows > .vr.grid[data-i]` rows; grid columns from `--cols`/`--tw` on `.listwrap`; header synced to horizontal scroll via translateX in `draw()`. Sticky Scopes (10) overlaying `.listwrap` would need `position: relative`. Fold caret `[data-fold=id]` toggles `list.collapsed`; no row click or details yet (10). `.strip[data-tone]`, `.notice[data-kind][data-tone]`.
  - The browser test PROBE in tests/test_report_browser.py reads `.strip`, `.notice`, `.lhead .hc` and `.vr` cell texts; keep these hooks or update the PROBE.
- Choices beyond the spec:
  - Flat mode shows Scope header rows as ordinary rows, with the full path (including the Scope itself) in the Scope column.
  - Unfinished Scope header: "unfinished" badge in Status; duration omitted from its totals.
  - Write Run planned Changes get a "planned ⚠" badge with an amber outline; Dry Run applied/failed get a solid red "⚠" badge.
- Gap: the Uniface NULL-vs-empty caveat is only a `title` tooltip on the NULL/`(empty)` badges so far; the help text (08's search help) should also explain it.

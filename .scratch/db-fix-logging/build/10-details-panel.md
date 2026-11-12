# Details panel, resize, sticky Scopes, folding

Status: resolved
Blocked by: 07

## What to build

- The on-demand details panel, for records and for Scope rows. Its "show only this Scope" link may set `in:<id>` once ticket 08 is merged; until then it scrolls to the Scope.
- Column resizing, with widths remembered per browser (wrap storage in try/catch). Double-click resets a width.
- Horizontal scroll.
- Sticky Scopes, jump on click.
- Expand all / fold to phases / fold all.

Spec: §6.2 (Columns, Tree mode sticky Scopes, Details panel), §6.2 item 4 (fold buttons).

## Acceptance

Headless Firefox checks:
- The panel opens on click, closes with ✕, and shows the raw JSON, the traceback, the field-changes table and a clickable Scope path.
- Sticky headers match the top visible row's enclosing Scopes.
- "Fold to phases" collapses entity Scopes and keeps phases visible.

## Done

- Commits: a931988 (merge of ticket/10-details-panel into build/db-fix-logging), 68ac53f (Add fold sets and sticky Scope paths to the Report model), 9de7550 (Remember Report column widths per browser, tolerating broken storage), e9b2073 (Add the Report details panel for records and Scopes), f5dd1a0 (Check sticky Scopes, fold buttons, resizing and sideways scroll in Firefox), 99e106b (merge of build/db-fix-logging into the ticket branch).
- 130 Python (incl. 7 new Firefox checks) + 17 JS tests passed on the ticket branch; after the merge 145 Python + 17 JS tests pass (`python3 -m unittest discover -s tests`, `node --test tests/js/*.test.js`).
- Files: `report.js`, `report.css` (appended section), `tests/js/details.test.js`, `tests/test_report_details_browser.py` (reuses the Firefox lifecycle of test_report_browser via `StubReportInFirefox.__dict__`, so its tests don't run twice).
- New API: `report.open(i)`, `report.close()`, `report.reveal(id)`, `report.fold(how)`; `list.selected`. Pure helpers: `foldSet(m, "none"|"phases"|"all")`, `stickyScopes(m, rows, k)`, `loadWidths`/`saveWidths` (localStorage key `dbfixlog-report-widths`, try/catch'd), `recordDetailsHTML`, `scopeDetailsHTML`, `detailsPanelHTML`. DOM: `installListTools(doc, app, report)` is called from `renderReport`; it moves `.listwrap` into `.main` beside `<aside class="panel">` and adds `.stick`, `.rz` handles and `#treetools`. `list.draw` is wrapped (selection + sticky); createList is untouched.
- "Fold to phases" folds keyed Scopes and keeps keyless phases open.
- For ticket 08: "show only this Scope" is `<a data-q="in:<id>">`, routed through `report.onQuery`. The 07 placeholder onQuery has one branch (`in:N` calls `report.reveal(N)`); when 08 replaces onQuery, `in:N` should set the query. Fold buttons are in their own `#treetools` div (`[data-foldall=...]`, delegated click); if moved into the filter bar they need their own delegation or `report.fold(how)`. `report.reveal(id)` switches to tree mode, so a Tree/Flat UI should sync from `list.mode`. Under filters, reveal relies on 08's rule that enclosing Scopes of visible rows stay visible; a filtered-out Scope makes `scrollToRecord` return false. Sticky rows follow `list.rows`.
- Known test-harness issue: an uncaught JS exception in a bidi_eval.mjs probe exits without `session.end`, leaking the Firefox session, and later tests fail with "Maximum number of active sessions". The try/catch probe pattern in `test_report_details_browser.probe()` avoids it.

# Search, views and filter pruning

Status: resolved
Blocked by: 07

## What to build

The filter bar (views with counts, search box, level ≥ dropdown, Tree/Flat switch), the query parser and matcher, and the one pruning rule for Scope headers. Expose a filter API that ticket 09's summary-card clicks can call.

Spec: §6.2 item 4, §6.3, §6.4 (every term, including `is:unfinished` and `is:warn`; `after:`/`before:` in UTC).

## Acceptance

- Node tests:
  - every query term
  - plain words matching enclosing Scopes' kind/key/label
  - the pruning rule in Tree mode (enclosing Scopes kept, a matching header shown when empty, the Errors view inside a raising Scope)
  - Flat mode, where Scope rows are ordinary rows
  - unfinished Scopes are not errors
  - "k of n shown"
- Search at 100k synthetic records completes in ≤ 50 ms in Node, as a rough early check (ticket 11 does the real check).

## Done

- Commits: cd8f42c (merge of ticket/08-search-filters into build/db-fix-logging, including the reconciliation with ticket 10), e843c5b (Query parser, matcher and Scope-header pruning for the Report list), 5f68db1 (Filter bar: views with counts, search box with help, level dropdown, Tree/Flat), 4b0cd76 (merge of build/db-fix-logging into the ticket branch).
- 141 Python + 32 Node tests passed on the ticket branch; after the merge 148 Python (all Firefox checks ran) + 36 Node tests pass (`python3 -m unittest discover -s tests`, `node --test tests/js/*.test.js`).
- Performance (Node, 100k synthetic): every query runs in 5–15 ms once the search index is built. The index (`m.search`, lazy) takes ~130–170 ms and the browser builds it in `requestIdleCallback` right after load. Ticket 11 should account for this when it compares "data ready" with the first search.
- Filter API: `window.dbfixlogReport.filter`, with `{query(q), set(partial), get(), last}`. `report.onQuery(q)` calls `filter.query(q)`, so every `[data-q]` link works. Pure exports: `parseQuery`, `compileFilter`, `matchRow`, `filterRows`, `viewCounts`, `VIEWS`. `rowCells`/`totalsHTML`/`detailsHTML` take an optional 5th/3rd `shown` argument.
- Behaviour choices:
  - All terms are ANDed. A comma inside one term means OR.
  - Unknown or malformed terms are treated as plain words.
  - `after:`/`before:` are inclusive at the precision typed (UTC).
  - `f.x=v` is an exact, case-insensitive match.
  - `logger:` is a prefix match.
  - Plain words don't search logger, src, ts or duration.
- Reconciliation with ticket 10 (in the merge commit):
  - "show only this Scope" (`in:<id>`) now sets the filter. Clicking a Scope-path crumb still reveals and scrolls.
  - The fold buttons live in the filter bar's `.fold-slot` and have their own delegated click. They are hidden in Flat mode. `#treetools` remains only as a fallback when there is no filter bar.
  - The Tree/Flat switch syncs from `list.mode` on every refresh, including after `report.reveal()`.
  - Sticky Scope rows pass `list.shown` to `rowCells`.
  - New Firefox assertions in `tests/test_report_details_browser.py` cover these.
- `tests/browser/bidi_eval.mjs` now ends the BiDi session before failing, so one failing probe no longer breaks every later Firefox test with "Maximum number of active sessions".

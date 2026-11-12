# Build tickets: Database Fix Logging

Implementation tickets for [SPEC.md](../SPEC.md). They form a task graph. A ticket is on the frontier when it is `Status: open`, unassigned, and every ticket in its `Blocked by` line is `Status: resolved`. A ticket is resolved by setting `Status: resolved` and appending `## Done` with the commit(s).

| # | Ticket | Blocked by |
|---|---|---|
| 01 | [Writer core and Run lifecycle](01-writer-core.md) | |
| 02 | [Value encoding](02-value-encoding.md) | 01 |
| 03 | [Scopes in the writer](03-scopes.md) | 01 |
| 04 | [Typed calls: change, finding, get_logger](04-typed-calls.md) | 02, 03 |
| 05 | [Console handler](05-console-handler.md) | 04 |
| 06 | [Render CLI and embedding](06-render-cli.md) | |
| 07 | [Report core: model, header, list](07-report-core.md) | 06 |
| 08 | [Search, views and filter pruning](08-search-filters.md) | 07 |
| 09 | [Summary cards](09-summary-cards.md) | 08 |
| 10 | [Details panel, resize, sticky Scopes, folding](10-details-panel.md) | 07 |
| 11 | [Budget fixture, 100k test, end-to-end](11-budget-e2e.md) | 05, 09, 10 |

## Conventions for every ticket

- **Files at the repo root:** `dbfixlog.py`, `dbfixlog_render.py`, `report.js`, `report.css`. Tests go in `tests/`.
- **Python tests:** stdlib `unittest` only, run with `python3 -m unittest discover -s tests`. There is no pytest and no third-party package.
- **JS logic tests:**
  - `node --test tests/js/*.test.js` (a bare `tests/js/` directory argument fails on Node 24).
  - `report.js` stays one plain script with no modules and no build step. Pure functions (query parser, filters, model) are exposed for Node with `if (typeof module !== "undefined") module.exports = {...}`.
- **Browser checks:** headless Firefox (`firefox --headless`) on a rendered Report opened from `file://`.
- **Python 3.6.3 compatibility:** this machine has no 3.6 interpreter and no Docker. `tests/test_py36_compat.py` (added in ticket 01) parses both Python files and fails on known 3.7+ constructs and imports. Running the suite under real Python 3.6 is still owed (SPEC §2).
- **Spec §9 gaps, settled by the user on 2026-11-12:**
  - The Report's Time column and `after:`/`before:` use **UTC** (the `hh:mm:ss.mmm` slice of `ts`, as in the prototype). There is no special handling for midnight.
  - The renderer's success summary line goes to **stderr**.
- **References:**
  - Prototype (throwaway, may be adapted): branch `prototype/report-layout`, `.scratch/db-fix-logging/prototypes/report-layout/` (`template.html` variant E).
  - Embedding and benchmark scripts: branch `research/large-single-file-html`.

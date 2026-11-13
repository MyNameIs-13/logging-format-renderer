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
- **No test-only code in shipped files:** `dbfixlog.py`, `dbfixlog_render.py`, `report.js` and `report.css` carry nothing that exists only for tests (no exported functions, no globals, no timing hooks, no data attributes or environment variables that only tests read).
- **Report tests:** `report.js` stays one plain script with no modules and no build step. Its behaviour is tested only in headless Firefox (`firefox --headless`) on rendered Reports opened from `file://`, driven through the DOM like a user (clicks, the search box, the level select) and reading what the page shows. The shared harness is `tests/browser_report.py`, and the WebDriver BiDi driver is `tests/browser/bidi_eval.mjs` (Node runs only that driver; there are no Node tests).
- **Python 3.6.3 compatibility:** this machine has no 3.6 interpreter and no Docker. `tests/test_py36_compat.py` (added in ticket 01) parses both Python files and fails on known 3.7+ constructs and imports. Running the suite under real Python 3.6 is still owed (SPEC §2).
- **Spec §9 gaps, settled by the user on 2026-11-12:**
  - The Report's Time column and `after:`/`before:` use **UTC** (the `hh:mm:ss.mmm` slice of `ts`, as in the prototype). There is no special handling for midnight.
  - The renderer's success summary line goes to **stderr**.
- **References:**
  - Prototype (throwaway, may be adapted): branch `prototype/report-layout`, `.scratch/db-fix-logging/prototypes/report-layout/` (`template.html` variant E).
  - Embedding and benchmark scripts: branch `research/large-single-file-html`.

## Review fixes

Branch `ticket/review-fixes` (no ticket file), merged in 636f819. 216 Python tests pass, including the Firefox tests and the 100k budget test. Measurements are in SPEC §7.

| # | Outcome |
|---|---|
| P1 | Fixed: cycles, raising dict keys and raising exception `__str__` give `$unencodable`; the record is kept. |
| P2 | Fixed: known types with missing or odd fields get a ⚠ badge, a details-panel warning and an `odd_fields` notice. |
| P3 | Skipped. Measuring a real Log File of 10k+ records is **still owed**. |
| P4 | Not fixed: no 3.6 interpreter. The 3.6 check now also scans `tests/`. A real Python 3.6 run is **still owed**. |
| P5 | Kept; documented in SPEC §4.1 (root level lowered during a Run). |
| P6/P7 | Fixed: `table:` exact, Write Run "planned ⚠" badge removed. Level aliases, `type:scope`, `logger:` prefix and `--version` kept. Timing hooks later removed (R2). |
| P8 | Fixed: `kind:` on Scope records matches their own kind; card numbers equal the matches they link to. |
| P9 | Fixed: a parseable last line without a newline is kept. |
| P10 | Fixed: console prints the record's UTC time. |
| P11 | Fixed: Message bodies use the handler's Formatter (exc and stack_info). |
| P12 | Fixed; documented in SPEC §4.3 (explicit `status=` vs ERROR level). |
| P13 | Documented, not changed: SPEC §6.1 (idle-time index build, 150 ms debounce). |
| S1–S7, S11–S13 | Fixed. |
| S8, S9 | Skipped (public signature; file-format values). |
| S10 | Partly fixed. |
| U1 | Fixed: no spec/ticket references in code or tests, enforced by a test. |
| U2 | Fixed: no module-level mutable state or active-Run lookup; a shared RunFilter resolves records. Concurrent `run()` from two threads is unsupported (SPEC §4.6). |
| R1 | `strict` removed from dbfixlog; logging never raises. `dbfixlog_render.py --strict` stays. |
| R2 | Timing hooks removed; the budget test measures from outside, from navigation start. |
| R3 | Page globals and test-only data attributes removed. |
| R4 | Node tests and `module.exports` removed; coverage moved to Firefox DOM tests. |
| R5 | `get_logger()` adapters have no `dry_run`/`write_run`; helpers get `log` or the mode passed in (SPEC §4.2). |
| R6 | Test-only payload fields removed; the Report now shows malformed lines' numbers and samples. |

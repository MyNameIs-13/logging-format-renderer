# Budget fixture, 100k test, end-to-end

Status: resolved
Blocked by: 05, 09, 10

## What to build

- A fixture generator with realistic entropy, written with `dbfixlog.py` itself so it doubles as an end-to-end test. It produces:
  - random ids, names and free text
  - mixed field counts
  - nested Scopes, Findings and failed Changes
  - a gzip ratio ≤ 5x
- A test that renders 100k records and measures, in headless Firefox from `file://`, data-ready time (≤ 0.5 s) and filter/search time (≤ 50 ms). It reports the file size.
- An end-to-end test: a sample check/fix script in a Dry Run and a Write Run, then render, then load the Report without JS errors.

Spec: §7. See the benchmark method on branch `research/large-single-file-html`.

## Acceptance

- Both budgets pass on this machine, and the measured numbers are recorded in this ticket's Done section.
- If a budget fails, the renderer may reshape the embedded data internally (SPEC §6.1). The Log File format must not change.

## Done

- Commits: 894e110 (merge of ticket/11-budget-e2e into build/db-fix-logging; clean, no conflicts), 9569051 (Add a realistic-entropy budget fixture written through dbfixlog), 798b81c (Measure the 100k budgets in Firefox; inflate the payload into a presized buffer), 8804f77 (End-to-end: sample check/fix script in Dry and Write Runs, rendered, loaded without JS errors).
- After the merge 165 Python (Firefox checks and the 100k budget test included) + 45 Node tests pass (`python3 -m unittest discover -s tests`, `node --test tests/js/*.test.js`). Set `DBFIXLOG_SKIP_BUDGET` to skip the 100k test (about 10 s); `DBFIXLOG_SKIP_BROWSER` skips it too.
- Files: `tests/budget_fixture.py` (`generate(path, n, seed)`; CLI `python3 tests/budget_fixture.py N OUT [SEED]`; simulated clock so `ts` varies), `tests/test_budget.py` (`BudgetFixture` 20k, `BudgetInFirefox` 100k, prints `[budget]` lines on stderr, judged on the median of 3 loads), `tests/test_e2e.py` + `tests/fixtures/sample_fix.py` (SQLite check/fix script, Dry Run and Write Run with one failed update), `tests/browser/bidi_eval.mjs` now reports `js-errors: [...]` from `log.entryAdded`.
- Measured (headless Firefox, `file://`, this machine, 100,011 records, seed 7, median of 3):
  - Data ready: ~375–380 ms (decode+parse ~340, model+render ~35; ~430 ms from navigation start) vs the 500 ms budget.
  - Slowest filter/search: ~36–39 ms (plain-word scans such as "INV-2024" and "deadlock"; structured filters 8–20 ms) vs the 50 ms budget.
  - Idle search-index build: ~190–200 ms after ready. A search typed before it finishes pays that once.
  - Log File 36.8 MB (~367 B/record). Report 11.8 MB. gzip ratio 4.28x (budget ≤ 5x).
- No data reshaping was needed and the payload format is unchanged (version 1). `decodePayload` was optimised: it inflates into a buffer presized from the gzip ISIZE trailer, uses `Uint8Array.fromBase64` when available, and decodes once with a single `TextDecoder` (inflate+decode ~180–350 ms down to ~140 ms; data ready ~440 ms down to ~375 ms). `report.timing = {decode, render, ready, nav}`, `<html data-ready-ms>` and `filter.indexMs` expose the timings.
- Margins are modest. On a slower machine the plain-word scan (linear over the search text) and `JSON.parse` are the first to break 50 ms / 500 ms.

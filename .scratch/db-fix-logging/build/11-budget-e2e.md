# Budget fixture, 100k test, end-to-end

Status: open
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

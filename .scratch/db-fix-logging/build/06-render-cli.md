# Render CLI and embedding

Status: resolved
Blocked by:

## What to build

`dbfixlog_render.py` (it must not import `dbfixlog.py`) plus stub `report.js` and `report.css` files that it inlines.

- Write a hand-made Log File in `tests/fixtures/` (the `dbfixlog.py` writer may not exist yet).
- Embed the records gzip+base64 in `<script type="application/json">`. Pass everything the Report needs alongside them: the records with their line numbers, the notices (skipped or incomplete lines, newer minor), the title and the renderer version. Choose a payload shape that ticket 07 can build on, and document it at the top of `report.js`.
- The stub `report.js` only decodes the payload and shows the record count, which proves the round trip works.

Spec: §2, §5.1, §5.2, §5.4, §5.3 (summary line to **stderr**, see build README), §6.1 (embedding).

## Acceptance

- Unittest coverage for:
  - each exit code (0–4)
  - the output path default, `-o PATH` and `-o -`
  - title precedence
  - an unfinished file
  - a partial last line
  - malformed lines, with and without `--strict`
  - an unknown major (exit 3) and a newer minor (notice)
  - the one-line `dbfixlog_render:` errors
- A headless Firefox check shows the stub decodes the embedded payload from `file://`.

## Done

- Commits: 3aec62c (merge of ticket/06-render-cli into build/db-fix-logging; drops tracked `tests/__pycache__/*.pyc`), 799b0f6 (default render embeds records gzip+base64), 3dc959d (`-o PATH`, `-o -`, summary line on stderr), 95705fe (title precedence, payload meta), 054a7db (unfinished files, partial last line, malformed lines, `--strict`), fa6777b (exit codes 1-3, newer-minor notice, one-line errors, `--help`, `--open`), 9a4ed54 (standalone copy tests), 03fc8bf (stub report.js decodes the payload; headless Firefox and Node checks), 1296e87 (merge of build/db-fix-logging into the ticket branch).
- Ticket branch: 62 Python tests + 1 Node test pass, including the headless Firefox `file://` decode. After the merge: 72 Python tests (`python3 -m unittest discover -s tests`) and 1 Node test (`node --test tests/js/*.test.js`) pass.
- Payload shape v1 is documented at the top of `report.js`: one `<script type="application/json" id="dbfixlog-payload">` holding base64(gzip(UTF-8 JSON)) with keys `payload`, `renderer`, `source`, `title`, `unfinished`, `notices`, `records`, `lines`. `_render()` builds the dict and `build_html(payload, title)` wraps it; bump `PAYLOAD_VERSION` if 07 reshapes it.
- Choices beyond the spec:
  - Exit 1 for a missing or garbled `run_start.format`, a malformed first line (even without `--strict`), an unwritable output, or an unreadable report.js/report.css.
  - The unknown-major check (exit 3) runs before the `--strict` malformed check (exit 4).
  - Empty, non-UTF-8 and NaN/Infinity lines count as malformed.
  - A last line without a trailing newline is always skipped as incomplete, even if it holds valid JSON.
- Seams for later tickets: `report.js` keeps `<html data-state data-record-count data-error>` hooks for `tests/test_report_browser.py`; `tests/browser/bidi_eval.mjs` is a reusable WebDriver BiDi driver for later browser checks.

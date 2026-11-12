# Render CLI and embedding

Status: open
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

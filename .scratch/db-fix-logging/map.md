# Map: Database Fix Logging → HTML Reports

Labels: wayfinder:map

## Destination

A spec, ready to hand off for building, for (1) a Python stdlib-`logging`-based Log File format for database check/fix scripts (Dry Runs and Write Runs) and (2) one general renderer that turns any Log File (up to ~100k records) into a self-contained, readable, searchable HTML Report.

## Notes

- Domain: ad-hoc scripts that check and manipulate databases; each Run spans multiple connected tables/fields. Vocabulary lives in [GLOSSARY.md](../../GLOSSARY.md): use its terms (Run, Dry Run, Write Run, Log File, Run Header, Report, Message, Finding, Change, Scope).
- Skills: consult `domain-modeling` (keep GLOSSARY.md current) on every grilling ticket.
- Settled while charting (destination-level, not tickets):
  - One Run → one Log File → one Report; a static, single HTML file (inline JS/CSS, no server), opened locally or shared as an attachment/CI artifact.
  - Log File is JSON Lines (one JSON object per line), first line a Run Header carrying a format version. An optional console handler gives a terse live view; it is not a second record.
  - Typed records: Message, Finding, Change. A Change has a status `planned` (Dry Run) / `applied` / `failed` (Write Run), and always records old and new value.
  - Connected-table work is grouped by Scope around a root entity (e.g. `with scope("customer", 42):`); Scopes nest.
  - Scripts log explicitly (`log.change(...)`, etc.); database-agnostic.
  - Search in the Report: free text, plus filters by level, logger, time, record type, table, key, and structured fields.
  - Shipped as plain files copied together from this repo (logging module + render script) so format and parser version together; see Package layout & render CLI.
  - Keeping sensitive values out of logs is the developer's responsibility.
- Tracker: local markdown in `.scratch/db-fix-logging/` (see `issues/`). No git remote: research branches are local only.

## Decisions so far

- [Prior-art survey for structured logs → HTML](issues/01-prior-art-survey.md): nothing does this end to end; use plain stdlib `logging` (ContextVar + Filter for Scopes); learn from Eliot (start/end records, sequence numbers) and pytest-html (embedded JSON blob + JS)
- [Making 100k records usable in one HTML file](issues/02-large-single-file-html.md): feasible with plain JS: gzip+base64 embedded JSON (~3 MB), fixed-height virtual rows, linear-scan search (2–6 ms); budgets ≤ 5 MB / ≤ 0.5 s load / ≤ 50 ms search
- [Record schema for Message, Finding, Change](issues/03-record-schema.md): flat JSON records (`ts`, `level`, `logger`, `type`, `src`, `msg`, `scope`, `fields`, `exc`); one Change per row operation (`op` update/insert/delete, `changes` old/new map, final `status`); rows identified by `key` + human `label`; order = line position
- [Serialization of database values](issues/04-value-serialization.md): display-only plain JSON (Decimal as string, ISO dates, Uniface date strings as received), `$truncated`/`$bytes`/`$unencodable` markers, no NULL-vs-empty guarantee, logging never raises
- [Scope model](issues/05-scope-model.md): `scope_start`/`scope_end` records (`id`, `kind`, optional `key`/`label`; end has `outcome` ok/error + `exc` + `duration_ms`), id path `scope: [1,2]` on every record; phases allowed, no merging, always written regardless of level, missing end = unfinished
- [Run Header contents](issues/06-run-header.md): `run_start` (`format` "1.0", required `mode` dry/write, optional `title`/`description`/`target`/`fields`, no automatic context or run id) and `run_end` (`outcome` ok/error/interrupted, `duration_ms`, `exit_code`; missing = unfinished), both always written
- [Report layout](issues/07-report-layout.md): prototype variant E: run summary (foldable cards) over one list with sticky, resizable columns (Time, Scope tree, Status = Change status or level, Op, Table, Key, Label, Details), sticky Scopes, All/Changes/Findings/Errors views, one query-syntax search that also matches enclosing Scopes, details panel on demand; red strip for a Dry Run that logged applied/failed Changes; budgets hold at 100k (2.9 MB, ~350 ms, ≤ 25 ms)
- [Logger API ergonomics](issues/08-logger-api.md): `with run(path, mode=...) as log:` writes run_start/run_end; handler on root logger so stdlib calls become Messages (since replaced: only `log` and `get_logger()` loggers reach the Log File, see SPEC §4.2), `get_logger()` adapters add `change`/`finding`/`scope`; Change status defaults from mode (`error=` → failed); the script does and guards its own writes, "applied" = executed (commit not tracked); config as `run()` kwargs, console on at INFO to stderr
- [Scope headers under filters](issues/09-scope-headers-under-filters.md): one rule for every filter (view, search, level, summary click): show a Scope header only if it matches itself or contains a visible row, and keep enclosing Scopes; totals cover the whole Scope plus "k of n shown"; Flat mode treats Scope rows as ordinary rows; unfinished Scopes are not errors (`is:unfinished`)
- [Package layout & render CLI](issues/10-package-and-cli.md): no pip package: `dbfixlog.py` + standalone `dbfixlog_render.py` (+ `report.js`/`report.css`) copied together; Python 3.6.3+, stdlib only (`threading.local` for Scopes); `python dbfixlog_render.py LOG [-o] [--title] [--open] [--strict]`, `.html` beside the log, lenient on bad lines, exit codes 0/1/2/3/4
- [Report size budget](issues/11-report-size-budget.md): no file-size budget (size follows the data; expected 3–7 MB at 100k, information only); budgets are ≤ 0.5 s data ready and ≤ 50 ms search at 100k, checked on a realistic-entropy fixture; record schema unchanged, no runtime size check, no record cap

- [Assemble hand-off spec](issues/12-assemble-handoff-spec.md): [SPEC.md](SPEC.md) gathers every decision, applies the replaced answers and links each section to its ticket. Two undecided details (display time zone, summary-line stream) are listed for the builder in §9

## Not yet specified

<!-- empty: the remaining fog was ticketed (Report size budget) or ruled out of scope -->

## Out of scope

- Searching/aggregating across multiple Runs: one Report per Log File.
- Generating rollback scripts from a Write Run's Log File (old values are recorded, so this stays possible later).
- Automatic capture at the database/driver layer (SQLAlchemy hooks, statement interception).
- Redaction/masking of sensitive values: the developer's responsibility.
- Dry Run vs Write Run comparison (did everything planned get applied?): it relates two Runs, against one Run → one Log File → one Report. Matching by `table` + `key` + `op` stays possible later.
- Rich content in records (tables, links, SQL blocks): Report layout found no need; a fresh effort if real scripts miss it.
- lnav format file for a terminal view of Log Files: a nice-to-have deferred by Package layout & render CLI.

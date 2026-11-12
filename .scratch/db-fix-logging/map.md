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
  - Shipped as one small installable package (logging helper + `render` CLI) so format and parser version together.
  - Keeping sensitive values out of logs is the developer's responsibility.
- Tracker: local markdown in `.scratch/db-fix-logging/` (see `issues/`). No git remote: research branches are local only.

## Decisions so far

- [Prior-art survey for structured logs → HTML](issues/01-prior-art-survey.md): nothing does this end to end; use plain stdlib `logging` (ContextVar + Filter for Scopes); learn from Eliot (start/end records, sequence numbers) and pytest-html (embedded JSON blob + JS)
- [Making 100k records usable in one HTML file](issues/02-large-single-file-html.md): feasible with plain JS: gzip+base64 embedded JSON (~3 MB), fixed-height virtual rows, linear-scan search (2–6 ms); budgets ≤ 5 MB / ≤ 0.5 s load / ≤ 50 ms search
- [Record schema for Message, Finding, Change](issues/03-record-schema.md): flat JSON records (`ts`, `level`, `logger`, `type`, `src`, `msg`, `scope`, `fields`, `exc`); one Change per row operation (`op` update/insert/delete, `changes` old/new map, final `status`); rows identified by `key` + human `label`; order = line position
- [Serialization of database values](issues/04-value-serialization.md): display-only plain JSON (Decimal as string, ISO dates, Uniface date strings as received), `$truncated`/`$bytes`/`$unencodable` markers, no NULL-vs-empty guarantee, logging never raises
- [Scope model](issues/05-scope-model.md): `scope_start`/`scope_end` records (`id`, `kind`, optional `key`/`label`; end has `outcome` ok/error + `exc` + `duration_ms`), id path `scope: [1,2]` on every record; phases allowed, no merging, always written regardless of level, missing end = unfinished

## Not yet specified

- **Dry Run vs Write Run comparison**: whether/how a Report can relate a Write Run to the Dry Run that preceded it (did everything planned get applied?). Hangs on the Run Header (run identity); Changes could be matched by `table` + `key`/`label` + `op` (see Record schema).
- **Rich content in records**: tables, links, code/SQL blocks beyond text and key/value fields. Revisit once the Record schema and Report layout show whether it's missed.
- **Package layout & CLI**: package name, `render` command options (output path, title, opening a browser), Python version support.

## Out of scope

- Searching/aggregating across multiple Runs: one Report per Log File.
- Generating rollback scripts from a Write Run's Log File (old values are recorded, so this stays possible later).
- Automatic capture at the database/driver layer (SQLAlchemy hooks, statement interception).
- Redaction/masking of sensitive values: the developer's responsibility.

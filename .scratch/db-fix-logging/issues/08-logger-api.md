# Logger API ergonomics

Type: grilling
Status: open
Blocked by:

## Question

Which calls does a script author actually write? Covers: setup (opening the Log File, writing the Run Header, choosing Dry Run vs Write Run, the optional console handler), `log.message`/`log.finding`/`log.change` signatures, and how a Change's status is set in each mode. Also `scope(kind, key=..., label=...)` as a context manager (and decorator?), the custom type → encoder mapping, the `strict` flag and the truncation limit. How does the API keep a Dry Run from writing, or is that left entirely to the script?

Context: see the Answer of 03-record-schema.md (record fields), 04-value-serialization.md (encoder mapping, `strict`, truncation; logging never raises) and 05-scope-model.md (`scope_start`/`scope_end`, ids, re-raise on error, written regardless of level).

Context: see the Answer of 06-run-header.md (`run_start` fields the API must accept: `mode` required, optional `title`/`description`/`target`/`fields`; `run_end` with `outcome` ok/error/interrupted, `exit_code`, `duration_ms`, written even on exceptions; both written regardless of level).

Context: see the Answer of 07-report-layout.md (a Dry Run with any `applied`/`failed` Change gets a red "the script may have written to the database" strip; the Report only knows what was logged, so whether the API itself guards a Dry Run against writes matters here).

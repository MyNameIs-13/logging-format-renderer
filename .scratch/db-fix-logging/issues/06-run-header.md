# Run Header contents

Type: grilling
Status: open
Blocked by:

## Question

What does the Run Header (first record of every Log File) contain? Candidates: format version, run id, mode (Dry Run / Write Run), script name and arguments, start time, host/user, database target (without credentials), git sha of the script, free-form description. Is there a matching run-end record (end time, totals, exit status) so a Report can tell a completed Run from a crashed one?

Context: see the Answer of 05-scope-model.md (a `scope_end` record carries `duration_ms`, `outcome` `ok`/`error` and `exc`; a run-end record could mirror it. Scope records are written regardless of level, and the Run's records probably should be too).

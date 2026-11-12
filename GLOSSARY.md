# Database Fix Logging

A log format for scripts that check and modify databases, plus the readable, searchable HTML reports rendered from those logs.

## Runs

**Run**:
One execution of a check/fix script, producing exactly one Log File.
_Avoid_: job, session, execution

**Dry Run**:
A Run that inspects the database and records what it would change, without writing.
_Avoid_: simulation, preview, test run

**Write Run**:
A Run that actually applies its Changes to the database.
_Avoid_: live run, real run, apply run

**Log File**:
The machine-readable record of one Run, starting with a Run Header.
_Avoid_: log, trace

**Run Header**:
The first record of a Log File, identifying the format version and describing the Run.
_Avoid_: preamble, metadata line

**Report**:
The self-contained HTML page rendered from one Log File.
_Avoid_: page, viewer, dashboard

## Records

**Message**:
A free-text record, like an ordinary log line.
_Avoid_: line, entry

**Finding**:
A record stating that a check detected something noteworthy in specific rows.
_Avoid_: issue, problem, error, violation

**Change**:
A record of one insert, update or delete of one row, with status (planned, applied, failed). An update lists the old and new value of each field it modifies.
_Avoid_: update, edit, fix, diff

**Scope**:
A named grouping, around either a root entity (e.g. customer 42) or a named phase of the Run (e.g. orphan check), under which all records logged inside it nest. Scopes can nest inside each other. The same entity can appear in several separate Scopes.
_Avoid_: section, block, context, group

**Key**:
The values of a row's identifying database columns; may span several columns.
_Avoid_: id, primary id

**Label**:
Values chosen by the script author that let a human recognise a row (e.g. a barcode), shown beside its Key.
_Avoid_: code, name, display id

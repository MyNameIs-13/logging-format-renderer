# Report layout

Type: prototype
Status: open
Blocked by: 01, 02, 03, 05

## Question

What does the Report look like and how does it behave? What is shown first (Run Header summary, totals of Changes per table and status, Findings per rule), how are Scopes and their records displayed (collapsible tree vs flat list with breadcrumbs), how are Changes shown (old → new), and how do free-text search and filters (level, logger, time, record type, table, key, fields) look and interact? Build a rough throwaway HTML prototype on sample data to react to.

Context: see the Answer of 02-large-single-file-html.md (fixed-height virtual rows, details in a side panel, own search box, Scope headers kept visible for matches).

Context: see the Answer of 03-record-schema.md (record fields, per-row Changes with a `changes` map, `key` + `label`). Re-measure the 02 budgets with records of that shape.

Context: see the Answer of 04-value-serialization.md (`$truncated`/`$bytes`/`$unencodable` markers, `null` vs `""` shown distinctly, values displayed as logged).

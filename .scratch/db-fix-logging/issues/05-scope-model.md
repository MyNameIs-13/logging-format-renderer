# Scope model

Type: grilling
Status: open
Blocked by: 03

## Question

How do Scopes work in the Log File? How is a Scope opened/closed (start/end records vs a scope path on every record), how does nesting work, what identifies the root entity (kind + key), and does a Scope record an outcome (ok / changed / failed) and duration? What happens to records logged outside any Scope, and to a Scope left open by a crash?

Context: see the Answer of 01-prior-art-survey.md (Eliot's start/end records and tree path; ContextVar + Filter pattern).

Context: see the Answer of 03-record-schema.md (the `scope` slot on every record; rows identified by `key` + `label`, which may suit a Scope's root entity too).

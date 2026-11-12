# Record schema for Message, Finding, Change

Type: grilling
Status: open
Blocked by:

## Question

What exact fields does each record type carry in the Log File? Common fields (timestamp, level, logger, record type, Scope reference, source location?), Message (text, free key/value fields), Finding (rule/check name, table, key, severity, details), Change (table, key, field, old, new, status `planned`/`applied`/`failed`, error on failure). How is a row key represented, including composite keys? One Change per field, or one per row with several fields? How are exceptions/tracebacks recorded?

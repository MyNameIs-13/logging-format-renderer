# Serialization of database values

Type: grilling
Status: open
Blocked by: 03

## Question

How are database values written into JSON Lines so values (Change `changes` old/new, `key`, `label`, `fields`) round-trip faithfully and display unambiguously in the Report? Cover None/NULL vs missing, Decimal, datetime/date/time with timezones, bytes/blobs, large text, JSON/array columns, UUIDs, and unknown types (fallback to `repr`?). Is a type tag needed alongside the value?

Context: see the Answer of 01-prior-art-survey.md (python-json-logger's str() fallback loses type information).

Context: see the Answer of 03-record-schema.md (where values appear in a record).

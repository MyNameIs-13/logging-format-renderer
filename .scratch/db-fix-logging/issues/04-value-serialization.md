# Serialization of database values

Type: grilling
Status: open
Blocked by: 03

## Question

How are database values written into JSON Lines so old/new values in Changes round-trip faithfully and display unambiguously in the Report? Cover None/NULL vs missing, Decimal, datetime/date/time with timezones, bytes/blobs, large text, JSON/array columns, UUIDs, and unknown types (fallback to `repr`?). Is a type tag needed alongside the value?

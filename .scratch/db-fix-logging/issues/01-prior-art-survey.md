# Prior-art survey for structured logs → HTML

Type: research
Status: open
Blocked by:

## Question

What existing tools/libraries already cover parts of this, and what should we reuse or learn from rather than reinvent? Survey at least: python-json-logger, structlog (JSON renderer, contextvars binding — relevant to Scopes), stdlib `logging` extension points (Formatter, Handler, LoggerAdapter, `extra`, filters), lnav, and existing JSON-Lines/log → static HTML viewers. For each: what it does, its record shape, licence/maintenance, and whether it fits a stdlib-`logging` + single-file-HTML design for database check/fix scripts (see GLOSSARY.md).

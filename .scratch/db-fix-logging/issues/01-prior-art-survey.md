# Prior-art survey for structured logs → HTML

Type: research
Status: resolved
Blocked by:

## Question

What existing tools/libraries already cover parts of this, and what should we reuse or learn from rather than reinvent? Survey at least: python-json-logger, structlog (JSON renderer, contextvars binding — relevant to Scopes), stdlib `logging` extension points (Formatter, Handler, LoggerAdapter, `extra`, filters), lnav, and existing JSON-Lines/log → static HTML viewers. For each: what it does, its record shape, licence/maintenance, and whether it fits a stdlib-`logging` + single-file-HTML design for database check/fix scripts (see GLOSSARY.md).

## Answer

No existing tool renders a typed, Scope-nested JSON Lines log into a self-contained searchable HTML Report, so the renderer is ours to build. Full findings with citations: branch `research/prior-art-survey` (commit 478f8cd), file `.scratch/db-fix-logging/research/prior-art-survey.md` (`git show research/prior-art-survey:.scratch/db-fix-logging/research/prior-art-survey.md`).

- **Reuse** stdlib `logging` only. Stamp Scopes onto every record via the cookbook's `ContextVar` + `Filter` pattern. Put typed fields under one namespaced record attribute, because `extra` keys that clash with LogRecord attributes raise `KeyError`.
- **Learn from, don't depend on:**
  - python-json-logger: its reserved-attribute list. Its `str()` fallback loses type information for Decimal and similar values (relevant to Serialization of database values).
  - structlog: token-reset context binding. Its flat bound context can't model nested Scopes.
  - Eliot: explicit start/end records with a status, a tree-position path on every record, and a sequence number for ordering because timestamps are unreliable (relevant to the Scope model).
  - pytest-html: one embedded JSON blob rendered by JS, with filter state kept in URL query parameters (relevant to Report layout).
- **Optional extra:** ship an lnav format file so Log Files can also be read in a terminal.

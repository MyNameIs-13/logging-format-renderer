# Console handler

Status: open
Blocked by: 04

## What to build

The terse stderr console view controlled by `run(console=...)`.

Spec: §4.5.

## Acceptance

- On by default at INFO on stderr. `console=logging.WARNING` raises the level, and `console=False` turns it off.
- Changes and Findings print one line prefixed by the Scope label, matching the §4.5 example.
- Scope starts print a line. Scope ends print only on `error`. Messages use the stdlib format.
- No colours.

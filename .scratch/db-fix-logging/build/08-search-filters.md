# Search, views and filter pruning

Status: open
Blocked by: 07

## What to build

The filter bar (views with counts, search box, level ≥ dropdown, Tree/Flat switch), the query parser and matcher, and the one pruning rule for Scope headers. Expose a filter API that ticket 09's summary-card clicks can call.

Spec: §6.2 item 4, §6.3, §6.4 (every term, including `is:unfinished` and `is:warn`; `after:`/`before:` in UTC).

## Acceptance

- Node tests:
  - every query term
  - plain words matching enclosing Scopes' kind/key/label
  - the pruning rule in Tree mode (enclosing Scopes kept, a matching header shown when empty, the Errors view inside a raising Scope)
  - Flat mode, where Scope rows are ordinary rows
  - unfinished Scopes are not errors
  - "k of n shown"
- Search at 100k synthetic records completes in ≤ 50 ms in Node, as a rough early check (ticket 11 does the real check).

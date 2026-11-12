# Details panel, resize, sticky Scopes, folding

Status: open
Blocked by: 07

## What to build

- The on-demand details panel, for records and for Scope rows. Its "show only this Scope" link may set `in:<id>` once ticket 08 is merged; until then it scrolls to the Scope.
- Column resizing, with widths remembered per browser (wrap storage in try/catch). Double-click resets a width.
- Horizontal scroll.
- Sticky Scopes, jump on click.
- Expand all / fold to phases / fold all.

Spec: §6.2 (Columns, Tree mode sticky Scopes, Details panel), §6.2 item 4 (fold buttons).

## Acceptance

Headless Firefox checks:
- The panel opens on click, closes with ✕, and shows the raw JSON, the traceback, the field-changes table and a clickable Scope path.
- Sticky headers match the top visible row's enclosing Scopes.
- "Fold to phases" collapses entity Scopes and keeps phases visible.

# Summary cards

Status: open
Blocked by: 08

## What to build

The foldable summary cards: Changes per table × op and status, Findings per check × level, and Scopes per kind with error and unfinished counts. Clicking any number sets the filter through ticket 08's API.

Spec: §6.2 item 3, §6.3 (a clicked summary number is a filter; clicking the unfinished count filters to `is:unfinished`).

## Acceptance

- Node tests for card counts.
- Applied and failed counts in a Dry Run show red when non-zero.
- A headless Firefox check shows a click filters the list.

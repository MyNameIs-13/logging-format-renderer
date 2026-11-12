# Summary cards

Status: resolved
Blocked by: 08

## What to build

The foldable summary cards: Changes per table × op and status, Findings per check × level, and Scopes per kind with error and unfinished counts. Clicking any number sets the filter through ticket 08's API.

Spec: §6.2 item 3, §6.3 (a clicked summary number is a filter; clicking the unfinished count filters to `is:unfinished`).

## Acceptance

- Node tests for card counts.
- Applied and failed counts in a Dry Run show red when non-zero.
- A headless Firefox check shows a click filters the list.

## Done

- Commits: 5b03f99 (merge of ticket/09-summary-cards into build/db-fix-logging; clean, no conflicts), 9de7deb (Add foldable summary cards whose numbers filter the list).
- After the merge 150 Python (all Firefox checks ran) + 44 Node tests pass (`python3 -m unittest discover -s tests`, `node --test tests/js/*.test.js`).
- Pure exports: `summaryCounts(m)` returns `{changes: {rows, total}, findings: {levels, rows}, kinds}`; `cardsHTML(m)` returns `<details class="cards" open>` with `.card[data-card=changes|findings|scopes]`, or "" when there is nothing to count. `renderReport` fills `#cards` with it. Every non-zero number is an `a.cn[data-q]` link; zero is a dim, unlinked 0.
- Queries: Changes `type:change table:T op:O status:S` (cell), `type:change table:T op:O` (row), `type:change status:S` / `type:change` (totals). Findings `check:C level:l` / `check:C`. Scopes `type:scope_start kind:K`, error `type:scope_end kind:K`, unfinished `is:unfinished kind:K`. Values with whitespace are quoted; an empty value drops the term.
- Red: failed always; applied in a Dry Run; ERROR/CRITICAL Finding counts; the Scope error count.
- `FILTER_PROBE` in `tests/test_report_browser.py` now clicks `.notices [data-q]` instead of the first `[data-q]` on the page, because card numbers now come first.
- Known limits (from ticket 08's query semantics, unchanged): `kind:` also matches Scopes nested inside a Scope of that kind, and `table:orders` also matches `shop.orders` (a comma in a value acts as OR), so a card click may list more rows than its number. Every row shown still matches the term. Exact counts need a new own-kind-only query term, which the spec §6.4 table does not have.
- For ticket 11: the cards are built synchronously in `renderReport`, one O(n) pass over the records plus a pass over the Scopes.

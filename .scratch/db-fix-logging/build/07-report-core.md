# Report core: model, header, list

Status: open
Blocked by: 06

## What to build

The `report.js`/`report.css` base:

- the decode
- the data model: Scope tree, derived Scope totals, unfinished Scopes and Run, mode-mismatch warnings
- the Run Header block, the mode strip and all notices
- the fixed-height virtual list with its columns in Tree and Flat mode, with Scope header rows and value display

Not included: the filter bar and search (08), summary cards (09), the details panel, resizing, sticky Scopes and folding beyond a basic caret (10).

Spec: §6.1, §6.2 items 1, 2 and 5, the Columns, Tree mode (except sticky Scopes) and Flat mode, Value display. Times are shown in UTC (build README).

## Acceptance

- Node tests cover the model:
  - Scope tree from paths
  - totals
  - unfinished detection
  - `is:warn`-style mismatch flags
  - unknown `type` handled as a generic row
- In headless Firefox, a rendered Dry Run fixture with applied Changes shows the red strip. A clean Dry Run shows the amber strip. A Write Run with planned Changes shows the amber notice.
- NULL, `(empty)` and `$`-marker values display as specified.

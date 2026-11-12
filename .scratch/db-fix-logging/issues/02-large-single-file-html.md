# Making 100k records usable in one HTML file

Type: research
Status: resolved
Blocked by:

## Question

How can a single, self-contained static HTML file (inline JS/CSS, no server, opened from disk) stay fast and searchable with up to ~100k records? Investigate: embedding data (inline JSON vs `<script type="application/json">` vs compressed/base64 + `DecompressionStream`), resulting file sizes, browser limits, virtual scrolling / windowed rendering options (vanilla vs small vendored libraries), client-side free-text + field filtering speed (plain scan vs index), and nested/collapsible groups (Scopes) under virtualization. Recommend an approach with numbers.

## Answer

It works, and the approach is simple. Measured on 100k synthetic records (~205 bytes each) in Node 24 and headless Firefox from file://, on a fast desktop; expect a typical laptop to be ~2–5x slower (estimate). Full findings and benchmark scripts: branch `research/large-single-file-html` (commit b0e97d9), file `.scratch/db-fix-logging/research/large-single-file-html.md`.

- **Embedding:** gzip, then base64, inside a `<script type="application/json">` block; decode with `DecompressionStream("gzip")` and `JSON.parse`. Works from file:// in Chrome 80+, Firefox 113+ and Safari 16.4+. Size: 20.5 MB raw vs 2.9 MB compressed (synthetic text, so a best case; real logs likely compress 4–6x). Data is ready in ~150–250 ms. The embedded data must escape `<` (as `<`) so it can't close the script block early.
- **Browser limits:** the binding one is maximum element height (Firefox ~17M px). 100k fixed-height rows at 24–28 px is ~2.8M px, which fits without tricks.
- **Rendering:** ~100 lines of plain JS that render only the visible fixed-height rows, with record details in a side panel. Add `@tanstack/virtual-core` only if rows must expand inline. Ctrl+F can't see unrendered rows, so the Report needs its own search box.
- **Search:** a linear scan takes 2–6 ms per query and field filters ~1 ms. No index and no Web Worker needed. Heap ~135 MB.
- **Scopes:** rebuilding the visible-row list after expand/collapse, search or filter takes 2–3 ms; matches keep their parent Scope headers visible.
- **Proposed budgets at 100k records:** file ≤ 5 MB, data ready ≤ 0.5 s, search ≤ 50 ms. Re-measure once Record schema is decided, since record size drives every number.
- **Unsettled:** the Web Worker test in Firefox was inconclusive (test setup suspect). The design doesn't need workers.

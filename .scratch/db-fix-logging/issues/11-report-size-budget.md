# Report size budget

Type: grilling
Status: resolved
Assignee: MyNameIs-13
Blocked by:

## Question

What size budget does a Report hold to at 100k records, and how is it checked? The Report layout prototype gave 2.9 MB, but its synthetic values compress ~9.5x. Real Log Files at 4–6x would give 5–7 MB, over the 5 MB budget proposed in Making 100k records usable in one HTML file. Real data exists only once a script has been built. Should the budget be raised, should records be slimmed, should the renderer enforce or warn, and what should the builder verify (and on which data)?

Context: Answers of 02-large-single-file-html.md (embedding, proposed budgets) and 07-report-layout.md (re-measured budgets).

## Answer

**No file-size budget.** The design is already fixed: gzip+base64 embedding (02-large-single-file-html.md) and hand-written viewer code with no libraries (10-package-and-cli.md). That leaves file size as roughly the compressed data plus a few tens of KB of viewer code. The builder can't make it noticeably smaller, and a Report too large to attach reflects the Run, not a renderer defect. The 5 MB figure only checked that the embedding approach worked at all.

**Budgets that stay** (acceptance criteria at 100k records, file://, a current desktop browser):

| Measure | Budget |
|---|---|
| Data ready | ≤ 0.5 s |
| Filter / search | ≤ 50 ms |

**Expected size, information only:** about 3–7 MB at 100k records, depending on how well the values compress (synthetic ~9.5x, real data likely 4–6x). Load time depends mainly on raw record bytes (parse and model building), so less compressible data barely affects it.

**Record schema unchanged.** No short keys or string tables in the Log File. Inside the Report, the renderer may reshape the embedded data (e.g. columnar arrays) if the builder needs it to meet the budgets. That is an internal detail, not a format change.

**No runtime enforcement.** `dbfixlog_render.py` has no size check, warning or refusal. On success it prints one summary line (record count, Report size), so a large Report is visible without being an error.

**No record cap.** Log Files above 100k records render in full. The budgets are guaranteed only up to 100k, and no records are ever dropped.

**Verification:** the build includes a fixture generator with realistic entropy (random ids, names, free-text values, mixed field counts; gzip ratio ≤ 5x) and a test that renders 100k records and checks the two budgets, reporting size. The first real Log File of ≥ 10k records is measured, and its numbers are added to the spec's budget table.

No glossary change.

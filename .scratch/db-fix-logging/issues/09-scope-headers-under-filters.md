# Scope headers under filters

Type: grilling
Status: resolved
Assignee: MyNameIs-13
Blocked by:

## Question

When a filter is active in the Report's tree mode, which Scope header rows stay visible? Scope model says the level filter never hides Scope headers, only their contents. Report layout's view buttons (Changes, Findings, Errors) and search instead hide Scopes that contain no match. Otherwise 3,888 errors drown in 85k rows of Scope headers. Should the level dropdown also prune empty Scopes, so that every filter behaves the same? Or does keeping headers under the level filter serve a purpose (seeing the Run's structure, counting Scopes with nothing above DEBUG)? And does a Scope whose own key/label matches a search stay visible with none of its records?

Context: see the Answer of 05-scope-model.md (Scope headers never hidden by the level filter) and of 07-report-layout.md (views and search prune Scopes without matches; search also matches enclosing Scopes' kind/key/label).

## Answer

Every filter follows one pruning rule. The level dropdown no longer keeps every Scope header.

- **One rule:** a filter is active when any of these applies: a view other than All, a search query, level ≥ above DEBUG, or a clicked summary number. While a filter is active, a Scope header shows only if it matches the filter itself or contains a visible row. Every Scope enclosing a visible row stays visible, so the tree path is never broken. Without a filter, everything shows. The Run's full structure stays visible through the unfiltered All view, "fold to phases" and the Scopes-per-kind summary card. This replaces Scope model's "the level filter never hides Scope headers".
- **A Scope header matches on its own fields:** `kind`, `key`, `label` and `msg`; its Status, which is its level (`info`, or `scope error` when an exception escaped); and its start time. A matching header shows even if nothing inside it matches. Its records are still filtered one by one. Plain search words already match the kind/key/label of the Scopes a record sits in, so `acme` shows the ACME Scope and everything in it, even an empty one. The Errors view shows a Scope that raised, but inside it only the records that are errors themselves.
- **Totals:** a header's derived totals (records, planned/applied/failed, Findings, duration) always cover the whole Scope. While a filter is active, the header adds "k of n shown".
- **Flat mode:** Scope rows are ordinary rows there. They show only when they match the filter themselves; enclosing Scopes are not kept. The Scope column already shows each row's path.
- **Unfinished Scopes** (no end record) are not errors. The Errors view and `level>=error` do not match them. A new query term, `is:unfinished`, finds them, and the Scopes summary card's unfinished count filters to them when clicked. The Run-level notice still reports them.

No glossary change.

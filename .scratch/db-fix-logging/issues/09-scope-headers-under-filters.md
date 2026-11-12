# Scope headers under filters

Type: grilling
Status: open
Blocked by:

## Question

When a filter is active in the Report's tree mode, which Scope header rows stay visible? Scope model says the level filter never hides Scope headers, only their contents. Report layout's view buttons (Changes, Findings, Errors) and search instead hide Scopes that contain no match. Otherwise 3,888 errors drown in 85k rows of Scope headers. Should the level dropdown also prune empty Scopes, so that every filter behaves the same? Or does keeping headers under the level filter serve a purpose (seeing the Run's structure, counting Scopes with nothing above DEBUG)? And does a Scope whose own key/label matches a search stay visible with none of its records?

Context: see the Answer of 05-scope-model.md (Scope headers never hidden by the level filter) and of 07-report-layout.md (views and search prune Scopes without matches; search also matches enclosing Scopes' kind/key/label).

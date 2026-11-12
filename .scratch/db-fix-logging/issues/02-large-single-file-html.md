# Making 100k records usable in one HTML file

Type: research
Status: open
Blocked by:

## Question

How can a single, self-contained static HTML file (inline JS/CSS, no server, opened from disk) stay fast and searchable with up to ~100k records? Investigate: embedding data (inline JSON vs `<script type="application/json">` vs compressed/base64 + `DecompressionStream`), resulting file sizes, browser limits, virtual scrolling / windowed rendering options (vanilla vs small vendored libraries), client-side free-text + field filtering speed (plain scan vs index), and nested/collapsible groups (Scopes) under virtualization. Recommend an approach with numbers.

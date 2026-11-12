# Assemble hand-off spec

Type: task
Status: resolved
Assignee: MyNameIs-13
Blocked by: 11

## Question

Assemble the resolved tickets into one hand-off spec document (`SPEC.md` in this directory) for the builder. It makes no new decisions. It applies superseded answers (e.g. `threading.local` instead of ContextVar, per 10-package-and-cli.md), uses GLOSSARY.md terms, links each section to its ticket, and lists the Out of scope items from the map. Done when every decision on the map's Decisions so far appears in it exactly once.

## Answer

Done: [SPEC.md](../SPEC.md). It assembles all 11 decisions without adding any. Each section links its ticket, and a traceability table maps every Decisions-so-far entry to the section that holds it. Answers that were replaced along the way are applied, and the spec lists them:

- `threading.local` instead of `ContextVar`.
- One pruning rule for every filter, including the level filter.
- No file-size budget.
- No vendored virtual-scroll library.
- Plain copied files instead of a pip package.

The map's Out of scope list is copied in.

Two gaps that no ticket decides are listed in SPEC.md §9 for the builder to ask about rather than guess:

- Whether the Report's Time column and `after:`/`before:` use UTC or local time, including Runs that cross midnight. The prototype shows UTC.
- Which stream the renderer's success summary line goes to under `-o -`.

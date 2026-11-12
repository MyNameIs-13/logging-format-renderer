// Ticket 10: folding, sticky Scopes, remembered column widths (pure parts).
const test = require("node:test");
const assert = require("node:assert");
const path = require("node:path");

const R = require(path.join(__dirname, "..", "..", "report.js"));

const TS = "2026-11-12T20:01:00.000Z";
function rec(type, extra) {
  return Object.assign({ ts: TS, level: "INFO", logger: "fix", type: type, src: "fix.py:1" }, extra);
}
function payload(records) {
  return { payload: 1, title: "t", source: "t.jsonl", notices: [], unfinished: false,
    records: records, lines: records.map((_, i) => i + 1) };
}
const START = { ts: TS, level: "INFO", logger: "dbfixlog", type: "run_start", format: "1.0", mode: "dry" };
const END = { ts: TS, level: "INFO", logger: "dbfixlog", type: "run_end", outcome: "ok", duration_ms: 1 };

// phase 1 { customer 2 { order 3 { change }, change }, customer 4 { change } }, phase 5 { message }
function tree() {
  return R.buildModel(payload([
    START,                                                                         // 0
    rec("scope_start", { id: 1, kind: "orphan-check" }),                           // 1
    rec("scope_start", { id: 2, kind: "customer", key: { id: 42 }, scope: [1] }),  // 2
    rec("scope_start", { id: 3, kind: "order", key: { id: 7 }, scope: [1, 2] }),   // 3
    rec("change", { op: "delete", table: "o", key: { id: 7 }, status: "planned", scope: [1, 2, 3] }), // 4
    rec("scope_end", { id: 3, outcome: "ok", duration_ms: 1, scope: [1, 2] }),     // 5
    rec("change", { op: "delete", table: "c", key: { id: 42 }, status: "planned", scope: [1, 2] }),   // 6
    rec("scope_end", { id: 2, outcome: "ok", duration_ms: 1, scope: [1] }),        // 7
    rec("scope_start", { id: 4, kind: "customer", key: { id: 43 }, scope: [1] }),  // 8
    rec("change", { op: "delete", table: "c", key: { id: 43 }, status: "planned", scope: [1, 4] }),   // 9
    rec("scope_end", { id: 4, outcome: "ok", duration_ms: 1, scope: [1] }),        // 10
    rec("scope_end", { id: 1, outcome: "ok", duration_ms: 1 }),                    // 11
    rec("scope_start", { id: 5, kind: "report" }),                                 // 12
    rec("message", { msg: "done", scope: [5] }),                                   // 13
    rec("scope_end", { id: 5, outcome: "ok", duration_ms: 1 }),                    // 14
    END,
  ]));
}

test("fold to phases collapses entity Scopes and keeps phases open", () => {
  const m = tree();
  const c = R.foldSet(m, "phases");
  assert.deepStrictEqual([...c].sort(), [2, 3, 4]);
  // Phase headers, their entity headers and the phases' direct records stay visible.
  assert.deepStrictEqual(R.treeRows(m, c), [1, 2, 8, 12, 13]);
});

test("fold all collapses every Scope, expand all none", () => {
  const m = tree();
  assert.deepStrictEqual(R.treeRows(m, R.foldSet(m, "all")), [1, 12]);
  assert.strictEqual(R.foldSet(m, "none").size, 0);
});

// Sticky row d covers list row k+d, so sticky row d is the depth-d Scope enclosing row k+d.
test("sticky Scopes are the Scopes enclosing the rows they cover", () => {
  const m = tree();
  const rows = R.treeRows(m, new Set()); // [1, 2, 3, 4, 6, 8, 9, 12, 13]
  assert.deepStrictEqual(rows, [1, 2, 3, 4, 6, 8, 9, 12, 13]);
  assert.deepStrictEqual(R.stickyScopes(m, rows, 0), []);        // phase 1 header on top
  assert.deepStrictEqual(R.stickyScopes(m, rows, 3), [1, 2]);    // change in order 3, then row 6 in customer 2
  assert.deepStrictEqual(R.stickyScopes(m, rows, 5), [1, 4]);    // customer 43 header, then its change
  assert.deepStrictEqual(R.stickyScopes(m, rows, 7), []);        // phase 5 header
  assert.deepStrictEqual(R.stickyScopes(m, rows, 8), [5]);
  assert.deepStrictEqual(R.stickyScopes(m, rows, 99), []);
});

function memStorage(init) {
  const data = Object.assign({}, init);
  return { getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = String(v); }, data };
}

test("column widths are remembered, and bad or missing storage falls back to defaults", () => {
  const s = memStorage();
  assert.deepStrictEqual(R.loadWidths(s), R.DEFAULT_WIDTHS);
  const w = [100, 210, 90, 60, 120, 160, 140, 500];
  R.saveWidths(s, w);
  assert.deepStrictEqual(R.loadWidths(s), w);
  const bad = (v) => { const o = {}; o[R.WIDTHS_KEY] = v; return memStorage(o); };
  assert.deepStrictEqual(R.loadWidths(bad("[1,2]")), R.DEFAULT_WIDTHS);
  assert.deepStrictEqual(R.loadWidths(bad("nope")), R.DEFAULT_WIDTHS);
  assert.deepStrictEqual(R.loadWidths(bad('[1,2,3,4,5,6,7,"x"]')), R.DEFAULT_WIDTHS);
  const throwing = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } };
  assert.deepStrictEqual(R.loadWidths(throwing), R.DEFAULT_WIDTHS);
  R.saveWidths(throwing, w); // does not throw
  assert.deepStrictEqual(R.loadWidths(null), R.DEFAULT_WIDTHS);
});

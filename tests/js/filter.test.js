// Search, views and the Scope-header pruning rule (SPEC §6.3, §6.4).
const test = require("node:test");
const assert = require("node:assert");
const path = require("node:path");

const R = require(path.join(__dirname, "..", "..", "report.js"));

function rec(type, extra) {
  return Object.assign({ ts: "2026-11-12T20:01:00.000Z", level: "INFO", logger: "fix.orders", type: type, src: "fix.py:1" }, extra);
}
function payload(records) {
  return { payload: 1, title: "t", source: "t.jsonl", notices: [],
    unfinished: !records.some((r) => r.type === "run_end"),
    records: records, lines: records.map((_, i) => i + 1) };
}
const START = (mode) => ({ ts: "2026-11-12T20:00:00.000Z", level: "INFO", logger: "dbfixlog", type: "run_start", format: "1.0", mode: mode || "dry" });
const END = { ts: "2026-11-12T20:09:00.000Z", level: "INFO", logger: "dbfixlog", type: "run_end", outcome: "ok", duration_ms: 1 };

// Index map (row ids are record indices):
//  1 message "connected" (outside, DEBUG, 20:01:00)
//  2 scope_start 1 phase "orphan-check" msg "pass 1"
//  3   scope_start 2 customer key id=42 label ACME
//  4     finding WARNING check no-lines table orders key id=156 (20:02:10)
//  5     change delete orders id=156 planned
//  6     change update customers id=42 failed, changes note null -> "x", ERROR (20:03:30)
//  7   scope_end 2 ok
//  8   scope_start 3 customer key id=43 label Globex
//  9     message "nothing to do" fields {city: "Gent"}
// 10   scope_end 3 error (raised) ERROR
// 11   scope_start 4 customer key id=44 label Initech   (empty)
// 12   scope_end 4 ok
// 13 scope_end 1 ok
// 14 message "done" logger "other"
function fixture() {
  return payload([
    START("dry"),
    rec("message", { level: "DEBUG", msg: "connected", ts: "2026-11-12T20:01:00.000Z" }),
    rec("scope_start", { id: 1, kind: "orphan-check", msg: "pass 1" }),
    rec("scope_start", { id: 2, kind: "customer", key: { id: 42 }, label: { name: "ACME" }, scope: [1] }),
    rec("finding", { level: "WARNING", check: "no-lines", table: "orders", key: { id: 156 }, scope: [1, 2], ts: "2026-11-12T20:02:10.000Z" }),
    rec("change", { op: "delete", table: "orders", key: { id: 156 }, status: "planned", scope: [1, 2] }),
    rec("change", { op: "update", table: "customers", key: { id: 42 }, status: "failed", level: "ERROR",
      changes: { note: { old: null, new: "x" } }, error: { type: "E", message: "boom" }, scope: [1, 2],
      ts: "2026-11-12T20:03:30.000Z" }),
    rec("scope_end", { id: 2, outcome: "ok", duration_ms: 4, scope: [1] }),
    rec("scope_start", { id: 3, kind: "customer", key: { id: 43 }, label: { name: "Globex" }, scope: [1] }),
    rec("message", { msg: "nothing to do", fields: { city: "Gent" }, scope: [1, 3] }),
    rec("scope_end", { id: 3, outcome: "error", level: "ERROR", duration_ms: 2, scope: [1],
      exc: { type: "ValueError", message: "bad", traceback: "tb" } }),
    rec("scope_start", { id: 4, kind: "customer", key: { id: 44 }, label: { name: "Initech" }, scope: [1] }),
    rec("scope_end", { id: 4, outcome: "ok", duration_ms: 1, scope: [1] }),
    rec("scope_end", { id: 1, outcome: "ok", duration_ms: 9 }),
    rec("message", { msg: "done", logger: "other" }),
    END,
  ]);
}
const M = R.buildModel(fixture());
const flat = (q, extra) => R.filterRows(M, Object.assign({ q: q }, extra), "flat", new Set()).rows;
const tree = (q, extra, collapsed) => R.filterRows(M, Object.assign({ q: q }, extra), "tree", collapsed || new Set()).rows;

test("flat: plain words match the record's own text", () => {
  assert.deepStrictEqual(flat("boom"), [6]);
  assert.deepStrictEqual(flat("NOTHING to"), [9]);
});

test("plain words also match the kind/key/label of the enclosing Scopes", () => {
  assert.deepStrictEqual(flat("acme"), [3, 4, 5, 6]);
  assert.deepStrictEqual(flat("acme status:failed"), [6]);
  // Each word may match the record or any enclosing Scope.
  assert.deepStrictEqual(flat("acme orders"), [4, 5]);
  assert.deepStrictEqual(flat("orphan-check boom"), [6]);
});

test("level terms: level>= and level: (a raising Scope's header is an error)", () => {
  assert.deepStrictEqual(flat("level>=warning"), [4, 6, 8, 10]);
  assert.deepStrictEqual(flat("level>=warn"), [4, 6, 8, 10]);
  assert.deepStrictEqual(flat("level:error"), [6, 8, 10]);
  assert.deepStrictEqual(flat("level:warning,debug"), [1, 4]);
  assert.deepStrictEqual(flat("level:info"), [2, 3, 5, 9, 11, 14]);
});

test("type, table, op, status, check, logger terms", () => {
  assert.deepStrictEqual(flat("type:change,finding"), [4, 5, 6]);
  assert.deepStrictEqual(flat("type:scope"), [2, 3, 8, 10, 11]);
  assert.deepStrictEqual(flat("table:orders"), [4, 5]);
  assert.deepStrictEqual(flat("table:ORDERS,customers"), [4, 5, 6]);
  assert.deepStrictEqual(flat("op:update"), [6]);
  assert.deepStrictEqual(flat("status:planned"), [5]);
  assert.deepStrictEqual(flat("check:no-lines"), [4]);
  assert.deepStrictEqual(flat("logger:other"), [14]);
  assert.deepStrictEqual(flat("logger:fix"), [1, 2, 3, 4, 5, 6, 8, 9, 10, 11]);
});

test("table: also finds a schema-qualified table", () => {
  const m = R.buildModel(payload([START(), rec("change", { op: "delete", table: "shop.orders", key: { id: 1 }, status: "planned" }), END]));
  assert.deepStrictEqual(R.filterRows(m, { q: "table:orders" }, "flat").rows, [1]);
  assert.deepStrictEqual(R.filterRows(m, { q: "table:shop.orders" }, "flat").rows, [1]);
});

test("key:, kind: and in: include the enclosing Scopes", () => {
  assert.deepStrictEqual(flat("key:156"), [4, 5]);
  assert.deepStrictEqual(flat("key:42"), [3, 4, 5, 6]);
  assert.deepStrictEqual(flat("key:id=43"), [8, 9, 10]);
  assert.deepStrictEqual(flat("kind:customer"), [3, 4, 5, 6, 8, 9, 10, 11]);
  assert.deepStrictEqual(flat("kind:orphan-check"), [2, 3, 4, 5, 6, 8, 9, 10, 11]);
  assert.deepStrictEqual(flat("in:2"), [3, 4, 5, 6]);
  assert.deepStrictEqual(flat("in:3"), [8, 9, 10]);
  assert.deepStrictEqual(flat("in:2,4"), [3, 4, 5, 6, 11]);
  assert.deepStrictEqual(flat("type:scope_end kind:customer"), [10]);
});

test("after: and before: compare the UTC hh:mm:ss.mmm slice, inclusive at the given precision", () => {
  assert.deepStrictEqual(flat("after:20:02"), [4, 6]);
  assert.deepStrictEqual(flat("before:20:01"), [1, 2, 3, 5, 8, 9, 10, 11, 14]);
  assert.deepStrictEqual(flat("after:20:02:10 before:20:02:10"), [4]);
  assert.deepStrictEqual(flat("after:20:03:30.001"), []);
});

test("f.<field>=<value> matches fields and changed fields' old or new values", () => {
  assert.deepStrictEqual(flat("f.city=gent"), [9]);
  assert.deepStrictEqual(flat("f.note=null"), [6]);
  assert.deepStrictEqual(flat("f.note=x"), [6]);
  assert.deepStrictEqual(flat("f.note=y"), []);
  assert.deepStrictEqual(flat("f.city=gen"), []); // equality, not substring
});

test("is:warn and is:unfinished", () => {
  assert.deepStrictEqual(flat("is:warn"), [6]); // failed in a Dry Run
  assert.deepStrictEqual(flat("is:unfinished"), []);
});

test("quotes group words; unknown terms are plain words", () => {
  assert.deepStrictEqual(flat('"nothing to"'), [9]);
  assert.deepStrictEqual(flat('"to nothing"'), []);
  assert.deepStrictEqual(flat("foo:bar"), []);
  assert.deepStrictEqual(flat("level>=loud"), []);
  assert.deepStrictEqual(flat("connected"), [1]);
});

test("no filter: every row shows, as treeRows / flatRows", () => {
  const r = R.filterRows(M, { q: "  " }, "tree", new Set());
  assert.strictEqual(r.active, false);
  assert.strictEqual(r.shown, null);
  assert.deepStrictEqual(r.rows, R.treeRows(M, new Set()));
  assert.deepStrictEqual(R.filterRows(M, {}, "flat").rows, R.flatRows(M));
  assert.strictEqual(R.filterRows(M, { level: "DEBUG", view: "all" }, "tree").active, false);
  assert.strictEqual(R.filterRows(M, { level: "INFO" }, "tree").active, true);
  assert.strictEqual(R.filterRows(M, { view: "changes" }, "tree").active, true);
});

test("tree: enclosing Scopes of a visible row stay; Scopes without matches are pruned", () => {
  assert.deepStrictEqual(tree("boom"), [2, 3, 6]);
  assert.deepStrictEqual(tree("acme"), [2, 3, 4, 5, 6]);
  assert.deepStrictEqual(tree("", { level: "WARNING" }), [2, 3, 4, 6, 8, 10]);
  assert.deepStrictEqual(tree("", { view: "changes" }), [2, 3, 5, 6]);
  assert.deepStrictEqual(tree("", { view: "findings" }), [2, 3, 4]);
  // Folding still applies under a filter.
  assert.deepStrictEqual(tree("boom", {}, new Set([2])), [2, 3]);
});

test("tree: a matching Scope header shows even when nothing inside it matches", () => {
  assert.deepStrictEqual(tree("initech"), [2, 11]); // an empty Scope
  assert.deepStrictEqual(tree("globex boom"), []);
});

test("tree: the Errors view shows a raising Scope but only the errors inside it", () => {
  assert.deepStrictEqual(tree("", { view: "errors" }), [2, 3, 6, 8, 10]);
});

test("flat: Scope rows are ordinary rows; enclosing Scopes are not kept", () => {
  assert.deepStrictEqual(flat("boom"), [6]);
  assert.deepStrictEqual(flat("", { view: "errors" }), [6, 8, 10]);
  assert.deepStrictEqual(flat("initech"), [11]);
});

test("unfinished Scopes are not errors; is:unfinished finds them", () => {
  const m = R.buildModel(payload(fixture().records.slice(0, 6))); // crash inside Scope 2
  const t = (q, x) => R.filterRows(m, Object.assign({ q: q }, x), "tree", new Set()).rows;
  const f = (q, x) => R.filterRows(m, Object.assign({ q: q }, x), "flat", new Set()).rows;
  assert.deepStrictEqual(t("", { view: "errors" }), []);
  assert.deepStrictEqual(t("level>=error"), []);
  assert.deepStrictEqual(t("is:unfinished"), [2, 3]);
  assert.deepStrictEqual(f("is:unfinished kind:customer"), [3]);
  assert.deepStrictEqual(t("is:unfinished kind:customer"), [2, 3]);
});

const text = (html) => html.replace(/<[^>]*>/g, "");

test("a header shows 'k of n shown' while a filter is active; totals cover the whole Scope", () => {
  const r = R.filterRows(M, { q: "boom" }, "tree", new Set());
  assert.strictEqual(r.shown.get(2), 1);
  assert.strictEqual(r.shown.get(1), 1);
  assert.strictEqual(r.matches, 1);
  const d = text(R.rowCells(M, 3, "tree", new Set(), r.shown)[7]);
  assert.match(d, /^3 records · 1 planned · 1 failed · 1 Finding · 4 ms · 1 of 3 shown$/);
  assert.match(text(R.rowCells(M, 2, "tree", new Set(), r.shown)[7]), /1 of 5 shown/);
  assert.doesNotMatch(text(R.rowCells(M, 3, "tree", new Set(), null)[7]), /shown/);
  // A matching empty Scope: 0 of 0.
  assert.match(text(R.rowCells(M, 11, "tree", new Set(), R.filterRows(M, { q: "initech" }, "tree").shown)[7]), /0 of 0 shown/);
});

test("view counts: All, Changes, Findings, Errors", () => {
  assert.deepStrictEqual(R.viewCounts(M), { all: 7, changes: 2, findings: 1, errors: 2 });
});

test("search over 100k synthetic records stays within 50 ms", () => {
  const recs = [START("write")];
  let id = 0;
  const kinds = ["customer", "order", "invoice"];
  while (recs.length < 100000) {
    const sid = ++id;
    recs.push(rec("scope_start", { id: sid, kind: kinds[sid % 3], key: { id: sid }, label: { name: "Name" + (sid * 7919 % 100003) } }));
    for (let k = 0; k < 8; k++) {
      const st = k % 7 === 0 ? "failed" : "applied";
      recs.push(rec(k % 3 ? "change" : "finding", {
        level: st === "failed" && k % 3 ? "ERROR" : "INFO", op: "update", table: "t" + (k % 5), check: "c" + k,
        status: k % 3 ? st : undefined, key: { id: sid * 10 + k }, label: { code: "X" + (sid * 31 + k) },
        changes: { a: { old: "v" + k, new: "w" + sid }, b: { old: null, new: k } },
        msg: "record " + sid + " step " + k, scope: [sid] }));
    }
    recs.push(rec("scope_end", { id: sid, outcome: sid % 50 ? "ok" : "error", duration_ms: 3 }));
  }
  recs.push(END);
  const m = R.buildModel(payload(recs));
  const t0 = Date.now();
  R.filterRows(m, { q: "warmup" }, "tree"); // builds the search index once
  const indexMs = Date.now() - t0;
  const time = (state, mode) => {
    let best = Infinity;
    for (let k = 0; k < 3; k++) best = Math.min(best, R.filterRows(m, state, mode || "tree").ms);
    return best;
  };
  const cases = [
    [{ q: "name4242" }], [{ q: "status:failed customer" }], [{ q: "w123 t3" }],
    [{ view: "errors" }], [{ q: "key:77" }, "flat"], [{ q: "f.a=v3 kind:order" }],
  ];
  const report = ["index " + indexMs + " ms"];
  for (const [s, mode] of cases) {
    const ms = time(s, mode);
    report.push(JSON.stringify(s) + " " + ms.toFixed(1) + " ms");
    assert.ok(ms <= 50, JSON.stringify(s) + " took " + ms.toFixed(1) + " ms");
  }
  console.log("# 100k search: " + report.join(", "));
});

// Report model: Scope tree, totals, unfinished detection, mode mismatches, row lists.
const test = require("node:test");
const assert = require("node:assert");
const path = require("node:path");

const R = require(path.join(__dirname, "..", "..", "report.js"));

const TS = "2026-11-12T20:01:00.000Z";
function rec(type, extra) {
  return Object.assign({ ts: TS, level: "INFO", logger: "fix", type: type, src: "fix.py:1" }, extra);
}
function payload(records, extra) {
  return Object.assign({ payload: 1, title: "t", source: "t.jsonl", notices: [],
    unfinished: !records.some((r) => r.type === "run_end"),
    records: records, lines: records.map((_, i) => i + 1) }, extra);
}
const START = (mode) => ({ ts: TS, level: "INFO", logger: "dbfixlog", type: "run_start", format: "1.0", mode: mode });
const END = { ts: "2026-11-12T20:03:00.000Z", level: "INFO", logger: "dbfixlog", type: "run_end", outcome: "ok", duration_ms: 120000 };

// run_start, phase 1 { customer 2 { finding, delete, planned update }, message }, outside message, run_end
function nested(mode, status) {
  return payload([
    START(mode),
    rec("scope_start", { id: 1, kind: "orphan-check", msg: "pass 1" }),
    rec("scope_start", { id: 2, kind: "customer", key: { id: 42 }, label: { name: "ACME" }, scope: [1] }),
    rec("finding", { level: "WARNING", check: "no-lines", table: "orders", key: { id: 156 }, scope: [1, 2] }),
    rec("change", { op: "delete", table: "orders", key: { id: 156 }, status: status || "planned", scope: [1, 2] }),
    rec("change", { op: "update", table: "customers", key: { id: 42 }, status: "planned",
      changes: { note: { old: null, new: "x" } }, scope: [1, 2] }),
    rec("scope_end", { id: 2, outcome: "ok", duration_ms: 40, scope: [1] }),
    rec("message", { msg: "pass done", scope: [1] }),
    rec("scope_end", { id: 1, outcome: "ok", duration_ms: 120 }),
    rec("message", { msg: "outside" }),
    END,
  ]);
}

test("Scope tree is built from the scope paths", () => {
  const m = R.buildModel(nested("dry"));
  assert.deepStrictEqual([...m.scopes.keys()], [1, 2]);
  const s1 = m.scopes.get(1), s2 = m.scopes.get(2);
  assert.strictEqual(s1.parent, null);
  assert.strictEqual(s1.depth, 0);
  assert.deepStrictEqual(s1.children, [2]);
  assert.strictEqual(s2.parent, 1);
  assert.deepStrictEqual(s2.path, [1]);
  assert.strictEqual(s2.depth, 1);
  assert.strictEqual(s2.kind, "customer");
  assert.strictEqual(s2.start, 2);
  assert.strictEqual(s2.end, 6);
  assert.strictEqual(s1.end, 8);
});

test("Scope totals cover every record inside, nested Scopes included", () => {
  const m = R.buildModel(nested("write", "applied"));
  assert.deepStrictEqual(m.scopes.get(2).totals,
    { records: 3, planned: 1, applied: 1, failed: 0, findings: 1, duration_ms: 40 });
  // Scope 1 also holds its own "pass done" message; Scope headers are not counted as records.
  assert.deepStrictEqual(m.scopes.get(1).totals,
    { records: 4, planned: 1, applied: 1, failed: 0, findings: 1, duration_ms: 120 });
});

test("a crash leaves the Run and its open Scopes unfinished, closing at the last record", () => {
  const recs = nested("dry").records.slice(0, 6); // cut after the planned update, inside Scope 2
  const m = R.buildModel(payload(recs));
  assert.strictEqual(m.unfinished, true);
  assert.strictEqual(m.outcome, "unfinished");
  for (const id of [1, 2]) {
    const s = m.scopes.get(id);
    assert.strictEqual(s.outcome, "unfinished");
    assert.strictEqual(s.end, null);
    assert.strictEqual(s.last, 5);
    assert.strictEqual(s.totals.duration_ms, null);
  }
  assert.deepStrictEqual(m.unfinishedScopes, [1, 2]);
});

test("finished Run and Scopes report their outcomes", () => {
  const p = nested("dry");
  p.records[6] = rec("scope_end", { id: 2, outcome: "error", duration_ms: 40, scope: [1],
    level: "ERROR", exc: { type: "ValueError", message: "bad", traceback: "tb" } });
  p.records[10] = Object.assign({}, END, { outcome: "error", level: "ERROR", exit_code: 3 });
  const m = R.buildModel(p);
  assert.strictEqual(m.unfinished, false);
  assert.strictEqual(m.outcome, "error");
  assert.strictEqual(m.scopes.get(1).outcome, "ok");
  assert.strictEqual(m.scopes.get(2).outcome, "error");
  assert.strictEqual(m.scopes.get(2).last, 6);
  assert.deepStrictEqual(m.unfinishedScopes, []);
});

test("is:warn flags: applied/failed in a Dry Run, planned in a Write Run", () => {
  const dry = R.buildModel(nested("dry", "applied"));
  assert.deepStrictEqual(dry.warnings, [4]);
  assert.match(dry.warn[4], /applied.*Dry Run/);
  assert.strictEqual(dry.warn[5], null);
  assert.strictEqual(dry.warn[3], null); // a Finding is never a mismatch

  const failed = R.buildModel(nested("dry", "failed"));
  assert.deepStrictEqual(failed.warnings, [4]);

  const write = R.buildModel(nested("write", "applied"));
  assert.deepStrictEqual(write.warnings, [5]); // the planned update
  assert.match(write.warn[5], /planned.*Write Run/);
});

test("mode strip: amber for a clean Dry Run, red when Changes were applied or failed", () => {
  const clean = R.modeStrip(R.buildModel(nested("dry")));
  assert.strictEqual(clean.tone, "amber");
  assert.strictEqual(clean.text, "Dry Run: the Changes below are planned, not applied.");

  const red = R.modeStrip(R.buildModel(nested("dry", "failed")));
  assert.strictEqual(red.tone, "red");
  assert.strictEqual(red.count, 1);
  assert.match(red.text, /^Dry Run, but 1 Change was logged as applied or failed: the script may have written to the database\./);

  assert.strictEqual(R.modeStrip(R.buildModel(nested("write", "applied"))), null);
});

test("notices: planned in a Write Run, unfinished Run and Scopes, outcome, render notices", () => {
  const kinds = (p) => R.runNotices(R.buildModel(p)).map((n) => n.kind);
  assert.deepStrictEqual(kinds(nested("write", "applied")), ["write_planned"]);
  assert.match(R.runNotices(R.buildModel(nested("write", "applied")))[0].text,
    /1 Change logged as planned in a Write Run: they were not carried out/);
  assert.deepStrictEqual(kinds(nested("dry")), []);

  const crashed = payload(nested("dry").records.slice(0, 6));
  assert.deepStrictEqual(kinds(crashed), ["run_unfinished", "unfinished_scopes"]);

  const p = nested("dry");
  p.records[10] = Object.assign({}, END, { outcome: "interrupted", level: "ERROR" });
  p.notices = [{ kind: "newer_minor", message: "format 1.3 is newer" },
    { kind: "something_new", message: "shown as is" }];
  const ns = R.runNotices(R.buildModel(p));
  assert.deepStrictEqual(ns.map((n) => n.kind), ["run_outcome", "newer_minor", "something_new"]);
  assert.strictEqual(ns[2].text, "shown as is");
});

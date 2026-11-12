// Summary cards (SPEC §6.2 item 3, §6.3): counts, and the queries their numbers apply.
const test = require("node:test");
const assert = require("node:assert");
const path = require("node:path");

const R = require(path.join(__dirname, "..", "..", "report.js"));

function rec(type, extra) {
  return Object.assign({ ts: "2026-11-12T20:01:00.000Z", level: "INFO", logger: "fix", type: type, src: "fix.py:1" }, extra);
}
function model(mode, body, ended) {
  const records = [{ ts: "2026-11-12T20:00:00.000Z", level: "INFO", logger: "dbfixlog", type: "run_start", format: "1.0", mode: mode }]
    .concat(body);
  if (ended !== false) records.push({ ts: "2026-11-12T20:09:00.000Z", level: "INFO", logger: "dbfixlog", type: "run_end", outcome: "ok", duration_ms: 1 });
  return R.buildModel({ payload: 1, title: "t", source: "t.jsonl", notices: [], unfinished: ended === false,
    records: records, lines: records.map((_, i) => i + 1) });
}
const ch = (table, op, status, extra) => rec("change", Object.assign({ table: table, op: op, status: status, key: { id: 1 } }, extra));
const fd = (check, level) => rec("finding", { check: check, level: level, table: "orders", key: { id: 1 }, msg: "m" });

test("Changes are counted per table and op, split by status, sorted by table", () => {
  const m = model("dry", [
    ch("orders", "update", "planned"), ch("orders", "update", "planned"), ch("orders", "delete", "applied"),
    ch("customers", "insert", "failed", { level: "ERROR" }), ch("orders", "update", "failed", { level: "ERROR" }),
  ]);
  const c = R.summaryCounts(m).changes;
  assert.deepStrictEqual(c.rows.map((r) => [r.table, r.op, r.planned, r.applied, r.failed, r.all]), [
    ["customers", "insert", 0, 0, 1, 1],
    ["orders", "update", 2, 0, 1, 3],
    ["orders", "delete", 0, 1, 0, 1],
  ]);
  assert.deepStrictEqual([c.total.planned, c.total.applied, c.total.failed, c.total.all], [2, 1, 2, 5]);
});

test("Findings are counted per check and level; only levels that occur get a column", () => {
  const m = model("write", [fd("no-lines", "WARNING"), fd("no-lines", "WARNING"), fd("no-lines", "ERROR"), fd("dup", "INFO")]);
  const f = R.summaryCounts(m).findings;
  assert.deepStrictEqual(f.levels, ["INFO", "WARNING", "ERROR"]);
  assert.deepStrictEqual(f.rows.map((r) => [r.check, r.INFO, r.WARNING, r.ERROR, r.all]), [
    ["dup", 1, 0, 0, 1],
    ["no-lines", 0, 2, 1, 3],
  ]);
});

test("Scopes are counted per kind with error and unfinished counts, in first-seen order", () => {
  const m = model("dry", [
    rec("scope_start", { id: 1, kind: "phase" }),
    rec("scope_start", { id: 2, kind: "customer", key: { id: 1 }, scope: [1] }),
    rec("scope_end", { id: 2, outcome: "error", level: "ERROR", scope: [1], exc: { type: "E", message: "x" } }),
    rec("scope_start", { id: 3, kind: "customer", key: { id: 2 }, scope: [1] }),
    rec("scope_end", { id: 3, outcome: "ok", scope: [1] }),
    rec("scope_start", { id: 4, kind: "customer", key: { id: 3 }, scope: [1] }),
  ], false);
  assert.deepStrictEqual(R.summaryCounts(m).kinds.map((k) => [k.kind, k.n, k.error, k.unfinished]), [
    ["phase", 1, 0, 1],
    ["customer", 3, 1, 1],
  ]);
});

// Every clickable number in cardsHTML as [query, text, red?].
function links(html) {
  const out = [];
  const re = /<a href="#" class="cn( red)?" data-q="([^"]*)">([^<]*)<\/a>/g;
  let mm;
  while ((mm = re.exec(html))) out.push([mm[2].replace(/&quot;/g, '"'), mm[3], !!mm[1]]);
  return out;
}

test("Change numbers filter by table, op and status; applied and failed are red in a Dry Run", () => {
  const m = model("dry", [ch("orders", "update", "planned"), ch("orders", "update", "applied"), ch("orders", "delete", "planned")]);
  const h = R.cardsHTML(m);
  assert.deepStrictEqual(links(h), [
    ["type:change table:orders op:update status:planned", "1", false],
    ["type:change table:orders op:update status:applied", "1", true],
    ["type:change table:orders op:update", "2", false],
    ["type:change table:orders op:delete status:planned", "1", false],
    ["type:change table:orders op:delete", "1", false],
    ["type:change status:planned", "2", false],
    ["type:change status:applied", "1", true],
    ["type:change", "3", false],
  ]);
  assert.match(h, /<details class="cards" open>/);
});

test("in a Write Run applied is not red, failed still is; zero counts are not links", () => {
  const m = model("write", [ch("orders", "update", "applied"), ch("orders", "update", "failed", { level: "ERROR" })]);
  const l = links(R.cardsHTML(m)).filter((x) => / status:/.test(x[0]) && x[0].indexOf("table:") > 0);
  assert.deepStrictEqual(l, [
    ["type:change table:orders op:update status:applied", "1", false],
    ["type:change table:orders op:update status:failed", "1", true],
  ]);
});

test("Finding and Scope numbers carry their queries; the unfinished count filters to is:unfinished", () => {
  const m = model("dry", [
    fd("no-lines", "WARNING"), fd("no lines 2", "ERROR"),
    rec("scope_start", { id: 1, kind: "customer", key: { id: 1 } }),
    rec("scope_end", { id: 1, outcome: "error", level: "ERROR", exc: { type: "E", message: "x" } }),
    rec("scope_start", { id: 2, kind: "customer", key: { id: 2 } }),
  ], false);
  const l = links(R.cardsHTML(m)).filter((x) => !x[0].startsWith("type:change"));
  assert.deepStrictEqual(l, [
    ['check:"no lines 2" level:error', "1", true],
    ['check:"no lines 2"', "1", false],
    ["check:no-lines level:warning", "1", false],
    ["check:no-lines", "1", false],
    ["type:scope_start kind:customer", "2", false],
    ["type:scope_end kind:customer", "1", true],
    ["is:unfinished kind:customer", "1", false],
  ]);
});

// Change and Finding numbers equal their query's matches. kind: also matches Scopes nested
// inside a Scope of that kind (ticket 08), so a Scope number equals the matches whose own
// Scope has that kind; nested Scopes of other kinds may show as well.
test("each card number equals the matches of its own query (flat filter)", () => {
  const m = model("dry", [
    rec("scope_start", { id: 1, kind: "orphan-check" }),
    rec("scope_start", { id: 2, kind: "customer", key: { id: 42 }, label: { name: "ACME" }, scope: [1] }),
    fd("no-lines", "WARNING"), Object.assign(fd("no-lines", "ERROR"), { scope: [1, 2] }),
    Object.assign(ch("orders", "update", "planned"), { scope: [1, 2] }),
    Object.assign(ch("orders", "delete", "applied"), { scope: [1, 2] }),
    ch("customers", "update", "failed", { level: "ERROR" }),
    rec("scope_end", { id: 2, outcome: "error", level: "ERROR", scope: [1], exc: { type: "E", message: "x" } }),
    rec("scope_start", { id: 3, kind: "customer", key: { id: 43 }, scope: [1] }),
    rec("message", { msg: "working", scope: [1, 3] }),
  ], false);
  const l = links(R.cardsHTML(m));
  assert.strictEqual(l.length, 18);
  for (const [q, text] of l) {
    const rows = R.filterRows(m, { q: q }, "flat", new Set()).rows;
    const kind = (q.match(/kind:(\S+)/) || [])[1];
    const own = kind ? rows.filter((i) => m.scopes.get(m.records[i].id).kind === kind) : rows;
    assert.strictEqual(own.length, Number(text), q);
  }
  // the nesting caveat, made explicit: the phase's own Scope plus the two customers inside it
  assert.strictEqual(R.filterRows(m, { q: "type:scope_start kind:orphan-check" }, "flat", new Set()).rows.length, 3);
});

test("a Run without Changes, Findings or Scopes gets no cards", () => {
  assert.strictEqual(R.cardsHTML(model("dry", [rec("message", { msg: "hi" })])), "");
});

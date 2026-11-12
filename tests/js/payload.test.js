// decodePayload round trip: render the fixture with dbfixlog_render.py, decode in Node.
const test = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const ROOT = path.join(__dirname, "..", "..");
const { decodePayload } = require(path.join(ROOT, "report.js"));

function renderFixture() {
  return execFileSync("python3", [path.join(ROOT, "dbfixlog_render.py"),
    path.join(ROOT, "tests", "fixtures", "basic.jsonl"), "-o", "-"],
    { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
}

test("decodePayload reads the payload the renderer embeds", async () => {
  const html = renderFixture();
  const m = html.match(/<script type="application\/json" id="dbfixlog-payload">([^<]*)<\/script>/);
  assert.ok(m, "payload block present");
  const payload = await decodePayload(m[1]);
  assert.strictEqual(payload.payload, 1);
  assert.strictEqual(payload.title, "Orphaned orders cleanup");
  assert.strictEqual(payload.records.length, 10);
  assert.deepStrictEqual(payload.lines, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  assert.strictEqual(payload.records[0].type, "run_start");
  assert.strictEqual(payload.records[6].changes.note.new, "cleaned <b>&amp;</b> </script> ünïcode");
  assert.strictEqual(payload.unfinished, false);
  assert.deepStrictEqual(payload.notices, []);
});

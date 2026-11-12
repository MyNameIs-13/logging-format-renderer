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

test("decodePayload reads a payload that inflates in many chunks", async () => {
  // The decoder copies stream chunks into one buffer sized from the gzip trailer;
  // multibyte characters straddle the chunk boundaries here.
  const zlib = require("node:zlib");
  const records = Array.from({ length: 20000 }, (_, i) => ({ i, msg: "ünï " + i }));
  const gz = zlib.gzipSync(Buffer.from(JSON.stringify({ payload: 1, records })));
  const payload = await decodePayload(gz.toString("base64"));
  assert.strictEqual(payload.records.length, 20000);
  assert.strictEqual(payload.records[19999].msg, "ünï 19999");
});

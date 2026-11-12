// Drive headless Firefox over WebDriver BiDi: open a URL, poll a JS expression until it
// yields a non-empty string (or time runs out), print that string on stdout.
// Usage: node bidi_eval.mjs WS_URL PAGE_URL EXPRESSION [TIMEOUT_MS]
// Uncaught JS errors and console.error calls on the page are printed on stderr as one line
// "js-errors: [...]" (JSON array of messages); they do not change the exit code.
const [wsUrl, pageUrl, expression, timeoutArg] = process.argv.slice(2);
const timeoutMs = Number(timeoutArg || 10000);

const ws = new WebSocket(wsUrl.replace(/\/?$/, "/session"));
let nextId = 0;
const pending = new Map();
const jsErrors = [];
let since = Infinity; // on subscribe, Firefox replays the previous page's entries: skip them
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  else if (m.method === "log.entryAdded" && m.params.timestamp >= since &&
           (m.params.type === "javascript" || m.params.level === "error"))
    jsErrors.push(m.params.text);
};
const reportErrors = () => { if (jsErrors.length) console.error("js-errors: " + JSON.stringify(jsErrors)); };
const send = (method, params) => new Promise((resolve) => {
  const id = ++nextId;
  pending.set(id, resolve);
  ws.send(JSON.stringify({ id, method, params }));
});
const fail = (msg) => { console.error(msg); process.exit(1); };
setTimeout(() => fail("timeout after " + timeoutMs + " ms"), timeoutMs + 2000).unref();

await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = () => reject(fail("cannot connect to " + wsUrl)); });
const session = await send("session.new", { capabilities: {} });
if (session.type === "error") fail("session.new: " + session.message);
const tree = await send("browsingContext.getTree", {});
const context = tree.result.contexts[0].context;
since = Date.now();
await send("session.subscribe", { events: ["log.entryAdded"], contexts: [context] });
const nav = await send("browsingContext.navigate", { context, url: pageUrl, wait: "complete" });
if (nav.type === "error") { await send("session.end", {}); fail("navigate: " + nav.message); }

const deadline = Date.now() + timeoutMs;
let value = "";
while (Date.now() < deadline) {
  const r = await send("script.evaluate", { expression, target: { context }, awaitPromise: true });
  // End the session before failing, or Firefox refuses the next test's session.new.
  const bail = async (msg) => { await send("session.end", {}); reportErrors(); fail(msg); };
  if (r.type === "error") await bail("evaluate: " + r.message);
  if (r.result.type === "exception") await bail("exception: " + JSON.stringify(r.result.exceptionDetails.text));
  value = r.result.result.type === "string" ? r.result.result.value : "";
  if (value) break;
  await new Promise((res) => setTimeout(res, 100));
}
await send("session.end", {});
ws.close();
reportErrors();
if (!value) fail("expression never yielded a value");
console.log(value);
process.exit(0);

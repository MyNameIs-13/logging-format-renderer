// Report viewer for Database Fix Logging. Plain script: no modules, no build step.
// dbfixlog_render.py inlines this file (and report.css) into every Report.
//
// ---------------------------------------------------------------------------------------
// Embedded payload (payload version 1)
// ---------------------------------------------------------------------------------------
// The Report carries one block:
//
//   <script type="application/json" id="dbfixlog-payload">BASE64</script>
//
// BASE64 is base64(gzip(UTF-8 JSON)). Base64 contains no "<", so the block cannot be
// closed early. Decode with atob + DecompressionStream("gzip") + JSON.parse
// (see decodePayload below). The JSON is one object:
//
//   {
//     "payload":    1,              // shape version of this object; bumped on breaking change
//     "renderer":   "0.1.0",        // dbfixlog_render.py __version__
//     "source":     "run.jsonl",    // Log File name (basename)
//     "title":      "...",          // resolved: --title, then run_start.title, then source
//     "unfinished": false,          // true when no run_end record is present
//     "notices":    [Notice, ...],  // render-time notices, in the order below; may be []
//     "records":    [Record, ...],  // every well-formed record, in file order, verbatim
//     "lines":      [1, 2, 4, ...]  // lines[i] = 1-based Log File line of records[i]
//   }
//
// records[0] is always the run_start (Run Header); the renderer refuses anything else.
// Records are the Log File's JSON objects unchanged (SPEC §3), including unknown types.
// A record's id within the Report is its index i; its line number is lines[i] (the two
// differ when malformed lines were skipped).
//
// Every Notice has "kind" and a human-readable "message"; show the message for unknown
// kinds. Known kinds:
//
//   {"kind": "newer_minor", "format": "1.7", "reads": "1.0", "message": "..."}
//       The Log File's minor format is newer than the renderer knows.
//   {"kind": "malformed_lines", "count": 3, "lines": [3, 5, 7],
//    "samples": [{"line": 3, "text": "not json"}, ...],   // first 5, each <= 200 chars
//    "message": "3 malformed lines skipped"}
//       Lines that were not JSON objects were skipped (only without --strict).
//   {"kind": "incomplete_last_line", "line": 10,
//    "message": "last line incomplete, file may still be written"}
//       The last line had no trailing newline and was skipped.
//
// The page also exposes its state for tests on <html>: data-state = "loading" | "ready" |
// "error", data-record-count, and data-error (on error).
// ---------------------------------------------------------------------------------------

async function decodePayload(base64Text) {
  const bin = atob(base64Text.trim());
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  return JSON.parse(await new Response(stream).text());
}

// ---------------------------------------------------------------------------------------
// Model (pure; exported for Node)
// ---------------------------------------------------------------------------------------
// buildModel(payload) derives everything the views need from the verbatim records.
// A record's id is its index i into model.records. Per-record derived data lives in
// parallel arrays (model.lv, model.warn) so the records themselves stay verbatim.

function buildModel(payload) {
  const records = payload.records;
  const scopes = new Map();
  const m = {
    payload: payload,
    records: records,
    lines: payload.lines,
    header: records[0],
    end: null,
    scopes: scopes,
  };
  for (let i = 0; i < records.length; i++) {
    const r = records[i];
    if (r.type === "run_end") m.end = r;
    else if (r.type === "scope_start" && !scopes.has(r.id)) {
      const path = Array.isArray(r.scope) ? r.scope : [];
      const parent = path.length ? path[path.length - 1] : null;
      scopes.set(r.id, {
        id: r.id, kind: r.kind, start: i, end: null, parent: parent, path: path,
        depth: path.length, children: [],
        totals: { records: 0, planned: 0, applied: 0, failed: 0, findings: 0, duration_ms: null },
      });
      if (scopes.has(parent)) scopes.get(parent).children.push(r.id);
      continue;
    } else if (r.type === "scope_end") {
      const s = scopes.get(r.id);
      if (s && s.end === null) {
        s.end = i;
        if (typeof r.duration_ms === "number") s.totals.duration_ms = r.duration_ms;
      }
    }
    if (!isEntry(r) || !Array.isArray(r.scope)) continue;
    for (const id of r.scope) {
      const s = scopes.get(id);
      if (!s) continue;
      const t = s.totals;
      t.records++;
      if (r.type === "change" && (r.status === "planned" || r.status === "applied" || r.status === "failed")) t[r.status]++;
      else if (r.type === "finding") t.findings++;
    }
  }
  // Status/mode mismatches (is:warn): warn[i] is a reason string or null.
  const mode = m.header.mode;
  m.mode = mode;
  m.warn = new Array(records.length).fill(null);
  m.warnings = [];
  for (let i = 0; i < records.length; i++) {
    const r = records[i];
    if (r.type !== "change") continue;
    if ((mode === "dry" && (r.status === "applied" || r.status === "failed")) ||
        (mode === "write" && r.status === "planned")) {
      m.warn[i] = 'status "' + r.status + '" in a ' + (mode === "dry" ? "Dry" : "Write") + " Run";
      m.warnings.push(i);
    }
  }
  m.unfinished = m.end === null;
  m.outcome = m.end ? m.end.outcome : "unfinished";
  m.unfinishedScopes = [];
  for (const s of scopes.values()) {
    if (s.end === null) {
      s.outcome = "unfinished";
      s.last = records.length - 1; // an unfinished Scope closes at the last record in the file
      m.unfinishedScopes.push(s.id);
    } else {
      s.outcome = records[s.end].outcome === "error" ? "error" : "ok";
      s.last = s.end;
    }
  }
  return m;
}

function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }

// The full-width Dry Run strip, or null for a Write Run. It only claims what the Log File
// shows. q is the query a "Show them" link should apply (wired by the filter bar, ticket 08).
function modeStrip(m) {
  if (m.mode !== "dry") return null;
  const n = m.warnings.length;
  if (!n) return { tone: "amber", count: 0, text: "Dry Run: the Changes below are planned, not applied." };
  return {
    tone: "red", count: n, q: "is:warn",
    text: "Dry Run, but " + plural(n, "Change was", "Changes were") +
      " logged as applied or failed: the script may have written to the database.",
  };
}

// Run-level notices below the strip, in display order. Each is {kind, tone, text, q?}.
// tone is "amber" or "red". Render-time notices from the payload keep their kind and message.
function runNotices(m) {
  const out = [];
  const given = (m.payload.notices || []).slice();
  if (m.mode === "write" && m.warnings.length) {
    out.push({ kind: "write_planned", tone: "amber", q: "is:warn",
      text: plural(m.warnings.length, "Change", "Changes") +
        " logged as planned in a Write Run: they were not carried out." });
  }
  if (m.unfinished) {
    const last = m.records[m.records.length - 1];
    out.push({ kind: "run_unfinished", tone: "red",
      text: "Run unfinished: there is no run_end record (the process was killed or crashed). " +
        "The last record is at " + hms(last.ts) + " UTC." });
  } else if (m.outcome !== "ok") {
    const e = m.end;
    let t = "Run ended with outcome " + m.outcome;
    if (e.exit_code !== undefined && e.exit_code !== null) t += " (exit code " + e.exit_code + ")";
    if (e.exc) t += ": " + e.exc.type + ": " + e.exc.message;
    out.push({ kind: "run_outcome", tone: "red", text: t + "." });
  }
  for (let k = 0; k < given.length; k++) {
    if (given[k].kind === "newer_minor") out.push(givenNotice(given.splice(k--, 1)[0]));
  }
  if (m.unfinishedScopes.length) {
    out.push({ kind: "unfinished_scopes", tone: "amber", q: "is:unfinished",
      text: plural(m.unfinishedScopes.length, "Scope", "Scopes") + " unfinished (no scope_end record)." });
  }
  for (const n of given) out.push(givenNotice(n));
  return out;
}

function givenNotice(n) {
  return { kind: n.kind, tone: "amber", text: String(n.message), source: n };
}

// Time column and notices use UTC: the hh:mm:ss.mmm slice of ts.
function hms(ts) { return typeof ts === "string" ? ts.slice(11, 23) : ""; }

// An entry is a record shown as an ordinary list row: everything except the Run Header,
// run_end, Scope starts (shown as Scope header rows) and Scope ends that closed "ok".
// Unknown record types are entries and render as generic rows.
function isEntry(r) {
  switch (r.type) {
    case "run_start": case "run_end": case "scope_start": return false;
    case "scope_end": return r.outcome === "error";
    default: return true;
  }
}

async function startReport(doc) {
  const root = doc.documentElement;
  const app = doc.getElementById("app");
  root.dataset.state = "loading";
  try {
    const payload = await decodePayload(doc.getElementById("dbfixlog-payload").textContent);
    root.dataset.recordCount = String(payload.records.length);
    app.textContent = payload.records.length + " records";
    root.dataset.state = "ready";
  } catch (e) {
    root.dataset.error = String(e);
    app.textContent = "Could not load the Report data: " + e;
    root.dataset.state = "error";
  }
}

if (typeof document !== "undefined") startReport(document);
if (typeof module !== "undefined") module.exports = { decodePayload, buildModel, modeStrip, runNotices };

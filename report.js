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
// "error", data-record-count, and data-error (on error). Once ready, window.dbfixlogReport
// is {model, list, onQuery} (see renderReport): the seam later tickets hook into.
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

// ---------------------------------------------------------------------------------------
// Row lists (pure). A row is a record index: a scope_start index is that Scope's header
// row, any other index is an entry. Ticket 08 adds filtering and pruning on top of these.
// ---------------------------------------------------------------------------------------

function isHeader(m, i) {
  const r = m.records[i];
  if (r.type !== "scope_start") return false;
  const s = m.scopes.get(r.id);
  return !!s && s.start === i;
}

function isRow(m, i) { return isEntry(m.records[i]) || isHeader(m, i); }

function anyIn(path, set) {
  if (!set.size || !Array.isArray(path)) return false;
  for (const id of path) if (set.has(id)) return true;
  return false;
}

// Tree mode: Scope headers and entries in file order; a folded Scope keeps its header
// but hides everything inside it. collapsed is a Set of Scope ids.
function treeRows(m, collapsed) {
  const out = [];
  const recs = m.records;
  for (let i = 0; i < recs.length; i++) {
    if (!isRow(m, i)) continue;
    if (anyIn(recs[i].scope, collapsed)) continue;
    out.push(i);
  }
  return out;
}

// Flat mode: a plain list in which Scope header rows are ordinary rows.
function flatRows(m) {
  const out = [];
  for (let i = 0; i < m.records.length; i++) if (isRow(m, i)) out.push(i);
  return out;
}

// ---------------------------------------------------------------------------------------
// Cells (pure; return HTML strings)
// ---------------------------------------------------------------------------------------

const LEVELS = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50 };
const COLUMNS = ["Time", "Scope", "Status", "Op", "Table", "Key", "Label", "Details"];

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function isPlainObject(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }

// Values are shown as logged. null and "" are distinct; $-marked values are markers.
function valueHTML(v) {
  if (v === null) return '<span class="null" title="NULL (the Uniface loader may not tell NULL from empty)">NULL</span>';
  if (v === "") return '<span class="empty" title="empty string (the Uniface loader may not tell NULL from empty)">(empty)</span>';
  if (isPlainObject(v)) {
    if ("$truncated" in v) {
      return esc(v.$truncated) + '… <span class="mark">truncated · ' + esc(v.length) + " chars</span>";
    }
    if ("$bytes" in v) {
      return '<span class="mark">bytes · ' + esc(v.length) + '</span> <span class="mono dim">' + esc(v.$bytes) + "</span>";
    }
    if ("$unencodable" in v) return '<span class="mark">unencodable</span> ' + esc(v.$unencodable);
  }
  if (v !== null && typeof v === "object") return '<span class="mono">' + esc(JSON.stringify(v)) + "</span>";
  return esc(v);
}

function pairsHTML(obj) {
  if (!isPlainObject(obj)) return obj === undefined ? "" : valueHTML(obj);
  return Object.keys(obj).map((k) => esc(k) + "=" + valueHTML(obj[k])).join(" ");
}

function keyHTML(k) { return '<span class="key">' + pairsHTML(k) + "</span>"; }

function labelHTML(l) {
  if (l === undefined) return "";
  const vals = isPlainObject(l) ? Object.keys(l).map((k) => valueHTML(l[k])) : [valueHTML(l)];
  return '<span class="lab">' + vals.join(" ") + "</span>";
}

function plainText(v) {
  if (v === null) return "NULL";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

// A Scope's short name: kind plus its label values, else its key.
function scopeName(m, id) {
  const s = m.scopes.get(id);
  if (!s) return "#" + id;
  const r = m.records[s.start];
  let extra = "";
  if (isPlainObject(r.label)) extra = Object.keys(r.label).map((k) => plainText(r.label[k])).join(" ");
  else if (isPlainObject(r.key)) extra = Object.keys(r.key).map((k) => k + "=" + plainText(r.key[k])).join(" ");
  return r.kind + (extra ? " " + extra : "");
}

function duration(ms) {
  if (typeof ms !== "number") return "";
  if (ms < 1000) return ms + " ms";
  if (ms < 60000) return (ms / 1000).toFixed(1) + " s";
  return Math.floor(ms / 60000) + " min " + Math.round((ms % 60000) / 1000) + " s";
}

function badge(cls, text, title) {
  return '<span class="b ' + cls + '"' + (title ? ' title="' + esc(title) + '"' : "") + ">" + esc(text) + "</span>";
}

function levelBadge(level) {
  const l = String(level || "");
  return badge("lvb-" + (l in LEVELS ? l : "other"), l.toLowerCase());
}

function statusHTML(m, i) {
  const r = m.records[i];
  if (isHeader(m, i)) {
    const o = m.scopes.get(r.id).outcome;
    if (o === "error") return badge("st-scope-error", "scope error");
    if (o === "unfinished") return badge("st-unfinished", "unfinished", "no scope_end record");
    return "";
  }
  if (r.type === "scope_end") return badge("st-scope-error", "scope error");
  if (r.type === "change") {
    const w = m.warn[i];
    if (w && m.mode === "dry") return badge("st-mismatch", r.status + " ⚠", w);
    if (w) return badge("st-" + r.status + " st-warn", r.status + " ⚠", w);
    return badge("st-" + r.status, r.status);
  }
  return levelBadge(r.level);
}

// Derived totals for a Scope header: records, planned/applied/failed, Findings, duration.
function totalsHTML(m, s) {
  const t = s.totals;
  const parts = [plural(t.records, "record", "records")];
  if (t.planned) parts.push(t.planned + " planned");
  if (t.applied) parts.push('<span class="' + (m.mode === "dry" ? "out-error" : "out-ok") + '">' + t.applied + " applied</span>");
  if (t.failed) parts.push('<span class="out-error">' + t.failed + " failed</span>");
  if (t.findings) parts.push(plural(t.findings, "Finding", "Findings"));
  if (t.duration_ms !== null) parts.push(duration(t.duration_ms));
  return parts.join(" · ");
}

function detailsHTML(m, i) {
  const r = m.records[i];
  const msg = r.msg !== undefined ? ' <span class="msg">' + esc(r.msg) + "</span>" : "";
  if (isHeader(m, i)) {
    const s = m.scopes.get(r.id);
    return (r.msg !== undefined ? esc(r.msg) + " · " : "") + '<span class="dim">' + totalsHTML(m, s) + "</span>";
  }
  switch (r.type) {
    case "change": {
      let h = "";
      if (isPlainObject(r.changes)) {
        h = Object.keys(r.changes).map((f) => {
          const c = isPlainObject(r.changes[f]) ? r.changes[f] : {};
          return '<span class="fld">' + esc(f) + ":</span> " + valueHTML(c.old) +
            '<span class="arrow"> → </span>' + valueHTML(c.new);
        }).join("  ");
      }
      if (isPlainObject(r.error)) {
        h += (h ? " " : "") + '<span class="out-error">' + esc(r.error.type) + ": " + esc(r.error.message) + "</span>";
      }
      return h + (h ? msg : msg.slice(1));
    }
    case "finding":
      return '<span class="chk">' + esc(r.check) + "</span>" + msg;
    case "scope_end": {
      const e = r.exc || {};
      return '<span class="out-error">' + esc(scopeName(m, r.id)) + " raised " + esc(e.type || "") +
        ": " + esc(e.message || "") + "</span>";
    }
    case "message":
      return (r.msg !== undefined ? esc(r.msg) : "") + fieldsHTML(r.fields, r.msg !== undefined);
    default: // unknown type: generic row
      return '<span class="dim">' + esc(r.type) + ":</span>" + msg + fieldsHTML(r.fields, true);
  }
}

function fieldsHTML(f, lead) {
  if (!isPlainObject(f) || !Object.keys(f).length) return "";
  return (lead ? " " : "") + '<span class="fld">' + pairsHTML(f) + "</span>";
}

function scopeCellHTML(m, i, mode, collapsed) {
  const r = m.records[i];
  const header = isHeader(m, i);
  if (mode === "flat") {
    const path = (Array.isArray(r.scope) ? r.scope : []).concat(header ? [r.id] : []);
    const full = path.map((id) => scopeName(m, id)).join(" › ");
    return '<span class="crumb" title="' + esc(full) + '">' + esc(full) + "</span>";
  }
  const depth = Array.isArray(r.scope) ? r.scope.length : 0;
  let h = '<span class="sc">' + "<i></i>".repeat(depth);
  if (header) {
    const folded = collapsed && collapsed.has(r.id);
    h += '<b class="caret" data-fold="' + esc(r.id) + '" title="' + (folded ? "expand" : "fold") + '">' +
      (folded ? "▸" : "▾") + '</b><b class="kind" title="' + esc(scopeName(m, r.id)) + '">' + esc(r.kind) + "</b>";
  }
  return h + "</span>";
}

// The eight column cells (see COLUMNS) of row i, as HTML strings.
function rowCells(m, i, mode, collapsed) {
  const r = m.records[i];
  const header = isHeader(m, i);
  let key = "";
  if (header) key = r.key !== undefined ? keyHTML(r.key) : '<span class="dim">phase</span>';
  else if (r.key !== undefined) key = keyHTML(r.key);
  else if (r.type === "change") key = '<span class="dim">(new)</span>';
  return [
    '<span class="t">' + esc(hms(r.ts)) + "</span>",
    scopeCellHTML(m, i, mode, collapsed),
    statusHTML(m, i),
    !header && r.op !== undefined ? '<span class="op op-' + esc(r.op) + '">' + esc(r.op) + "</span>" : "",
    !header && r.table !== undefined ? '<span class="tbl">' + esc(r.table) + "</span>" : "",
    key,
    labelHTML(r.label),
    detailsHTML(m, i),
  ];
}

// CSS classes for row i: sh (Scope header), err (raised), dbg (DEBUG, dimmed), warn (is:warn).
function rowClass(m, i) {
  const r = m.records[i];
  const c = [];
  if (isHeader(m, i)) {
    c.push("sh");
    const o = m.scopes.get(r.id).outcome;
    if (o !== "ok") c.push(o === "error" ? "err" : "unf");
  } else {
    if (r.level === "DEBUG") c.push("dbg");
    if (m.warn[i]) c.push("warn");
    if (r.type === "scope_end") c.push("err");
  }
  return c.join(" ");
}

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

// ---------------------------------------------------------------------------------------
// Folding, sticky Scopes, details panel, column widths (pure; ticket 10)
// ---------------------------------------------------------------------------------------

// The collapsed set for a fold button: "all" folds every Scope, "phases" folds every entity
// Scope (one with a key) so the phases stay open, "none" expands all.
function foldSet(m, how) {
  const out = new Set();
  if (how !== "all" && how !== "phases") return out;
  for (const s of m.scopes.values()) {
    if (how === "all" || m.records[s.start].key !== undefined) out.add(s.id);
  }
  return out;
}

// Tree mode sticky Scopes for a list scrolled so that rows[k] is the top row. The pinned
// rows overlay the list, so pinned row d covers rows[k + d]: it is the depth-d Scope that
// encloses rows[k + d]. Stops at the first covered row that is not that deep.
function stickyScopes(m, rows, k) {
  const path = [];
  for (let d = 0; k + d < rows.length; d++) {
    const p = m.records[rows[k + d]].scope;
    if (!Array.isArray(p) || p.length <= d) break;
    let same = true;
    for (let j = 0; j < d; j++) if (p[j] !== path[j]) same = false;
    if (!same) break;
    path.push(p[d]);
  }
  return path;
}

// Column widths are remembered per browser. Storage may be missing or throw (private
// windows, blocked site data), so both directions fall back quietly.
const WIDTHS_KEY = "dbfixlog-report-widths";

function loadWidths(storage) {
  try {
    const w = JSON.parse(storage.getItem(WIDTHS_KEY));
    if (Array.isArray(w) && w.length === DEFAULT_WIDTHS.length &&
        w.every((x) => typeof x === "number" && x > 0 && isFinite(x))) return w;
  } catch (e) { /* fall through */ }
  return DEFAULT_WIDTHS.slice();
}

function saveWidths(storage, widths) {
  try { storage.setItem(WIDTHS_KEY, JSON.stringify(widths)); } catch (e) { /* not remembered */ }
}

// Details panel content. Scope links carry data-reveal (reveal in the tree); the
// "show only this Scope" link carries data-q="in:<id>" so it goes through report.onQuery.
function crumbHTML(m, path) {
  if (!Array.isArray(path) || !path.length) return '<div class="crumb dim">Run level</div>';
  return '<div class="crumb">' + path.map((id) =>
    '<a href="#" data-reveal="' + esc(id) + '">' + esc(scopeName(m, id)) + "</a>").join(" › ") + "</div>";
}

function kvRow(k, v) { return '<tr><td class="k">' + esc(k) + "</td><td>" + v + "</td></tr>"; }

function fieldTableHTML(title, f) {
  if (!isPlainObject(f) || !Object.keys(f).length) return "";
  return "<section><b>" + esc(title) + '</b><table class="fieldtab">' +
    Object.keys(f).map((k) => '<tr><td class="k mono">' + esc(k) + "</td><td>" + valueHTML(f[k]) + "</td></tr>").join("") +
    "</table></section>";
}

function excHTML(exc) {
  if (!isPlainObject(exc)) return "";
  return '<section><b class="out-error">' + esc(exc.type || "") + ": " + esc(exc.message || "") + "</b>" +
    '<pre class="tb">' + esc(exc.traceback || "") + "</pre></section>";
}

function rawHTML(title, r) {
  return '<details class="rawbox"><summary class="dim">' + esc(title) + '</summary><pre class="raw">' +
    esc(JSON.stringify(r, null, 2)) + "</pre></details>";
}

const RECORD_TITLES = { change: "Change", finding: "Finding", message: "Message", scope_end: "Scope error" };
// Shown in their own sections (or the Scope path), not in the field table.
const OWN_SECTIONS = { scope: 1, changes: 1, fields: 1, exc: 1, error: 1 };

// Every field of record i, then field changes, error, fields, traceback and raw JSON.
function recordDetailsHTML(m, i) {
  const r = m.records[i];
  let h = '<div class="detail"><h3>' + esc(RECORD_TITLES[r.type] || r.type) + " " + statusHTML(m, i) + "</h3>" +
    crumbHTML(m, r.scope) + '<table class="facts">';
  for (const k of Object.keys(r)) {
    if (k in OWN_SECTIONS) continue;
    const v = r[k];
    if (k === "key" || k === "label") h += kvRow(k, pairsHTML(v));
    else if (k === "ts" || k === "src" || k === "logger") h += kvRow(k, '<span class="mono">' + esc(v) + "</span>");
    else h += kvRow(k, valueHTML(v));
  }
  h += kvRow("line", '<span class="mono">' + esc(m.lines[i]) + "</span>");
  if (m.warn[i]) h += kvRow("warning", '<span class="out-error">⚠ ' + esc(m.warn[i]) + "</span>");
  h += "</table>";
  if (isPlainObject(r.changes)) {
    h += '<section><b>Field changes</b><table class="fchanges">' +
      '<thead><tr><th>field</th><th>old</th><th></th><th>new</th></tr></thead><tbody>' +
      Object.keys(r.changes).map((f) => {
        const c = isPlainObject(r.changes[f]) ? r.changes[f] : {};
        return '<tr><td class="mono">' + esc(f) + "</td><td>" + valueHTML(c.old) +
          '</td><td class="arrow">→</td><td>' + valueHTML(c.new) + "</td></tr>";
      }).join("") + "</tbody></table></section>";
  }
  if (isPlainObject(r.error)) {
    h += '<section><b class="out-error">' + esc(r.error.type) + "</b>: " + esc(r.error.message) + "</section>";
  }
  h += fieldTableHTML("Fields", r.fields) + excHTML(r.exc) + rawHTML("raw JSON", r);
  return h + "</div>";
}

// A Scope row: its own fields, timing, outcome, totals and a "show only this Scope" link.
function scopeDetailsHTML(m, id) {
  const s = m.scopes.get(id);
  const r = m.records[s.start];
  const e = s.end !== null ? m.records[s.end] : null;
  const t = s.totals;
  const outcome = s.outcome === "ok" ? '<span class="out-ok">ok</span>' : statusHTML(m, s.start);
  let h = '<div class="detail"><h3>Scope: ' + esc(scopeName(m, id)) + " " + outcome + "</h3>" +
    crumbHTML(m, s.path) + '<table class="facts">' +
    kvRow("kind", '<span class="mono">' + esc(r.kind) + "</span>") +
    kvRow("key", r.key !== undefined ? pairsHTML(r.key) : '<span class="dim">phase (no key)</span>');
  if (r.label !== undefined) h += kvRow("label", pairsHTML(r.label));
  if (r.msg !== undefined) h += kvRow("msg", esc(r.msg));
  h += kvRow("id", esc(id)) + kvRow("logger", '<span class="mono">' + esc(r.logger) + "</span>");
  if (r.src !== undefined) h += kvRow("src", '<span class="mono">' + esc(r.src) + "</span>");
  h += kvRow("started", '<span class="mono">' + esc(r.ts) + "</span>");
  h += e ? kvRow("ended", '<span class="mono">' + esc(e.ts) + "</span>") + kvRow("duration", esc(duration(t.duration_ms)))
    : kvRow("ended", '<span class="out-unfinished">unfinished</span> (no scope_end record)');
  h += "</table>" +
    '<section><b>Totals</b> <span class="dim">(the whole Scope)</span><table class="totals">' +
    kvRow("records", esc(t.records)) + kvRow("planned", esc(t.planned)) +
    kvRow("applied", '<span class="' + (t.applied && m.mode === "dry" ? "out-error" : "") + '">' + esc(t.applied) + "</span>") +
    kvRow("failed", '<span class="' + (t.failed ? "out-error" : "") + '">' + esc(t.failed) + "</span>") +
    kvRow("Findings", esc(t.findings)) + "</table></section>" +
    '<p><a href="#" data-q="in:' + esc(id) + '">show only this Scope</a></p>' +
    fieldTableHTML("Fields", r.fields) + (e ? excHTML(e.exc) : "") +
    rawHTML("raw JSON (scope_start)", r) + (e ? rawHTML("raw JSON (scope_end)", e) : "");
  return h + "</div>";
}

function detailsPanelHTML(m, i) {
  return isHeader(m, i) ? scopeDetailsHTML(m, m.records[i].id) : recordDetailsHTML(m, i);
}

// ---------------------------------------------------------------------------------------
// DOM (browser only)
// ---------------------------------------------------------------------------------------

function runHeaderHTML(m) {
  const h = m.header;
  const p = m.payload;
  const rows = [];
  const row = (k, v) => rows.push('<tr><td class="dim">' + k + "</td><td>" + v + "</td></tr>");
  if (h.target !== undefined) row("target", pairsHTML(h.target));
  if (h.fields !== undefined) row("fields", pairsHTML(h.fields));
  row("started", '<span class="mono">' + esc(h.ts) + "</span>");
  if (m.unfinished) {
    row("outcome", '<span class="out-unfinished">unfinished</span>');
  } else {
    const e = m.end;
    const code = e.exit_code !== undefined && e.exit_code !== null ? " (exit code " + esc(e.exit_code) + ")" : "";
    row("outcome", '<span class="out-' + esc(m.outcome) + '">' + esc(m.outcome) + "</span>" + code);
    row("duration", esc(duration(e.duration_ms)));
  }
  row("records", esc(m.records.length.toLocaleString("en")));
  const mode = m.mode === "dry" ? "DRY RUN" : m.mode === "write" ? "WRITE RUN" : String(m.mode).toUpperCase();
  return '<header class="runhead">' +
    '<div class="title"><h1>' + esc(p.title) + "</h1>" +
    (h.description !== undefined ? '<div class="desc">' + esc(h.description) + "</div>" : "") +
    '<div class="dim src">' + esc(p.source || "") + "</div></div>" +
    '<div><span class="mode mode-' + esc(m.mode) + '">' + esc(mode) + "</span></div>" +
    '<table class="facts">' + rows.join("") + "</table></header>";
}

function noticesHTML(m) {
  let h = "";
  const s = modeStrip(m);
  if (s) {
    h += '<div class="strip" data-tone="' + s.tone + '">' + esc(s.text) +
      (s.q ? ' <a href="#" data-q="' + esc(s.q) + '">Show them</a>' : "") + "</div>";
  }
  for (const n of runNotices(m)) {
    h += '<div class="notice" data-kind="' + esc(n.kind) + '" data-tone="' + n.tone + '">' + esc(n.text) +
      (n.q ? ' <a href="#" data-q="' + esc(n.q) + '">show</a>' : "") + "</div>";
  }
  return h;
}

const ROW_HEIGHT = 24;
const DEFAULT_WIDTHS = [96, 200, 96, 64, 110, 150, 130, 400];

// The fixed-height virtual list. rowSource(model, mode, collapsed) returns the row indices;
// ticket 08 replaces it to filter. setWidths() is the hook for column resizing (ticket 10).
function createList(doc, wrap, m) {
  wrap.innerHTML = '<div class="lhead"><div class="grid">' +
    COLUMNS.map((c, k) => '<div class="hc" data-col="' + k + '">' + c + "</div>").join("") +
    '</div></div><div class="list"><div class="sizer"></div><div class="rows"></div></div>';
  const head = wrap.firstChild.firstChild;
  const el = wrap.lastChild;
  const sizer = el.firstChild;
  const box = el.lastChild;
  let raf = 0;
  const list = {
    model: m, mode: "tree", collapsed: new Set(), rows: [],
    rowSource: (model, mode, collapsed) => (mode === "flat" ? flatRows(model) : treeRows(model, collapsed)),
    refresh() {
      list.rows = list.rowSource(m, list.mode, list.collapsed);
      sizer.style.height = list.rows.length * ROW_HEIGHT + "px";
      list.draw();
    },
    setMode(mode) { list.mode = mode === "flat" ? "flat" : "tree"; list.refresh(); },
    toggle(id) {
      if (list.collapsed.has(id)) list.collapsed.delete(id); else list.collapsed.add(id);
      list.refresh();
    },
    setWidths(widths) {
      wrap.style.setProperty("--cols", widths.slice(0, -1).map((w) => w + "px").join(" ") +
        " minmax(" + widths[widths.length - 1] + "px, 1fr)");
      wrap.style.setProperty("--tw", widths.reduce((a, b) => a + b, 0) + "px");
    },
    scrollToRecord(i) {
      const k = list.rows.indexOf(i);
      if (k >= 0) el.scrollTop = Math.max(0, k * ROW_HEIGHT - el.clientHeight / 3);
      list.draw();
      return k >= 0;
    },
    draw() {
      raf = 0;
      const top = el.scrollTop;
      const a = Math.max(0, Math.floor(top / ROW_HEIGHT) - 8);
      const b = Math.min(list.rows.length, Math.ceil((top + el.clientHeight) / ROW_HEIGHT) + 8);
      let h = "";
      for (let k = a; k < b; k++) {
        const i = list.rows[k];
        h += '<div class="vr grid ' + rowClass(m, i) + '" data-i="' + i + '" style="top:' + k * ROW_HEIGHT + 'px">' +
          rowCells(m, i, list.mode, list.collapsed).map((c) => "<span>" + c + "</span>").join("") + "</div>";
      }
      box.innerHTML = h;
      head.style.transform = "translateX(" + -el.scrollLeft + "px)";
    },
  };
  el.addEventListener("scroll", () => { if (!raf) raf = requestAnimationFrame(list.draw); });
  doc.defaultView.addEventListener("resize", () => list.draw());
  box.addEventListener("click", (e) => {
    const c = e.target.closest("[data-fold]");
    if (c) list.toggle(Number(c.dataset.fold));
  });
  list.setWidths(DEFAULT_WIDTHS);
  return list;
}

// ---------------------------------------------------------------------------------------
// DOM: details panel, column resizing, sticky Scopes, fold buttons (ticket 10)
// ---------------------------------------------------------------------------------------
// installListTools(doc, app, report) wraps the list in .main next to an <aside class="panel">,
// overlays .stick on the list, adds resize handles to the header cells and puts the fold
// buttons in #treetools (the filter bar may adopt them). It adds to report:
//   open(i)     show row i in the panel (a Scope header row shows the Scope)
//   close()     hide the panel
//   reveal(id)  switch to Tree mode, unfold the Scope's ancestors, scroll to it, open it
//   fold(how)   "none" (expand all) / "phases" / "all"
// and list.selected (the row shown in the panel, or null).

function installListTools(doc, app, report) {
  const m = report.model;
  const list = report.list;
  const win = doc.defaultView;
  const wrap = app.querySelector(".listwrap");
  const el = wrap.querySelector(".list");
  const lhead = wrap.querySelector(".lhead");

  const main = doc.createElement("div");
  main.className = "main";
  wrap.parentNode.insertBefore(main, wrap);
  main.appendChild(wrap);
  const panel = doc.createElement("aside");
  panel.className = "panel";
  panel.hidden = true;
  main.appendChild(panel);
  const tools = doc.createElement("div");
  tools.id = "treetools";
  tools.innerHTML = '<span class="treebtns">' +
    '<button data-foldall="none" title="Expand all Scopes">Expand all</button>' +
    '<button data-foldall="phases" title="Fold entity Scopes, keep phases open">Fold to phases</button>' +
    '<button data-foldall="all" title="Fold all Scopes">Fold all</button></span>';
  main.parentNode.insertBefore(tools, main);
  const stick = doc.createElement("div");
  stick.className = "stick";
  wrap.appendChild(stick);

  list.selected = null;
  report.open = (i) => {
    panel.innerHTML = '<button class="close" title="Close">✕</button>' + detailsPanelHTML(m, i);
    panel.hidden = false;
    panel.scrollTop = 0;
    list.selected = i;
    list.draw();
  };
  report.close = () => {
    panel.hidden = true;
    list.selected = null;
    list.draw();
  };
  report.reveal = (id) => {
    const s = m.scopes.get(id);
    if (!s) return;
    for (const p of s.path) list.collapsed.delete(p);
    if (list.mode !== "tree") list.setMode("tree"); else list.refresh();
    list.scrollToRecord(s.start);
    report.open(s.start);
  };
  report.fold = (how) => {
    list.collapsed = foldSet(m, how);
    list.refresh();
  };

  // Jump so the Scope's header sits just below its own (pinned) parents.
  function jumpTo(id) {
    const s = m.scopes.get(id);
    const k = list.rows.indexOf(s.start);
    if (k < 0) return;
    el.scrollTop = Math.max(0, (k - s.depth) * ROW_HEIGHT);
    list.draw();
  }

  function drawSticky() {
    stick.style.top = lhead.offsetHeight + "px";
    stick.style.right = el.offsetWidth - el.clientWidth + "px";
    const ids = list.mode === "tree" ? stickyScopes(m, list.rows, Math.floor(el.scrollTop / ROW_HEIGHT)) : [];
    let h = "";
    ids.forEach((id, d) => {
      const i = m.scopes.get(id).start;
      h += '<div class="vr grid srow ' + rowClass(m, i) + '" data-sid="' + id + '" style="top:' + d * ROW_HEIGHT + 'px">' +
        rowCells(m, i, "tree", list.collapsed).map((c) => "<span>" + c + "</span>").join("") + "</div>";
    });
    stick.innerHTML = h ? '<div class="sinner" style="transform:translateX(' + -el.scrollLeft + 'px)">' + h + "</div>" : "";
    stick.style.height = ids.length * ROW_HEIGHT + "px";
  }

  // Wrap draw (the list looks list.draw up on every call): mark the selection, pin Scopes.
  const draw = list.draw;
  list.draw = () => {
    draw();
    if (list.selected !== null) {
      const r = el.querySelector('.vr[data-i="' + list.selected + '"]');
      if (r) r.classList.add("sel");
    }
    drawSticky();
  };

  el.addEventListener("click", (e) => {
    if (e.target.closest("[data-fold]")) return; // the caret folds (createList)
    const r = e.target.closest(".vr[data-i]");
    if (r) report.open(Number(r.dataset.i));
  });
  stick.addEventListener("click", (e) => {
    const r = e.target.closest("[data-sid]");
    if (!r) return;
    const id = Number(r.dataset.sid);
    if (e.target.closest("[data-fold]")) { list.collapsed.add(id); list.refresh(); }
    jumpTo(id);
  });
  panel.addEventListener("click", (e) => {
    if (e.target.closest(".close")) { report.close(); return; }
    const a = e.target.closest("[data-reveal]");
    if (a) { e.preventDefault(); report.reveal(Number(a.dataset.reveal)); }
  });
  tools.addEventListener("click", (e) => {
    const b = e.target.closest("[data-foldall]");
    if (b) report.fold(b.dataset.foldall);
  });

  // Column resizing: drag a header edge, double-click it to reset; widths are remembered.
  let storage = null;
  try { storage = win.localStorage; } catch (e) { /* no storage */ }
  const widths = loadWidths(storage);
  const apply = () => { list.setWidths(widths); list.draw(); };
  lhead.querySelectorAll(".hc").forEach((c) => {
    const z = doc.createElement("span");
    z.className = "rz";
    z.dataset.rz = c.dataset.col;
    z.title = "Drag to resize, double-click to reset";
    c.appendChild(z);
  });
  lhead.addEventListener("pointerdown", (e) => {
    const z = e.target.closest(".rz");
    if (!z) return;
    e.preventDefault();
    const c = Number(z.dataset.rz);
    const x0 = e.clientX;
    const w0 = widths[c];
    const move = (ev) => { widths[c] = Math.max(32, Math.round(w0 + ev.clientX - x0)); apply(); };
    const up = () => {
      win.removeEventListener("pointermove", move);
      win.removeEventListener("pointerup", up);
      saveWidths(storage, widths);
    };
    win.addEventListener("pointermove", move);
    win.addEventListener("pointerup", up);
  });
  lhead.addEventListener("dblclick", (e) => {
    const z = e.target.closest(".rz");
    if (!z) return;
    const c = Number(z.dataset.rz);
    widths[c] = DEFAULT_WIDTHS[c];
    apply();
    saveWidths(storage, widths);
  });
  list.setWidths(widths);
}

function renderReport(doc, app, payload) {
  const m = buildModel(payload);
  app.innerHTML = '<div class="report">' + runHeaderHTML(m) +
    '<div class="notices">' + noticesHTML(m) + "</div>" +
    '<div id="cards"></div><div id="bar"></div>' + // slots: summary cards (09), filter bar (08)
    '<div class="listwrap"></div></div>';
  const list = createList(doc, app.querySelector(".listwrap"), m);
  const report = {
    model: m, list: list,
    // Applies a query from a notice link. Ticket 08 replaces this with the real filter;
    // until then "is:warn" jumps to the first mismatched Change.
    onQuery(q) {
      if (q === "is:warn" && m.warnings.length) list.scrollToRecord(m.warnings[0]);
      else if (q === "is:unfinished" && m.unfinishedScopes.length) {
        list.scrollToRecord(m.scopes.get(m.unfinishedScopes[0]).start);
      } else if (/^in:\d+$/.test(q)) report.reveal(Number(q.slice(3))); // "show only this Scope"
    },
  };
  installListTools(doc, app, report);
  app.addEventListener("click", (e) => {
    const a = e.target.closest("[data-q]");
    if (!a) return;
    e.preventDefault();
    report.onQuery(a.dataset.q);
  });
  list.refresh();
  return report;
}

async function startReport(doc) {
  const root = doc.documentElement;
  const app = doc.getElementById("app");
  root.dataset.state = "loading";
  try {
    const payload = await decodePayload(doc.getElementById("dbfixlog-payload").textContent);
    root.dataset.recordCount = String(payload.records.length);
    doc.defaultView.dbfixlogReport = renderReport(doc, app, payload);
    root.dataset.state = "ready";
  } catch (e) {
    root.dataset.error = String(e);
    app.textContent = "Could not load the Report data: " + e;
    root.dataset.state = "error";
  }
}

if (typeof document !== "undefined") startReport(document);
if (typeof module !== "undefined") module.exports = {
  decodePayload, buildModel, modeStrip, runNotices, isEntry, isHeader, isRow, treeRows, flatRows,
  rowCells, rowClass, valueHTML, scopeName, hms, duration, esc, LEVELS, COLUMNS,
  // ticket 10
  foldSet, stickyScopes, loadWidths, saveWidths, WIDTHS_KEY, DEFAULT_WIDTHS,
};

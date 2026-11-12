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
      }
    },
  };
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

// Report code for Database Fix Logging. Plain script: no modules, no build step.
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
// Records are the Log File's JSON objects unchanged, including unknown types.
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
// is {model, list, filter, onQuery, timing} (see renderReport and startReport), which
// the browser tests drive. timing = {decode, render, ready, nav} in ms; <html data-ready-ms> too.
// ---------------------------------------------------------------------------------------

async function decodePayload(base64Text) {
  const bytes = base64Bytes(base64Text.trim());
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  // Copy the inflated chunks into one buffer sized from the gzip trailer (ISIZE, the
  // uncompressed size mod 2^32), then decode once. At 100k records this is ~2x faster in
  // Firefox than Response.text() or .arrayBuffer(). The buffer still grows if
  // the hint is short.
  const n = bytes.length < 18 ? 0 : (bytes[bytes.length - 4] | bytes[bytes.length - 3] << 8 |
    bytes[bytes.length - 2] << 16 | bytes[bytes.length - 1] << 24) >>> 0;
  let buf = new Uint8Array(n);
  let used = 0;
  const reader = stream.getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (used + value.length > buf.length) {
      const bigger = new Uint8Array(Math.max(buf.length * 2, used + value.length));
      bigger.set(buf.subarray(0, used));
      buf = bigger;
    }
    buf.set(value, used);
    used += value.length;
  }
  return JSON.parse(new TextDecoder().decode(buf.subarray(0, used)));
}

function base64Bytes(text) {
  if (typeof Uint8Array.fromBase64 === "function") return Uint8Array.fromBase64(text);
  const bin = atob(text);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

// ---------------------------------------------------------------------------------------
// Model (pure; exported for Node)
// ---------------------------------------------------------------------------------------
// buildModel(payload) derives everything the views need from the verbatim records.
// A record's id is its index i into model.records. Per-record derived data lives in
// parallel arrays (model.warn, model.odd) so the records themselves stay verbatim.

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
  // Known types with missing or odd fields: odd[i] is a reason string or null.
  m.odd = records.map(oddFields);
  m.oddRecords = [];
  for (let i = 0; i < records.length; i++) if (m.odd[i]) m.oddRecords.push(i);
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

// What is missing or odd about a record of a known type, or null. Such a record is still
// shown as well as possible, with this reason as a warning.
function oddFields(r) {
  const out = [];
  const has = (k) => r[k] !== undefined && r[k] !== null;
  const oneOf = (k, allowed) => {
    if (!has(k)) out.push("no " + k);
    else if (allowed.indexOf(r[k]) < 0) out.push(k + " " + JSON.stringify(r[k]));
  };
  switch (r.type) {
    case "change":
      oneOf("op", CHANGE_OPS);
      oneOf("status", CHANGE_STATUSES);
      if (typeof r.table !== "string") out.push("no table");
      if (has("key") && !isPlainObject(r.key)) out.push("key is not a {column: value} object");
      else if (!has("key") && r.op !== "insert") out.push("no key");
      if (r.op === "update" && !isPlainObject(r.changes)) out.push("update without changes");
      break;
    case "finding":
      if (typeof r.check !== "string" || !r.check) out.push("no check");
      break;
    case "message":
      if (!has("msg")) out.push("no msg");
      break;
    case "scope_start":
      if (!has("id")) out.push("no id");
      if (!has("kind")) out.push("no kind");
      break;
    case "scope_end":
      if (!has("id")) out.push("no id");
      oneOf("outcome", ["ok", "error"]);
      break;
  }
  return out.length ? out.join("; ") : null;
}

function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }

// The full-width Dry Run strip, or null for a Write Run. It only claims what the Log File
// shows. q is the query a "Show them" link should apply (wired by the filter bar).
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
  if (m.oddRecords.length) {
    const lines = m.oddRecords.map((i) => m.lines[i]);
    out.push({ kind: "odd_fields", tone: "amber",
      text: plural(lines.length, "record has", "records have") + " missing or odd fields (line" +
        (lines.length === 1 ? " " : "s ") + lines.slice(0, 20).join(", ") + (lines.length > 20 ? ", …" : "") +
        "); they are shown as well as possible, marked ⚠." });
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
// row, any other index is an entry. filterRows adds filtering and pruning on top of these.
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
// Filters and search (pure): the Scope-header pruning rule and the query syntax.
// ---------------------------------------------------------------------------------------
// A filter state is {view, q, level}:
//   view:  "all" | "changes" | "findings" | "errors"   (default "all")
//   q:     the search box text (default "")
//   level: the level ≥ dropdown, a LEVELS name (default "DEBUG", meaning no level filter)
// filterRows(m, state, mode, collapsed) returns {rows, active, matches, shown, ms}:
//   rows:    record indices to show, in file order
//   active:  whether a filter is active; when false, rows are treeRows/flatRows
//   matches: how many rows match the filter themselves (enclosing headers kept for the
//            tree path are not counted)
//   shown:   Map of Scope id -> matching entries inside it (any depth), or null when no
//            filter is active. A header shows "k of n shown" with n = totals.records.

const VIEWS = ["all", "changes", "findings", "errors"];
const LEVEL_ALIASES = { WARN: "WARNING", ERR: "ERROR", CRIT: "CRITICAL", FATAL: "CRITICAL" };
const QUERY_KEYS = ["level", "type", "table", "op", "status", "check", "logger", "key", "kind", "in",
  "after", "before", "is"];

function levelValue(name) {
  const n = String(name || "").toUpperCase();
  return LEVELS[LEVEL_ALIASES[n] || n] || 0;
}

// Splits on whitespace; double quotes group ("two words", f.city="new york") and are dropped.
function queryTokens(text) {
  return (String(text || "").match(/(?:[^\s"]+|"[^"]*"?)+/g) || []).map((t) => t.replace(/"/g, ""))
    .filter((t) => t.length);
}

// parseQuery(text) -> Query. Terms combine with AND; comma lists inside a term are OR.
// An unknown or malformed term (e.g. "foo:bar", "level>=loud") is kept as a plain word.
function parseQuery(text) {
  const Q = { words: [], minLevel: 0, levels: null, types: null, tables: null, ops: null, statuses: null,
    checks: null, loggers: null, keys: [], kinds: null, ins: null, after: null, before: null,
    fields: [], warn: false, unfinished: false, terms: 0 };
  const list = (v) => v.toLowerCase().split(",").filter(Boolean);
  const add = (prev, v) => { const s = prev || new Set(); for (const x of list(v)) s.add(x); return s; };
  for (const tok of queryTokens(text)) {
    let mm = tok.match(/^level>=(\w+)$/i);
    if (mm && levelValue(mm[1])) {
      Q.minLevel = Math.max(Q.minLevel, levelValue(mm[1])); Q.terms++; continue;
    }
    mm = tok.match(/^f\.([^=]+)=(.*)$/);
    if (mm) { Q.fields.push([mm[1], mm[2].toLowerCase()]); Q.terms++; continue; }
    mm = tok.match(/^(\w+):(.+)$/);
    const k = mm && mm[1].toLowerCase();
    const v = mm && mm[2];
    let ok = !!mm && QUERY_KEYS.indexOf(k) >= 0;
    if (ok) {
      switch (k) {
        case "level": {
          const names = list(v).map((x) => LEVEL_ALIASES[x.toUpperCase()] || x.toUpperCase());
          ok = names.every((x) => x in LEVELS);
          if (ok) { Q.levels = Q.levels || new Set(); for (const x of names) Q.levels.add(x); }
          break;
        }
        case "type": {
          const s = add(Q.types, v);
          if (s.has("scope")) { s.add("scope_start"); s.add("scope_end"); }
          Q.types = s;
          break;
        }
        case "table": Q.tables = add(Q.tables, v); break;
        case "op": Q.ops = add(Q.ops, v); break;
        case "status": Q.statuses = add(Q.statuses, v); break;
        case "check": Q.checks = add(Q.checks, v); break;
        case "logger": Q.loggers = (Q.loggers || []).concat(list(v)); break;
        case "key": Q.keys.push(v.toLowerCase()); break;
        case "kind": Q.kinds = add(Q.kinds, v); break;
        case "in": {
          const ids = v.split(",").filter(Boolean).map(Number);
          ok = ids.length > 0 && ids.every((x) => Number.isInteger(x));
          if (ok) { Q.ins = Q.ins || new Set(); for (const x of ids) Q.ins.add(x); }
          break;
        }
        case "after": Q.after = v; break;
        case "before": Q.before = v; break;
        case "is": {
          const w = v.toLowerCase();
          if (w === "warn") Q.warn = true;
          else if (w === "unfinished") Q.unfinished = true;
          else ok = false;
          break;
        }
      }
    }
    if (ok) Q.terms++;
    else { Q.words.push(tok.toLowerCase()); Q.terms++; }
  }
  return Q;
}

// Search text, built once per model on first use (m.search). For an entry, hay is its own
// text; for a Scope, scopeHay is kind + key + label (what enclosing-Scope matching sees).
function textOf(v) {
  if (v === undefined) return "";
  if (v === null) return "null";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
function pairsText(o) {
  if (!isPlainObject(o)) return textOf(o);
  let s = "";
  for (const k in o) s += k + "=" + textOf(o[k]) + " ";
  return s;
}
const HAY_SKIP = { ts: 1, src: 1, logger: 1, scope: 1, key: 1, label: 1, fields: 1, changes: 1, duration_ms: 1 };

function searchIndex(m) {
  if (m.search) return m.search;
  const recs = m.records;
  const n = recs.length;
  const hay = new Array(n);
  const keyText = new Array(n);
  const levelOf = new Uint8Array(n);
  const time = new Array(n);
  for (let i = 0; i < n; i++) {
    const r = recs[i];
    time[i] = hms(r.ts);
    keyText[i] = r.key === undefined ? "" : pairsText(r.key).toLowerCase();
    if (isHeader(m, i)) {
      const s = m.scopes.get(r.id);
      levelOf[i] = s.outcome === "error" ? LEVELS.ERROR : levelValue(r.level);
      hay[i] = (textOf(r.kind) + " " + keyText[i] + " " + pairsText(r.label) + " " + textOf(r.msg) + " " +
        (s.outcome === "error" ? "scope error" : String(r.level || "").toLowerCase())).toLowerCase();
      continue;
    }
    levelOf[i] = levelValue(r.level);
    let h = keyText[i] + " " + pairsText(r.label) + " " + pairsText(r.fields) + " ";
    if (isPlainObject(r.changes)) {
      for (const f in r.changes) {
        const c = r.changes[f];
        h += f + " " + (isPlainObject(c) ? textOf(c.old) + " " + textOf(c.new) : textOf(c)) + " ";
      }
    }
    for (const k in r) if (!HAY_SKIP[k]) h += textOf(r[k]) + " ";
    if (r.type === "scope_end" && r.outcome === "error") h += "scope error";
    hay[i] = h.toLowerCase();
  }
  const scopeHay = new Map();
  const scopeKey = new Map();
  for (const s of m.scopes.values()) {
    const r = recs[s.start];
    scopeKey.set(s.id, keyText[s.start]);
    scopeHay.set(s.id, (textOf(r.kind) + " " + keyText[s.start] + " " + pairsText(r.label)).toLowerCase());
  }
  m.search = { hay: hay, keyText: keyText, levelOf: levelOf, time: time, scopeHay: scopeHay, scopeKey: scopeKey };
  return m.search;
}

function normState(state) {
  const s = state || {};
  return {
    view: VIEWS.indexOf(s.view) >= 0 ? s.view : "all",
    q: typeof s.q === "string" ? s.q : "",
    level: levelValue(s.level) ? String(s.level).toUpperCase() : "DEBUG",
  };
}

// compileFilter(m, state) -> Filter: the parsed query plus the view and dropdown, with the
// per-Scope work (word, key, kind hits) done once so matchRow stays cheap.
function compileFilter(m, state) {
  const st = normState(state);
  const Q = parseQuery(st.q);
  const F = Q;
  F.state = st;
  F.minLevel = Math.max(Q.minLevel, st.level === "DEBUG" ? 0 : levelValue(st.level));
  if (st.view === "errors") F.minLevel = Math.max(F.minLevel, LEVELS.ERROR);
  F.viewType = st.view === "changes" ? "change" : st.view === "findings" ? "finding" : null;
  F.active = st.view !== "all" || Q.terms > 0 || F.minLevel > LEVELS.DEBUG;
  if (!F.active) return F;
  const ix = searchIndex(m);
  F.ix = ix;
  if (Q.words.length > 30) Q.words = Q.words.slice(0, 30); // bit mask per word below
  F.full = (1 << Q.words.length) - 1;
  // Per Scope: which words its kind/key/label contain (bit mask), whether every key: term
  // matches its key, whether its kind is wanted.
  F.scopeWords = new Map();
  F.scopeKeys = new Map();
  F.scopeKind = new Map();
  for (const s of m.scopes.values()) {
    const sh = ix.scopeHay.get(s.id);
    let mask = 0;
    for (let w = 0; w < Q.words.length; w++) if (sh.indexOf(Q.words[w]) >= 0) mask |= 1 << w;
    if (mask) F.scopeWords.set(s.id, mask);
    let km = 0;
    const kt = ix.scopeKey.get(s.id);
    for (let w = 0; w < Q.keys.length; w++) if (kt.indexOf(Q.keys[w]) >= 0) km |= 1 << w;
    if (km) F.scopeKeys.set(s.id, km);
    if (Q.kinds && Q.kinds.has(String(s.kind).toLowerCase())) F.scopeKind.set(s.id, true);
  }
  return F;
}

function lc(v) { return typeof v === "string" ? v.toLowerCase() : v === undefined || v === null ? "" : String(v).toLowerCase(); }

// The Scopes a row sits in for matching: its scope path, plus the Scope itself for that
// Scope's own start (header) and end records.
function rowScopes(r) {
  const p = Array.isArray(r.scope) ? r.scope : [];
  return r.type === "scope_start" || r.type === "scope_end" ? p.concat([r.id]) : p;
}

// Does row i (an entry or a Scope header) match the filter itself? A header matches on its
// own kind, key, label, msg, Status (info, or scope error, as its level) and start time.
function matchRow(m, i, F) {
  const r = m.records[i];
  const ix = F.ix;
  const header = isHeader(m, i);
  if (F.minLevel && ix.levelOf[i] < F.minLevel) return false;
  if (F.levels) {
    const name = header ? (ix.levelOf[i] === LEVELS.ERROR ? "ERROR" : String(r.level).toUpperCase()) : String(r.level).toUpperCase();
    if (!F.levels.has(LEVEL_ALIASES[name] || name)) return false;
  }
  if (F.viewType && r.type !== F.viewType) return false;
  if (F.types && !F.types.has(lc(r.type))) return false;
  if (F.unfinished && !(header && m.scopes.get(r.id).outcome === "unfinished")) return false;
  if (F.warn && !m.warn[i]) return false;
  if (header) {
    if (F.tables || F.ops || F.statuses || F.checks || F.fields.length) return false;
  } else {
    if (F.tables && !F.tables.has(lc(r.table))) return false;
    if (F.ops && !F.ops.has(lc(r.op))) return false;
    if (F.statuses && !F.statuses.has(lc(r.status))) return false;
    if (F.checks && !F.checks.has(lc(r.check))) return false;
  }
  if (F.loggers) {
    const lg = lc(r.logger);
    let any = false;
    for (const p of F.loggers) if (lg.startsWith(p)) { any = true; break; }
    if (!any) return false;
  }
  if (F.after !== null && ix.time[i].slice(0, F.after.length) < F.after) return false;
  if (F.before !== null && ix.time[i].slice(0, F.before.length) > F.before) return false;
  const needScopes = F.ins || F.kinds || F.keys.length || F.words.length;
  const sc = needScopes ? rowScopes(r) : null;
  if (F.ins) {
    let any = false;
    for (const id of sc) if (F.ins.has(id)) { any = true; break; }
    if (!any) return false;
  }
  if (F.kinds) {
    // A Scope's own records match on its own kind, so kind:K lists exactly the Scopes of
    // kind K; any other record matches on the kinds of the Scopes it sits in.
    let any = false;
    if (r.type === "scope_start" || r.type === "scope_end") any = F.scopeKind.has(r.id);
    else for (const id of sc) if (F.scopeKind.has(id)) { any = true; break; }
    if (!any) return false;
  }
  if (F.keys.length) {
    let mask = 0;
    const kt = ix.keyText[i];
    for (let w = 0; w < F.keys.length; w++) if (kt.indexOf(F.keys[w]) >= 0) mask |= 1 << w;
    for (const id of sc) mask |= F.scopeKeys.get(id) || 0;
    if (mask !== (1 << F.keys.length) - 1) return false;
  }
  if (F.fields.length && !fieldsMatch(r, F.fields)) return false;
  if (F.words.length) {
    let mask = 0;
    for (const id of sc) mask |= F.scopeWords.get(id) || 0;
    if (mask !== F.full) {
      const h = ix.hay[i];
      for (let w = 0; w < F.words.length; w++) if (!(mask & (1 << w)) && h.indexOf(F.words[w]) >= 0) mask |= 1 << w;
      if (mask !== F.full) return false;
    }
  }
  return true;
}

// f.<field>=<value>: equal (ignoring case) to fields[field] or to a changed field's old or
// new value. NULL is written f.x=null, an empty string f.x= .
function fieldsMatch(r, terms) {
  for (const [k, v] of terms) {
    const vals = [];
    if (isPlainObject(r.fields) && k in r.fields) vals.push(r.fields[k]);
    if (isPlainObject(r.changes) && isPlainObject(r.changes[k])) vals.push(r.changes[k].old, r.changes[k].new);
    let any = false;
    for (const x of vals) if (x !== undefined && textOf(x).toLowerCase() === v) { any = true; break; }
    if (!any) return false;
  }
  return true;
}

function filterRows(m, state, mode, collapsed) {
  const t0 = typeof performance !== "undefined" ? performance.now() : Date.now();
  const F = compileFilter(m, state);
  const coll = collapsed || new Set();
  const flat = mode === "flat";
  const out = { rows: null, active: F.active, matches: 0, shown: null, filter: F, ms: 0 };
  if (!F.active) {
    out.rows = flat ? flatRows(m) : treeRows(m, coll);
    out.matches = out.rows.length;
  } else {
    const recs = m.records;
    const n = recs.length;
    const hit = new Uint8Array(n);
    const shown = new Map();
    const keep = new Set(); // tree: Scope ids whose header shows
    let matches = 0;
    for (let i = 0; i < n; i++) {
      if (!isRow(m, i) || !matchRow(m, i, F)) continue;
      hit[i] = 1;
      matches++;
      const r = recs[i];
      const header = isHeader(m, i);
      const p = Array.isArray(r.scope) ? r.scope : [];
      if (!header) for (const id of p) shown.set(id, (shown.get(id) || 0) + 1);
      if (!flat) {
        if (header) keep.add(r.id);
        for (const id of p) keep.add(id);
      }
    }
    const rows = [];
    for (let i = 0; i < n; i++) {
      if (flat) { if (hit[i]) rows.push(i); continue; }
      const r = recs[i];
      if (isHeader(m, i) ? !keep.has(r.id) : !hit[i]) continue;
      if (anyIn(r.scope, coll)) continue;
      rows.push(i);
    }
    out.rows = rows;
    out.matches = matches;
    out.shown = shown;
  }
  out.ms = (typeof performance !== "undefined" ? performance.now() : Date.now()) - t0;
  return out;
}

// Static counts for the view buttons: entries per view (Errors = level ≥ ERROR, so failed
// Changes, error Findings and Messages, and Scopes that raised; never unfinished Scopes).
function viewCounts(m) {
  const c = { all: 0, changes: 0, findings: 0, errors: 0 };
  for (let i = 0; i < m.records.length; i++) {
    const r = m.records[i];
    if (!isEntry(r)) continue;
    c.all++;
    if (r.type === "change") c.changes++;
    else if (r.type === "finding") c.findings++;
    if (levelValue(r.level) >= LEVELS.ERROR) c.errors++;
  }
  return c;
}

// ---------------------------------------------------------------------------------------
// Summary cards (pure)
// ---------------------------------------------------------------------------------------
// summaryCounts(m) -> {changes, findings, kinds}:
//   changes:  {rows: [{table, op, planned, applied, failed, all}], total: {planned, applied, failed, all}}
//             one row per table x op, sorted by table, then update/insert/delete, then other ops.
//   findings: {levels: [LEVEL names that occur, by severity], rows: [{check, all, <LEVEL>: n}]}, by check.
//   kinds:    [{kind, n, error, unfinished}] in the order kinds first appear.
const CHANGE_STATUSES = ["planned", "applied", "failed"];
const CHANGE_OPS = ["update", "insert", "delete"];

function summaryCounts(m) {
  const changes = new Map();
  const total = { planned: 0, applied: 0, failed: 0, all: 0 };
  const checks = new Map();
  const levels = new Set();
  for (let i = 0; i < m.records.length; i++) {
    const r = m.records[i];
    if (r.type === "change") {
      const table = textOf(r.table);
      const op = textOf(r.op);
      const id = table + "\u0000" + op;
      let row = changes.get(id);
      if (!row) changes.set(id, row = { table: table, op: op, planned: 0, applied: 0, failed: 0, all: 0 });
      row.all++;
      total.all++;
      if (CHANGE_STATUSES.indexOf(r.status) >= 0) { row[r.status]++; total[r.status]++; }
    } else if (r.type === "finding") {
      const check = textOf(r.check);
      const level = String(r.level || "").toUpperCase();
      let row = checks.get(check);
      if (!row) checks.set(check, row = { check: check, all: 0 });
      row.all++;
      row[level] = (row[level] || 0) + 1;
      levels.add(level);
    }
  }
  const opRank = (op) => { const k = CHANGE_OPS.indexOf(op); return k < 0 ? CHANGE_OPS.length : k; };
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  const changeRows = Array.from(changes.values()).sort((a, b) =>
    cmp(a.table, b.table) || opRank(a.op) - opRank(b.op) || cmp(a.op, b.op));
  const findingLevels = Array.from(levels).sort((a, b) => (LEVELS[a] || 99) - (LEVELS[b] || 99) || cmp(a, b));
  const findingRows = Array.from(checks.values()).sort((a, b) => cmp(a.check, b.check));
  for (const row of findingRows) for (const l of findingLevels) row[l] = row[l] || 0;
  const kinds = new Map();
  for (const s of m.scopes.values()) {
    const kind = textOf(s.kind);
    let k = kinds.get(kind);
    if (!k) kinds.set(kind, k = { kind: kind, n: 0, error: 0, unfinished: 0 });
    k.n++;
    if (s.outcome === "error") k.error++;
    else if (s.outcome === "unfinished") k.unfinished++;
  }
  return { changes: { rows: changeRows, total: total }, findings: { levels: findingLevels, rows: findingRows }, kinds: Array.from(kinds.values()) };
}

// A query value, quoted when it holds whitespace (queryTokens groups on double quotes).
// An empty value yields no term at all ("table:" would be a plain word).
function queryTerm(key, v) {
  const s = String(v).replace(/"/g, "");
  if (!s) return "";
  return key + ":" + (/\s/.test(s) ? '"' + s + '"' : s);
}
function joinTerms(terms) { return terms.filter(Boolean).join(" "); }

// A clickable card number: a [data-q] link (the click handler in renderReport sends it to
// filter.query). Zero is plain dim text, not a link.
function cardNum(n, q, red) {
  if (!n) return '<td class="num"><span class="dim">0</span></td>';
  return '<td class="num"><a href="#" class="cn' + (red ? " red" : "") + '" data-q="' + esc(q) + '">' +
    n.toLocaleString("en") + "</a></td>";
}

// The foldable summary cards, or "" when there is nothing to count.
// Failed Changes are red when non-zero; applied ones too in a Dry Run.
function cardsHTML(m) {
  const c = summaryCounts(m);
  const dry = m.mode === "dry";
  const redStatus = (s) => s === "failed" || (s === "applied" && dry);
  const cards = [];
  if (c.changes.rows.length) {
    const head = "<tr><th>table</th><th>op</th>" + CHANGE_STATUSES.map((s) => "<th>" + s + "</th>").join("") + "<th>all</th></tr>";
    let prev = null;
    const body = c.changes.rows.map((r) => {
      const base = ["type:change", queryTerm("table", r.table), queryTerm("op", r.op)];
      const h = '<tr><td class="mono">' + (r.table === prev ? "" : esc(r.table)) + '</td><td>' + esc(r.op) + "</td>" +
        CHANGE_STATUSES.map((s) => cardNum(r[s], joinTerms(base.concat([queryTerm("status", s)])), redStatus(s))).join("") +
        cardNum(r.all, joinTerms(base), false) + "</tr>";
      prev = r.table;
      return h;
    }).join("");
    const t = c.changes.total;
    const foot = '<tr class="tot"><td>all</td><td></td>' +
      CHANGE_STATUSES.map((s) => cardNum(t[s], "type:change status:" + s, redStatus(s))).join("") +
      cardNum(t.all, "type:change", false) + "</tr>";
    cards.push('<div class="card" data-card="changes"><h4>Changes</h4><table>' + head + body + foot + "</table></div>");
  }
  if (c.findings.rows.length) {
    const levels = c.findings.levels;
    const head = "<tr><th>check</th>" + levels.map((l) => "<th>" + esc(l.toLowerCase()) + "</th>").join("") + "<th>all</th></tr>";
    const body = c.findings.rows.map((r) => {
      const ck = queryTerm("check", r.check);
      return '<tr><td class="mono">' + esc(r.check) + "</td>" +
        levels.map((l) => cardNum(r[l], joinTerms([ck, queryTerm("level", l.toLowerCase())]), levelValue(l) >= LEVELS.ERROR)).join("") +
        cardNum(r.all, ck, false) + "</tr>";
    }).join("");
    cards.push('<div class="card" data-card="findings"><h4>Findings</h4><table>' + head + body + "</table></div>");
  }
  if (c.kinds.length) {
    const head = "<tr><th>kind</th><th>Scopes</th><th>error</th><th>unfinished</th></tr>";
    const body = c.kinds.map((k) => {
      const kd = queryTerm("kind", k.kind);
      return '<tr><td class="mono">' + esc(k.kind) + "</td>" +
        cardNum(k.n, joinTerms(["type:scope_start", kd]), false) +
        cardNum(k.error, joinTerms(["type:scope_end", kd]), true) +
        cardNum(k.unfinished, joinTerms(["is:unfinished", kd]), false) + "</tr>";
    }).join("");
    cards.push('<div class="card" data-card="scopes"><h4>Scopes</h4><table>' + head + body + "</table></div>");
  }
  if (!cards.length) return "";
  return '<details class="cards" open><summary>Summary</summary><div class="cardrow">' + cards.join("") + "</div></details>";
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

function levelBadge(level, odd) {
  const l = String(level || "");
  return badge("lvb-" + (l in LEVELS ? l : "other") + (odd ? " st-odd" : ""), l.toLowerCase() + (odd ? " ⚠" : ""), odd);
}

function statusHTML(m, i) {
  const r = m.records[i];
  if (isHeader(m, i)) {
    const o = m.scopes.get(r.id).outcome;
    if (o === "error") return badge("st-scope-error", "scope error");
    if (o === "unfinished") return badge("st-unfinished", "unfinished", "no scope_end record");
    return "";
  }
  const odd = m.odd[i];
  if (r.type === "scope_end") return badge("st-scope-error", "scope error" + (odd ? " ⚠" : ""), odd);
  if (r.type === "change") {
    const w = m.warn[i];
    // In a Dry Run an applied or failed Change is red with ⚠. A planned one in a Write Run
    // only gets the Run-level notice.
    if (w && m.mode === "dry") return badge("st-mismatch", r.status + " ⚠", w);
    const status = r.status === undefined || r.status === null ? "no status" : String(r.status);
    if (odd) return badge("st-odd", status + " ⚠", odd);
    return badge("st-" + status, status);
  }
  return levelBadge(r.level, odd);
}

// Derived totals for a Scope header: records, planned/applied/failed, Findings, duration.
// shown (Map of Scope id -> matching entries, from filterRows) adds "k of n shown" while a
// filter is active; null or undefined without one.
function totalsHTML(m, s, shown) {
  const t = s.totals;
  const parts = [plural(t.records, "record", "records")];
  if (t.planned) parts.push(t.planned + " planned");
  if (t.applied) parts.push('<span class="' + (m.mode === "dry" ? "out-error" : "out-ok") + '">' + t.applied + " applied</span>");
  if (t.failed) parts.push('<span class="out-error">' + t.failed + " failed</span>");
  if (t.findings) parts.push(plural(t.findings, "Finding", "Findings"));
  if (t.duration_ms !== null) parts.push(duration(t.duration_ms));
  if (shown) parts.push((shown.get(s.id) || 0) + " of " + t.records + " shown");
  return parts.join(" · ");
}

function detailsHTML(m, i, shown) {
  const r = m.records[i];
  const msg = r.msg !== undefined ? ' <span class="msg">' + esc(r.msg) + "</span>" : "";
  if (isHeader(m, i)) {
    const s = m.scopes.get(r.id);
    return (r.msg !== undefined ? esc(r.msg) + " · " : "") + '<span class="dim">' + totalsHTML(m, s, shown) + "</span>";
  }
  switch (r.type) {
    case "change": {
      let h = changeEntries(r).map(([f, c]) =>
        '<span class="fld">' + esc(f) + ":</span> " + valueHTML(c.old) +
        '<span class="arrow"> → </span>' + valueHTML(c.new)).join("  ");
      if (isPlainObject(r.error)) {
        h += (h ? " " : "") + '<span class="out-error">' + esc(r.error.type) + ": " + esc(r.error.message) + "</span>";
      }
      return h + (h ? msg : msg.slice(1));
    }
    case "finding":
      return r.check === undefined ? msg.slice(1) : '<span class="chk">' + esc(r.check) + "</span>" + msg;
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

// A Change's field changes as [field, {old, new}] pairs; [] when it has none.
function changeEntries(r) {
  if (!isPlainObject(r.changes)) return [];
  return Object.keys(r.changes).map((f) => [f, isPlainObject(r.changes[f]) ? r.changes[f] : {}]);
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

// The eight column cells (see COLUMNS) of row i, as HTML strings. shown: see totalsHTML.
function rowCells(m, i, mode, collapsed, shown) {
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
    detailsHTML(m, i, shown),
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
// Folding, sticky Scopes, details panel, column widths (pure)
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
  if (m.odd[i]) h += kvRow("warning", '<span class="out-error">⚠ ' + esc(m.odd[i]) + "</span>");
  h += "</table>";
  if (isPlainObject(r.changes)) {
    h += '<section><b>Field changes</b><table class="fchanges">' +
      '<thead><tr><th>field</th><th>old</th><th></th><th>new</th></tr></thead><tbody>' +
      changeEntries(r).map(([f, c]) =>
        '<tr><td class="mono">' + esc(f) + "</td><td>" + valueHTML(c.old) +
        '</td><td class="arrow">→</td><td>' + valueHTML(c.new) + "</td></tr>").join("") + "</tbody></table></section>";
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
// the filter bar replaces it to filter. setWidths() is the hook for column resizing.
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
          rowCells(m, i, list.mode, list.collapsed, list.shown).map((c) => "<span>" + c + "</span>").join("") + "</div>";
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
// DOM: details panel, column resizing, sticky Scopes, fold buttons
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
  // Fold buttons go in the filter bar's .fold-slot, else in their own #treetools.
  const btns = '<span class="treebtns">' +
    '<button type="button" data-foldall="none" title="Expand all Scopes">Expand all</button>' +
    '<button type="button" data-foldall="phases" title="Fold entity Scopes, keep phases open">Fold to phases</button>' +
    '<button type="button" data-foldall="all" title="Fold all Scopes">Fold all</button></span>';
  let tools = app.querySelector(".fold-slot");
  if (tools) tools.innerHTML = btns;
  else {
    tools = doc.createElement("div");
    tools.id = "treetools";
    tools.innerHTML = btns;
    main.parentNode.insertBefore(tools, main);
  }
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
        rowCells(m, i, "tree", list.collapsed, list.shown).map((c) => "<span>" + c + "</span>").join("") + "</div>";
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

// ---------------------------------------------------------------------------------------
// Filter bar (browser only). Views with counts, search box, level ≥, Tree/Flat.
// ---------------------------------------------------------------------------------------
// createFilterBar returns the filter API (window.dbfixlogReport.filter):
//   get()          -> a copy of the state {view, q, level} (see filterRows)
//   set(partial)   -> merges into the state, updates the controls and refreshes the list
//   query(q)       -> shows exactly what q matches: view All, level DEBUG, search box q.
//                     Notice links and summary-card numbers use this.
//   last           -> the latest filterRows result {rows, active, matches, shown, ms}
// It installs itself as list.rowSource and sets list.shown for "k of n shown".

const VIEW_LABELS = { all: "All", changes: "Changes", findings: "Findings", errors: "Errors" };

const SEARCH_HELP =
  "<p>Words match a record's text and the kind, key and label of the Scopes it sits in. " +
  "All words and terms must match. Use quotes for spaces: <code>\"two words\"</code>.</p><table>" +
  [["level>=warning, level:error,info", "level"],
    ["type:change,finding,message,scope", "record type"],
    ["table:orders  op:update  status:failed  check:name", "that field"],
    ["logger:fix", "logger name (prefix)"],
    ["key:156", "key, including enclosing Scopes' keys"],
    ["kind:customer", "Scope kind"],
    ["in:12", "records inside Scope 12"],
    ["after:20:05  before:20:06:30", "time (UTC, as shown), inclusive"],
    ["f.city=gent  f.note=null  f.note=", "fields and changed fields (old or new)"],
    ["is:warn", "Change status that doesn't fit the Run's mode"],
    ["is:unfinished", "unfinished Scopes"]].map((r) => "<tr><td><code>" + esc(r[0]) + "</code></td><td>" + r[1] + "</td></tr>").join("") +
  "</table><p>While a filter is active, a Scope shows when it matches itself or holds a visible row; " +
  "its header then adds \"k of n shown\". In Flat mode Scope rows show only when they match.</p>" +
  "<p><span class=\"null\">NULL</span> and <span class=\"empty\">(empty)</span> are shown as logged, " +
  "but the Uniface database loader doesn't reliably tell NULL and empty strings apart, so treat " +
  "them as possibly the same.</p>";

function filterBarHTML(m) {
  const c = viewCounts(m);
  const levels = Object.keys(LEVELS);
  return '<div class="fbar">' +
    '<span class="seg views">' + VIEWS.map((v) =>
      '<button type="button" data-view="' + v + '" class="' + (v === "all" ? "on" : "") +
      (v === "errors" && c.errors ? " haserr" : "") + '">' + VIEW_LABELS[v] + ' <span class="n">' +
      c[v].toLocaleString("en") + "</span></button>").join("") + "</span>" +
    '<input type="search" name="q" spellcheck="false" autocomplete="off" ' +
    'placeholder="search… e.g. acme status:failed, key:156, f.city=gent">' +
    '<details class="qhelp"><summary title="search help">?</summary><div class="qhelp-body">' + SEARCH_HELP +
    "</div></details>" +
    '<label class="lvl">level ≥ <select name="level">' + levels.map((l) =>
      '<option value="' + l + '">' + (l === "DEBUG" ? "all" : l.toLowerCase()) + "</option>").join("") +
    "</select></label>" +
    '<span class="seg modes"><button type="button" data-mode="tree" class="on">Tree</button>' +
    '<button type="button" data-mode="flat">Flat</button></span>' +
    '<span class="fold-slot"></span>' + // fold buttons
    '<span class="fcount dim"></span></div>';
}

function createFilterBar(doc, bar, list, m, listEl) {
  bar.innerHTML = filterBarHTML(m);
  const input = bar.querySelector("input[name=q]");
  const select = bar.querySelector("select[name=level]");
  const count = bar.querySelector(".fcount");
  let state = normState({});
  let timer = 0;
  const filter = {
    last: null,
    indexMs: null,
    get() { return Object.assign({}, state); },
    set(partial) {
      clearTimeout(timer);
      state = normState(Object.assign({}, state, partial));
      if (input.value !== state.q) input.value = state.q;
      if (listEl) listEl.scrollTop = 0;
      list.refresh();
    },
    query(q) { filter.set({ view: "all", level: "DEBUG", q: String(q) }); },
  };
  function sync() {
    for (const b of bar.querySelectorAll("[data-view]")) b.classList.toggle("on", b.dataset.view === state.view);
    for (const b of bar.querySelectorAll("[data-mode]")) b.classList.toggle("on", b.dataset.mode === list.mode);
    const fold = bar.querySelector(".fold-slot");
    if (fold) fold.hidden = list.mode !== "tree"; // fold buttons only act in Tree mode
    select.value = state.level;
    const r = filter.last;
    count.textContent = r.active
      ? r.matches.toLocaleString("en") + " matching · " + r.rows.length.toLocaleString("en") + " rows"
      : r.rows.length.toLocaleString("en") + " rows";
  }
  list.rowSource = (model, mode, collapsed) => {
    const r = filterRows(model, state, mode, collapsed);
    filter.last = r;
    list.shown = r.shown;
    sync();
    return r.rows;
  };
  bar.addEventListener("click", (e) => {
    const v = e.target.closest("[data-view]");
    if (v) { filter.set({ view: v.dataset.view }); return; }
    const md = e.target.closest("[data-mode]");
    if (md) { if (listEl) listEl.scrollTop = 0; list.setMode(md.dataset.mode); }
  });
  select.addEventListener("change", () => filter.set({ level: select.value }));
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => filter.set({ q: input.value }), 150);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") filter.set({ q: input.value });
    else if (e.key === "Escape") filter.set({ q: "" });
  });
  // Build the search index while idle, so the first keystroke doesn't pay for it.
  // filter.indexMs records how long that took (read by the budget test).
  const idle = doc.defaultView.requestIdleCallback || ((f) => setTimeout(f, 50));
  idle(() => {
    const t0 = performance.now();
    searchIndex(m);
    filter.indexMs = performance.now() - t0;
  });
  return filter;
}

function renderReport(doc, app, payload) {
  const m = buildModel(payload);
  app.innerHTML = '<div class="report">' + runHeaderHTML(m) +
    '<div class="notices">' + noticesHTML(m) + "</div>" +
    '<div id="cards">' + cardsHTML(m) + '</div><div id="bar"></div>' + // filter bar slot
    '<div class="listwrap"></div></div>';
  const list = createList(doc, app.querySelector(".listwrap"), m);
  const filter = createFilterBar(doc, app.querySelector("#bar"), list, m, app.querySelector(".listwrap .list"));
  const report = {
    model: m, list: list, filter: filter,
    // Applies a query from a [data-q] link (notices, the mode strip, summary cards, and the
    // details panel's "show only this Scope", which is in:<id>).
    onQuery(q) { filter.query(q); },
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
  const t0 = performance.now();
  try {
    const payload = await decodePayload(doc.getElementById("dbfixlog-payload").textContent);
    const t1 = performance.now();
    root.dataset.recordCount = String(payload.records.length);
    const report = renderReport(doc, app, payload);
    const t2 = performance.now();
    // Data ready: decode + parse + model + first list render, in ms from the
    // start of this function; nav is the same moment measured from navigation start.
    report.timing = { decode: t1 - t0, render: t2 - t1, ready: t2 - t0, nav: t2 };
    root.dataset.readyMs = String(Math.round(t2 - t0));
    doc.defaultView.dbfixlogReport = report;
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
  parseQuery, compileFilter, matchRow, filterRows, viewCounts, VIEWS,
  foldSet, stickyScopes, loadWidths, saveWidths, WIDTHS_KEY, DEFAULT_WIDTHS,
  summaryCounts, cardsHTML,
};

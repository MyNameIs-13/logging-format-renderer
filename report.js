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
if (typeof module !== "undefined") module.exports = { decodePayload };

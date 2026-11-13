"""Shared harness for the headless-Firefox tests of rendered Reports.

A test renders a Log File, opens the Report from file:// and runs one probe: JS
statements that drive the page through its DOM (clicks, the search box, the level
select) and fill ``out`` with what the page shows. Nothing in the Report exists for
these tests; they read what a user sees.

Skipped when firefox or node is not on PATH, or when DBFIXLOG_SKIP_BROWSER is set.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from helpers import ROOT, render_records

DRIVER = os.path.join(ROOT, "tests", "browser", "bidi_eval.mjs")
FIREFOX = shutil.which("firefox")
NODE = shutil.which("node")

skip_without_browser = unittest.skipIf(
    os.environ.get("DBFIXLOG_SKIP_BROWSER") or not (FIREFOX and NODE),
    "needs firefox and node on PATH, and DBFIXLOG_SKIP_BROWSER unset")

# Helpers every probe body can use. The probe waits until the Report is rendered
# (or shows its load error), then runs the body.
PRELUDE = r"""
  const app = document.getElementById("app");
  if (!app) return "";
  if (/^Could not load/.test(app.textContent)) return JSON.stringify({loadError: app.textContent});
  if (!app.querySelector(".report")) return "";
  const q = (s, el) => Array.from((el || document).querySelectorAll(s));
  const $ = (s, el) => (el || document).querySelector(s);
  const texts = (s, el) => q(s, el).map((e) => e.textContent);
  const listRows = () => q(".list .rows .vr");
  const rowText = (r) => Array.from(r.children).map((c) => c.textContent).join(" | ");
  const rows = () => listRows().map(rowText);
  const ids = () => listRows().map((r) => Number(r.dataset.i));
  const row = (i) => $('.list .rows .vr[data-i="' + i + '"]');
  const cells = (i) => { const r = row(i); return r ? Array.from(r.children).map((c) => c.textContent) : null; };
  const searchBox = () => $("#bar input[type=search]");
  const search = (text) => {
    const box = searchBox();
    box.value = text;
    box.dispatchEvent(new KeyboardEvent("keydown", {key: "Enter", bubbles: true}));
  };
  const view = (v) => $('#bar [data-view="' + v + '"]').click();
  const level = (l) => {
    const s = $("#bar select[name=level]");
    s.value = l;
    s.dispatchEvent(new Event("change", {bubbles: true}));
  };
  const mode = (m) => $('#bar [data-mode="' + m + '"]').click();
  const count = () => $("#bar .fcount").textContent;
  const fold = (id) => $('.list .rows [data-fold="' + id + '"]').click();
  // The list rows for one filter: view, level, mode, then the search box.
  const filtered = (text, o) => {
    o = o || {};
    view(o.view || "all"); level(o.level || "DEBUG"); mode(o.mode || "flat"); search(text || "");
    return ids();
  };
  const frame = () => new Promise((res) => requestAnimationFrame(() => res()));
  const notices = () => q(".notices .notice").map((n) => ({tone: n.dataset.tone, text: n.textContent}));
  const strip = () => { const s = $(".notices .strip"); return s ? {tone: s.dataset.tone, text: s.textContent} : null; };
  const out = {};
"""

TS = "2026-11-12T20:01:00.000Z"


def START(mode, **extra):
    r = {"ts": TS, "level": "INFO", "logger": "dbfixlog", "type": "run_start",
         "format": "1.0", "mode": mode, "title": "T"}
    r.update(extra)
    return r


END = {"ts": "2026-11-12T20:02:00.000Z", "level": "INFO", "logger": "dbfixlog",
       "type": "run_end", "outcome": "ok", "duration_ms": 60000}


def msg(type_, **extra):
    r = {"ts": TS, "level": "INFO", "logger": "fix", "type": type_, "src": "fix.py:1"}
    r.update(extra)
    return r


def change(status, **extra):
    r = msg("change", op="update", table="orders", key={"id": 7}, status=status,
            changes={"total": {"old": 1, "new": 2}})
    r.update(extra)
    return r


class FirefoxCase(unittest.TestCase):
    """One headless Firefox per test class, driven over WebDriver BiDi."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        os.mkdir(os.path.join(cls.dir, "profile"))
        cls.firefox = subprocess.Popen(
            [FIREFOX, "--headless", "--no-remote", "--profile", os.path.join(cls.dir, "profile"),
             "--remote-debugging-port", "0", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        cls.ws_url = cls._wait_for_bidi()
        # Keep draining Firefox's chatter so a full pipe never blocks it.
        threading.Thread(target=cls.firefox.stderr.read, daemon=True).start()

    @classmethod
    def _wait_for_bidi(cls):
        deadline = time.time() + 30
        while time.time() < deadline:
            line = cls.firefox.stderr.readline().decode("utf-8", "replace")
            m = re.search(r"WebDriver BiDi listening on (ws://\S+)", line)
            if m:
                return m.group(1)
            if not line and cls.firefox.poll() is not None:
                break
        cls.tearDownClass()
        raise RuntimeError("Firefox did not start WebDriver BiDi")

    @classmethod
    def tearDownClass(cls):
        cls.firefox.kill()
        cls.firefox.wait()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def evaluate(self, page, expression, timeout_ms=10000, preload=None):
        """Poll ``expression`` on ``page`` until it yields a string; return that string."""
        args = [NODE, DRIVER, self.ws_url, Path(page).as_uri(), expression, str(timeout_ms)]
        if preload:
            args.append(preload)
        proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout_ms / 1000 + 60)
        err = proc.stderr.decode("utf-8", "replace")
        self.assertEqual(proc.returncode, 0, err)
        self.assertNotIn("js-errors:", err)
        return proc.stdout.decode("utf-8")

    def probe(self, report, body, timeout_ms=10000, preload=None):
        """Run the probe ``body`` (JS statements filling ``out``) once ``report`` is rendered."""
        expr = ("(async () => {" + PRELUDE + " try {" + body +
                "} catch (e) { out.error = String(e) + ' ' + e.stack; }"
                " return JSON.stringify(out); })()")
        out = json.loads(self.evaluate(report, expr, timeout_ms, preload))
        self.assertNotIn("loadError", out, out)
        self.assertNotIn("error", out, out)
        return out

    def render(self, name, records):
        return render_records(self.dir, name, records)

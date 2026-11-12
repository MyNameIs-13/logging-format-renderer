"""Headless Firefox checks on rendered Reports opened from file://.

Covers decoding (ticket 06), the Report core (ticket 07: Run Header, mode strip,
notices, the list's columns and value display) and the filter bar (ticket 08).

Skipped when firefox or node is not on PATH, or when DBFIXLOG_SKIP_BROWSER is set.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "dbfixlog_render.py")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "basic.jsonl")
DRIVER = os.path.join(ROOT, "tests", "browser", "bidi_eval.mjs")

# What the page exposes once report.js has run: its state, the record count, the visible
# text, the mode strip, the notices and the rendered list rows (cells joined by " | ").
PROBE = """(() => {
  const d = document.documentElement.dataset;
  if (!d.state || d.state === "loading") return "";
  const q = (s) => Array.from(document.querySelectorAll(s));
  const strip = document.querySelector(".strip");
  return JSON.stringify({
    state: d.state, count: d.recordCount, error: d.error || null,
    text: document.getElementById("app").textContent,
    strip: strip ? {tone: strip.dataset.tone, text: strip.textContent} : null,
    notices: q(".notice").map((n) => ({kind: n.dataset.kind, tone: n.dataset.tone, text: n.textContent})),
    header: q(".lhead .hc").map((c) => c.textContent),
    rows: q(".vr").map((r) => Array.from(r.children).map((c) => c.textContent).join(" | ")),
    marks: {null: q(".vr .null").length, empty: q(".vr .empty").length, mark: q(".vr .mark").map((m) => m.textContent)},
  });
})()"""

# Drives the filter bar through its controls, reading the list after each step.
FILTER_PROBE = """(() => {
  const d = document.documentElement.dataset;
  if (!d.state || d.state === "loading") return "";
  const $ = (s) => document.querySelector(s);
  const rows = () => Array.from(document.querySelectorAll(".vr")).map((r) =>
    Array.from(r.children).map((c) => c.textContent).join(" | "));
  const out = {};
  out.views = Array.from(document.querySelectorAll("[data-view]")).map((b) =>
    ({view: b.dataset.view, text: b.textContent, on: b.classList.contains("on"), err: b.classList.contains("haserr")}));
  out.initial = rows();
  const lvl = $("#bar select[name=level]");
  lvl.value = "WARNING"; lvl.dispatchEvent(new Event("change", {bubbles: true}));
  out.warning = rows();
  out.count = $("#bar .fcount").textContent;
  lvl.value = "DEBUG"; lvl.dispatchEvent(new Event("change", {bubbles: true}));
  $("[data-view=changes]").click();
  out.changes = rows();
  $("[data-view=all]").click();
  const q = $("#bar input[type=search]");
  q.value = "acme";
  q.dispatchEvent(new KeyboardEvent("keydown", {key: "Enter", bubbles: true}));
  out.acme = rows();
  $("[data-mode=flat]").click();
  out.acmeFlat = rows();
  $("[data-mode=tree]").click();
  const link = $("[data-q]");
  if (link) { link.click(); out.link = {q: q.value, rows: rows()}; }
  return JSON.stringify(out);
})()"""

FIREFOX = shutil.which("firefox")
NODE = shutil.which("node")


@unittest.skipIf(os.environ.get("DBFIXLOG_SKIP_BROWSER"), "DBFIXLOG_SKIP_BROWSER set")
@unittest.skipUnless(FIREFOX and NODE, "needs firefox and node on PATH")
class StubReportInFirefox(unittest.TestCase):
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

    def open_report(self, report, probe=PROBE):
        proc = subprocess.run(
            [NODE, DRIVER, self.ws_url, Path(report).as_uri(), probe, "10000"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        return json.loads(proc.stdout.decode("utf-8"))

    def render(self, name, records, probe=PROBE):
        log = os.path.join(self.dir, name + ".jsonl")
        with open(log, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        report = os.path.join(self.dir, name + ".html")
        subprocess.run([sys.executable, SCRIPT, log, "-o", report], check=True,
                       stderr=subprocess.DEVNULL)
        page = self.open_report(report, probe)
        if probe is PROBE:
            self.assertEqual(page["state"], "ready", page)
        return page

    def test_basic_fixture_renders_header_and_tree(self):
        report = os.path.join(self.dir, "basic.html")
        subprocess.run([sys.executable, SCRIPT, FIXTURE, "-o", report], check=True,
                       stderr=subprocess.DEVNULL)
        page = self.open_report(report)
        self.assertEqual(page["state"], "ready", page)
        self.assertEqual(page["count"], "10")
        self.assertIn("Orphaned orders cleanup", page["text"])
        self.assertIn("TICKET-123", page["text"])
        self.assertIn("shop_prod", page["text"])
        self.assertEqual(page["header"],
                         ["Time", "Scope", "Status", "Op", "Table", "Key", "Label", "Details"])
        # Scope headers and entries, in file order: phase, customer, finding, 2 changes, message.
        self.assertEqual(len(page["rows"]), 6, page["rows"])
        self.assertTrue(page["rows"][0].startswith("20:01:00.120 | "), page["rows"][0])
        self.assertIn("orphan-check", page["rows"][1])
        self.assertIn("| phase |", page["rows"][1])
        self.assertIn("customer", page["rows"][2])
        self.assertIn("id=42 | ACME |", page["rows"][2])
        self.assertIn("planned | delete | orders | id=156 | A88f", page["rows"][4])
        self.assertIn("cleaned <b>&amp;</b> </script> ünïcode", page["rows"][5])

    def test_dry_run_with_applied_changes_shows_red_strip(self):
        page = self.render("dry_applied", [
            START("dry"), change("applied"), change("failed", error={"type": "E", "message": "x"}), END])
        self.assertEqual(page["strip"]["tone"], "red", page["strip"])
        self.assertIn("Dry Run, but 2 Changes were logged as applied or failed", page["strip"]["text"])
        self.assertIn("Show them", page["strip"]["text"])
        self.assertIn("applied ⚠", page["rows"][0])

    def test_clean_dry_run_shows_amber_strip(self):
        page = self.render("dry_clean", [START("dry"), change("planned"), END])
        self.assertEqual(page["strip"]["tone"], "amber")
        self.assertEqual(page["strip"]["text"], "Dry Run: the Changes below are planned, not applied.")
        self.assertEqual(page["notices"], [])

    def test_write_run_with_planned_changes_shows_amber_notice(self):
        page = self.render("write_planned", [START("write"), change("planned"), change("applied"), END])
        self.assertIsNone(page["strip"])
        self.assertEqual([(n["kind"], n["tone"]) for n in page["notices"]], [("write_planned", "amber")])
        self.assertIn("logged as planned in a Write Run: they were not carried out",
                      page["notices"][0]["text"])

    def test_unfinished_run_and_scope_notices(self):
        page = self.render("crashed", [
            START("write"),
            msg("scope_start", id=1, kind="customer", key={"id": 1}),
            change("applied", scope=[1])])
        self.assertEqual([n["kind"] for n in page["notices"]], ["run_unfinished", "unfinished_scopes"])
        self.assertIn("unfinished", page["text"])

    def test_values_display_null_empty_and_markers(self):
        page = self.render("values", [
            START("write"),
            change("applied", changes={
                "a": {"old": None, "new": ""},
                "b": {"old": {"$truncated": "long text", "length": 5000}, "new": "20261122053550"},
                "c": {"old": {"$bytes": "00ff", "length": 2}, "new": {"$unencodable": "<Thing>"}}}),
            END])
        self.assertEqual(page["marks"]["null"], 1)
        self.assertEqual(page["marks"]["empty"], 1)
        self.assertEqual(page["marks"]["mark"], ["truncated · 5000 chars", "bytes · 2", "unencodable"])
        self.assertIn("a: NULL → (empty)", page["rows"][0])
        self.assertIn("→ 20261122053550", page["rows"][0])
        self.assertIn("<Thing>", page["rows"][0])

    def test_filter_bar_views_level_search_and_mode(self):
        report = os.path.join(self.dir, "basic_filter.html")
        subprocess.run([sys.executable, SCRIPT, FIXTURE, "-o", report], check=True,
                       stderr=subprocess.DEVNULL)
        page = self.open_report(report, FILTER_PROBE)
        self.assertEqual([(v["view"], v["on"], v["err"]) for v in page["views"]],
                         [("all", True, False), ("changes", False, False),
                          ("findings", False, False), ("errors", False, False)])
        self.assertEqual([v["text"] for v in page["views"]],
                         ["All 4", "Changes 2", "Findings 1", "Errors 0"])
        self.assertEqual(len(page["initial"]), 6)
        # level >= warning: the Finding plus the two Scopes that enclose it.
        self.assertEqual(len(page["warning"]), 3, page["warning"])
        self.assertIn("1 of 3 shown", page["warning"][1])
        self.assertIn("1 of 3 shown", page["warning"][0])
        self.assertIn("1 matching", page["count"])
        self.assertEqual(len(page["changes"]), 4, page["changes"])
        # acme matches the ACME Scope and everything in it; the phase encloses it.
        self.assertEqual(len(page["acme"]), 5, page["acme"])
        self.assertEqual(len(page["acmeFlat"]), 4, page["acmeFlat"])
        self.assertNotIn("link", page)

    def test_show_them_link_filters_to_mismatches(self):
        page = self.render("dry_link", [
            START("dry"), change("planned"), change("applied"), change("planned"), END],
            probe=FILTER_PROBE)
        self.assertEqual(page["views"][3]["text"], "Errors 0")
        self.assertEqual(page["link"]["q"], "is:warn")
        self.assertEqual(len(page["link"]["rows"]), 1)
        self.assertIn("applied ⚠", page["link"]["rows"][0])

    def test_errors_button_is_red_when_non_zero(self):
        page = self.render("errors", [
            START("write"), change("failed", level="ERROR", error={"type": "E", "message": "x"}), END],
            probe=FILTER_PROBE)
        self.assertEqual(page["views"][3]["text"], "Errors 1")
        self.assertTrue(page["views"][3]["err"])


TS = "2026-11-12T20:01:00.000Z"


def START(mode):
    return {"ts": TS, "level": "INFO", "logger": "dbfixlog", "type": "run_start",
            "format": "1.0", "mode": mode, "title": "T"}


END = {"ts": "2026-11-12T20:02:00.000Z", "level": "INFO", "logger": "dbfixlog",
       "type": "run_end", "outcome": "ok", "duration_ms": 60000}


def msg(type_, **extra):
    r = {"ts": TS, "level": "INFO", "logger": "fix", "type": type_, "src": "fix.py:1"}
    r.update(extra)
    return r


def change(status, **extra):
    r = msg("change", op="update", table="orders", key={"id": 7}, status=status)
    r.update(extra)
    return r


if __name__ == "__main__":
    unittest.main()

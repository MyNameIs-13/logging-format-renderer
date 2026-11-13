"""Headless Firefox checks on rendered Reports opened from file://.

Covers decoding the embedded data, the Report core (Run Header, mode strip,
notices, the list's columns and value display) and the filter bar.
"""
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browser_report import (  # noqa: E402
    END, START, FirefoxCase, change, msg, skip_without_browser)
from helpers import RENDER_SCRIPT, ROOT  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "basic.jsonl")

# The visible text, the Run Header facts, the mode strip, the notices, the column
# headers and the rendered list rows (cells joined by " | ").
PAGE = """
  out.text = app.textContent;
  out.facts = q(".runhead .facts tr").map((tr) => texts("td", tr).join("|"));
  out.strip = strip();
  out.notices = notices();
  out.header = texts(".lhead .hc");
  out.rows = rows();
  out.marks = {null: q(".list .vr .null").length, empty: q(".list .vr .empty").length,
               mark: texts(".list .vr .mark")};
"""

# Drives the filter bar through its controls, reading the list after each step.
FILTER = """
  out.views = q("#bar [data-view]").map((b) =>
    ({view: b.dataset.view, text: b.textContent, on: b.classList.contains("on"), err: b.classList.contains("haserr")}));
  out.initial = rows();
  level("WARNING");
  out.warning = rows();
  out.count = count();
  level("DEBUG");
  view("changes");
  out.changes = rows();
  view("all");
  search("acme");
  out.acme = rows();
  mode("flat");
  out.acmeFlat = rows();
  mode("tree");
  const link = $(".notices [data-q]");  // strip or notice link, not a summary card number
  if (link) { link.click(); out.link = {q: searchBox().value, rows: rows()}; }
"""


@skip_without_browser
class ReportInFirefox(FirefoxCase):
    def basic_report(self, name):
        report = os.path.join(self.dir, name + ".html")
        subprocess.run([sys.executable, RENDER_SCRIPT, FIXTURE, "-o", report], check=True,
                       stderr=subprocess.DEVNULL)
        return report

    def test_basic_fixture_renders_header_and_tree(self):
        page = self.probe(self.basic_report("basic"), PAGE)
        self.assertIn("records|10", page["facts"])
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

    def test_large_multibyte_payload_decodes_completely(self):
        # Enough data to inflate in many chunks, with multibyte characters across them.
        recs = [START("dry")] + [msg("message", msg="ünï %d €" % i) for i in range(20000)] + [END]
        page = self.probe(self.render("multibyte", recs), """
          out.facts = q(".runhead .facts tr").map((tr) => texts("td", tr).join("|"));
          search('"ünï 19999 €"');
          out.last = rows();
        """)
        self.assertIn("records|20,002", page["facts"])
        self.assertEqual(len(page["last"]), 1)
        self.assertIn("ünï 19999 €", page["last"][0])

    def test_a_broken_payload_shows_a_load_error(self):
        report = self.basic_report("broken")
        with open(report, encoding="utf-8") as f:
            html = f.read()
        start = html.index('id="dbfixlog-payload">') + len('id="dbfixlog-payload">')
        with open(report, "w", encoding="utf-8") as f:
            f.write(html[:start] + "AAAA" + html[html.index("</script>", start):])
        text = self.evaluate(report, """(() => {
          const t = document.getElementById("app").textContent;
          return /^Could not load/.test(t) ? t : "";
        })()""")
        self.assertIn("Could not load the Report data", text)

    def test_dry_run_with_applied_changes_shows_red_strip(self):
        page = self.probe(self.render("dry_applied", [
            START("dry"), change("applied"), change("failed", error={"type": "E", "message": "x"}), END]), PAGE)
        self.assertEqual(page["strip"]["tone"], "red", page["strip"])
        self.assertIn("Dry Run, but 2 Changes were logged as applied or failed", page["strip"]["text"])
        self.assertIn("Show them", page["strip"]["text"])
        self.assertIn("applied ⚠", page["rows"][0])

    def test_clean_dry_run_shows_amber_strip(self):
        page = self.probe(self.render("dry_clean", [START("dry"), change("planned"), END]), PAGE)
        self.assertEqual(page["strip"]["tone"], "amber")
        self.assertEqual(page["strip"]["text"], "Dry Run: the Changes below are planned, not applied.")
        self.assertEqual(page["notices"], [])

    def test_write_run_with_planned_changes_shows_amber_notice(self):
        page = self.probe(self.render("write_planned", [
            START("write"), change("planned"), change("applied"), END]), PAGE)
        self.assertIsNone(page["strip"])
        self.assertEqual(len(page["notices"]), 1, page["notices"])
        self.assertEqual(page["notices"][0]["tone"], "amber")
        self.assertIn("1 Change logged as planned in a Write Run: they were not carried out",
                      page["notices"][0]["text"])
        self.assertTrue(page["rows"][0].split(" | ")[2] == "planned", page["rows"][0])

    def test_unfinished_run_and_scope_notices(self):
        page = self.probe(self.render("crashed", [
            START("write"),
            msg("scope_start", id=1, kind="customer", key={"id": 1}),
            change("applied", scope=[1])]), PAGE)
        texts = [n["text"] for n in page["notices"]]
        self.assertEqual(len(texts), 2, texts)
        self.assertIn("Run unfinished: there is no run_end record", texts[0])
        self.assertIn("1 Scope unfinished", texts[1])
        self.assertIn("outcome|unfinished", page["facts"])
        self.assertIn("unfinished", page["rows"][0])

    def test_run_outcome_and_render_time_notices(self):
        recs = [START("dry", format="1.3"), change("planned"),
                dict(END, outcome="interrupted", level="ERROR")]
        log = os.path.join(self.dir, "notices.jsonl")
        with open(log, "w", encoding="utf-8") as f:
            f.write(json.dumps(recs[0]) + "\nnot json\n" + json.dumps(recs[1]) + "\n" +
                    json.dumps(recs[2]) + "\n" + '{"partial": ')
        report = os.path.join(self.dir, "notices.html")
        subprocess.run([sys.executable, RENDER_SCRIPT, log, "-o", report], check=True,
                       stderr=subprocess.DEVNULL)
        page = self.probe(report, PAGE + 'out.samples = texts(".notices .samples li");')
        texts = [n["text"] for n in page["notices"]]
        self.assertIn("Run ended with outcome interrupted", texts[0])
        self.assertIn("1.3", texts[1])
        self.assertIn("1 malformed line skipped (line 2)", texts[2])
        self.assertEqual(page["samples"], ["line 2 not json"])
        self.assertIn("last line incomplete, file may still be written (line 5)", texts[3])

    def test_values_display_null_empty_and_markers(self):
        page = self.probe(self.render("values", [
            START("write"),
            change("applied", changes={
                "a": {"old": None, "new": ""},
                "b": {"old": {"$truncated": "long text", "length": 5000}, "new": "20261122053550"},
                "c": {"old": {"$bytes": "00ff", "length": 2}, "new": {"$unencodable": "<Thing>"}}}),
            END]), PAGE)
        self.assertEqual(page["marks"]["null"], 1)
        self.assertEqual(page["marks"]["empty"], 1)
        self.assertEqual(page["marks"]["mark"], ["truncated · 5000 chars", "bytes · 2", "unencodable"])
        self.assertIn("a: NULL → (empty)", page["rows"][0])
        self.assertIn("→ 20261122053550", page["rows"][0])
        self.assertIn("<Thing>", page["rows"][0])

    def test_filter_bar_views_level_search_and_mode(self):
        page = self.probe(self.basic_report("basic_filter"), FILTER)
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
        page = self.probe(self.render("dry_link", [
            START("dry"), change("planned"), change("applied"), change("planned"), END]), FILTER)
        self.assertEqual(page["views"][3]["text"], "Errors 0")
        self.assertEqual(page["link"]["q"], "is:warn")
        self.assertEqual(len(page["link"]["rows"]), 1)
        self.assertIn("applied ⚠", page["link"]["rows"][0])

    def test_errors_button_is_red_when_non_zero(self):
        page = self.probe(self.render("errors", [
            START("write"), change("failed", level="ERROR", error={"type": "E", "message": "x"}), END]),
            FILTER)
        self.assertEqual(page["views"][3]["text"], "Errors 1")
        self.assertTrue(page["views"][3]["err"])


if __name__ == "__main__":
    unittest.main()

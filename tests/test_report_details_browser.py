"""Headless Firefox checks for ticket 10: details panel, column resizing, horizontal
scroll, sticky Scopes and the fold buttons.

Reuses the Firefox lifecycle of test_report_browser (without re-running its tests).
Each check renders a Log File, then drives the page with one probe expression that
returns a JSON string once the Report is ready.
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import test_report_browser as base
from test_report_browser import START, END, msg, change

_FF = base.StubReportInFirefox.__dict__  # not the class itself: unittest would collect it


@unittest.skipIf(os.environ.get("DBFIXLOG_SKIP_BROWSER"), "DBFIXLOG_SKIP_BROWSER set")
@unittest.skipUnless(base.FIREFOX and base.NODE, "needs firefox and node on PATH")
class DetailsPanelInFirefox(unittest.TestCase):
    setUpClass = _FF["setUpClass"]
    tearDownClass = _FF["tearDownClass"]
    _wait_for_bidi = _FF["_wait_for_bidi"]

    def render(self, name, records):
        log = os.path.join(self.dir, name + ".jsonl")
        with open(log, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        report = os.path.join(self.dir, name + ".html")
        subprocess.run([sys.executable, base.SCRIPT, log, "-o", report], check=True,
                       stderr=subprocess.DEVNULL)
        return report

    def probe(self, report, body):
        """Run body (JS statements that fill `out`) once the Report is ready."""
        expr = ("(() => { const d = document.documentElement.dataset;"
                " if (d.state !== 'ready') return d.state === 'error' ? JSON.stringify({error: d.error}) : '';"
                " const R = window.dbfixlogReport, out = {}; try {"
                " const q = (s, el) => Array.from((el || document).querySelectorAll(s));"
                " const row = (i) => document.querySelector('.vr[data-i=\"' + i + '\"]');"
                " const texts = (s, el) => q(s, el).map((e) => e.textContent);"
                + body + " } catch (e) { out.error = String(e) + ' ' + e.stack; }"
                " return JSON.stringify(out); })()")
        proc = subprocess.run(
            [base.NODE, base.DRIVER, self.ws_url, Path(report).as_uri(), expr, "10000"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        out = json.loads(proc.stdout.decode("utf-8"))
        self.assertNotIn("error", out, out)
        return out

    # 0 start, 1 phase{ 2 customer{ 3 change, 4 message with exc, 5 scope_end error }, 6 end }, 7 run_end
    def panel_report(self):
        tb = "Traceback (most recent call last):\n  File \"fix.py\", line 9\nValueError: bad row"
        return self.render("panel", [
            START("dry"),
            msg("scope_start", id=1, kind="orphan-check", msg="pass 1"),
            msg("scope_start", id=2, kind="customer", key={"id": 42}, label={"name": "ACME"}, scope=[1]),
            change("planned", table="customers", key={"id": 42}, scope=[1, 2],
                   changes={"note": {"old": None, "new": "x"}, "flag": {"old": "", "new": 1}}),
            msg("message", level="ERROR", msg="could not parse", scope=[1, 2], fields={"row": 3},
                exc={"type": "ValueError", "message": "bad row", "traceback": tb}),
            msg("scope_end", id=2, level="ERROR", outcome="error", duration_ms=5, scope=[1],
                exc={"type": "KeyError", "message": "'id'", "traceback": "TB-OF-SCOPE\nKeyError: 'id'"}),
            msg("scope_end", id=1, outcome="ok", duration_ms=9),
            END])

    def test_panel_opens_on_click_shows_record_and_closes(self):
        out = self.probe(self.panel_report(), """
          const panel = document.querySelector('.panel');
          out.closedAtStart = panel.hidden;
          row(3).lastElementChild.click();
          out.open = !panel.hidden;
          out.selected = row(3).classList.contains('sel');
          out.text = panel.textContent;
          out.fchanges = q('.fchanges tbody tr', panel).map((tr) => texts('td', tr).join('|'));
          out.raw = JSON.parse(panel.querySelector('pre.raw').textContent);
          out.crumb = texts('.crumb [data-reveal]', panel);
          row(4).lastElementChild.click();
          out.traceback = panel.querySelector('pre.tb').textContent;
          out.fields = texts('.fieldtab td', panel);
          panel.querySelector('.close').click();
          out.closed = panel.hidden;
        """)
        self.assertTrue(out["closedAtStart"])
        self.assertTrue(out["open"])
        self.assertTrue(out["selected"])
        self.assertEqual(out["fchanges"], ["note|NULL|→|x", "flag|(empty)|→|1"])
        self.assertEqual(out["raw"]["changes"]["note"], {"old": None, "new": "x"})
        self.assertEqual(out["raw"]["type"], "change")
        self.assertEqual(out["crumb"], ["orphan-check", "customer ACME"])
        for s in ("fix.py:1", "customers", "planned", "line"):
            self.assertIn(s, out["text"])
        self.assertIn("ValueError: bad row", out["traceback"])
        self.assertIn("File \"fix.py\", line 9", out["traceback"])
        self.assertEqual(out["fields"], ["row", "3"])
        self.assertTrue(out["closed"])

    def test_scope_row_shows_totals_traceback_and_show_only_link(self):
        out = self.probe(self.panel_report(), """
          const panel = document.querySelector('.panel');
          row(2).lastElementChild.click();
          out.text = panel.textContent;
          out.totals = q('.totals tr', panel).map((tr) => texts('td', tr).join('|'));
          out.only = q('a[data-q]', panel).map((a) => [a.textContent, a.dataset.q]);
          out.traceback = panel.querySelector('pre.tb').textContent;
          row(5).lastElementChild.click();
          out.endTraceback = panel.querySelector('pre.tb').textContent;
        """)
        self.assertIn("customer ACME", out["text"])
        self.assertIn("scope error", out["text"])
        # change + message; the raising scope_end sits at the parent's level
        self.assertEqual(out["totals"], ["records|2", "planned|1", "applied|0", "failed|0", "Findings|0"])
        self.assertEqual(out["only"], [["show only this Scope", "in:2"]])
        self.assertIn("TB-OF-SCOPE", out["traceback"])
        self.assertIn("TB-OF-SCOPE", out["endTraceback"])

    def test_scope_path_click_reveals_scope_in_tree(self):
        out = self.probe(self.panel_report(), """
          const panel = document.querySelector('.panel');
          row(3).lastElementChild.click();
          R.list.collapsed.add(1); R.list.refresh();  // the record is now hidden under phase 1
          out.hidden = !row(2);
          q('.crumb [data-reveal]', panel)[1].click();  // customer ACME
          out.collapsed = Array.from(R.list.collapsed);
          out.shown = !!row(2);
          out.selected = !!row(2) && row(2).classList.contains('sel');
          out.title = panel.querySelector('h3').textContent;
          R.onQuery('in:2');  // until ticket 08: scrolls to the Scope
          out.afterQuery = !!row(2);
        """)
        self.assertTrue(out["hidden"])
        self.assertEqual(out["collapsed"], [])
        self.assertTrue(out["shown"])
        self.assertTrue(out["selected"])
        self.assertIn("customer ACME", out["title"])
        self.assertTrue(out["afterQuery"])


if __name__ == "__main__":
    unittest.main()

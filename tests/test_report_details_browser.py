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
          q('a[data-q]', panel)[0].click();  // "show only this Scope": filters to in:2 (ticket 08)
          out.afterQuery = !!row(2);
          out.query = R.filter.get().q;
          out.filtered = R.list.rows.slice();
          R.list.setMode('flat');
          q('.crumb [data-reveal]', panel)[0].click();  // reveal switches back to Tree ...
          out.mode = R.list.mode;
          out.treeOn = document.querySelector('[data-mode="tree"]').classList.contains('on');  // ... and the switch follows
          out.flatOn = document.querySelector('[data-mode="flat"]').classList.contains('on');
        """)
        self.assertTrue(out["hidden"])
        self.assertEqual(out["collapsed"], [])
        self.assertTrue(out["shown"])
        self.assertTrue(out["selected"])
        self.assertIn("customer ACME", out["title"])
        self.assertTrue(out["afterQuery"])
        self.assertEqual(out["query"], "in:2")
        self.assertEqual(out["filtered"], [1, 2, 3, 4, 5])  # phase 1 kept as an enclosing Scope
        self.assertEqual([out["mode"], out["treeOn"], out["flatOn"]], ["tree", True, False])

    # Record indices: 1 phase{ 2 customer{ 3..62 changes } 63 end, 64 customer{ 65..124 } 125 end } 126 end,
    # 127 phase{ 128 message } 129 end. Tree rows: 1, 2, 3..62, 64, 65..124, 127, 128.
    def long_report(self, name):
        recs = [START("dry"), msg("scope_start", id=1, kind="orphan-check")]
        for sid, cid in ((2, 42), (3, 43)):
            recs.append(msg("scope_start", id=sid, kind="customer", key={"id": cid}, scope=[1]))
            recs += [change("planned", key={"id": n}, scope=[1, sid]) for n in range(60)]
            recs.append(msg("scope_end", id=sid, outcome="ok", duration_ms=1, scope=[1]))
        recs += [msg("scope_end", id=1, outcome="ok", duration_ms=2),
                 msg("scope_start", id=4, kind="report"), msg("message", msg="done", scope=[4]),
                 msg("scope_end", id=4, outcome="ok", duration_ms=1), END]
        return self.render(name, recs)

    STICKY_JS = """
      const el = document.querySelector('.list');
      // Scroll so list row k is on top; return the pinned Scope ids and the enclosing
      // Scopes of the first row that the pinned rows do not cover.
      const at = (k) => {
        el.scrollTop = k * 24; R.list.draw();
        const sids = q('.stick [data-sid]').map((r) => Number(r.dataset.sid));
        const first = R.list.rows[Math.floor(el.scrollTop / 24) + sids.length];
        return {top: el.scrollTop, sids: sids, under: R.model.records[first].scope || [],
                text: texts('.stick .vr')};
      };
    """

    def test_sticky_scopes_match_enclosing_scopes_and_jump(self):
        out = self.probe(self.long_report("sticky"), self.STICKY_JS + """
          out.top = at(0); out.mid = at(30); out.edge = at(61); out.second = at(100);
          q('.stick [data-sid="3"]')[0].click();
          out.jumpTop = el.scrollTop;
          out.jumpRow = !!row(64);
          R.list.setMode('flat'); out.flat = at(30); R.list.setMode('tree');
        """)
        self.assertEqual(out["top"]["sids"], [])
        self.assertEqual(out["mid"]["sids"], [1, 2])
        self.assertEqual(out["mid"]["under"], [1, 2])
        self.assertIn("orphan-check", out["mid"]["text"][0])
        self.assertIn("id=42", out["mid"]["text"][1])
        self.assertEqual(out["edge"]["sids"], [1])  # the next row is customer 43's header
        self.assertEqual(out["second"]["sids"], [1, 3])
        self.assertEqual(out["second"]["under"], [1, 3])
        self.assertEqual(out["jumpTop"], 61 * 24)  # customer 43's header right below phase 1
        self.assertTrue(out["jumpRow"])
        self.assertEqual(out["flat"]["sids"], [])

    def test_fold_buttons(self):
        out = self.probe(self.long_report("fold"), """
          const shown = () => q('.list .vr').map((r) => Number(r.dataset.i));
          const click = (how) => { document.querySelector('[data-foldall="' + how + '"]').click(); return shown(); };
          out.phases = click('phases');
          out.all = click('all');
          out.none = click('none').slice(0, 4);
          out.inBar = !!document.querySelector('#bar .fold-slot [data-foldall="all"]');
          R.list.setMode('flat'); out.hiddenInFlat = document.querySelector('.fold-slot').hidden;
          document.querySelector('[data-mode="tree"]').click();
          out.shownInTree = !document.querySelector('.fold-slot').hidden;
        """)
        self.assertEqual(out["phases"], [1, 2, 64, 127, 128])
        self.assertEqual(out["all"], [1, 127])
        self.assertEqual(out["none"], [1, 2, 3, 4])
        self.assertTrue(out["inBar"])
        self.assertTrue(out["hiddenInFlat"])
        self.assertTrue(out["shownInTree"])

    def test_resize_remembers_widths_and_double_click_resets(self):
        report = self.long_report("resize")
        out = self.probe(report, """
          const wrap = document.querySelector('.listwrap');
          const z = document.querySelector('.hc[data-col="1"] .rz');
          const drag = (dx) => {
            z.dispatchEvent(new PointerEvent('pointerdown', {clientX: 100, bubbles: true}));
            window.dispatchEvent(new PointerEvent('pointermove', {clientX: 100 + dx, bubbles: true}));
            window.dispatchEvent(new PointerEvent('pointerup', {clientX: 100 + dx, bubbles: true}));
            return wrap.style.getPropertyValue('--cols');
          };
          out.start = wrap.style.getPropertyValue('--cols');
          out.dragged = drag(60);
          out.cellWidth = Math.round(document.querySelector('.lhead .hc[data-col="1"]').getBoundingClientRect().width);
          out.stored = JSON.parse(localStorage.getItem('dbfixlog-report-widths'));
          z.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
          out.reset = wrap.style.getPropertyValue('--cols');
          out.kept = drag(100);
        """)
        self.assertTrue(out["start"].startswith("96px 200px 96px"), out["start"])
        self.assertTrue(out["dragged"].startswith("96px 260px 96px"), out["dragged"])
        self.assertEqual(out["cellWidth"], 260)
        self.assertEqual(out["stored"][:3], [96, 260, 96])
        self.assertTrue(out["reset"].startswith("96px 200px 96px"), out["reset"])
        self.assertTrue(out["kept"].startswith("96px 300px"), out["kept"])
        again = self.probe(report, """
          out.cols = document.querySelector('.listwrap').style.getPropertyValue('--cols');
          localStorage.removeItem('dbfixlog-report-widths');
        """)
        self.assertTrue(again["cols"].startswith("96px 300px"), again["cols"])

    def test_wide_columns_scroll_sideways_with_header_and_sticky_rows(self):
        out = self.probe(self.long_report("hscroll"), self.STICKY_JS + """
          R.list.setWidths([96, 200, 96, 64, 110, 150, 130, 3000]);
          at(30);
          el.scrollLeft = 500; R.list.draw();
          out.left = el.scrollLeft;
          out.head = document.querySelector('.lhead .grid').style.transform;
          out.stick = document.querySelector('.stick .sinner').style.transform;
        """)
        self.assertEqual(out["left"], 500)
        self.assertEqual(out["head"], "translateX(-500px)")
        self.assertEqual(out["stick"], "translateX(-500px)")


if __name__ == "__main__":
    unittest.main()

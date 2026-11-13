"""Headless Firefox checks for the details panel, column resizing, horizontal
scroll, sticky Scopes and the fold buttons."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browser_report import (  # noqa: E402
    END, START, FirefoxCase, change, msg, skip_without_browser)

WIDTHS_KEY = "dbfixlog-report-widths"


def long_records():
    """1 phase{ 2 customer{ 3..62 changes } 63 end, 64 customer{ 65..124 } 125 end } 126 end,
    127 phase{ 128 message } 129 end. Tree rows: 1, 2, 3..62, 64, 65..124, 127, 128."""
    recs = [START("dry"), msg("scope_start", id=1, kind="orphan-check")]
    for sid, cid in ((2, 42), (3, 43)):
        recs.append(msg("scope_start", id=sid, kind="customer", key={"id": cid}, scope=[1]))
        recs += [change("planned", key={"id": n}, scope=[1, sid]) for n in range(60)]
        recs.append(msg("scope_end", id=sid, outcome="ok", duration_ms=1, scope=[1]))
    recs += [msg("scope_end", id=1, outcome="ok", duration_ms=2),
             msg("scope_start", id=4, kind="report"), msg("message", msg="done", scope=[4]),
             msg("scope_end", id=4, outcome="ok", duration_ms=1), END]
    return recs


# Scroll so list row k is on top; return the pinned Scope ids, their text and the record
# index of the first list row the pinned rows do not cover.
STICKY_JS = """
  const el = $('.list');
  const at = async (k) => {
    el.scrollTop = k * 24;
    await frame(); await frame();
    const sids = q('.stick [data-sid]').map((r) => Number(r.dataset.sid));
    const top = (Math.floor(el.scrollTop / 24) + sids.length) * 24 + 'px';
    const first = listRows().find((r) => r.style.top === top);
    return {top: el.scrollTop, sids: sids, first: first ? Number(first.dataset.i) : null,
            text: texts('.stick .vr')};
  };
"""


@skip_without_browser
class DetailsPanelInFirefox(FirefoxCase):
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
          const panel = $('.panel');
          out.closedAtStart = panel.hidden;
          row(3).lastElementChild.click();
          out.open = !panel.hidden;
          out.selected = row(3).classList.contains('sel');
          out.text = panel.textContent;
          out.fchanges = q('.fchanges tbody tr', panel).map((tr) => texts('td', tr).join('|'));
          out.raw = JSON.parse($('pre.raw', panel).textContent);
          out.crumb = texts('.crumb [data-reveal]', panel);
          row(4).lastElementChild.click();
          out.traceback = $('pre.tb', panel).textContent;
          out.fields = texts('.fieldtab td', panel);
          $('.close', panel).click();
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
          const panel = $('.panel');
          row(2).lastElementChild.click();
          out.text = panel.textContent;
          out.totals = q('.totals tr', panel).map((tr) => texts('td', tr).join('|'));
          out.only = q('a[data-q]', panel).map((a) => a.textContent);
          out.traceback = $('pre.tb', panel).textContent;
          row(5).lastElementChild.click();
          out.endTraceback = $('pre.tb', panel).textContent;
        """)
        self.assertIn("customer ACME", out["text"])
        self.assertIn("scope error", out["text"])
        # change + message; the raising scope_end sits at the parent's level
        self.assertEqual(out["totals"], ["records|2", "planned|1", "applied|0", "failed|0", "Findings|0"])
        self.assertEqual(out["only"], ["show only this Scope"])
        self.assertIn("TB-OF-SCOPE", out["traceback"])
        self.assertIn("TB-OF-SCOPE", out["endTraceback"])

    def test_scope_path_click_reveals_scope_in_tree(self):
        out = self.probe(self.panel_report(), """
          const panel = $('.panel');
          row(3).lastElementChild.click();
          fold(1);  // the record is now hidden under phase 1
          out.hidden = !row(2);
          q('.crumb [data-reveal]', panel)[1].click();  // customer ACME
          out.expanded = $('[data-fold="1"]', row(1)).title;
          out.shown = !!row(2);
          out.selected = !!row(2) && row(2).classList.contains('sel');
          out.title = $('h3', panel).textContent;
          q('a[data-q]', panel)[0].click();  // "show only this Scope"
          out.query = searchBox().value;
          out.filtered = ids();
          mode('flat');
          q('.crumb [data-reveal]', panel)[0].click();  // reveal switches back to Tree ...
          out.treeOn = $('[data-mode="tree"]').classList.contains('on');  // ... and the switch follows
          out.flatOn = $('[data-mode="flat"]').classList.contains('on');
          out.treeRows = ids();
        """)
        self.assertTrue(out["hidden"])
        self.assertEqual(out["expanded"], "fold")
        self.assertTrue(out["shown"])
        self.assertTrue(out["selected"])
        self.assertIn("customer ACME", out["title"])
        self.assertEqual(out["query"], "in:2")
        self.assertEqual(out["filtered"], [1, 2, 3, 4, 5])  # phase 1 kept as an enclosing Scope
        self.assertEqual([out["treeOn"], out["flatOn"]], [True, False])

    def test_sticky_scopes_match_enclosing_scopes_and_jump(self):
        recs = long_records()
        out = self.probe(self.render("sticky", recs), STICKY_JS + """
          out.top = await at(0); out.mid = await at(30); out.edge = await at(61); out.second = await at(100);
          q('.stick [data-sid="3"]')[0].click();
          out.jumpTop = el.scrollTop;
          out.jumpRow = !!row(64);
          mode('flat'); out.flat = await at(30); mode('tree');
        """)
        under = lambda page: recs[page["first"]].get("scope", [])
        self.assertEqual(out["top"]["sids"], [])
        self.assertEqual(out["mid"]["sids"], [1, 2])
        self.assertEqual(under(out["mid"]), [1, 2])
        self.assertIn("orphan-check", out["mid"]["text"][0])
        self.assertIn("id=42", out["mid"]["text"][1])
        self.assertEqual(out["edge"]["sids"], [1])  # the next row is customer 43's header
        self.assertEqual(out["second"]["sids"], [1, 3])
        self.assertEqual(under(out["second"]), [1, 3])
        self.assertEqual(out["jumpTop"], 61 * 24)  # customer 43's header right below phase 1
        self.assertTrue(out["jumpRow"])
        self.assertEqual(out["flat"]["sids"], [])

    def test_fold_buttons(self):
        out = self.probe(self.render("fold", long_records()), """
          const click = (how) => { $('[data-foldall="' + how + '"]').click(); return ids(); };
          out.phases = click('phases');
          out.all = click('all');
          out.none = click('none').slice(0, 4);
          out.inBar = !!$('#bar .fold-slot [data-foldall="all"]');
          mode('flat'); out.hiddenInFlat = $('.fold-slot').hidden;
          mode('tree'); out.shownInTree = !$('.fold-slot').hidden;
        """)
        # Fold to phases keeps phases open, their entity Scopes folded.
        self.assertEqual(out["phases"], [1, 2, 64, 127, 128])
        self.assertEqual(out["all"], [1, 127])
        self.assertEqual(out["none"], [1, 2, 3, 4])
        self.assertTrue(out["inBar"])
        self.assertTrue(out["hiddenInFlat"])
        self.assertTrue(out["shownInTree"])

    def test_a_folded_scope_hides_its_rows_and_its_caret_unfolds_it(self):
        out = self.probe(self.render("caret", long_records()), """
          fold(2); out.folded = ids().slice(0, 4);
          fold(2); out.open = ids().slice(0, 4);
        """)
        self.assertEqual(out["folded"], [1, 2, 64, 65])
        self.assertEqual(out["open"], [1, 2, 3, 4])

    def test_resize_remembers_widths_and_double_click_resets(self):
        report = self.render("resize", long_records())
        out = self.probe(report, """
          const wrap = $('.listwrap');
          const z = $('.hc[data-col="1"] .rz');
          const drag = (dx) => {
            z.dispatchEvent(new PointerEvent('pointerdown', {clientX: 100, bubbles: true}));
            window.dispatchEvent(new PointerEvent('pointermove', {clientX: 100 + dx, bubbles: true}));
            window.dispatchEvent(new PointerEvent('pointerup', {clientX: 100 + dx, bubbles: true}));
            return wrap.style.getPropertyValue('--cols');
          };
          out.start = wrap.style.getPropertyValue('--cols');
          out.dragged = drag(60);
          out.cellWidth = Math.round($('.lhead .hc[data-col="1"]').getBoundingClientRect().width);
          z.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
          out.reset = wrap.style.getPropertyValue('--cols');
          out.kept = drag(100);
        """)
        self.assertTrue(out["start"].startswith("96px 200px 96px"), out["start"])
        self.assertTrue(out["dragged"].startswith("96px 260px 96px"), out["dragged"])
        self.assertEqual(out["cellWidth"], 260)
        self.assertTrue(out["reset"].startswith("96px 200px 96px"), out["reset"])
        self.assertTrue(out["kept"].startswith("96px 300px"), out["kept"])
        # A fresh load of the Report remembers the last widths.
        again = self.probe(report, """
          out.cols = $('.listwrap').style.getPropertyValue('--cols');
          localStorage.removeItem('%s');
        """ % WIDTHS_KEY)
        self.assertTrue(again["cols"].startswith("96px 300px"), again["cols"])

    def test_bad_remembered_widths_fall_back_to_the_defaults(self):
        report = self.render("badwidths", long_records())
        for bad in ("[1,2]", "nope", '[1,2,3,4,5,6,7,"x"]'):
            with self.subTest(stored=bad):
                self.probe(report, "localStorage.setItem(%r, %r);" % (WIDTHS_KEY, bad))
                out = self.probe(report, """
                  out.cols = $('.listwrap').style.getPropertyValue('--cols');
                  localStorage.removeItem(%r);
                """ % WIDTHS_KEY)
                self.assertTrue(out["cols"].startswith("96px 200px 96px 64px"), out["cols"])

    def test_wide_columns_scroll_sideways_with_header_and_sticky_rows(self):
        report = self.render("hscroll", long_records())
        self.probe(report, "localStorage.setItem(%r, '[96,200,96,64,110,150,130,3000]');" % WIDTHS_KEY)
        out = self.probe(report, STICKY_JS + """
          await at(30);
          el.scrollLeft = 500;
          await frame(); await frame();
          out.left = el.scrollLeft;
          out.head = $('.lhead .grid').style.transform;
          out.stick = $('.stick .sinner').style.transform;
          localStorage.removeItem(%r);
        """ % WIDTHS_KEY)
        self.assertEqual(out["left"], 500)
        self.assertEqual(out["head"], "translateX(-500px)")
        self.assertEqual(out["stick"], "translateX(-500px)")


if __name__ == "__main__":
    unittest.main()

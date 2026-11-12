"""Headless Firefox checks for the summary cards, and that clicking a card
number filters the list.

Reuses the Firefox lifecycle and probe helper of test_report_details_browser (without
re-running its tests).
"""
import os
import unittest

import test_report_browser as base
import test_report_details_browser as details
from test_report_browser import START, END, msg, change

_FF = base.StubReportInFirefox.__dict__  # not the classes themselves: unittest would collect them
_DP = details.DetailsPanelInFirefox.__dict__


@unittest.skipIf(os.environ.get("DBFIXLOG_SKIP_BROWSER"), "DBFIXLOG_SKIP_BROWSER set")
@unittest.skipUnless(base.FIREFOX and base.NODE, "needs firefox and node on PATH")
class SummaryCardsInFirefox(unittest.TestCase):
    setUpClass = _FF["setUpClass"]
    tearDownClass = _FF["tearDownClass"]
    _wait_for_bidi = _FF["_wait_for_bidi"]
    render = _DP["render"]
    probe = _DP["probe"]

    # 0 start, 1 phase{ 2 customer{ 3 planned, 4 applied, 5 finding }, 6 customer{ unfinished
    # 7 failed }, ... no run_end
    def cards_report(self):
        return self.render("cards", [
            START("dry"),
            msg("scope_start", id=1, kind="orphan-check"),
            msg("scope_start", id=2, kind="customer", key={"id": 42}, scope=[1]),
            change("planned", scope=[1, 2]),
            change("applied", scope=[1, 2], table="customers"),
            msg("finding", level="WARNING", check="no-lines", table="orders", key={"id": 1}, scope=[1, 2]),
            msg("scope_end", id=2, outcome="ok", duration_ms=3, scope=[1]),
            msg("scope_start", id=3, kind="customer", key={"id": 43}, scope=[1]),
            change("failed", level="ERROR", error={"type": "E", "message": "x"}, scope=[1, 3]),
        ])

    def test_cards_show_counts_and_red_dry_run_numbers(self):
        out = self.probe(self.cards_report(), """
          const cards = document.querySelector('#cards details.cards');
          out.open = cards.open;
          out.titles = texts('.card h4', cards);
          out.red = q('a.cn.red', cards).map((a) => [a.textContent, a.dataset.q]);
          out.unfinished = q('[data-card=scopes] a.cn', cards).map((a) => [a.textContent, a.dataset.q]);
          const color = (a) => getComputedStyle(a).color;
          out.redColor = color(q('a.cn.red', cards)[0]);
          out.plainColor = color(q('a.cn:not(.red)', cards)[0]);
        """)
        self.assertTrue(out["open"])
        self.assertEqual(out["titles"], ["Changes", "Findings", "Scopes"])
        self.assertIn(["1", "type:change table:customers op:update status:applied"], out["red"])
        self.assertIn(["1", "type:change table:orders op:update status:failed"], out["red"])
        self.assertIn(["1", "type:change status:applied"], out["red"])
        self.assertIn(["1", "is:unfinished kind:customer"], out["unfinished"])
        self.assertNotEqual(out["redColor"], out["plainColor"])

    def test_clicking_a_number_filters_the_list(self):
        out = self.probe(self.cards_report(), """
          const rows = () => q('.vr').map((r) => r.dataset.i);
          out.before = rows();
          const a = (sel) => document.querySelector('#cards a.cn[data-q="' + sel + '"]');
          a('type:change status:applied').click();
          out.search = document.querySelector('#bar input[type=search]').value;
          out.applied = rows();
          out.count = document.querySelector('#bar .fcount').textContent;
          a('is:unfinished kind:customer').click();
          out.unfinished = rows();
          out.state = R.filter.get();
        """)
        self.assertEqual(out["before"], ["1", "2", "3", "4", "5", "7", "8"])
        self.assertEqual(out["search"], "type:change status:applied")
        # tree mode: the applied Change plus the Scopes that enclose it
        self.assertEqual(out["applied"], ["1", "2", "4"])
        self.assertIn("1 matching", out["count"])
        self.assertEqual(out["unfinished"], ["1", "7"])
        self.assertEqual(out["state"]["q"], "is:unfinished kind:customer")


if __name__ == "__main__":
    unittest.main()

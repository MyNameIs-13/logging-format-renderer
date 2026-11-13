"""Headless Firefox checks for the summary cards: their counts, and that clicking a
number lists exactly what it counts."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browser_report import (  # noqa: E402
    END, START, FirefoxCase, msg, skip_without_browser)


def ch(table, op, status, **extra):
    r = msg("change", table=table, op=op, status=status, key={"id": 1})
    if op == "update":
        r["changes"] = {"a": {"old": 1, "new": 2}}
    r.update(extra)
    return r


def fd(check, level, **extra):
    r = msg("finding", check=check, level=level, table="orders", key={"id": 1}, msg="m")
    r.update(extra)
    return r


# Each card's body rows (cells joined by "|"), and every clickable number as
# [text, red?, the query its click puts in the search box].
CARDS = """
  out.cards = {};
  for (const c of q('#cards .card')) {
    out.cards[$('h4', c).textContent] = q('tr', c).slice(1).map((tr) => texts('td', tr).join('|'));
  }
  out.links = [];
  for (const a of q('#cards a.cn')) {
    a.click();
    out.links.push([a.textContent, a.classList.contains('red'), searchBox().value]);
  }
  out.open = !!$('#cards details.cards[open]');
"""


@skip_without_browser
class SummaryCardsInFirefox(FirefoxCase):
    def cards(self, name, mode, body, ended=True):
        recs = [START(mode)] + body + ([END] if ended else [])
        return self.probe(self.render(name, recs), CARDS)

    def test_changes_are_counted_per_table_and_op_by_status(self):
        out = self.cards("changes", "dry", [
            ch("orders", "update", "planned"), ch("orders", "update", "planned"),
            ch("orders", "delete", "applied"),
            ch("customers", "insert", "failed", level="ERROR"),
            ch("orders", "update", "failed", level="ERROR")])
        self.assertTrue(out["open"])
        # table, op, planned, applied, failed, all; sorted by table, then update/insert/delete
        self.assertEqual(out["cards"]["Changes"], [
            "customers|insert|0|0|1|1",
            "orders|update|2|0|1|3",
            "|delete|0|1|0|1",
            "all||2|1|2|5",
        ])

    def test_findings_are_counted_per_check_and_level(self):
        out = self.cards("findings", "write", [
            fd("no-lines", "WARNING"), fd("no-lines", "WARNING"), fd("no-lines", "ERROR"),
            fd("dup", "INFO")])
        # Only levels that occur get a column: info, warning, error, then all.
        self.assertEqual(out["cards"]["Findings"], ["dup|1|0|0|1", "no-lines|0|2|1|3"])

    def test_scopes_are_counted_per_kind_in_first_seen_order(self):
        out = self.cards("scopes", "dry", [
            msg("scope_start", id=1, kind="phase"),
            msg("scope_start", id=2, kind="customer", key={"id": 1}, scope=[1]),
            msg("scope_end", id=2, outcome="error", level="ERROR", scope=[1],
                exc={"type": "E", "message": "x"}),
            msg("scope_start", id=3, kind="customer", key={"id": 2}, scope=[1]),
            msg("scope_end", id=3, outcome="ok", scope=[1]),
            msg("scope_start", id=4, kind="customer", key={"id": 3}, scope=[1])], ended=False)
        # kind, Scopes, error, unfinished
        self.assertEqual(out["cards"]["Scopes"], ["phase|1|0|1", "customer|3|1|1"])

    def test_change_numbers_carry_queries_and_are_red_in_a_dry_run(self):
        out = self.cards("dry_links", "dry", [
            ch("orders", "update", "planned"), ch("orders", "update", "applied"),
            ch("orders", "delete", "planned")])
        self.assertEqual(out["links"], [
            ["1", False, "type:change table:orders op:update status:planned"],
            ["1", True, "type:change table:orders op:update status:applied"],
            ["2", False, "type:change table:orders op:update"],
            ["1", False, "type:change table:orders op:delete status:planned"],
            ["1", False, "type:change table:orders op:delete"],
            ["2", False, "type:change status:planned"],
            ["1", True, "type:change status:applied"],
            ["3", False, "type:change"],
        ])

    def test_in_a_write_run_only_failed_is_red_and_zeros_are_not_links(self):
        out = self.cards("write_links", "write", [
            ch("orders", "update", "applied"), ch("orders", "update", "failed", level="ERROR")])
        per_row = [l for l in out["links"] if " status:" in l[2] and "table:" in l[2]]
        self.assertEqual(per_row, [
            ["1", False, "type:change table:orders op:update status:applied"],
            ["1", True, "type:change table:orders op:update status:failed"],
        ])
        self.assertNotIn("status:planned", " ".join(l[2] for l in out["links"]))

    def test_finding_and_scope_numbers_carry_their_queries(self):
        out = self.cards("other_links", "dry", [
            fd("no-lines", "WARNING"), fd("no lines 2", "ERROR"),
            msg("scope_start", id=1, kind="customer", key={"id": 1}),
            msg("scope_end", id=1, outcome="error", level="ERROR", exc={"type": "E", "message": "x"}),
            msg("scope_start", id=2, kind="customer", key={"id": 2})], ended=False)
        self.assertEqual([l for l in out["links"] if not l[2].startswith("type:change")], [
            ["1", True, 'check:"no lines 2" level:error'],
            ["1", False, 'check:"no lines 2"'],
            ["1", False, "check:no-lines level:warning"],
            ["1", False, "check:no-lines"],
            ["2", False, "type:scope_start kind:customer"],
            ["1", True, "type:scope_end kind:customer"],
            ["1", False, "is:unfinished kind:customer"],
        ])

    def test_each_number_lists_exactly_what_it_counts_in_flat_and_tree_mode(self):
        recs = [
            START("dry"),
            msg("scope_start", id=1, kind="orphan-check"),
            msg("scope_start", id=2, kind="customer", key={"id": 42}, label={"name": "ACME"}, scope=[1]),
            msg("scope_start", id=4, kind="orphan-check", msg="nested phase", scope=[1, 2]),
            msg("scope_end", id=4, outcome="error", level="ERROR", scope=[1, 2], exc={"type": "E", "message": "y"}),
            fd("no-lines", "WARNING"), fd("no-lines", "ERROR", scope=[1, 2]),
            ch("orders", "update", "planned", scope=[1, 2]),
            ch("orders", "delete", "applied", scope=[1, 2]),
            ch("shop.orders", "delete", "planned"),
            ch("customers", "update", "failed", level="ERROR"),
            msg("scope_end", id=2, outcome="error", level="ERROR", scope=[1], exc={"type": "E", "message": "x"}),
            msg("scope_start", id=3, kind="customer", key={"id": 43}, scope=[1]),
            msg("message", msg="working", scope=[1, 3]),
        ]
        out = self.probe(self.render("exact", recs), """
          out.checks = [];
          for (const m of ['flat', 'tree']) {
            mode(m);
            for (const a of q('#cards a.cn')) {
              a.click();
              out.checks.push([m, a.textContent, searchBox().value, count()]);
            }
          }
        """)
        self.assertGreater(len(out["checks"]), 30)
        for m, number, query, shown in out["checks"]:
            self.assertTrue(shown.startswith(number + " matching"), (m, query, number, shown))

    def test_a_run_without_changes_findings_or_scopes_gets_no_cards(self):
        out = self.probe(self.render("nocards", [START("dry"), msg("message", msg="hi"), END]),
                         "out.cards = q('#cards *').length;")
        self.assertEqual(out["cards"], 0)


if __name__ == "__main__":
    unittest.main()

"""Headless Firefox checks for what the Report derives from the records: the Scope
tree and its totals, outcomes, status/mode warnings, odd records and the columns."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browser_report import (  # noqa: E402
    END, START, FirefoxCase, msg, skip_without_browser)

COLS = ["Time", "Scope", "Status", "Op", "Table", "Key", "Label", "Details"]


def nested(mode, status="planned"):
    """run_start, phase 1 { customer 2 { finding, delete, planned update }, message },
    outside message, run_end."""
    return [
        START(mode),
        msg("scope_start", id=1, kind="orphan-check", msg="pass 1"),                         # 1
        msg("scope_start", id=2, kind="customer", key={"id": 42}, label={"name": "ACME"}, scope=[1]),
        msg("finding", level="WARNING", check="no-lines", table="orders", key={"id": 156}, scope=[1, 2]),
        msg("change", op="delete", table="orders", key={"id": 156}, status=status, scope=[1, 2]),  # 4
        msg("change", op="update", table="customers", key={"id": 42}, status="planned",
            changes={"note": {"old": None, "new": "x"}}, scope=[1, 2]),                       # 5
        msg("scope_end", id=2, outcome="ok", duration_ms=40, scope=[1]),                      # 6
        msg("message", msg="pass done", scope=[1]),                                           # 7
        msg("scope_end", id=1, outcome="ok", duration_ms=120),                                # 8
        msg("message", msg="outside"),                                                        # 9
        END,
    ]


# Every rendered row as {i, cells: {column: text}, cls}, for Tree and Flat mode.
ROWS = """
  const grab = () => listRows().map((r) => {
    const c = {}; Array.from(r.children).forEach((e, k) => { c[%r[k]] = e.textContent; });
    return {i: Number(r.dataset.i), cells: c, cls: r.className};
  });
  mode('tree'); out.tree = grab();
  mode('flat'); out.flat = grab();
  mode('tree');
  out.notices = notices().map((n) => n.text);
  out.facts = q('.runhead .facts tr').map((tr) => texts('td', tr).join('|'));
""" % COLS


def by_index(rows):
    return {r["i"]: r for r in rows}


@skip_without_browser
class ModelInFirefox(FirefoxCase):
    def page(self, name, records):
        return self.probe(self.render(name, records), ROWS)

    def test_tree_rows_follow_the_scope_paths_in_file_order(self):
        out = self.page("tree", nested("dry"))
        # Scope headers are their scope_start rows; ok scope_ends, run_start and run_end are not rows.
        self.assertEqual([r["i"] for r in out["tree"]], [1, 2, 3, 4, 5, 7, 9])
        self.assertEqual([r["i"] for r in out["flat"]], [1, 2, 3, 4, 5, 7, 9])
        tree = by_index(out["tree"])
        self.assertIn("orphan-check", tree[1]["cells"]["Scope"])
        self.assertIn("customer", tree[2]["cells"]["Scope"])
        self.assertEqual(by_index(out["flat"])[4]["cells"]["Scope"], "orphan-check › customer ACME")

    def test_folding_a_scope_hides_its_contents(self):
        out = self.probe(self.render("folding", nested("dry")), """
          fold(2); out.two = ids(); fold(2);
          fold(1); out.one = ids(); fold(1);
        """)
        self.assertEqual(out["two"], [1, 2, 7, 9])
        self.assertEqual(out["one"], [1, 9])

    def test_scope_totals_cover_every_record_inside_nested_scopes_included(self):
        tree = by_index(self.page("totals", nested("write", "applied"))["tree"])
        self.assertEqual(tree[2]["cells"]["Details"],
                         "3 records · 1 planned · 1 applied · 1 Finding · 40 ms")
        # Scope 1 also holds its own "pass done" message; Scope headers are not counted.
        self.assertEqual(tree[1]["cells"]["Details"],
                         "pass 1 · 4 records · 1 planned · 1 applied · 1 Finding · 120 ms")
        self.assertEqual(tree[1]["cells"]["Key"], "phase")

    def test_columns_for_a_change_a_finding_and_a_scope_header(self):
        tree = by_index(self.page("columns", nested("dry", "applied"))["tree"])
        c = tree[4]["cells"]
        self.assertEqual(c["Time"], "20:01:00.000")
        self.assertEqual(c["Status"], "applied ⚠")
        self.assertEqual([c["Op"], c["Table"], c["Key"]], ["delete", "orders", "id=156"])
        self.assertEqual(tree[5]["cells"]["Details"], "note: NULL → x")
        h = tree[2]["cells"]
        self.assertEqual([h["Status"], h["Key"], h["Label"]], ["", "id=42", "ACME"])
        self.assertEqual(tree[3]["cells"]["Status"], "warning")
        self.assertIn("no-lines", tree[3]["cells"]["Details"])

    def test_a_crash_leaves_the_run_and_its_open_scopes_unfinished(self):
        out = self.page("crash", nested("dry")[:6])
        tree = by_index(out["tree"])
        self.assertEqual(tree[1]["cells"]["Status"], "unfinished")
        self.assertEqual(tree[2]["cells"]["Status"], "unfinished")
        self.assertIn("outcome|unfinished", out["facts"])
        # An unfinished Scope closes at the last record in the file and has no duration.
        self.assertEqual(tree[2]["cells"]["Details"], "3 records · 2 planned · 1 Finding")

    def test_finished_run_and_scopes_report_their_outcomes(self):
        recs = nested("dry")
        recs[6] = msg("scope_end", id=2, outcome="error", duration_ms=40, scope=[1], level="ERROR",
                      exc={"type": "ValueError", "message": "bad", "traceback": "tb"})
        out = self.page("outcomes", recs)
        tree = by_index(out["tree"])
        self.assertEqual(tree[2]["cells"]["Status"], "scope error")
        self.assertEqual(tree[6]["cells"]["Status"], "scope error")
        self.assertIn("ValueError: bad", tree[6]["cells"]["Details"])
        self.assertEqual([r["i"] for r in out["tree"]], [1, 2, 3, 4, 5, 6, 7, 9])
        self.assertIn("outcome|ok", out["facts"])
        self.assertIn("duration|1 min 0 s", out["facts"])

    def test_status_that_does_not_fit_the_mode_is_a_warning(self):
        report_dry = self.render("warn_dry", nested("dry", "applied"))
        report_failed = self.render("warn_failed", nested("dry", "failed"))
        report_write = self.render("warn_write", nested("write", "applied"))
        warn = "out.rows = filtered('is:warn');"
        self.assertEqual(self.probe(report_dry, warn)["rows"], [4])  # never the Finding
        self.assertEqual(self.probe(report_failed, warn)["rows"], [4])
        self.assertEqual(self.probe(report_write, warn)["rows"], [5])  # the planned update
        page = self.probe(report_write, """
          row(5).lastElementChild.click();
          out.panel = $('.panel').textContent;
        """)
        self.assertIn('⚠ status "planned" in a Write Run', page["panel"])

    def test_an_unknown_record_type_is_a_generic_row(self):
        recs = nested("dry")
        recs.insert(9, msg("heartbeat", level="DEBUG", msg="tick", fields={"n": 1}, scope=[1]))
        tree = by_index(self.page("unknown", recs)["tree"])
        self.assertEqual(tree[9]["cells"]["Status"], "debug")
        self.assertEqual(tree[9]["cells"]["Details"], "heartbeat: tick n=1")
        self.assertIn("dbg", tree[9]["cls"].split())
        self.assertTrue(tree[1]["cells"]["Details"].startswith("pass 1 · 5 records"))

    def test_known_types_with_missing_or_odd_fields_are_shown_with_a_warning(self):
        recs = nested("dry")
        recs[9:9] = [
            msg("change", table="orders", key={"id": 1}),                                # no op, no status
            msg("finding", level="WARNING", msg="no rule name"),                         # no check
            msg("change", op="merge", table="orders", key=7, status="done"),
        ]
        out = self.probe(self.render("odd", recs), ROWS + """
          const reasons = (i) => { row(i).lastElementChild.click(); return $('.panel').textContent; };
          out.why = [9, 10, 11, 4, 3].map(reasons);
        """)
        tree = by_index(out["tree"])
        self.assertEqual(tree[9]["cells"]["Status"], "no status ⚠")
        self.assertEqual(tree[10]["cells"]["Status"], "warning ⚠")
        self.assertNotIn("undefined", tree[10]["cells"]["Details"])
        self.assertEqual(tree[11]["cells"]["Status"], "done ⚠")
        self.assertIn("no op", out["why"][0])
        self.assertIn("no status", out["why"][0])
        self.assertIn("no check", out["why"][1])
        self.assertIn('op "merge"', out["why"][2])
        self.assertIn('status "done"', out["why"][2])
        self.assertIn("key is not a {column: value} object", out["why"][2])
        self.assertNotIn("⚠", out["why"][3])  # a valid Change
        self.assertNotIn("⚠", out["why"][4])  # a valid Finding
        [n] = [t for t in out["notices"] if "odd fields" in t]
        self.assertTrue(n.startswith("3 records have missing or odd fields (lines 10, 11, 12)"), n)

    def test_a_valid_run_has_no_odd_fields_notice(self):
        out = self.page("valid", nested("write", "applied"))
        self.assertFalse(any("odd fields" in t for t in out["notices"]))
        self.assertFalse(any("⚠" in r["cells"]["Status"] for r in out["tree"] if r["i"] != 5))


if __name__ == "__main__":
    unittest.main()

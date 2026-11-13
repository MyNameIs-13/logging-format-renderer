"""Headless Firefox checks for search, views and the Scope-header pruning rule, driven
through the filter bar. Rows are identified by their record index (the row's data-i,
which the list uses to open the details panel)."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browser_report import (  # noqa: E402
    END, START, FirefoxCase, msg, skip_without_browser)


def rec(type_, **extra):
    return msg(type_, **extra)


#  1 message "connected" (outside, DEBUG, 20:01:00)
#  2 scope_start 1 phase "orphan-check" msg "pass 1"
#  3   scope_start 2 customer key id=42 label ACME
#  4     finding WARNING check no-lines table orders key id=156 (20:02:10)
#  5     change delete orders id=156 planned
#  6     change update customers id=42 failed, changes note null -> "x", ERROR (20:03:30)
#  7   scope_end 2 ok
#  8   scope_start 3 customer key id=43 label Globex
#  9     message "nothing to do" fields {city: "Gent"}
# 10   scope_end 3 error (raised) ERROR
# 11   scope_start 4 customer key id=44 label Initech   (empty)
# 12   scope_end 4 ok
# 13 scope_end 1 ok
# 14 message "done" logger "other"
def fixture():
    return [
        START("dry"),
        rec("message", level="DEBUG", msg="connected", ts="2026-11-12T20:01:00.000Z"),
        rec("scope_start", id=1, kind="orphan-check", msg="pass 1"),
        rec("scope_start", id=2, kind="customer", key={"id": 42}, label={"name": "ACME"}, scope=[1]),
        rec("finding", level="WARNING", check="no-lines", table="orders", key={"id": 156}, scope=[1, 2],
            ts="2026-11-12T20:02:10.000Z"),
        rec("change", op="delete", table="orders", key={"id": 156}, status="planned", scope=[1, 2]),
        rec("change", op="update", table="customers", key={"id": 42}, status="failed", level="ERROR",
            changes={"note": {"old": None, "new": "x"}}, error={"type": "E", "message": "boom"},
            scope=[1, 2], ts="2026-11-12T20:03:30.000Z"),
        rec("scope_end", id=2, outcome="ok", duration_ms=4, scope=[1]),
        rec("scope_start", id=3, kind="customer", key={"id": 43}, label={"name": "Globex"}, scope=[1]),
        rec("message", msg="nothing to do", fields={"city": "Gent"}, scope=[1, 3]),
        rec("scope_end", id=3, outcome="error", level="ERROR", duration_ms=2, scope=[1],
            exc={"type": "ValueError", "message": "bad", "traceback": "tb"}),
        rec("scope_start", id=4, kind="customer", key={"id": 44}, label={"name": "Initech"}, scope=[1]),
        rec("scope_end", id=4, outcome="ok", duration_ms=1, scope=[1]),
        rec("scope_end", id=1, outcome="ok", duration_ms=9),
        rec("message", msg="done", logger="other"),
        END,
    ]


@skip_without_browser
class FilterInFirefox(FirefoxCase):
    @classmethod
    def setUpClass(cls):
        FirefoxCase.setUpClass()
        cls.report = None

    def fixture_report(self):
        if type(self).report is None:
            type(self).report = self.render("filter", fixture())
        return type(self).report

    def rows(self, cases, report=None):
        """The list rows for each [query, options] case (options: view, level, mode)."""
        out = self.probe(report or self.fixture_report(),
                         "const cases = %s; out.rows = cases.map(([t, o]) => filtered(t, o));"
                         % json.dumps(cases))
        return out["rows"]

    def check(self, expected, mode="flat", report=None):
        """``expected`` maps a query, or (query, option, value) for a view or level, to
        the expected rows."""
        cases = [[k, {"mode": mode}] if isinstance(k, str) else [k[0], {k[1]: k[2], "mode": mode}]
                 for k in expected]
        got = self.rows(cases, report)
        for (k, want), have in zip(expected.items(), got):
            self.assertEqual(have, want, k)

    def test_plain_words_match_the_records_own_text(self):
        self.check({"boom": [6], "NOTHING to": [9]})

    def test_plain_words_also_match_the_enclosing_scopes(self):
        self.check({
            "acme": [3, 4, 5, 6],
            "acme status:failed": [6],
            # Each word may match the record or any enclosing Scope.
            "acme orders": [4, 5],
            "orphan-check boom": [6],
        })

    def test_level_terms(self):
        # A raising Scope's header counts as an error.
        self.check({
            "level>=warning": [4, 6, 8, 10],
            "level>=warn": [4, 6, 8, 10],
            "level:error": [6, 8, 10],
            "level:warning,debug": [1, 4],
            "level:info": [2, 3, 5, 9, 11, 14],
        })

    def test_type_table_op_status_check_logger_terms(self):
        self.check({
            "type:change,finding": [4, 5, 6],
            "type:scope": [2, 3, 8, 10, 11],
            "table:orders": [4, 5],
            "table:ORDERS,customers": [4, 5, 6],
            "op:update": [6],
            "status:planned": [5],
            "check:no-lines": [4],
            "logger:other": [14],
            "logger:fix": [1, 2, 3, 4, 5, 6, 8, 9, 10, 11],
        })

    def test_table_matches_the_table_field_exactly_ignoring_case(self):
        report = self.render("schema_table", [
            START("dry"), rec("change", op="delete", table="shop.orders", key={"id": 1}, status="planned"), END])
        self.check({"table:orders": [], "table:Shop.Orders": [1]}, report=report)

    def test_key_kind_and_in_include_the_enclosing_scopes(self):
        self.check({
            "key:156": [4, 5],
            "key:42": [3, 4, 5, 6],
            "key:id=43": [8, 9, 10],
            "kind:customer": [3, 4, 5, 6, 8, 9, 10, 11],
            # A Scope's own header and end records match on its own kind only.
            "kind:orphan-check": [2, 4, 5, 6, 9],
            "in:2": [3, 4, 5, 6],
            "in:3": [8, 9, 10],
            "in:2,4": [3, 4, 5, 6, 11],
            "type:scope_end kind:customer": [10],
        })

    def test_after_and_before_compare_utc_time_at_the_given_precision(self):
        self.check({
            "after:20:02": [4, 6],
            "before:20:01": [1, 2, 3, 5, 8, 9, 10, 11, 14],
            "after:20:02:10 before:20:02:10": [4],
            "after:20:03:30.001": [],
        })

    def test_field_terms_match_fields_and_changed_values(self):
        self.check({
            "f.city=gent": [9],
            "f.note=null": [6],
            "f.note=x": [6],
            "f.note=y": [],
            "f.city=gen": [],  # equality, not substring
        })

    def test_is_warn_and_is_unfinished(self):
        self.check({"is:warn": [6], "is:unfinished": []})  # 6: failed in a Dry Run

    def test_quotes_group_words_and_unknown_terms_are_plain_words(self):
        self.check({
            '"nothing to"': [9],
            '"to nothing"': [],
            "foo:bar": [],
            "level>=loud": [],
            "connected": [1],
        })

    def test_without_a_filter_every_row_shows(self):
        out = self.probe(self.fixture_report(), """
          out.tree = filtered("  ", {mode: "tree"}); out.treeCount = count();
          out.flat = filtered("", {mode: "flat"}); out.flatCount = count();
          filtered("", {mode: "tree", level: "INFO"}); out.infoCount = count();
          filtered("", {mode: "tree", view: "changes"}); out.changesCount = count();
        """)
        self.assertEqual(out["tree"], [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 14])
        self.assertEqual(out["treeCount"], "11 rows")
        self.assertEqual(out["flat"], [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 14])
        self.assertIn("matching", out["infoCount"])
        self.assertIn("matching", out["changesCount"])

    def test_tree_keeps_enclosing_scopes_and_prunes_the_rest(self):
        self.check({
            "boom": [2, 3, 6],
            "acme": [2, 3, 4, 5, 6],
            ("", "level", "WARNING"): [2, 3, 4, 6, 8, 10],
            ("", "view", "changes"): [2, 3, 5, 6],
            ("", "view", "findings"): [2, 3, 4],
        }, mode="tree")

    def test_folding_still_applies_under_a_filter(self):
        out = self.probe(self.fixture_report(), """
          filtered("", {mode: "tree"}); fold(2);
          out.rows = filtered("boom", {mode: "tree"});
          fold(2);
        """)
        self.assertEqual(out["rows"], [2, 3])

    def test_tree_shows_a_matching_scope_header_even_when_nothing_inside_matches(self):
        self.check({"initech": [2, 11], "globex boom": []}, mode="tree")

    def test_tree_errors_view_shows_a_raising_scope_but_only_errors_inside(self):
        self.check({("", "view", "errors"): [2, 3, 6, 8, 10]}, mode="tree")

    def test_flat_scope_rows_are_ordinary_rows(self):
        self.check({"boom": [6], ("", "view", "errors"): [6, 8, 10], "initech": [11]})

    def test_unfinished_scopes_are_not_errors_and_is_unfinished_finds_them(self):
        report = self.render("crashed", fixture()[:6])  # crash inside Scope 2
        out = self.probe(report, """
          out.errors = filtered("", {mode: "tree", view: "errors"});
          out.levelError = filtered("level>=error", {mode: "tree"});
          out.unfinished = filtered("is:unfinished", {mode: "tree"});
          out.flatCustomer = filtered("is:unfinished kind:customer", {mode: "flat"});
          out.treeCustomer = filtered("is:unfinished kind:customer", {mode: "tree"});
        """)
        self.assertEqual(out["errors"], [])
        self.assertEqual(out["levelError"], [])
        self.assertEqual(out["unfinished"], [2, 3])
        self.assertEqual(out["flatCustomer"], [3])
        self.assertEqual(out["treeCustomer"], [2, 3])

    def test_headers_show_k_of_n_shown_under_a_filter_with_whole_scope_totals(self):
        out = self.probe(self.fixture_report(), """
          filtered("boom", {mode: "tree"});
          out.customer = cells(3)[7]; out.phase = cells(2)[7]; out.count = count();
          filtered("", {mode: "tree"});
          out.plain = cells(3)[7];
          filtered("initech", {mode: "tree"});
          out.empty = cells(11)[7];
        """)
        self.assertEqual(out["customer"], "3 records · 1 planned · 1 failed · 1 Finding · 4 ms · 1 of 3 shown")
        self.assertIn("1 of 5 shown", out["phase"])
        self.assertTrue(out["count"].startswith("1 matching"), out["count"])
        self.assertNotIn("shown", out["plain"])
        self.assertIn("0 of 0 shown", out["empty"])

    def test_view_buttons_count_entries(self):
        out = self.probe(self.fixture_report(), 'out.views = texts("#bar [data-view]");')
        self.assertEqual(out["views"], ["All 7", "Changes 2", "Findings 1", "Errors 2"])


if __name__ == "__main__":
    unittest.main()

"""SPEC §7 budgets: the realistic-entropy fixture and the 100k Report in Firefox.

The fixture is written through dbfixlog.py itself (tests/budget_fixture.py), so these
tests also run the writer end to end at volume.

The Firefox budget test is skipped without firefox/node, or when DBFIXLOG_SKIP_BROWSER or
DBFIXLOG_SKIP_BUDGET is set. It prints the measured numbers to stderr.
"""
import collections
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import budget_fixture
import test_report_browser as base

_FF = base.StubReportInFirefox.__dict__  # not the class: unittest would collect it

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "dbfixlog_render.py")


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


class BudgetFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.path = os.path.join(cls.dir, "fixture.jsonl")
        budget_fixture.generate(cls.path, 20000, seed=1)
        cls.records = read_jsonl(cls.path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_writes_about_the_requested_number_of_records_as_one_run(self):
        self.assertGreaterEqual(len(self.records), 20000)
        self.assertLess(len(self.records), 20000 * 1.02)
        self.assertEqual(self.records[0]["type"], "run_start")
        self.assertEqual(self.records[-1]["type"], "run_end")
        self.assertEqual(self.records[-1]["outcome"], "ok")

    def test_mixes_every_entry_type(self):
        types = collections.Counter(r["type"] for r in self.records)
        for t in ("message", "finding", "change", "scope_start", "scope_end"):
            self.assertGreater(types[t], 200, (t, types))

    def test_nests_scopes_at_least_three_deep(self):
        depth = max(len(r.get("scope", [])) for r in self.records)
        self.assertGreaterEqual(depth, 3)

    def test_has_failed_changes_and_raised_scopes(self):
        failed = [r for r in self.records if r["type"] == "change" and r.get("status") == "failed"]
        self.assertGreater(len(failed), 20)
        self.assertTrue(all(r.get("error", {}).get("message") for r in failed))
        raised = [r for r in self.records if r["type"] == "scope_end" and r["outcome"] == "error"]
        self.assertGreater(len(raised), 5)
        self.assertTrue(all("traceback" in r["exc"] for r in raised))

    def test_field_counts_vary(self):
        counts = {len(r.get("fields", {})) for r in self.records if r["type"] == "message"}
        self.assertGreaterEqual(len(counts), 4, counts)

    def test_ids_and_names_are_mostly_unique(self):
        keys = [json.dumps(r["key"]) for r in self.records if r["type"] == "change"]
        self.assertGreater(len(set(keys)) / len(keys), 0.8)
        names = [r["label"]["name"] for r in self.records
                 if r["type"] == "scope_start" and r["kind"] == "customer"]
        self.assertGreater(len(set(names)) / len(names), 0.9)

    def test_gzip_ratio_is_at_most_5x(self):
        with open(self.path, "rb") as f:
            raw = f.read()
        ratio = len(raw) / len(gzip.compress(raw, 9))
        self.assertLessEqual(ratio, 5.0)
        self.assertGreater(ratio, 2.5)  # still log-like, not random noise

    def test_same_seed_gives_the_same_shape(self):
        other = os.path.join(self.dir, "again.jsonl")
        budget_fixture.generate(other, 20000, seed=1)
        strip = lambda rs: [(r["type"], r.get("key"), r.get("msg")) for r in rs]
        self.assertEqual(strip(read_jsonl(other)), strip(self.records))


# Waits for the Report and its idle-time search index (ticket 08), then times a set of
# filters and searches through the real filter bar: filter.set() runs filterRows and
# redraws the list synchronously; reading offsetHeight adds the forced layout.
BUDGET_PROBE = """(() => {
  const R = window.dbfixlogReport, d = document.documentElement.dataset;
  if (d.state === "error") return JSON.stringify({error: d.error});
  if (d.state !== "ready" || !R || !R.model.search) return "";
  const t = R.timing;
  const queries = [
    {q: "deadlock"}, {q: "table:orders op:update"}, {q: "status:failed"},
    {q: "check:no-lines level:warning"}, {q: "kind:customer is:unfinished"},
    {q: "f.city=utrecht"}, {q: "INV-2024"}, {q: "lock timeout"}, {q: "zzzz-no-match"},
    {view: "changes", q: ""}, {view: "findings"}, {view: "errors"},
    {view: "all", level: "WARNING"}, {level: "DEBUG", q: "type:scope"}, {q: ""},
  ];
  const search = [];
  for (const s of queries) {
    const t0 = performance.now();
    R.filter.set(s);
    void document.body.offsetHeight;
    search.push({s: s, ms: performance.now() - t0, filterMs: R.filter.last.ms,
                 rows: R.list.rows.length});
  }
  return JSON.stringify({count: Number(d.recordCount), timing: t, indexMs: R.filter.indexMs,
                        search: search});
})()"""

BUDGET_N = 100000
DATA_READY_MS = 500
SEARCH_MS = 50


@unittest.skipIf(os.environ.get("DBFIXLOG_SKIP_BROWSER") or os.environ.get("DBFIXLOG_SKIP_BUDGET"),
                 "DBFIXLOG_SKIP_BROWSER or DBFIXLOG_SKIP_BUDGET set")
@unittest.skipUnless(base.FIREFOX and base.NODE, "needs firefox and node on PATH")
class BudgetInFirefox(unittest.TestCase):
    setUpClass = _FF["setUpClass"]
    tearDownClass = _FF["tearDownClass"]
    _wait_for_bidi = _FF["_wait_for_bidi"]
    open_report = _FF["open_report"]

    def test_100k_records_meet_the_data_ready_and_search_budgets(self):
        log = os.path.join(self.dir, "budget.jsonl")
        budget_fixture.generate(log, BUDGET_N, seed=7)
        report = os.path.join(self.dir, "budget.html")
        subprocess.run([sys.executable, SCRIPT, log, "-o", report], check=True,
                       stderr=subprocess.DEVNULL)
        with open(log, "rb") as f:
            raw = f.read()
        ratio = len(raw) / len(gzip.compress(raw, 9))
        runs = [self.open_report(report, BUDGET_PROBE) for _ in range(3)]
        for page in runs:
            self.assertNotIn("error", page)
            self.assertEqual(page["count"], len(raw.splitlines()))
        ready = [p["timing"]["ready"] for p in runs]
        worst = [max(s["ms"] for s in p["search"]) for p in runs]
        # Budgets: the median of three loads, so one hiccup on a busy machine doesn't fail it.
        med = lambda xs: sorted(xs)[len(xs) // 2]
        t = runs[ready.index(med(ready))]["timing"]
        sys.stderr.write(
            "\n[budget] %d records, Log File %.1f MB, Report %.1f MB, gzip ratio %.2fx\n"
            "[budget] data ready %s ms (median of %s; decode+parse %d, model+render %d,"
            " since navigation %d), search index %d ms (idle)\n"
            "[budget] filter/search worst %s ms (median of %s; filterRows alone <= %.1f)\n"
            % (page["count"], len(raw) / 1e6, os.path.getsize(report) / 1e6, ratio,
               round(med(ready)), [round(x) for x in ready], t["decode"], t["render"], t["nav"],
               runs[ready.index(med(ready))]["indexMs"], round(med(worst), 1), [round(x, 1) for x in worst],
               max(s["filterMs"] for p in runs for s in p["search"])))
        self.assertLessEqual(ratio, 5.0)
        self.assertLessEqual(med(ready), DATA_READY_MS)
        self.assertLessEqual(med(worst), SEARCH_MS)

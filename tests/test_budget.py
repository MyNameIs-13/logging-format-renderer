"""Load and search budgets: the realistic-entropy fixture and the 100k Report in Firefox.

The fixture is written through dbfixlog.py itself (tests/budget_fixture.py), so these
tests also run the writer end to end at volume.

The Firefox budget test measures from outside the page: data ready is when the list first
shows rows, and each filter or search is timed around the filter bar control that applies
it. It is skipped without firefox/node, or when DBFIXLOG_SKIP_BROWSER or
DBFIXLOG_SKIP_BUDGET is set, and prints the measured numbers to stderr.
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import budget_fixture  # noqa: E402
from browser_report import FirefoxCase, skip_without_browser  # noqa: E402

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


# Runs in the page before any of its scripts: notes when the list first shows rows,
# in ms since navigation start (performance.now()).
FIRST_ROWS = """() => {
  const seen = () => {
    if (document.querySelector(".list .rows .vr")) { window.firstRowsAt = performance.now(); obs.disconnect(); }
  };
  const obs = new MutationObserver(seen);
  obs.observe(document, {childList: true, subtree: true});
}"""

# Waits for the first rows, then a second more so the idle-time search index is built,
# then times filters and searches through the filter bar's own controls. Each one is
# applied synchronously; reading offsetHeight adds the forced layout.
BUDGET_PROBE = """
  if (!window.firstRowsAt || performance.now() < window.firstRowsAt + 1000) return "";
  const nav = performance.getEntriesByType("navigation")[0];
  out.firstRows = window.firstRowsAt;
  out.responseEnd = nav ? nav.responseEnd : 0;
  out.facts = q(".runhead .facts tr").map((tr) => texts("td", tr).join("|"));
  const steps = [
    () => search("deadlock"), () => search("table:orders op:update"), () => search("status:failed"),
    () => search("check:no-lines level:warning"), () => search("kind:customer is:unfinished"),
    () => search("f.city=utrecht"), () => search("INV-2024"), () => search("lock timeout"),
    () => search("zzzz-no-match"), () => { search(""); view("changes"); }, () => view("findings"),
    () => view("errors"), () => { view("all"); level("WARNING"); },
    () => { level("DEBUG"); search("type:scope"); }, () => search(""),
  ];
  out.search = [];
  for (const step of steps) {
    const t0 = performance.now();
    step();
    void document.body.offsetHeight;
    out.search.push({ms: performance.now() - t0, count: count()});
  }
"""

BUDGET_N = 100000
DATA_READY_MS = 500
SEARCH_MS = 50


@unittest.skipIf(os.environ.get("DBFIXLOG_SKIP_BUDGET"), "DBFIXLOG_SKIP_BUDGET set")
@skip_without_browser
class BudgetInFirefox(FirefoxCase):
    def test_100k_records_meet_the_data_ready_and_search_budgets(self):
        log = os.path.join(self.dir, "budget.jsonl")
        budget_fixture.generate(log, BUDGET_N, seed=7)
        report = os.path.join(self.dir, "budget.html")
        subprocess.run([sys.executable, SCRIPT, log, "-o", report], check=True,
                       stderr=subprocess.DEVNULL)
        with open(log, "rb") as f:
            raw = f.read()
        ratio = len(raw) / len(gzip.compress(raw, 9))
        runs = [self.probe(report, BUDGET_PROBE, timeout_ms=20000, preload=FIRST_ROWS)
                for _ in range(3)]
        records = len(raw.splitlines())
        for page in runs:
            self.assertIn("records|%s" % format(records, ","), page["facts"])
            self.assertTrue(all(s["count"] for s in page["search"]))
        ready = [p["firstRows"] for p in runs]
        worst = [max(s["ms"] for s in p["search"]) for p in runs]
        # Budgets: the median of three loads, so one hiccup on a busy machine doesn't fail it.
        med = lambda xs: sorted(xs)[len(xs) // 2]
        sys.stderr.write(
            "\n[budget] %d records, Log File %.1f MB, Report %.1f MB, gzip ratio %.2fx\n"
            "[budget] data ready (first rows, since navigation start) %d ms (median of %s)\n"
            "[budget] filter/search worst %.1f ms (median of %s)\n"
            % (records, len(raw) / 1e6, os.path.getsize(report) / 1e6, ratio,
               round(med(ready)), [round(x) for x in ready],
               med(worst), [round(x, 1) for x in worst]))
        self.assertLessEqual(ratio, 5.0)
        self.assertLessEqual(med(ready), DATA_READY_MS)
        self.assertLessEqual(med(worst), SEARCH_MS)

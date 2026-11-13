"""End to end: a sample check/fix script (tests/fixtures/sample_fix.py) in a Dry Run and a
Write Run, then dbfixlog_render.py, then the Report in headless Firefox without JS errors.

The Firefox part is skipped without firefox/node, or when DBFIXLOG_SKIP_BROWSER is set.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browser_report import DRIVER, NODE, FirefoxCase, skip_without_browser  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "tests", "fixtures", "sample_fix.py")
RENDER = os.path.join(ROOT, "dbfixlog_render.py")


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def run_sample(workdir, write):
    db = os.path.join(workdir, "shop.db")
    log = os.path.join(workdir, "write.jsonl" if write else "dry.jsonl")
    args = [sys.executable, SAMPLE, db, log] + (["--write"] if write else [])
    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    return proc, log, db


def render(log):
    report = log[:-len(".jsonl")] + ".html"
    proc = subprocess.run([sys.executable, RENDER, log, "-o", report],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    return proc, report


class SampleScriptRuns(unittest.TestCase):
    """The sample script against a fresh SQLite database: Dry Run first, then Write Run."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.dry_proc, cls.dry_log, db = run_sample(cls.dir, write=False)
        cls.dry_counts = cls.count_rows(db)
        cls.write_proc, cls.write_log, db = run_sample(cls.dir, write=True)
        cls.write_counts = cls.count_rows(db)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    @staticmethod
    def count_rows(db):
        con = sqlite3.connect(db)
        try:
            return {t: con.execute("select count(*) from " + t).fetchone()[0]
                    for t in ("customers", "orders")}
        finally:
            con.close()

    def test_both_runs_exit_cleanly_and_print_console_lines(self):
        for proc in (self.dry_proc, self.write_proc):
            self.assertEqual(proc.returncode, 0, proc.stderr.decode())
            self.assertIn("orphan-order", proc.stderr.decode())

    def test_dry_run_plans_and_leaves_the_database_alone(self):
        recs = read_jsonl(self.dry_log)
        self.assertEqual((recs[0]["type"], recs[0]["mode"]), ("run_start", "dry"))
        self.assertEqual((recs[-1]["type"], recs[-1]["outcome"]), ("run_end", "ok"))
        statuses = {r["status"] for r in recs if r["type"] == "change"}
        self.assertEqual(statuses, {"planned"})
        self.assertEqual(self.dry_counts, {"customers": 4, "orders": 7})

    def test_write_run_applies_fixes_and_logs_the_one_that_fails(self):
        recs = read_jsonl(self.write_log)
        self.assertEqual(recs[0]["mode"], "write")
        changes = [r for r in recs if r["type"] == "change"]
        statuses = sorted(r["status"] for r in changes)
        self.assertIn("applied", statuses)
        failed = [r for r in changes if r["status"] == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["error"]["type"], "IntegrityError")
        self.assertEqual(self.write_counts["orders"], 7 - 2)  # the two orphan orders
        findings = {r["check"] for r in recs if r["type"] == "finding"}
        self.assertEqual(findings, {"orphan-order", "missing-email"})
        kinds = {r["kind"] for r in recs if r["type"] == "scope_start"}
        self.assertEqual(kinds, {"phase", "customer", "order"})

    def test_both_log_files_render(self):
        for log in (self.dry_log, self.write_log):
            proc, report = render(log)
            self.assertEqual(proc.returncode, 0, proc.stderr.decode())
            self.assertGreater(os.path.getsize(report), 1000)


# Ready, plus a few interactions that touch every part of the page.
E2E_PROBE = """
  out.facts = q(".runhead .facts tr").map((tr) => texts("td", tr).join("|"));
  out.strip = (strip() || {}).text || "";
  out.cards = texts("#cards .card h4");
  const cn = $("#cards a.cn");
  if (cn) { cn.click(); out.cardQuery = searchBox().value; }
  out.failedRows = filtered("status:failed").length;
  filtered("", {mode: "tree"});
  const first = listRows()[0];
  if (first) first.lastElementChild.click();
  out.panel = !$(".panel").hidden;
  for (const how of ["all", "phases", "none"]) $('[data-foldall="' + how + '"]').click();
  mode("flat"); mode("tree");
  out.rows = ids().length;
"""


@skip_without_browser
class SampleReportsInFirefox(FirefoxCase):
    def test_dry_and_write_reports_load_and_work_without_js_errors(self):
        for write in (False, True):
            proc, log, _ = run_sample(self.dir, write)
            self.assertEqual(proc.returncode, 0, proc.stderr.decode())
            _, report = render(log)
            page = self.probe(report, E2E_PROBE)
            self.assertIn("records|%s" % format(len(read_jsonl(log)), ","), page["facts"])
            if write:
                self.assertEqual(page["strip"], "")  # a Write Run has no mode strip
            else:
                self.assertIn("Dry Run", page["strip"])
            self.assertEqual(page["cards"], ["Changes", "Findings", "Scopes"])
            self.assertTrue(page["cardQuery"])
            self.assertTrue(page["panel"])
            self.assertGreater(page["rows"], 0)
            if write:
                self.assertGreater(page["failedRows"], 0)
            else:
                self.assertEqual(page["failedRows"], 0)

    def test_driver_reports_js_errors(self):
        # The no-errors check in probe() only means something if the driver sees errors at all.
        page = os.path.join(self.dir, "broken.html")
        with open(page, "w") as f:
            f.write("<!doctype html><title>x</title><script>window.x = 1; undefinedFn();</script>")
        proc = subprocess.run(
            [NODE, DRIVER, self.ws_url, Path(page).as_uri(), "String(window.x)", "3000"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertIn("js-errors:", proc.stderr.decode())
        self.assertIn("undefinedFn", proc.stderr.decode())

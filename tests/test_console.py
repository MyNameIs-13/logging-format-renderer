import io
import logging
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

import dbfixlog  # noqa: E402

TIME = r"\d\d:\d\d:\d\d"


class ConsoleTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "run.jsonl")
        self.err = io.StringIO()
        self._stderr = sys.stderr
        sys.stderr = self.err

    def tearDown(self):
        sys.stderr = self._stderr
        shutil.rmtree(self.dir)

    def lines(self):
        return self.err.getvalue().splitlines()

    def assertLines(self, patterns):
        """Each console line matches the regex after the ``hh:mm:ss`` time."""
        lines = self.lines()
        self.assertEqual(len(lines), len(patterns), lines)
        for line, pattern in zip(lines, patterns):
            self.assertRegex(line, "^" + TIME + " " + pattern + "$")


class ChangeAndFindingLineTest(ConsoleTestCase):
    def test_change_in_scope_matches_spec_example(self):
        with dbfixlog.run(self.path, mode="dry") as log:
            with log.scope("customer", key={"id": 42}, label={"name": "ACME"}):
                log.change("orders", "delete", key={"id": 156})
        self.assertLines([
            re.escape("INFO  start customer 42 ACME"),
            re.escape("INFO  customer 42 ACME › delete orders {id:156} planned"),
        ])


class LevelTest(ConsoleTestCase):
    def test_console_false_prints_nothing(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            log.warning("careful")
        self.assertEqual(self.lines(), [])

    def test_console_warning_hides_info(self):
        with dbfixlog.run(self.path, mode="dry",
                          console=logging.WARNING) as log:
            log.info("connected")
            log.change("orders", "delete", key={"id": 1})
            log.warning("careful")
        self.assertLines([re.escape("WARNING careful")])

    def test_console_below_file_level_still_sees_its_records(self):
        with dbfixlog.run(self.path, mode="dry", level=logging.WARNING,
                          console=logging.INFO) as log:
            log.info("connected")
        self.assertLines([re.escape("INFO  connected")])
        with open(self.path, encoding="utf-8") as f:
            self.assertNotIn("connected", f.read())

    def test_handler_is_removed_after_the_run(self):
        with dbfixlog.run(self.path, mode="dry"):
            pass
        logging.getLogger("after").warning("outside")
        # Only stdlib's lastResort ("outside", no time prefix) may print.
        self.assertEqual(self.lines(), ["outside"])


if __name__ == "__main__":
    unittest.main()

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


if __name__ == "__main__":
    unittest.main()

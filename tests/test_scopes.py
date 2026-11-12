import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

import dbfixlog  # noqa: E402

THIS_FILE = os.path.basename(__file__)


def read_records(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def lineno_of(marker):
    with open(__file__, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if marker in line and "lineno_of" not in line:
                return i
    raise AssertionError(marker)


class ScopeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "run.jsonl")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def body(self):
        """Records between run_start and run_end."""
        return read_records(self.path)[1:-1]

    def test_single_scope_writes_start_and_end_and_stamps_inner_records(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            with dbfixlog.scope("orphan-check", msg="pass 1",  # MARK-with
                                fields={"pass": 1}):
                log.info("inside")
        start, inner, end = self.body()

        self.assertEqual(start["type"], "scope_start")
        self.assertEqual(start["level"], "INFO")
        self.assertEqual(start["id"], 1)
        self.assertEqual(start["kind"], "orphan-check")
        self.assertEqual(start["msg"], "pass 1")
        self.assertEqual(start["fields"], {"pass": 1})
        self.assertEqual(start["src"], "%s:%d" % (THIS_FILE, lineno_of("MARK-with")))
        self.assertEqual(start["logger"], __name__)
        self.assertNotIn("scope", start)
        self.assertNotIn("key", start)

        self.assertEqual(inner["msg"], "inside")
        self.assertEqual(inner["scope"], [1])

        self.assertEqual(end["type"], "scope_end")
        self.assertEqual(end["level"], "INFO")
        self.assertEqual(end["id"], 1)
        self.assertEqual(end["outcome"], "ok")
        self.assertIsInstance(end["duration_ms"], int)
        self.assertNotIn("scope", end)
        self.assertNotIn("exc", end)


if __name__ == "__main__":
    unittest.main()

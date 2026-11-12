import json
import logging
import os
import shutil
import sys
import tempfile
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


class TypedCallTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "run.jsonl")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def body(self):
        """Records between run_start and run_end."""
        return read_records(self.path)[1:-1]


class ChangeTest(TypedCallTestCase):
    def test_delete_in_dry_run_is_planned_info(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            log.change("orders", "delete", key={"id": 156},  # MARK-delete
                       label={"no": "A88f"})
        [c] = self.body()
        self.assertEqual(c["type"], "change")
        self.assertEqual(c["level"], "INFO")
        self.assertEqual(c["logger"], "__main__")
        self.assertEqual(c["src"], "%s:%d" % (THIS_FILE, lineno_of("MARK-delete")))
        self.assertEqual(c["table"], "orders")
        self.assertEqual(c["op"], "delete")
        self.assertEqual(c["key"], {"id": 156})
        self.assertEqual(c["label"], {"no": "A88f"})
        self.assertEqual(c["status"], "planned")
        for absent in ("msg", "changes", "error", "fields"):
            self.assertNotIn(absent, c)


if __name__ == "__main__":
    unittest.main()

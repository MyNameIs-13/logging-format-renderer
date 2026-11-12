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

    def test_write_run_defaults_to_applied(self):
        with dbfixlog.run(self.path, mode="write", console=False) as log:
            log.change("orders", "delete", key={"id": 156})
        [c] = self.body()
        self.assertEqual(c["status"], "applied")
        self.assertEqual(c["level"], "INFO")

    def test_error_makes_failed_at_error_level(self):
        with dbfixlog.run(self.path, mode="write", console=False) as log:
            try:
                raise ValueError("FK violation")
            except ValueError as e:
                log.change("orders", "delete", key={"id": 156}, error=e,
                           msg="delete failed")
        [c] = self.body()
        self.assertEqual(c["status"], "failed")
        self.assertEqual(c["level"], "ERROR")
        self.assertEqual(c["error"], {"type": "ValueError",
                                      "message": "FK violation"})
        self.assertEqual(c["msg"], "delete failed")
        self.assertNotIn("exc", c)

    def test_explicit_status_wins(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            log.change("orders", "delete", key={"id": 1}, status="applied")
            log.change("orders", "delete", key={"id": 2}, status="planned",
                       error=RuntimeError("x"))
            log.change("orders", "delete", key={"id": 3}, status="failed")
        a, b, c = self.body()
        self.assertEqual(a["status"], "applied")
        self.assertEqual(b["status"], "planned")
        self.assertEqual(b["error"], {"type": "RuntimeError", "message": "x"})
        self.assertEqual(c["status"], "failed")
        self.assertEqual(c["level"], "ERROR")

    def test_explicit_level_wins(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            log.change("orders", "delete", key={"id": 1},
                       level=logging.WARNING, fields={"batch": 3})
            log.change("orders", "delete", key={"id": 2},
                       error=RuntimeError("x"), level=logging.CRITICAL)
        a, b = self.body()
        self.assertEqual(a["level"], "WARNING")
        self.assertEqual(a["fields"], {"batch": 3})
        self.assertEqual(b["level"], "CRITICAL")

    def test_changes_tuple_and_dict_forms_keep_unchanged_entries(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            log.change("customers", "update", key={"id": 42},
                       changes={"name": ("ACME", "Acme Ltd"),
                                "city": {"old": "Oslo", "new": "Bergen"},
                                "vip": (True, True),
                                "note": (None, "x")})
        [c] = self.body()
        self.assertEqual(c["changes"], {
            "name": {"old": "ACME", "new": "Acme Ltd"},
            "city": {"old": "Oslo", "new": "Bergen"},
            "vip": {"old": True, "new": True},
            "note": {"old": None, "new": "x"},
        })
        self.assertEqual(list(c["changes"]), ["name", "city", "vip", "note"])
        self.assertEqual(c["level"], "INFO")

    def test_change_values_are_encoded(self):
        import decimal
        with dbfixlog.run(self.path, mode="dry", console=False,
                          max_text=3) as log:
            log.change("t", "update", key={"id": 1},
                       changes={"price": (decimal.Decimal("1.50"),
                                          decimal.Decimal("2.00")),
                                "text": ("abcdef", "ab")})
        [c] = self.body()
        self.assertEqual(c["changes"]["price"], {"old": "1.50", "new": "2.00"})
        self.assertEqual(c["changes"]["text"]["old"],
                         {"$truncated": "abc", "length": 6})


if __name__ == "__main__":
    unittest.main()

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


class ChangeMisuseTest(TypedCallTestCase):
    CASES = [
        ("unknown op", ("orders", "upsert"), {"key": {"id": 1}}, "op"),
        ("update without changes", ("orders", "update"), {"key": {"id": 1}},
         "changes"),
        ("missing key on delete", ("orders", "delete"), {}, "key"),
        ("missing key on update", ("orders", "update"),
         {"changes": {"a": (1, 2)}}, "key"),
        ("scalar key", ("orders", "delete"), {"key": 156}, "key"),
    ]

    def test_misuse_writes_record_then_warning(self):
        for name, args, kwargs, word in self.CASES:
            with self.subTest(name):
                with dbfixlog.run(self.path, mode="dry", console=False,
                                  overwrite=True) as log:
                    log.change(*args, **kwargs)  # MARK-misuse
                change, warning = self.body()
                self.assertEqual(change["type"], "change")
                self.assertEqual(change["table"], args[0])
                self.assertEqual(change["op"], args[1])
                if "key" in kwargs:
                    self.assertEqual(change["key"], kwargs["key"])
                else:
                    self.assertNotIn("key", change)
                self.assertEqual(warning["type"], "message")
                self.assertEqual(warning["level"], "WARNING")
                self.assertEqual(warning["logger"], "__main__")
                self.assertTrue(
                    warning["msg"].startswith("invalid change call: "),
                    warning["msg"])
                self.assertIn(word, warning["msg"])
                src = "%s:%d" % (THIS_FILE, lineno_of("MARK-misuse"))
                self.assertEqual(change["src"], src)
                self.assertEqual(warning["src"], src)

    def test_misuse_raises_under_strict(self):
        for name, args, kwargs, _ in self.CASES:
            with self.subTest(name):
                with dbfixlog.run(self.path, mode="dry", console=False,
                                  strict=True, overwrite=True) as log:
                    with self.assertRaises(ValueError) as cm:
                        log.change(*args, **kwargs)
                self.assertIn("invalid change call", str(cm.exception))
                self.assertEqual(self.body(), [])

    def test_valid_calls_write_no_warning(self):
        with dbfixlog.run(self.path, mode="dry", console=False,
                          strict=True) as log:
            log.change("orders", "insert", label={"no": "B1"})
            log.change("orders", "insert", key={"id": 9})
            log.change("orders", "update", key={"id": 1},
                       changes={"a": (1, 1)})
            log.change("orders", "delete", key={"order_id": 7, "line_no": 3})
        self.assertEqual([r["type"] for r in self.body()], ["change"] * 4)


if __name__ == "__main__":
    unittest.main()

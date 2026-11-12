import json
import logging
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dbfixlog  # noqa: E402
import helpers  # noqa: E402
from helpers import read_records  # noqa: E402

THIS_FILE = os.path.basename(__file__)


def lineno_of(marker):
    return helpers.lineno_of(__file__, marker)


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

    def test_explicit_status_with_error_keeps_error_level(self):
        # status= overrides the status only; the error still means ERROR.
        with dbfixlog.run(self.path, mode="write", console=False) as log:
            log.change("orders", "delete", key={"id": 1}, status="applied",
                       error=RuntimeError("x"))
        [c] = self.body()
        self.assertEqual(c["status"], "applied")
        self.assertEqual(c["level"], "ERROR")
        self.assertEqual(c["error"], {"type": "RuntimeError", "message": "x"})

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


class FindingTest(TypedCallTestCase):
    def test_finding_defaults_to_warning(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            log.finding("orphan-order", "no customer",  # MARK-finding
                        table="orders", key={"id": 156},
                        label={"no": "A88f"}, fields={"customer_id": 9})
        [f] = self.body()
        self.assertEqual(f["type"], "finding")
        self.assertEqual(f["level"], "WARNING")
        self.assertEqual(f["logger"], "__main__")
        self.assertEqual(f["src"], "%s:%d" % (THIS_FILE, lineno_of("MARK-finding")))
        self.assertEqual(f["check"], "orphan-order")
        self.assertEqual(f["msg"], "no customer")
        self.assertEqual(f["table"], "orders")
        self.assertEqual(f["key"], {"id": 156})
        self.assertEqual(f["label"], {"no": "A88f"})
        self.assertEqual(f["fields"], {"customer_id": 9})

    def test_table_level_finding_with_level_override(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            log.finding("dup-index", table="orders", level=logging.ERROR)
            log.finding("stats-stale", level=logging.INFO)
        a, b = self.body()
        self.assertEqual(a["level"], "ERROR")
        self.assertEqual(b["level"], "INFO")
        for absent in ("msg", "key", "label", "fields"):
            self.assertNotIn(absent, a)
        self.assertNotIn("table", b)

    def test_check_is_required(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            with self.assertRaises(TypeError):
                log.finding()
            with self.assertRaises(TypeError):
                log.finding(msg="no check", table="orders")

    def test_finding_respects_configured_level(self):
        with dbfixlog.run(self.path, mode="dry", console=False,
                          level=logging.ERROR) as log:
            log.finding("x")
        self.assertEqual(self.body(), [])


class LogScopeTest(TypedCallTestCase):
    def test_log_scope_stamps_caller_src_and_logger(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            helper = dbfixlog.get_logger("shop.fixes")
            with log.scope("customer", key={"id": 42},  # MARK-log-scope
                           label={"name": "ACME"}):
                with helper.scope("phase"):  # MARK-helper-scope
                    log.change("orders", "delete", key={"id": 156})
        outer, inner, change, inner_end, outer_end = self.body()
        self.assertEqual(outer["type"], "scope_start")
        self.assertEqual(outer["logger"], "__main__")
        self.assertEqual(outer["src"],
                         "%s:%d" % (THIS_FILE, lineno_of("MARK-log-scope")))
        self.assertEqual(outer["key"], {"id": 42})
        self.assertEqual(outer["label"], {"name": "ACME"})
        self.assertEqual(inner["logger"], "shop.fixes")
        self.assertEqual(inner["src"],
                         "%s:%d" % (THIS_FILE, lineno_of("MARK-helper-scope")))
        self.assertEqual(inner["scope"], [1])
        self.assertEqual(change["scope"], [1, 2])
        self.assertEqual(outer_end["outcome"], "ok")

    def test_log_scope_as_decorator(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            @log.scope("orphan-check")
            def check():
                log.finding("orphan-order", key={"id": 1})
            check()
            check()
        recs = self.body()
        self.assertEqual([r["type"] for r in recs],
                         ["scope_start", "finding", "scope_end"] * 2)
        self.assertEqual(recs[1]["scope"], [1])
        self.assertEqual(recs[4]["scope"], [2])


HELPER_SOURCE = '''\
import dbfixlog

log = dbfixlog.get_logger(__name__)


def fix(order_id):
    log.info("fixing", fields={"id": order_id})
    log.finding("orphan-order", key={"id": order_id})
    log.change("orders", "delete", key={"id": order_id})
'''


class GetLoggerTest(TypedCallTestCase):
    def import_helper(self):
        with open(os.path.join(self.dir, "fixhelper.py"), "w") as f:
            f.write(HELPER_SOURCE)
        sys.path.insert(0, self.dir)
        self.addCleanup(sys.path.remove, self.dir)
        self.addCleanup(sys.modules.pop, "fixhelper", None)
        import fixhelper
        return fixhelper

    def test_helper_module_logs_into_active_run(self):
        # The helper's logger is created at import time, before the Run.
        helper = self.import_helper()
        with dbfixlog.run(self.path, mode="dry", console=False):
            helper.fix(156)
        msg, finding, change = self.body()
        for rec, line in ((msg, 7), (finding, 8), (change, 9)):
            self.assertEqual(rec["logger"], "fixhelper")
            self.assertEqual(rec["src"], "fixhelper.py:%d" % line)
        self.assertEqual(msg["fields"], {"id": 156})
        self.assertEqual(finding["type"], "finding")
        self.assertEqual(change["status"], "planned")

    def test_get_logger_returns_adapter_for_named_logger(self):
        log = dbfixlog.get_logger("shop.fixes")
        self.assertIsInstance(log, logging.LoggerAdapter)
        self.assertIs(log.logger, logging.getLogger("shop.fixes"))


class _Capture(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)
        self.records = []

    def emit(self, record):
        self.records.append(record)


class OutsideRunTest(unittest.TestCase):
    def test_typed_calls_fall_back_to_plain_logging(self):
        logger = logging.getLogger("outside.run")
        cap = _Capture()
        logger.addHandler(cap)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        self.addCleanup(logger.removeHandler, cap)
        self.addCleanup(setattr, logger, "propagate", True)
        log = dbfixlog.get_logger("outside.run")

        log.change("orders", "delete", key={"id": 156})
        log.change("orders", "delete", key=156)
        log.finding("orphan-order", "no customer")
        with log.scope("customer", key={"id": 42}):
            log.info("inside")

        self.assertEqual(
            [(r.levelname, r.getMessage()) for r in cap.records],
            [("INFO", "delete orders"),
             ("INFO", "delete orders"),
             ("WARNING", "invalid change call: key must be a {column: value} "
                         "object, got int 156"),
             ("WARNING", "orphan-order: no customer"),
             ("INFO", "inside")])
        self.assertFalse(log.dry_run)
        self.assertFalse(log.write_run)


if __name__ == "__main__":
    unittest.main()

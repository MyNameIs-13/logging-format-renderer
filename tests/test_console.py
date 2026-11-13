import io
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
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
    def test_change_in_scope_is_prefixed_by_the_scope_label(self):
        with dbfixlog.run(self.path, mode="dry") as log:
            with log.scope("customer", key={"id": 42}, label={"name": "ACME"}):
                log.change("orders", "delete", key={"id": 156})
        self.assertLines([
            re.escape("INFO  start customer 42 ACME"),
            re.escape("INFO  customer 42 ACME › delete orders {id:156} planned"),
        ])

    def test_finding_line_shows_check_row_and_msg(self):
        with dbfixlog.run(self.path, mode="dry") as log:
            log.finding("orphan-order", "no customer", table="orders",
                        key={"id": 156}, label={"no": "A88f"})
            log.finding("table-empty")
        self.assertLines([
            re.escape("WARNING orphan-order orders {id:156} A88f - no customer"),
            re.escape("WARNING table-empty"),
        ])

    def test_failed_change_shows_error_at_error_level(self):
        with dbfixlog.run(self.path, mode="write") as log:
            log.change("orders", "update", key={"id": 7},
                       changes={"total": (1, 2)},
                       error=RuntimeError("deadlock"))
        self.assertLines([
            re.escape("ERROR update orders {id:7} failed: RuntimeError: deadlock"),
        ])

    def test_change_label_and_msg_follow_the_key(self):
        with dbfixlog.run(self.path, mode="write") as log:
            log.change("orders", "insert", label={"no": "B1"}, msg="re-created")
        self.assertLines([
            re.escape("INFO  insert orders B1 applied - re-created"),
        ])


class MessageLineTest(ConsoleTestCase):
    def test_message_uses_stdlib_text_with_args(self):
        with dbfixlog.run(self.path, mode="dry") as log:
            dbfixlog.get_logger("helper").info("rows: %d", 12)
            log.info("connected", fields={"rows": 12})
        self.assertLines([re.escape("INFO  rows: 12"),
                          re.escape("INFO  connected")])

    def test_message_inside_nested_scope_uses_innermost_label(self):
        with dbfixlog.run(self.path, mode="dry") as log:
            with log.scope("orphan-check"):
                with log.scope("customer", key={"id": 42}):
                    log.info("checking")
        self.assertLines([
            re.escape("INFO  start orphan-check"),
            re.escape("INFO  orphan-check › start customer 42"),
            re.escape("INFO  customer 42 › checking"),
        ])

    def test_logged_exception_includes_traceback(self):
        with dbfixlog.run(self.path, mode="dry") as log:
            try:
                raise ValueError("bad row")
            except ValueError:
                log.exception("failed")
        out = self.err.getvalue()
        self.assertRegex(out, "^" + TIME + " ERROR failed\nTraceback")
        self.assertIn("ValueError: bad row", out)

    def test_invalid_change_warning_is_a_message_line(self):
        with dbfixlog.run(self.path, mode="dry") as log:
            log.change("orders", "delete")
        self.assertLines([
            re.escape("INFO  delete orders planned"),
            re.escape("WARNING invalid change call: delete without key"),
        ])


    def test_message_with_stack_info_includes_the_stack(self):
        with dbfixlog.run(self.path, mode="dry") as log:
            log.info("here", stack_info=True)
        out = self.err.getvalue()
        self.assertRegex(out, "^" + TIME + " INFO  here\nStack \\(most recent")


class TimeTest(ConsoleTestCase):
    def setUp(self):
        ConsoleTestCase.setUp(self)
        self._tz = os.environ.get("TZ")
        os.environ["TZ"] = "Asia/Kolkata"  # +05:30, never equal to UTC
        time.tzset()

    def tearDown(self):
        if self._tz is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = self._tz
        time.tzset()
        ConsoleTestCase.tearDown(self)

    def test_console_time_is_the_utc_time_of_the_record(self):
        with dbfixlog.run(self.path, mode="dry") as log:
            log.info("connected")
        with open(self.path, encoding="utf-8") as f:
            [rec] = [json.loads(l) for l in f if '"connected"' in l]
        [line] = self.lines()
        self.assertEqual(line[:8], rec["ts"][11:19])


class ScopeLineTest(ConsoleTestCase):
    def test_ok_scope_end_prints_nothing(self):
        with dbfixlog.run(self.path, mode="dry") as log:
            with log.scope("phase", msg="pass 1"):
                pass
        self.assertLines([re.escape("INFO  start phase - pass 1")])

    def test_error_scope_end_prints_a_line(self):
        with self.assertRaises(KeyError):
            with dbfixlog.run(self.path, mode="dry") as log:
                with log.scope("outer"):
                    with log.scope("customer", key={"id": 42}):
                        raise KeyError("x")
        self.assertLines([
            re.escape("INFO  start outer"),
            re.escape("INFO  outer › start customer 42"),
            re.escape("ERROR outer › end customer 42 error: KeyError: 'x'"),
            re.escape("ERROR end outer error: KeyError: 'x'"),
        ])

    def test_scope_start_hidden_when_console_above_info(self):
        with dbfixlog.run(self.path, mode="dry",
                          console=logging.WARNING) as log:
            with log.scope("customer"):
                log.warning("careful")
        self.assertLines([re.escape("WARNING customer › careful")])


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

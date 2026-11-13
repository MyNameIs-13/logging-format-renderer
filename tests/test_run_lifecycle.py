import json
import logging
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dbfixlog  # noqa: E402
import helpers  # noqa: E402

TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


def read_records(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


class RunTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "run.jsonl")

    def tearDown(self):
        shutil.rmtree(self.dir)


class RunBracketTest(RunTestCase):
    def test_ok_run_writes_header_first_and_end_last(self):
        with dbfixlog.run(self.path, mode="dry", title="T", description="D",
                          target={"database": "shop"}, fields={"a": 1},
                          console=False) as log:
            log.info("hello")
        recs = read_records(self.path)
        self.assertEqual(len(recs), 3)
        start, end = recs[0], recs[-1]
        self.assertEqual(start["type"], "run_start")
        self.assertEqual(start["format"], "1.0")
        self.assertEqual(start["mode"], "dry")
        self.assertEqual(start["level"], "INFO")
        self.assertEqual(start["logger"], "dbfixlog")
        self.assertEqual(start["title"], "T")
        self.assertEqual(start["description"], "D")
        self.assertEqual(start["target"], {"database": "shop"})
        self.assertEqual(start["fields"], {"a": 1})
        self.assertNotIn("src", start)
        self.assertRegex(start["ts"], TS_RE)
        self.assertEqual(end["type"], "run_end")
        self.assertEqual(end["outcome"], "ok")
        self.assertEqual(end["level"], "INFO")
        self.assertEqual(end["logger"], "dbfixlog")
        self.assertNotIn("src", end)
        self.assertNotIn("exit_code", end)
        self.assertIsInstance(end["duration_ms"], int)
        self.assertRegex(end["ts"], TS_RE)

    def test_optional_header_fields_absent_when_not_given(self):
        with dbfixlog.run(self.path, mode="write", console=False):
            pass
        start = read_records(self.path)[0]
        self.assertEqual(start["mode"], "write")
        for k in ("title", "description", "target", "fields"):
            self.assertNotIn(k, start)

    def test_error_outcome_attaches_exc_and_reraises(self):
        with self.assertRaises(ValueError):
            with dbfixlog.run(self.path, mode="dry", console=False):
                raise ValueError("boom")
        end = read_records(self.path)[-1]
        self.assertEqual(end["type"], "run_end")
        self.assertEqual(end["outcome"], "error")
        self.assertEqual(end["level"], "ERROR")
        self.assertEqual(end["exc"]["type"], "ValueError")
        self.assertEqual(end["exc"]["message"], "boom")
        self.assertIsInstance(end["exc"]["traceback"], str)
        self.assertIn("raise ValueError", end["exc"]["traceback"])

    def test_keyboard_interrupt_is_interrupted(self):
        with self.assertRaises(KeyboardInterrupt):
            with dbfixlog.run(self.path, mode="dry", console=False):
                raise KeyboardInterrupt
        end = read_records(self.path)[-1]
        self.assertEqual(end["outcome"], "interrupted")
        self.assertEqual(end["level"], "ERROR")

    def test_system_exit_zero_and_none_are_ok(self):
        for code in (0, None):
            path = os.path.join(self.dir, "exit-%s.jsonl" % code)
            with self.assertRaises(SystemExit):
                with dbfixlog.run(path, mode="dry", console=False):
                    sys.exit(code)
            end = read_records(path)[-1]
            self.assertEqual(end["outcome"], "ok")
            self.assertEqual(end["level"], "INFO")
            self.assertIn("exit_code", end)
            self.assertEqual(end["exit_code"], code)

    def test_system_exit_nonzero_is_error(self):
        with self.assertRaises(SystemExit):
            with dbfixlog.run(self.path, mode="dry", console=False):
                sys.exit(3)
        end = read_records(self.path)[-1]
        self.assertEqual(end["outcome"], "error")
        self.assertEqual(end["level"], "ERROR")
        self.assertEqual(end["exit_code"], 3)


class HandlerLifecycleTest(RunTestCase):
    def test_root_logger_untouched(self):
        root = logging.getLogger()
        mine = logging.NullHandler()
        root.addHandler(mine)
        self.addCleanup(root.removeHandler, mine)
        before = (list(root.handlers), root.level)
        with dbfixlog.run(self.path, mode="dry"):
            self.assertEqual((root.handlers, root.level), before)
        self.assertEqual((root.handlers, root.level), before)
        with self.assertRaises(RuntimeError):
            with dbfixlog.run(os.path.join(self.dir, "b.jsonl"), mode="dry"):
                raise RuntimeError("x")
        self.assertEqual((root.handlers, root.level), before)

    def test_helper_logging_reaches_root_again_after_run(self):
        cap = helpers.capture_root(self)
        helper = dbfixlog.get_logger("x")
        with dbfixlog.run(self.path, mode="dry", console=False):
            helper.warning("during")
        helper.warning("after")
        self.assertEqual([r.getMessage() for r in cap.records], ["after"])

    def assertHelperLoggingRestored(self):
        cap = helpers.capture_root(self, level=logging.DEBUG)
        dbfixlog.get_logger("x").info("after")
        self.assertEqual([r.getMessage() for r in cap.records], ["after"])

    def test_namespace_restored_after_run_with_high_level(self):
        with dbfixlog.run(self.path, mode="dry", level=logging.ERROR,
                          console=False):
            pass
        self.assertHelperLoggingRestored()

    def test_namespace_restored_after_exception(self):
        with self.assertRaises(KeyError):
            with dbfixlog.run(self.path, mode="dry", level=logging.ERROR,
                              console=logging.ERROR):
                raise KeyError("x")
        self.assertHelperLoggingRestored()

    @unittest.skipUnless(os.path.exists("/dev/full"), "needs /dev/full")
    def test_namespace_restored_after_failed_header_write(self):
        with self.assertRaises(OSError):
            with dbfixlog.run("/dev/full", mode="dry", level=logging.ERROR,
                              console=False, overwrite=True):
                pass
        self.assertHelperLoggingRestored()

    def test_namespace_restored_after_failed_setup(self):
        with self.assertRaises(TypeError):
            with dbfixlog.run(self.path, mode="dry", level=logging.ERROR,
                              console="loud"):
                pass
        self.assertHelperLoggingRestored()

    def test_logging_after_run_does_not_reach_file(self):
        with dbfixlog.run(self.path, mode="dry", console=False):
            pass
        dbfixlog.get_logger("x").warning("after")
        self.assertEqual(read_records(self.path)[-1]["type"], "run_end")


class RunSetupTest(RunTestCase):
    def test_ts_placeholder_becomes_start_time(self):
        pattern = os.path.join(self.dir, "fix-{ts}.jsonl")
        with dbfixlog.run(pattern, mode="dry", console=False):
            pass
        names = os.listdir(self.dir)
        self.assertEqual(len(names), 1)
        m = re.match(r"^fix-(\d{8}T\d{6}Z)\.jsonl$", names[0])
        self.assertIsNotNone(m, names[0])
        start = read_records(os.path.join(self.dir, names[0]))[0]
        # "2026-11-12T20:01:00.000Z" -> "20261112T200100Z"
        expected = start["ts"][:19].replace("-", "").replace(":", "") + "Z"
        self.assertEqual(m.group(1), expected)

    def test_existing_file_refused_unless_overwrite(self):
        with open(self.path, "w") as f:
            f.write("old\n")
        with self.assertRaises(FileExistsError):
            with dbfixlog.run(self.path, mode="dry", console=False):
                self.fail("body must not run")
        with open(self.path) as f:
            self.assertEqual(f.read(), "old\n")
        with dbfixlog.run(self.path, mode="dry", overwrite=True, console=False):
            pass
        self.assertEqual(read_records(self.path)[0]["type"], "run_start")

    def test_unopenable_path_raises(self):
        with self.assertRaises(OSError):
            with dbfixlog.run(os.path.join(self.dir, "no", "such", "x.jsonl"),
                              mode="dry", console=False):
                pass
        # A failed setup leaves no Run active.
        with dbfixlog.run(self.path, mode="dry", console=False):
            pass

    def test_invalid_mode_refused(self):
        for mode in ("Dry", "live", None):
            with self.assertRaises(ValueError):
                with dbfixlog.run(self.path, mode=mode, console=False):
                    pass
        self.assertFalse(os.path.exists(self.path))

    def test_nested_run_refused(self):
        inner = os.path.join(self.dir, "inner.jsonl")
        with dbfixlog.run(self.path, mode="dry", console=False):
            with self.assertRaises(RuntimeError):
                with dbfixlog.run(inner, mode="dry", console=False):
                    pass
        self.assertFalse(os.path.exists(inner))
        self.assertEqual(read_records(self.path)[-1]["outcome"], "ok")
        # A new Run is allowed once the first has ended.
        with dbfixlog.run(os.path.join(self.dir, "again.jsonl"),
                          mode="dry", console=False):
            pass

    def test_encoding_and_console_options_are_accepted(self):
        with dbfixlog.run(self.path, mode="dry", encoders={int: str},
                          max_text=10, console=logging.WARNING):
            pass
        self.assertEqual(read_records(self.path)[-1]["outcome"], "ok")

    def test_dry_run_and_write_run_flags(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            self.assertTrue(log.dry_run)
            self.assertFalse(log.write_run)
        with dbfixlog.run(self.path, mode="write", overwrite=True,
                          console=False) as log:
            self.assertFalse(log.dry_run)
            self.assertTrue(log.write_run)


if __name__ == "__main__":
    unittest.main()

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
from helpers import read_records  # noqa: E402

TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
THIS_FILE = os.path.basename(__file__)


def lineno_of(marker):
    return helpers.lineno_of(__file__, marker)


class MessageTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "run.jsonl")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def messages(self):
        return [r for r in read_records(self.path) if r["type"] == "message"]

    def test_get_logger_plain_call_becomes_message(self):
        helper = dbfixlog.get_logger("x.helper")
        with dbfixlog.run(self.path, mode="dry", console=False):
            helper.info("hi %s", "there")  # MARK-plain
        [m] = self.messages()
        self.assertEqual(m["logger"], "x.helper")
        self.assertEqual(m["level"], "INFO")
        self.assertEqual(m["msg"], "hi there")
        self.assertRegex(m["ts"], TS_RE)
        self.assertEqual(m["src"], "%s:%d" % (THIS_FILE, lineno_of("MARK-plain")))
        self.assertEqual(list(m)[:6], ["ts", "level", "logger", "type", "src", "msg"])
        self.assertNotIn("fields", m)
        self.assertNotIn("scope", m)

    def test_plain_stdlib_loggers_stay_out(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            logging.getLogger("x.helper").warning("plain")
            logging.getLogger("__main__").error("plain main")
            logging.getLogger().critical("plain root")
            log.info("kept")
        self.assertEqual([m["msg"] for m in self.messages()], ["kept"])

    def test_records_do_not_reach_root_handlers_during_run(self):
        cap = helpers.capture_root(self)
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            log.warning("only in the file")
            dbfixlog.get_logger("x.helper").finding("orphan-order")
            with dbfixlog.scope("phase"):
                pass
        self.assertEqual(cap.records, [])
        self.assertEqual(len(self.messages()), 1)

    def test_log_adapter_message_with_fields(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            log.info("connected", fields={"rows": 12})  # MARK-adapter
        [m] = self.messages()
        self.assertEqual(m["logger"], "__main__")
        self.assertEqual(m["msg"], "connected")
        self.assertEqual(m["fields"], {"rows": 12})
        self.assertEqual(m["src"], "%s:%d" % (THIS_FILE, lineno_of("MARK-adapter")))

    def test_all_levels_and_methods(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            log.debug("d")
            log.info("i")
            log.warning("w")
            log.error("e")
            log.critical("c")
            log.log(logging.WARNING, "l", fields={"k": None})
        levels = [m["level"] for m in self.messages()]
        self.assertEqual(levels, ["DEBUG", "INFO", "WARNING", "ERROR",
                                  "CRITICAL", "WARNING"])
        self.assertEqual(self.messages()[-1]["fields"], {"k": None})

    def test_exception_attaches_exc(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            try:
                raise KeyError("missing")
            except KeyError:
                log.exception("lookup failed")
        [m] = self.messages()
        self.assertEqual(m["level"], "ERROR")
        self.assertEqual(m["exc"]["type"], "KeyError")
        self.assertEqual(m["exc"]["message"], "'missing'")
        self.assertIn("Traceback", m["exc"]["traceback"])

    def test_records_below_level_dropped_but_run_records_kept(self):
        with dbfixlog.run(self.path, mode="dry", level=logging.ERROR,
                          console=False) as log:
            log.info("dropped")
            dbfixlog.get_logger("x").warning("dropped too")
            log.error("kept")
        recs = read_records(self.path)
        self.assertEqual([r["type"] for r in recs],
                         ["run_start", "message", "run_end"])
        self.assertEqual(recs[1]["msg"], "kept")

    def test_debug_written_by_default_even_if_root_is_warning(self):
        root = logging.getLogger()
        old = root.level
        root.setLevel(logging.WARNING)
        try:
            with dbfixlog.run(self.path, mode="dry", console=False) as log:
                log.debug("d")
                self.assertEqual(root.level, logging.WARNING)
            self.assertEqual(root.level, logging.WARNING)
        finally:
            root.setLevel(old)
        self.assertEqual([m["msg"] for m in self.messages()], ["d"])

    def test_extra_keys_do_not_clash(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            log.info("m", extra={"custom": 1}, fields={"msg": "x", "name": "y"})
        [m] = self.messages()
        self.assertEqual(m["msg"], "m")
        self.assertEqual(m["fields"], {"msg": "x", "name": "y"})

    def test_unserialisable_fields_never_raise(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            log.info("m", fields={"obj": object()})
        [m] = self.messages()
        self.assertIsInstance(m["fields"]["obj"], str)


if __name__ == "__main__":
    unittest.main()

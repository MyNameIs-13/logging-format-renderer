import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dbfixlog  # noqa: E402
import helpers  # noqa: E402
from helpers import read_records  # noqa: E402

THIS_FILE = os.path.basename(__file__)


def lineno_of(marker):
    return helpers.lineno_of(__file__, marker)


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

    def test_nested_scopes_match_spec_example(self):
        # SPEC 3.6: start/end carry the parent's path, inner records the full path.
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            log.info("connected")
            with dbfixlog.scope("orphan-check", msg="pass 1"):
                with dbfixlog.scope("customer", key={"id": 42},
                                    label={"name": "ACME"}):
                    log.info("deleting")
        got = [(r["type"], r.get("id"), r.get("scope")) for r in self.body()]
        self.assertEqual(got, [
            ("message", None, None),
            ("scope_start", 1, None),
            ("scope_start", 2, [1]),
            ("message", None, [1, 2]),
            ("scope_end", 2, [1]),
            ("scope_end", 1, None),
        ])
        inner_start = self.body()[2]
        self.assertEqual(inner_start["key"], {"id": 42})
        self.assertEqual(inner_start["label"], {"name": "ACME"})

    def test_sibling_scopes_get_fresh_ids_and_path_resets_after_exit(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            with dbfixlog.scope("customer", key={"id": 42}):
                pass
            with dbfixlog.scope("customer", key={"id": 42}):
                pass
            log.info("after")
        recs = self.body()
        self.assertEqual([r.get("id") for r in recs], [1, 1, 2, 2, None])
        self.assertNotIn("scope", recs[-1])

    def test_ids_restart_per_run(self):
        with dbfixlog.run(self.path, mode="dry", console=False):
            with dbfixlog.scope("a"):
                pass
        second = os.path.join(self.dir, "second.jsonl")
        with dbfixlog.run(second, mode="dry", console=False):
            with dbfixlog.scope("a"):
                pass
        self.assertEqual(read_records(second)[1]["id"], 1)

    def test_escaping_exception_ends_scope_as_error_and_reraises(self):
        with dbfixlog.run(self.path, mode="dry", console=False) as log:
            with self.assertRaises(ZeroDivisionError):
                with dbfixlog.scope("customer", key={"id": 7}):
                    1 / 0
            log.info("after")
        start, end, after = self.body()
        self.assertEqual(end["type"], "scope_end")
        self.assertEqual(end["outcome"], "error")
        self.assertEqual(end["level"], "ERROR")
        self.assertEqual(end["exc"]["type"], "ZeroDivisionError")
        self.assertIn("1 / 0", end["exc"]["traceback"])
        self.assertNotIn("scope", after)

    def test_caught_exception_inside_scope_leaves_it_ok(self):
        with dbfixlog.run(self.path, mode="dry", console=False):
            with dbfixlog.scope("customer"):
                try:
                    raise ValueError("handled")
                except ValueError:
                    pass
        self.assertEqual(self.body()[-1]["outcome"], "ok")

    def test_start_and_end_written_even_above_info(self):
        with dbfixlog.run(self.path, mode="dry", console=False,
                          level=logging.ERROR) as log:
            with dbfixlog.scope("phase"):
                log.warning("filtered out")
        self.assertEqual([r["type"] for r in self.body()],
                         ["scope_start", "scope_end"])

    def test_threads_keep_separate_paths(self):
        ready = threading.Barrier(2)

        def worker(name):
            with dbfixlog.scope("worker", key={"name": name}):
                ready.wait()  # both Scopes open at once
                logging.getLogger("w").info(name)
                ready.wait()

        with dbfixlog.run(self.path, mode="dry", console=False):
            with dbfixlog.scope("main"):
                threads = [threading.Thread(target=worker, args=(n,))
                           for n in ("a", "b")]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
        recs = self.body()
        ids = {r["key"]["name"]: r["id"] for r in recs
               if r["type"] == "scope_start" and r["kind"] == "worker"}
        msgs = {r["msg"]: r for r in recs if r["type"] == "message"}
        self.assertEqual(sorted(ids.values()), [2, 3])
        # A worker thread starts with no path: the main thread's Scope is not inherited.
        self.assertEqual(msgs["a"]["scope"], [ids["a"]])
        self.assertEqual(msgs["b"]["scope"], [ids["b"]])

    def test_decorator_opens_a_fresh_scope_per_call(self):
        @dbfixlog.scope("orphan-check", msg="check")
        def check(n):
            logging.getLogger("x").info("n=%d", n)
            return n * 2

        with dbfixlog.run(self.path, mode="dry", console=False):
            self.assertEqual(check(1), 2)  # MARK-deco
            check(2)
        recs = self.body()
        self.assertEqual([(r["type"], r.get("id"), r.get("scope")) for r in recs], [
            ("scope_start", 1, None), ("message", None, [1]), ("scope_end", 1, None),
            ("scope_start", 2, None), ("message", None, [2]), ("scope_end", 2, None),
        ])
        self.assertEqual(recs[0]["kind"], "orphan-check")
        self.assertEqual(recs[0]["msg"], "check")
        self.assertEqual(recs[0]["src"], "%s:%d" % (THIS_FILE, lineno_of("MARK-deco")))
        self.assertEqual(check.__name__, "check")

    def test_outside_a_run_scope_is_transparent(self):
        with dbfixlog.scope("phase"):
            value = 3
        self.assertEqual(value, 3)
        with self.assertRaises(KeyError):
            with dbfixlog.scope("phase"):
                raise KeyError("x")


if __name__ == "__main__":
    unittest.main()

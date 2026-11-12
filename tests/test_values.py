"""Value encoding (SPEC 3.5), observed through the Log File."""

import datetime
import decimal
import json
import logging
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

import dbfixlog  # noqa: E402


def read_records(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


class ValueTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "run.jsonl")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def messages(self):
        return [r for r in read_records(self.path) if r["type"] == "message"]

    def logged(self, value, **run_kwargs):
        """Log ``value`` as ``fields={"v": value}``; return the written value."""
        with dbfixlog.run(self.path, mode="dry", console=False,
                          **run_kwargs) as log:
            log.info("v", fields={"v": value})
        [m] = self.messages()
        return m["fields"]["v"]

    def test_nan_and_infinities_become_strings(self):
        self.assertEqual(self.logged(float("nan")), "NaN")
        self.assertEqual(self.logged(float("inf"), overwrite=True), "Infinity")
        self.assertEqual(self.logged(float("-inf"), overwrite=True),
                         "-Infinity")

    def test_decimal_keeps_its_scale(self):
        self.assertEqual(self.logged(decimal.Decimal("12.30")), "12.30")

    def test_naive_datetime_is_iso_without_offset(self):
        v = datetime.datetime(2026, 11, 22, 5, 35, 50, 123000)
        self.assertEqual(self.logged(v), "2026-11-22T05:35:50.123000")

    def test_aware_datetime_keeps_its_offset_unconverted(self):
        tz = datetime.timezone(datetime.timedelta(hours=1))
        v = datetime.datetime(2026, 11, 22, 5, 35, 50, tzinfo=tz)
        self.assertEqual(self.logged(v), "2026-11-22T05:35:50+01:00")

    def test_date_and_time_objects_are_iso(self):
        self.assertEqual(self.logged(datetime.date(2026, 11, 22)), "2026-11-22")
        self.assertEqual(self.logged(datetime.time(5, 35, 50), overwrite=True),
                         "05:35:50")


if __name__ == "__main__":
    unittest.main()

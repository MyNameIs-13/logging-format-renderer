"""Value encoding (SPEC 3.5), observed through the Log File."""

import datetime
import decimal
import enum
import ipaddress
import json
import logging
import os
import shutil
import sys
import tempfile
import unittest
import uuid

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

    def test_none_and_native_json_types_pass_through(self):
        v = {"n": None, "i": 3, "f": 1.5, "b": True, "s": "x"}
        self.assertEqual(self.logged(v), v)

    def test_date_strings_are_written_as_received(self):
        self.assertEqual(self.logged("20261122053550"), "20261122053550")

    def test_nested_dict_list_tuple(self):
        v = {"a": [1, (2, 3)], "b": {"c": (4,)}}
        self.assertEqual(self.logged(v), {"a": [1, [2, 3]], "b": {"c": [4]}})

    def test_set_becomes_sorted_array(self):
        self.assertEqual(self.logged({3, 1, 2}), [1, 2, 3])
        self.assertEqual(self.logged(frozenset("cab"), overwrite=True),
                         ["a", "b", "c"])

    def test_unsortable_set_still_becomes_array(self):
        v = self.logged({1, "a", None})
        self.assertEqual(len(v), 3)
        self.assertEqual(set(map(repr, v)), {"1", "'a'", "None"})

    def test_long_text_is_truncated_at_default_1000(self):
        self.assertEqual(self.logged("x" * 1000), "x" * 1000)
        self.assertEqual(self.logged("y" * 1001, overwrite=True),
                         {"$truncated": "y" * 1000, "length": 1001})

    def test_max_text_sets_the_limit_for_nested_text(self):
        v = self.logged({"a": ["abcdef"]}, max_text=4)
        self.assertEqual(v, {"a": [{"$truncated": "abcd", "length": 6}]})

    def test_msg_is_not_a_value_slot_and_is_not_truncated(self):
        with dbfixlog.run(self.path, mode="dry", console=False,
                          max_text=4) as log:
            log.info("a long message")
        [m] = self.messages()
        self.assertEqual(m["msg"], "a long message")

    def test_bytes_become_hex_of_first_64_bytes(self):
        self.assertEqual(self.logged(b"\x00\xffA"),
                         {"$bytes": "00ff41", "length": 3})
        v = self.logged(bytes(range(100)), overwrite=True)
        self.assertEqual(v, {"$bytes": bytes(range(64)).hex(), "length": 100})
        self.assertEqual(len(v["$bytes"]), 128)
        self.assertEqual(self.logged(bytearray(b"\x01"), overwrite=True),
                         {"$bytes": "01", "length": 1})

    def test_uuid_ip_and_other_types_use_str(self):
        u = uuid.UUID("12345678-1234-5678-1234-567812345678")
        self.assertEqual(self.logged(u), "12345678-1234-5678-1234-567812345678")
        self.assertEqual(self.logged(ipaddress.ip_address("10.0.0.1"),
                                     overwrite=True), "10.0.0.1")

        class Thing(object):
            def __str__(self):
                return "thing!"
        self.assertEqual(self.logged(Thing(), overwrite=True), "thing!")

    def test_enum_is_written_as_its_value(self):
        class Color(enum.Enum):
            RED = "red"
            BLUE = 2
        self.assertEqual(self.logged(Color.RED), "red")
        self.assertEqual(self.logged(Color.BLUE, overwrite=True), 2)

    def test_failing_str_gives_unencodable(self):
        class Bad(object):
            def __str__(self):
                raise ValueError("boom")

            def __repr__(self):
                return "<Bad>"
        self.assertEqual(self.logged(Bad()), {"$unencodable": "<Bad>"})

    def test_failing_str_and_repr_gives_error_text(self):
        class Worse(object):
            def __str__(self):
                raise ValueError("boom")

            def __repr__(self):
                raise ValueError("boom")
        v = self.logged({"w": Worse(), "ok": 1})
        self.assertEqual(v["ok"], 1)
        self.assertIn("ValueError: boom", v["w"]["$unencodable"])

    def test_strict_raises_instead_of_unencodable(self):
        class Bad(object):
            def __str__(self):
                raise ValueError("boom")
        with dbfixlog.run(self.path, mode="dry", console=False,
                          strict=True) as log:
            with self.assertRaises(ValueError):
                log.info("v", fields={"v": Bad()})
        self.assertEqual(self.messages(), [])


if __name__ == "__main__":
    unittest.main()

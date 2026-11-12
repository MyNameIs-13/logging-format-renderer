"""Render CLI (dbfixlog_render.py), tested through the command line and the embedded payload."""
import base64
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "dbfixlog_render.py")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "basic.jsonl")

PAYLOAD_RE = re.compile(
    r'<script type="application/json" id="dbfixlog-payload">([^<]*)</script>')


def fixture_lines():
    with open(FIXTURE, encoding="utf-8") as f:
        return f.read().splitlines()


def decode_payload(html):
    m = PAYLOAD_RE.search(html)
    if m is None:
        raise AssertionError("no payload block in Report")
    return json.loads(gzip.decompress(base64.b64decode(m.group(1))).decode("utf-8"))


class RenderCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def write_log(self, text, name="run.jsonl"):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as f:
            f.write(text.encode("utf-8") if isinstance(text, str) else text)
        return path

    def log_from(self, lines, name="run.jsonl", trailing_newline=True):
        text = "\n".join(lines) + ("\n" if trailing_newline else "")
        return self.write_log(text, name)

    def render(self, *args):
        proc = subprocess.run(
            [sys.executable, SCRIPT] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.dir)
        return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8")

    def report(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()


class DefaultRender(RenderCase):
    def test_writes_report_next_to_log_file_with_all_records_and_line_numbers(self):
        log = self.log_from(fixture_lines())
        code, out, err = self.render(log)
        self.assertEqual(code, 0, err)
        payload = decode_payload(self.report(os.path.join(self.dir, "run.html")))
        self.assertEqual(len(payload["records"]), 10)
        self.assertEqual(payload["lines"], list(range(1, 11)))
        self.assertEqual(payload["records"][4]["check"], "order-without-lines")
        self.assertEqual(payload["records"][6]["changes"]["note"]["new"],
                         "cleaned <b>&amp;</b> </script> ünïcode")
        self.assertEqual(payload["notices"], [])
        self.assertFalse(payload["unfinished"])

    def test_existing_report_is_overwritten(self):
        log = self.log_from(fixture_lines())
        self.write_log("old report", "run.html")
        code, _, err = self.render(log)
        self.assertEqual(code, 0, err)
        decode_payload(self.report(os.path.join(self.dir, "run.html")))

    def test_success_prints_one_summary_line_with_count_and_size_to_stderr(self):
        log = self.log_from(fixture_lines())
        code, out, err = self.render(log)
        self.assertEqual(out, "")
        size = os.path.getsize(os.path.join(self.dir, "run.html"))
        self.assertEqual(err.count("\n"), 1, err)
        self.assertTrue(err.startswith("dbfixlog_render: "), err)
        self.assertIn("10 records", err)
        self.assertIn("{:,} bytes".format(size), err)


class Title(RenderCase):
    def rendered(self, lines, *args):
        log = self.log_from(lines, name="cleanup-2026.jsonl")
        code, out, err = self.render(log, "-o", "-", *args)
        self.assertEqual(code, 0, err)
        return out, decode_payload(out)

    def test_title_flag_wins_over_run_header_title(self):
        out, payload = self.rendered(fixture_lines(), "--title", "Nightly <fix> & check")
        self.assertEqual(payload["title"], "Nightly <fix> & check")
        self.assertIn("<title>Nightly &lt;fix&gt; &amp; check</title>", out)

    def test_run_header_title_is_used_without_flag(self):
        _, payload = self.rendered(fixture_lines())
        self.assertEqual(payload["title"], "Orphaned orders cleanup")

    def test_log_file_name_is_the_fallback(self):
        lines = fixture_lines()
        header = json.loads(lines[0])
        del header["title"]
        lines[0] = json.dumps(header)
        _, payload = self.rendered(lines)
        self.assertEqual(payload["title"], "cleanup-2026.jsonl")


class PayloadMeta(RenderCase):
    def test_payload_names_renderer_version_and_source_file(self):
        log = self.log_from(fixture_lines())
        code, out, err = self.render(log, "-o", "-")
        payload = decode_payload(out)
        self.assertEqual(payload["payload"], 1)
        self.assertRegex(payload["renderer"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(payload["source"], "run.jsonl")


class OutputPath(RenderCase):
    def test_dash_o_path_writes_there_and_not_next_to_log(self):
        log = self.log_from(fixture_lines())
        target = os.path.join(self.dir, "elsewhere.html")
        code, _, err = self.render(log, "-o", target)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(decode_payload(self.report(target))["records"]), 10)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "run.html")))

    def test_dash_o_dash_writes_report_to_stdout_and_summary_to_stderr(self):
        log = self.log_from(fixture_lines())
        code, out, err = self.render(log, "-o", "-")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(decode_payload(out)["records"]), 10)
        self.assertIn("10 records", err)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "run.html")))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "-")))


if __name__ == "__main__":
    unittest.main()

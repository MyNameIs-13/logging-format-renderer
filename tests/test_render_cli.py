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

    def render(self, *args, env=None):
        proc = subprocess.run(
            [sys.executable, SCRIPT] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.dir, env=env)
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


class InputHandling(RenderCase):
    def render_payload(self, log, *args):
        code, out, err = self.render(log, "-o", "-", *args)
        self.assertEqual(code, 0, err)
        return decode_payload(out), err

    def test_unfinished_file_renders_and_is_marked_unfinished(self):
        log = self.log_from(fixture_lines()[:-1])
        payload, _ = self.render_payload(log)
        self.assertTrue(payload["unfinished"])
        self.assertEqual(len(payload["records"]), 9)
        self.assertEqual(payload["notices"], [])

    def test_partial_last_line_is_skipped_with_notice(self):
        lines = fixture_lines()[:-1] + ['{"ts":"2026-11-12T20:01:01.000Z","lev']
        log = self.log_from(lines, trailing_newline=False)
        payload, err = self.render_payload(log)
        self.assertEqual(len(payload["records"]), 9)
        self.assertTrue(payload["unfinished"])
        self.assertEqual(payload["notices"], [{
            "kind": "incomplete_last_line",
            "line": 10,
            "message": "last line incomplete, file may still be written",
        }])

    def test_complete_json_without_trailing_newline_is_kept(self):
        log = self.log_from(fixture_lines(), trailing_newline=False)
        payload, _ = self.render_payload(log)
        self.assertEqual(len(payload["records"]), 10)
        self.assertEqual(payload["lines"][-1], 10)
        self.assertFalse(payload["unfinished"])
        self.assertEqual(payload["notices"], [])

    def test_malformed_lines_are_skipped_with_notice_and_stderr_warning(self):
        lines = fixture_lines()
        lines.insert(2, "not json at all")
        lines.insert(4, "[1, 2, 3]")
        lines.insert(6, "")
        log = self.log_from(lines)
        payload, err = self.render_payload(log)
        self.assertEqual(len(payload["records"]), 10)
        self.assertEqual(payload["lines"], [1, 2, 4, 6] + list(range(8, 14)))
        self.assertEqual(payload["notices"], [{
            "kind": "malformed_lines",
            "count": 3,
            "lines": [3, 5, 7],
            "samples": [
                {"line": 3, "text": "not json at all"},
                {"line": 5, "text": "[1, 2, 3]"},
                {"line": 7, "text": ""},
            ],
            "message": "3 malformed lines skipped",
        }])
        warnings = [l for l in err.splitlines() if "malformed" in l]
        self.assertEqual(len(warnings), 1, err)
        self.assertTrue(warnings[0].startswith("dbfixlog_render: warning: "))
        self.assertIn("3, 5, 7", warnings[0])

    def test_malformed_notice_keeps_only_the_first_few_samples(self):
        lines = fixture_lines()
        for i in range(8):
            lines.insert(1, "bad %d" % i)
        payload, _ = self.render_payload(self.log_from(lines))
        notice = payload["notices"][0]
        self.assertEqual(notice["count"], 8)
        self.assertEqual(notice["lines"], list(range(2, 10)))
        self.assertEqual(len(notice["samples"]), 5)

    def test_non_utf8_and_nan_lines_count_as_malformed(self):
        lines = [l.encode("utf-8") for l in fixture_lines()]
        lines.insert(1, b'{"type":"message","msg":"\xff\xfe"}')
        lines.insert(2, b'{"type":"message","x":NaN}')
        log = self.write_log(b"\n".join(lines) + b"\n")
        payload, _ = self.render_payload(log)
        self.assertEqual(payload["notices"][0]["lines"], [2, 3])

    def test_strict_aborts_on_malformed_lines_with_exit_4(self):
        lines = fixture_lines()
        lines.insert(2, "not json at all")
        log = self.log_from(lines)
        code, out, err = self.render(log, "--strict")
        self.assertEqual(code, 4)
        self.assertEqual(len(err.splitlines()), 1, err)
        self.assertTrue(err.startswith("dbfixlog_render: "))
        self.assertIn("line 3", err)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "run.html")))

    def test_strict_with_clean_file_succeeds(self):
        code, _, err = self.render(self.log_from(fixture_lines()), "--strict")
        self.assertEqual(code, 0, err)

    def test_unknown_record_type_is_kept(self):
        lines = fixture_lines()
        lines.insert(1, '{"ts":"2026-11-12T20:01:00.100Z","level":"INFO","logger":"x","type":"metric","src":"a.py:1"}')
        payload, _ = self.render_payload(self.log_from(lines))
        self.assertEqual(payload["records"][1]["type"], "metric")


def with_format(lines, fmt):
    header = json.loads(lines[0])
    if fmt is None:
        del header["format"]
    else:
        header["format"] = fmt
    return [json.dumps(header)] + lines[1:]


class FormatVersion(RenderCase):
    def test_unknown_major_exits_3_naming_formats_and_update_advice(self):
        log = self.log_from(with_format(fixture_lines(), "2.0"))
        code, out, err = self.render(log)
        self.assertEqual(code, 3)
        self.assert_one_error_line(err)
        self.assertIn("2.0", err)
        self.assertIn("reads format major 1", err)
        self.assertIn("update dbfixlog_render.py", err)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "run.html")))

    def test_newer_minor_renders_with_notice(self):
        log = self.log_from(with_format(fixture_lines(), "1.7"))
        code, out, err = self.render(log, "-o", "-")
        self.assertEqual(code, 0, err)
        notices = decode_payload(out)["notices"]
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]["kind"], "newer_minor")
        self.assertEqual(notices[0]["format"], "1.7")
        self.assertEqual(notices[0]["reads"], "1.0")
        self.assertIn("1.7", notices[0]["message"])

    def test_known_minor_has_no_notice(self):
        code, out, err = self.render(self.log_from(fixture_lines()), "-o", "-")
        self.assertEqual(decode_payload(out)["notices"], [])

    def test_missing_or_garbled_format_is_not_a_log_file(self):
        for fmt in (None, "one", 1, "1"):
            with self.subTest(fmt=fmt):
                code, _, err = self.render(self.log_from(with_format(fixture_lines(), fmt)))
                self.assertEqual(code, 1, err)
                self.assert_one_error_line(err)

    def assert_one_error_line(self, err):
        self.assertEqual(len(err.splitlines()), 1, err)
        self.assertTrue(err.startswith("dbfixlog_render: "), err)


class FatalErrors(RenderCase):
    def assert_fatal(self, code, args, needle):
        got, out, err = self.render(*args)
        self.assertEqual(got, code, err)
        self.assertEqual(out, "")
        self.assertEqual(len(err.splitlines()), 1, err)
        self.assertTrue(err.startswith("dbfixlog_render: "), err)
        self.assertIn(needle, err)
        return err

    def test_missing_log_file_exits_1(self):
        self.assert_fatal(1, [os.path.join(self.dir, "nope.jsonl")], "nope.jsonl")

    def test_directory_as_log_file_exits_1(self):
        self.assert_fatal(1, [self.dir], self.dir)

    def test_empty_file_exits_1(self):
        self.assert_fatal(1, [self.write_log("")], "not a Log File")

    def test_first_line_not_run_start_exits_1(self):
        self.assert_fatal(1, [self.log_from(fixture_lines()[1:])], "not a Log File")

    def test_first_line_malformed_exits_1_even_without_strict(self):
        self.assert_fatal(1, [self.log_from(["garbage"] + fixture_lines())], "not a Log File")

    def test_unwritable_output_exits_1(self):
        log = self.log_from(fixture_lines())
        self.assert_fatal(1, [log, "-o", os.path.join(self.dir, "no", "such", "dir.html")],
                          "dir.html")

    def test_usage_errors_exit_2_with_one_line(self):
        self.assert_fatal(2, [], "usage")
        self.assert_fatal(2, ["a.jsonl", "--bogus"], "--bogus")
        self.assert_fatal(2, ["a.jsonl", "-o"], "-o")

    def test_help_documents_exit_codes(self):
        code, out, err = self.render("--help")
        self.assertEqual(code, 0)
        for n in range(5):
            self.assertRegex(out, r"(?m)^\s+%d\s" % n)
        for flag in ("-o", "--title", "--open", "--strict"):
            self.assertIn(flag, out)


class OpenFlag(RenderCase):
    def browser_env(self):
        recorder = os.path.join(self.dir, "recorder.py")
        self.opened = os.path.join(self.dir, "opened.txt")
        with open(recorder, "w") as f:
            f.write("import sys\nopen(%r, 'a').write(sys.argv[1] + '\\n')\n" % self.opened)
        env = dict(os.environ)
        env["BROWSER"] = "{} {} %s".format(sys.executable, recorder)
        return env

    def opened_urls(self):
        if not os.path.exists(self.opened):
            return []
        with open(self.opened) as f:
            return f.read().split()

    def test_open_opens_the_written_report_as_file_url(self):
        log = self.log_from(fixture_lines())
        code, _, err = self.render(log, "--open", env=self.browser_env())
        self.assertEqual(code, 0, err)
        self.assertEqual(self.opened_urls(),
                         ["file://" + os.path.join(self.dir, "run.html")])

    def test_report_is_not_opened_without_flag(self):
        code, _, err = self.render(self.log_from(fixture_lines()), env=self.browser_env())
        self.assertEqual(code, 0, err)
        self.assertEqual(self.opened_urls(), [])


class Standalone(RenderCase):
    def copy_renderer(self, *names):
        dest = os.path.join(self.dir, "tools")
        os.mkdir(dest)
        for name in names:
            shutil.copy(os.path.join(ROOT, name), dest)
        return os.path.join(dest, "dbfixlog_render.py")

    def run_copy(self, script, *args):
        proc = subprocess.run([sys.executable, "-I", script] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.dir)
        return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8")

    def test_renders_when_copied_alone_with_report_js_and_css(self):
        script = self.copy_renderer("dbfixlog_render.py", "report.js", "report.css")
        code, out, err = self.run_copy(script, self.log_from(fixture_lines()), "-o", "-")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(decode_payload(out)["records"]), 10)
        with open(os.path.join(ROOT, "report.js"), encoding="utf-8") as f:
            self.assertIn(f.read().strip().splitlines()[0], out)

    def test_missing_report_js_is_a_one_line_error(self):
        script = self.copy_renderer("dbfixlog_render.py", "report.css")
        code, out, err = self.run_copy(script, self.log_from(fixture_lines()))
        self.assertEqual(code, 1)
        self.assertEqual(len(err.splitlines()), 1, err)
        self.assertIn("report.js", err)


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

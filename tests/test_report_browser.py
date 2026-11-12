"""Headless Firefox check: a rendered Report decodes its embedded payload from file://.

Skipped when firefox or node is not on PATH, or when DBFIXLOG_SKIP_BROWSER is set.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "dbfixlog_render.py")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "basic.jsonl")
DRIVER = os.path.join(ROOT, "tests", "browser", "bidi_eval.mjs")

# What the page exposes once report.js has run: its state, the record count, the visible text.
PROBE = ("(() => { const d = document.documentElement.dataset;"
         " return d.state ? JSON.stringify({state: d.state, count: d.recordCount,"
         " error: d.error || null, text: document.getElementById('app').textContent}) : ''; })()")

FIREFOX = shutil.which("firefox")
NODE = shutil.which("node")


@unittest.skipIf(os.environ.get("DBFIXLOG_SKIP_BROWSER"), "DBFIXLOG_SKIP_BROWSER set")
@unittest.skipUnless(FIREFOX and NODE, "needs firefox and node on PATH")
class StubReportInFirefox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        os.mkdir(os.path.join(cls.dir, "profile"))
        cls.firefox = subprocess.Popen(
            [FIREFOX, "--headless", "--no-remote", "--profile", os.path.join(cls.dir, "profile"),
             "--remote-debugging-port", "0", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        cls.ws_url = cls._wait_for_bidi()
        # Keep draining Firefox's chatter so a full pipe never blocks it.
        threading.Thread(target=cls.firefox.stderr.read, daemon=True).start()

    @classmethod
    def _wait_for_bidi(cls):
        deadline = time.time() + 30
        while time.time() < deadline:
            line = cls.firefox.stderr.readline().decode("utf-8", "replace")
            m = re.search(r"WebDriver BiDi listening on (ws://\S+)", line)
            if m:
                return m.group(1)
            if not line and cls.firefox.poll() is not None:
                break
        cls.tearDownClass()
        raise RuntimeError("Firefox did not start WebDriver BiDi")

    @classmethod
    def tearDownClass(cls):
        cls.firefox.kill()
        cls.firefox.wait()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def open_report(self, report):
        proc = subprocess.run(
            [NODE, DRIVER, self.ws_url, Path(report).as_uri(), PROBE, "10000"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        return json.loads(proc.stdout.decode("utf-8"))

    def test_stub_decodes_embedded_payload_from_file_url(self):
        report = os.path.join(self.dir, "basic.html")
        subprocess.run([sys.executable, SCRIPT, FIXTURE, "-o", report], check=True,
                       stderr=subprocess.DEVNULL)
        page = self.open_report(report)
        self.assertEqual(page["state"], "ready", page)
        self.assertEqual(page["count"], "10")
        self.assertIn("10 records", page["text"])


if __name__ == "__main__":
    unittest.main()

"""Helpers shared by the test modules."""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENDER_SCRIPT = os.path.join(ROOT, "dbfixlog_render.py")


def read_records(path):
    """The records of a Log File, one per line."""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def lineno_of(path, marker):
    """The number of the line in ``path`` that holds ``marker``."""
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if marker in line and "lineno_of" not in line:
                return i
    raise AssertionError(marker)


def render_records(directory, name, records):
    """Write ``records`` as ``<name>.jsonl`` in ``directory``, render it to
    ``<name>.html`` next to it, and return the Report's path."""
    log = os.path.join(directory, name + ".jsonl")
    with open(log, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    report = os.path.join(directory, name + ".html")
    subprocess.run([sys.executable, RENDER_SCRIPT, log, "-o", report], check=True,
                   stderr=subprocess.DEVNULL)
    return report

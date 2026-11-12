#!/usr/bin/env python3
"""Render a Database Fix Logging Log File into a self-contained HTML Report.

Stdlib only, Python 3.6.3+. Does not import dbfixlog.py, so it can be copied on its own,
together with report.js and report.css, which it reads at render time and inlines.
"""
import argparse
import base64
import gzip
import html
import io
import json
import os
import sys

__version__ = "0.1.0"
# Shape version of the payload embedded in the Report (documented at the top of report.js).
PAYLOAD_VERSION = 1

PROG = "dbfixlog_render"
HERE = os.path.dirname(os.path.abspath(__file__))


MAX_SAMPLES = 5
MAX_SAMPLE_CHARS = 200
INCOMPLETE_MESSAGE = "last line incomplete, file may still be written"


class Fatal(Exception):
    """A fatal error: one stderr line prefixed with the program name, then exit `code`."""

    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code


def _reject_constant(name):
    raise ValueError("non-JSON constant " + name)


def _parse_line(line):
    """The record on one Log File line, or None if the line is malformed."""
    try:
        value = json.loads(line.decode("utf-8"), parse_constant=_reject_constant)
    except ValueError:  # includes UnicodeDecodeError and json's decode error
        return None
    return value if isinstance(value, dict) else None


def _load_records(raw):
    """Split a snapshot of the Log File into records, their 1-based line numbers, and the
    numbers and text of malformed lines. A last line without a trailing newline is
    returned separately as incomplete (its line number), never parsed."""
    chunks = raw.split(b"\n")
    incomplete = None
    if chunks[-1] == b"":
        chunks.pop()  # the file ends with a newline
    else:
        incomplete = len(chunks)
        chunks.pop()
    records, lines, bad = [], [], []
    for number, line in enumerate(chunks, start=1):
        record = _parse_line(line)
        if record is None:
            bad.append((number, line))
        else:
            records.append(record)
            lines.append(number)
    return records, lines, bad, incomplete


def _malformed_notice(bad):
    samples = []
    for number, line in bad[:MAX_SAMPLES]:
        text = line.decode("utf-8", "replace").rstrip("\r")
        if len(text) > MAX_SAMPLE_CHARS:
            text = text[:MAX_SAMPLE_CHARS] + "…"
        samples.append({"line": number, "text": text})
    count = len(bad)
    return {
        "kind": "malformed_lines",
        "count": count,
        "lines": [number for number, _ in bad],
        "samples": samples,
        "message": "{} malformed line{} skipped".format(count, "" if count == 1 else "s"),
    }


def _line_list(numbers, limit=20):
    text = ", ".join(str(n) for n in numbers[:limit])
    return text + (", …" if len(numbers) > limit else "")


def _title(flag, header, log_path):
    """--title, then run_start.title, then the Log File's name."""
    if flag is not None:
        return flag
    if isinstance(header.get("title"), str) and header["title"]:
        return header["title"]
    return os.path.basename(log_path)


def _gzip_b64(data):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as f:
        f.write(data)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _read_asset(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def build_html(payload, title):
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")
    css = _read_asset("report.css").replace("</style", "<\\/style")
    js = _read_asset("report.js").replace("</script", "<\\/script")
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<meta name=\"generator\" content=\"dbfixlog_render " + __version__ + "\">\n"
        "<title>" + html.escape(title) + "</title>\n"
        "<style>\n" + css + "\n</style>\n</head>\n<body>\n"
        "<div id=\"app\"></div>\n"
        "<script type=\"application/json\" id=\"dbfixlog-payload\">"
        + _gzip_b64(data) + "</script>\n"
        "<script>\n" + js + "\n</script>\n</body>\n</html>\n"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("log")
    parser.add_argument("-o", dest="output", metavar="PATH|-")
    parser.add_argument("--title", metavar="TEXT")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        return _render(args)
    except Fatal as e:
        sys.stderr.write("{}: {}\n".format(PROG, e))
        return e.code


def _render(args):
    with open(args.log, "rb") as f:
        raw = f.read()
    records, lines, bad, incomplete = _load_records(raw)
    notices = []
    if bad:
        if args.strict:
            raise Fatal(4, "{}: {} malformed line{} (line {}); not rendering under --strict".format(
                args.log, len(bad), "" if len(bad) == 1 else "s", _line_list([n for n, _ in bad])))
        notices.append(_malformed_notice(bad))
        sys.stderr.write("{}: warning: {}: skipped {} malformed line{}: {}\n".format(
            PROG, args.log, len(bad), "" if len(bad) == 1 else "s",
            _line_list([n for n, _ in bad])))
    if incomplete is not None:
        notices.append({"kind": "incomplete_last_line", "line": incomplete,
                        "message": INCOMPLETE_MESSAGE})
    title = _title(args.title, records[0], args.log)
    payload = {
        "payload": PAYLOAD_VERSION,
        "renderer": __version__,
        "source": os.path.basename(args.log),
        "title": title,
        "unfinished": not any(r.get("type") == "run_end" for r in records),
        "notices": notices,
        "records": records,
        "lines": lines,
    }
    report = build_html(payload, title).encode("utf-8")
    if args.output == "-":
        sys.stdout.buffer.write(report)
        sys.stdout.buffer.flush()
        where = "stdout"
    else:
        where = args.output or os.path.splitext(args.log)[0] + ".html"
        with open(where, "wb") as f:
            f.write(report)
    sys.stderr.write("{}: wrote {} records to {} ({:,} bytes)\n".format(
        PROG, len(records), where, len(report)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

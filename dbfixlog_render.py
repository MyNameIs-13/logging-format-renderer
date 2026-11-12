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


def _load_records(raw):
    records = []
    lines = []
    for number, line in enumerate(raw.split(b"\n"), start=1):
        if not line:
            continue
        records.append(json.loads(line.decode("utf-8")))
        lines.append(number)
    return records, lines


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
    args = parser.parse_args(argv)
    with open(args.log, "rb") as f:
        raw = f.read()
    records, lines = _load_records(raw)
    title = _title(args.title, records[0], args.log)
    payload = {
        "payload": PAYLOAD_VERSION,
        "renderer": __version__,
        "source": os.path.basename(args.log),
        "title": title,
        "unfinished": False,
        "notices": [],
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

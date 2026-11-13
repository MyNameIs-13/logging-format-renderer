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
import pathlib
import sys
import types
import webbrowser

__version__ = "0.1.0"
# Format majors this renderer reads, each mapped to the newest minor it knows.
KNOWN_MINORS = types.MappingProxyType({1: 0})
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
    numbers and text of malformed lines. A last line without a trailing newline is kept
    if it parses as a whole record; otherwise it is a partial line, returned separately
    as incomplete (its line number)."""
    chunks = raw.split(b"\n")
    incomplete = None
    if chunks[-1] == b"":
        chunks.pop()  # the file ends with a newline
    elif _parse_line(chunks[-1]) is None:
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


def _plural(count, noun):
    return "{} {}{}".format(count, noun, "" if count == 1 else "s")


def _known_majors():
    return ", ".join(str(m) for m in sorted(KNOWN_MINORS))


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
        "lines": [number for number, _ in bad],
        "samples": samples,
        "message": "{} skipped".format(_plural(count, "malformed line")),
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
    path = os.path.join(HERE, name)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (IOError, OSError) as e:
        raise Fatal(1, "cannot read {} (it must sit next to dbfixlog_render.py): {}".format(
            path, e.strerror or e))


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


EPILOG = """\
exit codes:
  0  Report written (also for unfinished Runs, skipped lines and newer-minor notices)
  1  Log File unreadable, or its first line isn't a run_start (not a Log File);
     also when the Report or report.js/report.css can't be read or written
  2  usage error
  3  unknown major format: update dbfixlog_render.py
  4  --strict and malformed lines found

Every fatal error is one stderr line prefixed "dbfixlog_render:". The success
summary line (record count and Report size) also goes to stderr.
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        usage = " ".join(self.format_usage().split()[1:])  # one line, without "usage:"
        raise Fatal(2, "{} (usage: {})".format(message, usage))


def _parser():
    parser = _Parser(
        prog="dbfixlog_render.py",
        description="Render a Log File into a self-contained HTML Report "
                    "(renderer {}, reads format major {}).".format(
                        __version__, _known_majors()),
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log_file", metavar="LOG_FILE", help="the Log File (JSON Lines)")
    parser.add_argument("-o", dest="output", metavar="PATH|-",
                        help="output path, or - for stdout "
                             "(default: the Log File's stem with .html, next to it; overwritten)")
    parser.add_argument("--title", metavar="TEXT",
                        help="Report title (default: run_start.title, then the Log File's name)")
    parser.add_argument("--open", action="store_true",
                        help="open the Report in the default browser")
    parser.add_argument("--strict", action="store_true",
                        help="abort (exit 4) instead of skipping malformed lines")
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    return parser


def main(argv=None):
    try:
        args = _parser().parse_args(argv)
        return _render(args)
    except Fatal as e:
        sys.stderr.write("{}: {}\n".format(PROG, e))
        return e.code


def _check_format(header, log):
    fmt = header.get("format")
    parts = fmt.split(".") if isinstance(fmt, str) else []
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise Fatal(1, "{}: run_start has no valid format (got {}), not a Log File".format(
            log, json.dumps(fmt)))
    major, minor = int(parts[0]), int(parts[1])
    if major not in KNOWN_MINORS:
        raise Fatal(3, "{}: format {} is not supported; this renderer reads format major {}; "
                       "update dbfixlog_render.py".format(
                           log, fmt, _known_majors()))
    known = "{}.{}".format(major, KNOWN_MINORS[major])
    if minor > KNOWN_MINORS[major]:
        return {"kind": "newer_minor",
                "message": "Log File format {} is newer than {}, which this renderer knows; "
                           "newer fields may not be shown".format(fmt, known)}
    return None


def _read_log(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except (IOError, OSError) as e:
        raise Fatal(1, "cannot read {}: {}".format(path, e.strerror or e))


def _render(args):
    raw = _read_log(args.log_file)
    records, lines, bad, incomplete = _load_records(raw)
    if not records or lines[0] != 1 or records[0].get("type") != "run_start":
        raise Fatal(1, "{}: first line is not a run_start, not a Log File".format(args.log_file))
    notices = []
    newer = _check_format(records[0], args.log_file)
    if newer:
        notices.append(newer)
    if bad:
        what = _plural(len(bad), "malformed line")
        numbers = _line_list([n for n, _ in bad])
        if args.strict:
            raise Fatal(4, "{}: {} (line {}); not rendering under --strict".format(
                args.log_file, what, numbers))
        notices.append(_malformed_notice(bad))
        sys.stderr.write("{}: warning: {}: skipped {}: {}\n".format(PROG, args.log_file, what, numbers))
    if incomplete is not None:
        notices.append({"kind": "incomplete_last_line", "line": incomplete,
                        "message": INCOMPLETE_MESSAGE})
    title = _title(args.title, records[0], args.log_file)
    payload = {
        "payload": PAYLOAD_VERSION,
        "source": os.path.basename(args.log_file),
        "title": title,
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
        where = args.output or os.path.splitext(args.log_file)[0] + ".html"
        try:
            with open(where, "wb") as f:
                f.write(report)
        except (IOError, OSError) as e:
            raise Fatal(1, "cannot write {}: {}".format(where, e.strerror or e))
    sys.stderr.write("{}: wrote {} records to {} ({:,} bytes)\n".format(
        PROG, len(records), where, len(report)))
    if args.open and where != "stdout":
        webbrowser.open(pathlib.Path(os.path.abspath(where)).as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())

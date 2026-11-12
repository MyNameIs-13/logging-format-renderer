"""dbfixlog: stdlib-logging writer for Database Fix Log Files (JSON Lines).

Python 3.6.3+, stdlib only. See .scratch/db-fix-logging/SPEC.md.
"""

import datetime
import enum
import functools
import json
import logging
import os
import sys
import threading
import time
import traceback

__version__ = "0.1.0"

FORMAT_VERSION = "1.0"
LOGGER_NAME = "dbfixlog"

# The one namespaced LogRecord attribute that carries typed fields (SPEC 4.6).
# Pass it as ``extra={ATTR: {...}}``; its keys are merged into the record dict.
ATTR = "dbfixlog"

MODES = ("dry", "write")

_lock = threading.Lock()
_active = None  # the active _Run, or None


def _active_run():
    return _active


# --------------------------------------------------------------------------
# Value encoding (SPEC 3.5).
# --------------------------------------------------------------------------

# Record slots that hold logged *values*: they get the full SPEC 3.5
# encoding, including ``max_text`` truncation. Every other slot (msg,
# Run Header fields, exc, ...) is only made JSON-safe.
VALUE_SLOTS = ("key", "label", "fields", "changes")

DEFAULT_MAX_TEXT = 1000
BYTES_PREFIX = 64


def _encode(value, run=None, truncate=True, _open=None):
    """Return ``value`` in JSON-safe form, for display (SPEC 3.5).

    This is the single place that turns a Python value into something
    ``json.dumps(..., allow_nan=False)`` accepts. ``run`` carries the
    Run's ``encoders``, ``strict`` and ``max_text`` settings. With
    ``truncate=False`` long text is kept whole (non-value slots).

    A custom encoder (``encoders={Type: fn}``, matched along the value's
    MRO) wins over the built-in rules. Its result is encoded again, by
    the built-in rules alone if it has the same type as the input.

    ``_open`` holds the ids of the containers being encoded around this
    value: a container that contains itself becomes ``$unencodable``.
    """
    fn = _custom_encoder(value, run)
    if fn is not None:
        try:
            result = fn(value)
        except Exception as e:
            return _unencodable(value, e, run)
        if type(result) is type(value):
            return _builtin_encode(result, run, truncate, _open)
        return _encode(result, run, truncate, _open)
    return _builtin_encode(value, run, truncate, _open)


def _custom_encoder(value, run):
    encoders = getattr(run, "encoders", None)
    if not encoders:
        return None
    for cls in type(value).__mro__:
        fn = encoders.get(cls)
        if fn is not None:
            return fn
    return None


CONTAINERS = (dict, list, tuple, set, frozenset)


def _builtin_encode(value, run, truncate, _open=None):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, enum.Enum):
        return _encode(value.value, run, truncate, _open)
    if isinstance(value, str):
        limit = (getattr(run, "max_text", DEFAULT_MAX_TEXT) if run is not None
                 else DEFAULT_MAX_TEXT)
        if truncate and limit is not None and len(value) > limit:
            return {"$truncated": value[:limit], "length": len(value)}
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value:
            return "NaN"
        if value in (float("inf"), float("-inf")):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        data = bytes(value)
        return {"$bytes": data[:BYTES_PREFIX].hex(), "length": len(data)}
    if isinstance(value, CONTAINERS):
        if _open is None:
            _open = set()
        if id(value) in _open:
            return _unencodable(value, ValueError("value contains itself"),
                                run)
        _open.add(id(value))
        try:
            return _encode_container(value, run, truncate, _open)
        finally:
            _open.discard(id(value))
    return _str_or_unencodable(value, run)


def _encode_container(value, run, truncate, _open):
    if isinstance(value, dict):
        return {_encode_key(k, run): _encode(v, run, truncate, _open)
                for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        try:
            value = sorted(value)
        except TypeError:
            value = list(value)
    return [_encode(v, run, truncate, _open) for v in value]


def _encode_key(key, run):
    """A dict key as a JSON object key: ``str(key)``, or the
    ``$unencodable`` text when that raises."""
    text = _str_or_unencodable(key, run)
    if isinstance(text, dict):
        return "$unencodable: " + text["$unencodable"]
    return text


def _str_or_unencodable(value, run):
    try:
        return str(value)
    except Exception as e:
        return _unencodable(value, e, run)


def _unencodable(value, error, run):
    """``{"$unencodable": ...}`` for ``error``; re-raises it under strict."""
    if run is not None and run.strict:
        raise error
    try:
        text = repr(value)
    except Exception:
        text = "%s: %s" % (type(error).__name__, error)
    return {"$unencodable": text}


def _encode_record(rec, run=None):
    """Encode a whole record dict: value slots fully, the rest JSON-safe."""
    return {k: _encode(v, run, truncate=k in VALUE_SLOTS)
            for k, v in rec.items()}


# --------------------------------------------------------------------------
# Record building.
# --------------------------------------------------------------------------

def _format_ts(t):
    """ISO 8601 UTC with milliseconds: 2026-11-12T20:01:00.000Z."""
    ms = int(round((t - int(t)) * 1000))
    secs = int(t)
    if ms == 1000:
        secs, ms = secs + 1, 0
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(secs)) + ".%03dZ" % ms


def _path_ts(t):
    """The ``{ts}`` path form of a time: 20261112T200100Z."""
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(int(t)))


def _exc_dict(exc_info):
    etype, evalue, tb = exc_info
    return {
        "type": etype.__name__,
        # Encoded with str() at write time, so a raising __str__ becomes
        # $unencodable instead of losing the record.
        "message": evalue,
        "traceback": "".join(traceback.format_exception(etype, evalue, tb)),
    }


def _build_record(created, levelname, logger, rtype, src=None, msg=None,
                  exc_info=None, extra=None, scope=None):
    """The one place that builds a record dict, in field order.

    ``extra`` holds the type-specific fields (already JSON-safe or not:
    values pass through ``_encode`` at write time).
    """
    rec = {
        "ts": _format_ts(created),
        "level": levelname,
        "logger": logger,
        "type": rtype,
    }
    if src is not None:
        rec["src"] = src
    if scope:
        rec["scope"] = list(scope)
    if msg is not None:
        rec["msg"] = msg
    if extra:
        for k, v in extra.items():
            rec[k] = v
    if exc_info:
        rec["exc"] = _exc_dict(exc_info)
    return rec


def _record_from_logrecord(record):
    data = getattr(record, ATTR, None) or {}
    data = dict(data)
    rtype = data.pop("type", "message")
    scope = data.pop("scope", None)
    src = data.pop("src", None)
    if src is None:
        src = "%s:%d" % (os.path.basename(record.pathname), record.lineno)
    if "msg" in data:
        msg = data.pop("msg")
    else:
        msg = record.getMessage()
    exc_info = record.exc_info if record.exc_info and record.exc_info[0] else None
    return _build_record(
        record.created, record.levelname, record.name, rtype,
        src=src, msg=msg, exc_info=exc_info, extra=data, scope=scope,
    )


# --------------------------------------------------------------------------
# JSONL handler.
# --------------------------------------------------------------------------

class JsonlHandler(logging.Handler):
    """Writes one JSON object per line. Never raises from ``emit``."""

    def __init__(self, stream, run, level=logging.NOTSET):
        logging.Handler.__init__(self, level)
        self.stream = stream
        self.run = run

    def write_dict(self, rec):
        line = json.dumps(_encode_record(rec, self.run), ensure_ascii=False,
                          allow_nan=False, separators=(",", ":"))
        self.acquire()
        try:
            self.stream.write(line + "\n")
            self.stream.flush()
        finally:
            self.release()

    def emit(self, record):
        try:
            self.write_dict(_record_from_logrecord(record))
        except Exception:
            if self.run is not None and self.run.strict:
                raise
            self.handleError(record)


# --------------------------------------------------------------------------
# Console handler (SPEC 4.5).
# --------------------------------------------------------------------------

def _show(value):
    """A value as console text: strings bare, everything else ``str()``."""
    if value is None:
        return "null"
    if isinstance(value, dict):
        return "{%s}" % ",".join("%s:%s" % (k, _show(v))
                                 for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return "[%s]" % ",".join(_show(v) for v in value)
    return str(value)


def _show_values(value):
    """``{"id": 42}`` -> ``42``: the values of a key/label, space-joined."""
    if isinstance(value, dict):
        return " ".join(_show(v) for v in value.values())
    return _show(value)


def scope_label(kind, key=None, label=None):
    """The console label of a Scope: ``customer 42 ACME``."""
    parts = [str(kind)]
    for v in (key, label):
        if v is not None:
            parts.append(_show_values(v))
    return " ".join(p for p in parts if p)


class ConsoleHandler(logging.Handler):
    """The terse stderr view: one line per record, prefixed by the label
    of the innermost Scope. Changes and Findings are summarised from their
    ATTR fields; Messages use the stdlib message text. No colours."""

    def __init__(self, stream, run, level=logging.INFO):
        logging.Handler.__init__(self, level)
        self.stream = stream
        self.run = run
        self.setFormatter(logging.Formatter())

    def emit(self, record):
        try:
            data = getattr(record, ATTR, None) or {}
            rtype = data.get("type")
            if rtype == "change":
                body = self._change(data)
            elif rtype == "finding":
                body = self._finding(data)
            else:
                body = record.getMessage()
                if record.exc_info:
                    body += "\n" + self.formatter.formatException(
                        record.exc_info)
            self._line(record.created, record.levelno, record.levelname,
                       data.get("scope"), body)
        except Exception:
            if self.run is not None and self.run.strict:
                raise
            self.handleError(record)

    def write_scope(self, rec, levelno):
        """Console line for a scope_start (always) or an error scope_end."""
        try:
            label = self.run.scope_labels.get(rec["id"], "")
            if rec["type"] == "scope_start":
                body = "start " + label
            elif rec.get("outcome") == "error":
                exc = rec.get("exc") or {}
                body = "end %s error" % label
                if exc:
                    body += ": %s: %s" % (exc.get("type"), exc.get("message"))
            else:
                return
            if rec.get("msg") is not None:
                body += " - %s" % rec["msg"]
            self._line(time.time(), levelno, rec["level"], rec.get("scope"),
                       body)
        except Exception:
            if self.run is not None and self.run.strict:
                raise

    def _line(self, created, levelno, levelname, path, body):
        if levelno < self.level:
            return
        prefix = time.strftime("%H:%M:%S", time.localtime(created))
        prefix += " %-5s " % levelname
        if path:
            label = self.run.scope_labels.get(path[-1])
            if label:
                prefix += label + " › "
        self.acquire()
        try:
            self.stream.write(prefix + body + "\n")
            self.stream.flush()
        finally:
            self.release()

    @staticmethod
    def _row(data):
        parts = []
        for k in ("table", "key", "label"):
            v = data.get(k)
            if v is not None:
                parts.append(_show_values(v) if k == "label" else _show(v))
        return parts

    def _change(self, data):
        parts = [str(data.get("op"))] + self._row(data)
        if data.get("status") is not None:
            parts.append(str(data["status"]))
        error = data.get("error")
        if error:
            parts[-1] += ":"
            parts.append("%s: %s" % (error.get("type"), error.get("message")))
        return self._with_msg(" ".join(parts), data)

    def _finding(self, data):
        parts = [str(data.get("check"))] + self._row(data)
        return self._with_msg(" ".join(parts), data)

    @staticmethod
    def _with_msg(text, data):
        if data.get("msg") is not None:
            text += " - %s" % data["msg"]
        return text


# --------------------------------------------------------------------------
# Adapter returned by run().
# --------------------------------------------------------------------------

OPS = ("update", "insert", "delete")


def _change_misuse(op, key, changes):
    """What is wrong with a ``change(...)`` call (SPEC 4.3), or None."""
    if op not in OPS:
        return "unknown op %r (expected update, insert or delete)" % (op,)
    if op == "update" and not changes:
        return "update without changes"
    if key is None and op != "insert":
        return "%s without key" % op
    if key is not None and not isinstance(key, dict):
        return ("key must be a {column: value} object, got %s %r"
                % (type(key).__name__, key))
    return None


def _old_new(entry):
    """One ``changes`` entry: an ``(old, new)`` pair becomes
    ``{"old": ..., "new": ...}``; anything else is written as given."""
    if isinstance(entry, (tuple, list)) and len(entry) == 2:
        return {"old": entry[0], "new": entry[1]}
    return entry


class RunLogger(logging.LoggerAdapter):
    """Stdlib adapter: the usual methods plus ``fields=``.

    Typed calls (finding, change, scope) are added by later tickets.
    """

    def __init__(self, logger, extra=None):
        logging.LoggerAdapter.__init__(self, logger, extra or {})

    def process(self, msg, kwargs):
        fields = kwargs.pop("fields", None)
        if fields is not None:
            extra = dict(kwargs.get("extra") or {})
            data = dict(extra.get(ATTR) or {})
            data["fields"] = fields
            extra[ATTR] = data
            kwargs["extra"] = extra
        return msg, kwargs

    def change(self, table, op, *, key=None, label=None, changes=None,
               msg=None, status=None, error=None, level=None, fields=None):
        """Log one row operation as a Change (SPEC 3.3, 4.3)."""
        run = _active_run()
        src = _caller(1)[0]
        problem = _change_misuse(op, key, changes)
        if problem is not None and run is not None and run.strict:
            raise ValueError("invalid change call: " + problem)
        if status is None:
            if error is not None:
                status = "failed"
            elif run is not None:
                status = "planned" if run.mode == "dry" else "applied"
        if error is not None:
            # The exception itself becomes ``str()`` at write time, through
            # _encode, so a raising __str__ never escapes the call.
            error = {"type": type(error).__name__, "message": error}
        data = {"type": "change", "msg": msg, "table": table, "op": op}
        if isinstance(changes, dict):
            changes = {f: _old_new(v) for f, v in changes.items()}
        for k, v in (("key", key), ("label", label), ("changes", changes),
                     ("status", status), ("error", error), ("fields", fields)):
            if v is not None:
                data[k] = v
        if level is None:
            # An explicit status= overrides the status only: a Change that
            # carries an error is still logged at ERROR.
            failed = status == "failed" or error is not None
            level = logging.ERROR if failed else logging.INFO
        self._typed(level, "%s %s" % (op, table), data, src)
        if problem is not None:
            self._typed(logging.WARNING, "invalid change call: " + problem,
                        {}, src)

    def finding(self, check, msg=None, *, table=None, key=None, label=None,
                level=logging.WARNING, fields=None):
        """Log a Finding: ``check`` is the stable rule name (SPEC 3.3, 4.3)."""
        data = {"type": "finding", "msg": msg, "check": check}
        for k, v in (("table", table), ("key", key), ("label", label),
                     ("fields", fields)):
            if v is not None:
                data[k] = v
        text = check if msg is None else "%s: %s" % (check, msg)
        self._typed(level, text, data, _caller(1)[0])

    def scope(self, kind, *, key=None, label=None, msg=None, fields=None):
        """Open a Scope stamped with this logger's name (SPEC 3.4, 4.3)."""
        return _Scope(kind, key, label, msg, fields, _caller(1)[0],
                      self.logger.name)

    def _typed(self, level, text, data, src):
        # Typed methods live in this file, so findCaller would stamp
        # dbfixlog.py: the caller's src is passed through ATTR instead.
        data["src"] = src
        self.logger.log(level, "%s", text, extra={ATTR: data})

    @property
    def dry_run(self):
        run = _active_run()
        return run is not None and run.mode == "dry"

    @property
    def write_run(self):
        run = _active_run()
        return run is not None and run.mode == "write"


def get_logger(name):
    """The adapter for helper modules: ``log = dbfixlog.get_logger(__name__)``.

    It finds the active Run at call time, so it may be created at import
    time, before any Run is open.
    """
    return RunLogger(logging.getLogger(name))


# --------------------------------------------------------------------------
# Scopes (SPEC 3.4, 4.6).
# --------------------------------------------------------------------------

_scope_state = threading.local()  # .path: open Scope ids in this thread


def _scope_path():
    return getattr(_scope_state, "path", None) or []


class ScopeFilter(logging.Filter):
    """Stamps the current thread's Scope path into the ATTR dict."""

    def filter(self, record):
        path = _scope_path()
        if path:
            data = dict(getattr(record, ATTR, None) or {})
            data.setdefault("scope", list(path))
            setattr(record, ATTR, data)
        return True


def _caller(depth):
    """``(src, logger name)`` of the frame ``depth`` levels above the caller."""
    f = sys._getframe(depth + 1)
    return ("%s:%d" % (os.path.basename(f.f_code.co_filename), f.f_lineno),
            f.f_globals.get("__name__", "__main__"))


class _Scope(object):
    """One ``scope(...)`` use: a context manager, or a decorator that opens
    a fresh Scope with the same static arguments on every call."""

    def __init__(self, kind, key, label, msg, fields, src, logger):
        self.kind = kind
        self.key = key
        self.label = label
        self.msg = msg
        self.fields = fields
        self.src = src
        self.logger = logger
        self.run = None

    def __call__(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            src, _ = _caller(1)
            with _Scope(self.kind, self.key, self.label, self.msg,
                        self.fields, src, self.logger):
                return func(*args, **kwargs)
        return wrapper

    def __enter__(self):
        run = _active_run()
        if run is None:
            return self
        self.run = run
        self.id = run.next_scope_id()
        self.parent = list(_scope_path())
        self.start = time.time()
        extra = {"id": self.id, "kind": self.kind}
        for k in ("key", "label", "fields"):
            v = getattr(self, k)
            if v is not None:
                extra[k] = v
        run.scope_labels[self.id] = _safe(
            lambda: scope_label(self.kind, self.key, self.label),
            str(self.kind))
        self._write(self.start, "INFO", "scope_start", msg=self.msg,
                    extra=extra)
        _scope_state.path = self.parent + [self.id]
        return self

    def __exit__(self, etype, evalue, tb):
        if self.run is None:
            return False
        _scope_state.path = self.parent
        end = time.time()
        extra = {"id": self.id, "outcome": "ok",
                 "duration_ms": int(round((end - self.start) * 1000))}
        exc_info = None
        if etype is not None and not (issubclass(etype, SystemExit)
                                      and evalue.code in (0, None)):
            extra["outcome"] = "error"
            exc_info = (etype, evalue, tb)
        self._write(end, "ERROR" if exc_info else "INFO", "scope_end",
                    exc_info=exc_info, extra=extra)
        return False

    def _write(self, created, level, rtype, **kw):
        # Always written, whatever the configured level. Never raises
        # unless the Run is strict.
        rec = _build_record(created, level, self.logger, rtype, src=self.src,
                            scope=self.parent, **kw)
        try:
            self.run.handler.write_dict(rec)
        except Exception:
            if self.run.strict:
                raise
        if self.run.console_handler is not None:
            self.run.console_handler.write_scope(
                rec, logging.ERROR if level == "ERROR" else logging.INFO)


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def scope(kind, *, key=None, label=None, msg=None, fields=None):
    """Open a Scope: ``with dbfixlog.scope("customer", key={"id": 42}):``,
    or decorate a function with ``@dbfixlog.scope("orphan-check")``."""
    src, logger = _caller(1)
    return _Scope(kind, key, label, msg, fields, src, logger)


# --------------------------------------------------------------------------
# run()
# --------------------------------------------------------------------------

def _console_level(console):
    """``console=`` as a level, or None when the console is off."""
    if console is None or console is False:
        return None
    if console is True:
        return logging.INFO
    return console


class _Run(object):
    def __init__(self, path, mode, title, description, target, fields,
                 level, console, encoders, strict, max_text, overwrite):
        if mode not in MODES:
            raise ValueError("mode must be 'dry' or 'write', got %r" % (mode,))
        self.path = path
        self.mode = mode
        self.title = title
        self.description = description
        self.target = target
        self.fields = fields
        self.level = level
        self.console = console
        self.encoders = dict(encoders or {})
        self.strict = strict
        self.max_text = max_text
        self.overwrite = overwrite
        self.handler = None
        self.console_handler = None
        self.scope_labels = {}  # Scope id -> console label
        self.stream = None
        self.log = None
        self._scope_ids = 0
        self._scope_lock = threading.Lock()

    def next_scope_id(self):
        with self._scope_lock:
            self._scope_ids += 1
            return self._scope_ids

    def __enter__(self):
        global _active
        with _lock:
            if _active is not None:
                raise RuntimeError("dbfixlog.run() is already active; "
                                   "nested Runs are not supported")
            self.start = time.time()
            self.path = self.path.replace("{ts}", _path_ts(self.start))
            self.stream = open(self.path, "w" if self.overwrite else "x",
                               encoding="utf-8")
            _active = self
        try:
            self.handler = JsonlHandler(self.stream, self, self.level)
            self.handler.addFilter(ScopeFilter())
            root = logging.getLogger()
            self._root_level = root.level
            root.addHandler(self.handler)
            lowest = self.level
            console = _console_level(self.console)
            if console is not None:
                self.console_handler = ConsoleHandler(sys.stderr, self,
                                                      console)
                self.console_handler.addFilter(ScopeFilter())
                root.addHandler(self.console_handler)
                lowest = min(lowest, console)
            if root.level > lowest or root.level == logging.NOTSET:
                root.setLevel(lowest)
            header = {"format": FORMAT_VERSION, "mode": self.mode}
            for k in ("title", "description", "target", "fields"):
                v = getattr(self, k)
                if v is not None:
                    header[k] = v
            self.handler.write_dict(_build_record(
                self.start, "INFO", LOGGER_NAME, "run_start", extra=header))
            self.log = RunLogger(logging.getLogger("__main__"))
        except BaseException:
            self._teardown()
            raise
        return self.log

    def __exit__(self, etype, evalue, tb):
        try:
            end = time.time()
            extra = {"outcome": "ok",
                     "duration_ms": int(round((end - self.start) * 1000))}
            exc_info = None
            if etype is None:
                pass
            elif issubclass(etype, SystemExit):
                code = evalue.code if evalue is not None else None
                extra["exit_code"] = code
                if code not in (0, None):
                    extra["outcome"] = "error"
            elif issubclass(etype, KeyboardInterrupt):
                extra["outcome"] = "interrupted"
            else:
                extra["outcome"] = "error"
                exc_info = (etype, evalue, tb)
            level = "INFO" if extra["outcome"] == "ok" else "ERROR"
            try:
                self.handler.write_dict(_build_record(
                    end, level, LOGGER_NAME, "run_end",
                    exc_info=exc_info, extra=extra))
            except Exception:
                pass
        finally:
            self._teardown()
        return False

    def _teardown(self):
        global _active
        root = logging.getLogger()
        if self.handler is not None:
            root.removeHandler(self.handler)
            root.setLevel(self._root_level)
            self.handler.close()
        if self.console_handler is not None:
            root.removeHandler(self.console_handler)
            self.console_handler.close()
        if self.stream is not None:
            self.stream.close()
        with _lock:
            if _active is self:
                _active = None


def run(path, *, mode, title=None, description=None, target=None, fields=None,
        level=logging.DEBUG, console=logging.INFO, encoders=None, strict=False,
        max_text=1000, overwrite=False):
    """Open a Run: ``with dbfixlog.run(path, mode="dry") as log: ...``."""
    return _Run(path, mode, title, description, target, fields, level,
                console, encoders, strict, max_text, overwrite)

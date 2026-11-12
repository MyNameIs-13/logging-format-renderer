"""dbfixlog: stdlib-logging writer for Database Fix Log Files (JSON Lines).

Python 3.6.3+, stdlib only. See .scratch/db-fix-logging/SPEC.md.
"""

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
# Value encoding seam (ticket 02 fills this in).
# --------------------------------------------------------------------------

def _encode(value, run=None):
    """Return ``value`` in JSON-safe form.

    This is the single place that turns a Python value into something
    ``json.dumps(..., allow_nan=False)`` accepts. ``run`` carries the
    Run's ``encoders``, ``strict`` and ``max_text`` settings.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, dict):
        return {str(k): _encode(v, run) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(v, run) for v in value]
    return str(value)


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
        "message": str(evalue),
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
    if "msg" in data:
        msg = data.pop("msg")
    else:
        msg = record.getMessage()
    exc_info = record.exc_info if record.exc_info and record.exc_info[0] else None
    return _build_record(
        record.created, record.levelname, record.name, rtype,
        src="%s:%d" % (os.path.basename(record.pathname), record.lineno),
        msg=msg, exc_info=exc_info, extra=data, scope=scope,
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
        line = json.dumps(_encode(rec, self.run), ensure_ascii=False,
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
            self.handleError(record)


# --------------------------------------------------------------------------
# Adapter returned by run().
# --------------------------------------------------------------------------

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

    @property
    def dry_run(self):
        run = _active_run()
        return run is not None and run.mode == "dry"

    @property
    def write_run(self):
        run = _active_run()
        return run is not None and run.mode == "write"


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
        try:
            self.run.handler.write_dict(_build_record(
                created, level, self.logger, rtype, src=self.src,
                scope=self.parent, **kw))
        except Exception:
            if self.run.strict:
                raise


def scope(kind, *, key=None, label=None, msg=None, fields=None):
    """Open a Scope: ``with dbfixlog.scope("customer", key={"id": 42}):``,
    or decorate a function with ``@dbfixlog.scope("orphan-check")``."""
    src, logger = _caller(1)
    return _Scope(kind, key, label, msg, fields, src, logger)


# --------------------------------------------------------------------------
# run()
# --------------------------------------------------------------------------

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
            if root.level > self.level or root.level == logging.NOTSET:
                root.setLevel(self.level)
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

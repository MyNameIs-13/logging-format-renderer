"""dbfixlog: stdlib-logging writer for Database Fix Log Files (JSON Lines).

Python 3.6.3+, stdlib only.
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

# The one namespaced LogRecord attribute that carries typed fields, so they
# never clash with the stdlib's own LogRecord attributes.
# Pass it as ``extra={ATTR: {...}}``; its keys are merged into the record dict.
ATTR = "dbfixlog"

MODES = ("dry", "write")


# --------------------------------------------------------------------------
# Value encoding.
# --------------------------------------------------------------------------

# Record slots that hold logged *values*: they get the full value
# encoding, including ``max_text`` truncation. Every other slot (msg,
# Run Header fields, exc, ...) is only made JSON-safe.
VALUE_SLOTS = ("key", "label", "fields", "changes")

DEFAULT_MAX_TEXT = 1000
BYTES_PREFIX = 64


def _encode(value, run=None, truncate=True, _open=None):
    """Return ``value`` in JSON-safe form, for display.

    This is the single place that turns a Python value into something
    ``json.dumps(..., allow_nan=False)`` accepts. ``run`` carries the
    Run's ``encoders`` and ``max_text`` settings. With
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
            return _unencodable(value, e)
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
            return _unencodable(value, ValueError("value contains itself"))
        _open.add(id(value))
        try:
            return _encode_container(value, run, truncate, _open)
        finally:
            _open.discard(id(value))
    return _str_or_unencodable(value)


def _encode_container(value, run, truncate, _open):
    if isinstance(value, dict):
        return {_encode_key(k): _encode(v, run, truncate, _open)
                for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        try:
            value = sorted(value)
        except TypeError:
            value = list(value)
    return [_encode(v, run, truncate, _open) for v in value]


def _encode_key(key):
    """A dict key as a JSON object key: ``str(key)``, or the
    ``$unencodable`` text when that raises."""
    text = _str_or_unencodable(key)
    if isinstance(text, dict):
        return "$unencodable: " + text["$unencodable"]
    return text


def _str_or_unencodable(value):
    try:
        return str(value)
    except Exception as e:
        return _unencodable(value, e)


def _given(**values):
    """The keyword arguments that are not None, in order."""
    return {k: v for k, v in values.items() if v is not None}


def _unencodable(value, error):
    """``{"$unencodable": ...}`` for ``error``."""
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
# Run filter, shared by the Run's handlers.
# --------------------------------------------------------------------------

# LogRecord attribute naming the RunFilter that already resolved the record.
RESOLVED_BY = "dbfixlog_resolved_by"

# Record types written whatever the configured level.
ALWAYS_WRITTEN = ("scope_start", "scope_end")


class RunFilter(logging.Filter):
    """Resolves the Run-dependent parts of a record once, for all of the
    Run's handlers: Scope ids and the thread's Scope path, a Change's
    default status."""

    def __init__(self, run):
        logging.Filter.__init__(self)
        self.run = run
        self.scope_state = threading.local()  # .path: this thread's Scopes
        self.scope_labels = {}  # Scope id -> console label
        self._scope_ids = 0
        self._scope_lock = threading.Lock()

    def _next_scope_id(self):
        with self._scope_lock:
            self._scope_ids += 1
            return self._scope_ids

    def filter(self, record):
        if getattr(record, RESOLVED_BY, None) is self:
            return True
        original = getattr(record, ATTR, None) or {}
        data = dict(original)
        rtype = data.get("type")
        path = list(getattr(self.scope_state, "path", None) or [])
        if rtype == "scope_start":
            data["id"] = original["id"] = self._next_scope_id()
            self.scope_labels[data["id"]] = _safe(
                lambda: scope_label(data.get("kind"), data.get("key"),
                                    data.get("label")),
                str(data.get("kind")))
        elif rtype == "scope_end" and data.get("id") in path:
            path = path[:path.index(data["id"])]
            self.scope_state.path = path
        if path:
            data.setdefault("scope", list(path))
        if rtype == "scope_start":
            self.scope_state.path = path + [data["id"]]
        if rtype == "change" and data.get("status") is None:
            if data.get("error") is not None:
                data["status"] = "failed"
            else:
                data["status"] = "planned" if self.run.mode == "dry" else "applied"
        setattr(record, ATTR, data)
        setattr(record, RESOLVED_BY, self)
        return True


def _below(record, threshold):
    data = getattr(record, ATTR, None) or {}
    return (record.levelno < threshold
            and data.get("type") not in ALWAYS_WRITTEN)


# --------------------------------------------------------------------------
# JSONL handler.
# --------------------------------------------------------------------------

class JsonlHandler(logging.Handler):
    """Writes one JSON object per line. Never raises from ``emit``."""

    def __init__(self, stream, run, level=logging.NOTSET):
        logging.Handler.__init__(self)
        self.stream = stream
        self.run = run
        self.threshold = level

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
        if _below(record, self.threshold):
            return
        try:
            self.write_dict(_record_from_logrecord(record))
        except Exception:
            self.handleError(record)


# --------------------------------------------------------------------------
# Console handler.
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
    ATTR fields; Messages go through a stdlib ``logging.Formatter``
    (message, exception and stack). Times are UTC. No colours."""

    def __init__(self, stream, run, level=logging.INFO):
        logging.Handler.__init__(self)
        self.stream = stream
        self.run = run
        self.threshold = level
        self.setFormatter(logging.Formatter())

    def emit(self, record):
        if record.levelno < self.threshold:
            return
        try:
            data = getattr(record, ATTR, None) or {}
            rtype = data.get("type")
            if rtype == "change":
                body = self._change(data)
            elif rtype == "finding":
                body = self._finding(data)
            elif rtype in ALWAYS_WRITTEN:
                body = self._scope(data, record.exc_info)
                if body is None:
                    return
            else:
                body = self.format(record)
            self._line(record.created, record.levelname, data.get("scope"),
                       body)
        except Exception:
            self.handleError(record)

    def _scope(self, data, exc_info):
        """A scope_start line, an error scope_end line, or None."""
        label = self.run.filter.scope_labels.get(data.get("id"), "")
        if data["type"] == "scope_start":
            body = "start " + label
        elif data.get("outcome") == "error":
            body = "end %s error" % label
            if exc_info and exc_info[0]:
                body += ": %s: %s" % (exc_info[0].__name__,
                                      _safe(lambda: str(exc_info[1]), "?"))
        else:
            return None
        return self._with_msg(body, data)

    def _line(self, created, levelname, path, body):
        # The UTC hh:mm:ss of the record's ts, as the Report shows it.
        prefix = _format_ts(created)[11:19]
        prefix += " %-5s " % levelname
        if path:
            label = self.run.filter.scope_labels.get(path[-1])
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
# Adapters.
# --------------------------------------------------------------------------

OPS = ("update", "insert", "delete")


def _change_misuse(op, key, changes):
    """What is wrong with a ``change(...)`` call, or None."""
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


class TypedLogger(logging.LoggerAdapter):
    """Stdlib adapter: the usual methods plus ``fields=``, and the typed
    calls ``change``, ``finding`` and ``scope``."""

    def __init__(self, logger):
        logging.LoggerAdapter.__init__(self, logger, {})

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
        """Log one row operation as a Change."""
        src = _caller(1)[0]
        problem = _change_misuse(op, key, changes)
        if level is None:
            failed = status == "failed" or error is not None
            level = logging.ERROR if failed else logging.INFO
        if error is not None:
            # The exception itself becomes ``str()`` at write time, through
            # _encode, so a raising __str__ never escapes the call.
            error = {"type": type(error).__name__, "message": error}
        if isinstance(changes, dict):
            changes = {f: _old_new(v) for f, v in changes.items()}
        data = {"type": "change", "msg": msg, "table": table, "op": op}
        data.update(_given(key=key, label=label, changes=changes))
        data["status"] = status
        data.update(_given(error=error, fields=fields))
        self._typed(level, "%s %s" % (op, table), data, src)
        if problem is not None:
            self._typed(logging.WARNING, "invalid change call: " + problem,
                        {}, src)

    def finding(self, check, msg=None, *, table=None, key=None, label=None,
                level=logging.WARNING, fields=None):
        """Log a Finding: ``check`` is the stable rule name."""
        data = {"type": "finding", "msg": msg, "check": check}
        data.update(_given(table=table, key=key, label=label, fields=fields))
        text = check if msg is None else "%s: %s" % (check, msg)
        self._typed(level, text, data, _caller(1)[0])

    def scope(self, kind, *, key=None, label=None, msg=None, fields=None):
        """Open a Scope stamped with this logger's name."""
        return _Scope(kind, key, label, msg, fields, _caller(1)[0],
                      self.logger.name)

    def _typed(self, level, text, data, src):
        # Typed methods live in this file, so findCaller would stamp
        # dbfixlog.py: the caller's src is passed through ATTR instead.
        data["src"] = src
        self.logger.log(level, "%s", text, extra={ATTR: data})


class RunLogger(TypedLogger):
    """The adapter ``run()`` returns: a TypedLogger that also knows the
    Run's mode."""

    def __init__(self, logger, run):
        TypedLogger.__init__(self, logger)
        self.run = run

    @property
    def dry_run(self):
        return self.run.mode == "dry"

    @property
    def write_run(self):
        return self.run.mode == "write"


def get_logger(name):
    """The adapter for helper modules: ``log = dbfixlog.get_logger(__name__)``.

    It may be created at import time, before any Run is open: its records
    reach whichever Run is open when they are logged.
    """
    return TypedLogger(logging.getLogger(name))


# --------------------------------------------------------------------------
# Scopes.
# --------------------------------------------------------------------------

def _caller(depth):
    """``(src, logger name)`` of the frame ``depth`` levels above the caller."""
    f = sys._getframe(depth + 1)
    return ("%s:%d" % (os.path.basename(f.f_code.co_filename), f.f_lineno),
            f.f_globals.get("__name__", "__main__"))


class _Scope(object):
    """One ``scope(...)`` use: a context manager, or a decorator that opens
    a fresh Scope with the same static arguments on every call."""

    def __init__(self, kind, key, label, msg, fields, src, logger_name):
        self.kind = kind
        self.key = key
        self.label = label
        self.msg = msg
        self.fields = fields
        self.src = src
        self.logger_name = logger_name

    def __call__(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            src, _ = _caller(1)
            with _Scope(self.kind, self.key, self.label, self.msg,
                        self.fields, src, self.logger_name):
                return func(*args, **kwargs)
        return wrapper

    def __enter__(self):
        self.start = time.time()
        # The Run's filter fills in "id".
        self.data = {"type": "scope_start", "msg": self.msg, "id": None,
                     "kind": self.kind}
        self.data.update(_given(key=self.key, label=self.label,
                                fields=self.fields))
        self._emit(logging.INFO, self.data, None)
        return self

    def __exit__(self, etype, evalue, tb):
        end = time.time()
        data = {"type": "scope_end", "msg": None, "id": self.data.get("id"),
                "outcome": "ok",
                "duration_ms": int(round((end - self.start) * 1000))}
        exc_info = None
        if etype is not None and not (issubclass(etype, SystemExit)
                                      and evalue.code in (0, None)):
            data["outcome"] = "error"
            exc_info = (etype, evalue, tb)
        self._emit(logging.ERROR if exc_info else logging.INFO, data, exc_info)
        return False

    def _emit(self, level, data, exc_info):
        # Handled directly, past the loggers' level checks: start and end
        # records are written whatever the configured level.
        data["src"] = self.src
        logger = logging.getLogger(LOGGER_NAME)
        record = logger.makeRecord(self.logger_name, level, self.src, 0,
                                   "%s %s", (data["type"], self.kind),
                                   exc_info, extra={ATTR: data})
        logger.handle(record)


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
                 level, console, encoders, max_text, overwrite):
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
        self.max_text = max_text
        self.overwrite = overwrite
        self.filter = RunFilter(self)
        self.handler = None
        self.console_handler = None
        self.stream = None
        self.log = None

    def __enter__(self):
        root = logging.getLogger()
        if any(isinstance(h, JsonlHandler) for h in root.handlers):
            raise RuntimeError("dbfixlog.run() is already active; "
                               "nested Runs are not supported")
        self.start = time.time()
        self.path = self.path.replace("{ts}", _path_ts(self.start))
        self.stream = open(self.path, "w" if self.overwrite else "x",
                           encoding="utf-8")
        try:
            self.handler = JsonlHandler(self.stream, self, self.level)
            self.handler.addFilter(self.filter)
            self._root_level = root.level
            root.addHandler(self.handler)
            lowest = self.level
            console = _console_level(self.console)
            if console is not None:
                self.console_handler = ConsoleHandler(sys.stderr, self,
                                                      console)
                self.console_handler.addFilter(self.filter)
                root.addHandler(self.console_handler)
                lowest = min(lowest, console)
            if root.level > lowest or root.level == logging.NOTSET:
                root.setLevel(lowest)
            header = {"format": FORMAT_VERSION, "mode": self.mode}
            header.update(_given(title=self.title, description=self.description,
                                 target=self.target, fields=self.fields))
            self.handler.write_dict(_build_record(
                self.start, "INFO", LOGGER_NAME, "run_start", extra=header))
            self.log = RunLogger(logging.getLogger("__main__"), self)
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


def run(path, *, mode, title=None, description=None, target=None, fields=None,
        level=logging.DEBUG, console=logging.INFO, encoders=None,
        max_text=DEFAULT_MAX_TEXT, overwrite=False):
    """Open a Run: ``with dbfixlog.run(path, mode="dry") as log: ...``."""
    return _Run(path, mode, title, description, target, fields, level,
                console, encoders, max_text, overwrite)


# Scope records go through this logger; without a handler of its own, the
# stdlib's last-resort handler would print error Scope ends outside a Run.
logging.getLogger(LOGGER_NAME).addHandler(logging.NullHandler())

"""Static guard for the Python 3.6.3 target (SPEC section 2).

There is no 3.6 interpreter here, so this test parses the shipped Python
files and fails on known 3.7+ constructs and imports. It is not a
substitute for running the suite under real Python 3.6.
"""

import ast
import os
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
FILES = ["dbfixlog.py", "dbfixlog_render.py"]

# Modules that don't exist in 3.6.
NEW_MODULES = {
    "contextvars": "3.7", "dataclasses": "3.7", "importlib.resources": "3.7",
    "importlib.metadata": "3.8", "graphlib": "3.9", "zoneinfo": "3.9",
    "tomllib": "3.11",
}

# Attribute names that only exist on 3.7+ (module or method attributes).
NEW_ATTRIBUTES = {
    "fromisoformat": "3.7", "time_ns": "3.7", "monotonic_ns": "3.7",
    "perf_counter_ns": "3.7", "isascii": "3.7", "reconfigure": "3.7",
    "removeprefix": "3.9", "removesuffix": "3.9", "is_relative_to": "3.9",
    "shlex_join": "3.8", "cached_property": "3.8", "to_thread": "3.9",
    "get_running_loop": "3.7", "create_task": "3.7", "nullcontext": "3.7",
    "asynccontextmanager": "3.7", "bit_count": "3.10", "pairwise": "3.10",
}

# Builtins added after 3.6.
NEW_BUILTINS = {"breakpoint": "3.7", "aiter": "3.10", "anext": "3.10"}

# Keyword arguments added after 3.6 to calls we are likely to make.
NEW_KWARGS = {"stacklevel": "3.8 (logging)",
              "capture_output": "3.7 (subprocess)"}

# Specific (module, attr) uses.
NEW_MODULE_ATTRS = {("asyncio", "run"): "3.7", ("math", "prod"): "3.8",
                    ("math", "isqrt"): "3.8", ("math", "dist"): "3.8",
                    ("functools", "cache"): "3.9", ("typing", "Literal"): "3.8",
                    ("typing", "Protocol"): "3.8", ("typing", "Final"): "3.8",
                    ("typing", "TypedDict"): "3.8"}


def problems(source, filename):
    tree = ast.parse(source, filename)
    found = []

    def add(node, what):
        found.append("%s:%d: %s" % (filename, getattr(node, "lineno", 0), what))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for mod, ver in NEW_MODULES.items():
                    if alias.name == mod or alias.name.startswith(mod + "."):
                        add(node, "import %s (%s+)" % (alias.name, ver))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "__future__" and any(a.name == "annotations"
                                           for a in node.names):
                add(node, "from __future__ import annotations (3.7+)")
            for name, ver in NEW_MODULES.items():
                if mod == name or mod.startswith(name + "."):
                    add(node, "from %s import (%s+)" % (mod, ver))
                if "." in name:
                    parent, child = name.rsplit(".", 1)
                    if mod == parent and any(a.name == child for a in node.names):
                        add(node, "from %s import %s (%s+)" % (parent, child, ver))
            for a in node.names:
                if (mod, a.name) in NEW_MODULE_ATTRS:
                    add(node, "%s.%s (%s+)" % (mod, a.name,
                                               NEW_MODULE_ATTRS[(mod, a.name)]))
        elif isinstance(node, ast.Attribute):
            if node.attr in NEW_ATTRIBUTES:
                add(node, ".%s (%s+)" % (node.attr, NEW_ATTRIBUTES[node.attr]))
            if (isinstance(node.value, ast.Name)
                    and (node.value.id, node.attr) in NEW_MODULE_ATTRS):
                add(node, "%s.%s (%s+)" % (node.value.id, node.attr,
                                           NEW_MODULE_ATTRS[(node.value.id, node.attr)]))
        elif isinstance(node, ast.Name):
            if node.id in NEW_BUILTINS and isinstance(node.ctx, ast.Load):
                add(node, "builtin %s (%s+)" % (node.id, NEW_BUILTINS[node.id]))
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in NEW_KWARGS:
                    add(node, "keyword %s= (%s+)" % (kw.arg, NEW_KWARGS[kw.arg]))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            if getattr(node.args, "posonlyargs", None):
                add(node, "positional-only parameters (3.8+)")
        elif isinstance(node, ast.JoinedStr):
            # f"{x=}" self-documenting expressions (3.8+) leave the
            # literal "x=" text immediately before the formatted value.
            vals = node.values
            for prev, cur in zip(vals, vals[1:]):
                if (isinstance(cur, ast.FormattedValue)
                        and isinstance(prev, ast.Constant)
                        and isinstance(prev.value, str)
                        and prev.value.rstrip().endswith("=")):
                    add(node, "f-string '=' specifier (3.8+)")
        if type(node).__name__ in ("NamedExpr",):
            add(node, "walrus operator := (3.8+)")
        if type(node).__name__ in ("Match", "TryStar", "TypeAlias"):
            add(node, "%s statement (3.10+)" % type(node).__name__)
        if (isinstance(node, (ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith,
                              ast.Await))):
            add(node, "async code (asyncio scripts unsupported, SPEC 4.6)")
    return found


class Py36CompatTest(unittest.TestCase):
    def test_shipped_python_files_avoid_37_plus_constructs(self):
        checked = 0
        for name in FILES:
            path = os.path.join(ROOT, name)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                source = f.read()
            checked += 1
            with self.subTest(file=name):
                self.assertEqual(problems(source, name), [])
        self.assertGreater(checked, 0, "no shipped Python file found")

    def test_checker_catches_known_constructs(self):
        samples = [
            "import contextvars",
            "from dataclasses import dataclass",
            "from __future__ import annotations",
            "import datetime\ndatetime.datetime.fromisoformat('x')",
            "import logging\nlogging.info('x', stacklevel=2)",
            "breakpoint()",
            "if (n := 1): pass",
            "def f(a, /): pass",
            "import asyncio\nasyncio.run(None)",
            "import time\ntime.time_ns()",
            "x = 1\ns = f'{x=}'",
        ]
        for src in samples:
            with self.subTest(src=src):
                self.assertNotEqual(problems(src, "<sample>"), [])

    def test_checker_allows_36_constructs(self):
        ok = ("import json, logging, threading\n"
              "x = 1\ns = f'{x}'\n"
              "def f(a, *, b=None): return {**{}, 'a': a}\n")
        self.assertEqual(problems(ok, "<sample>"), [])


if __name__ == "__main__":
    unittest.main()

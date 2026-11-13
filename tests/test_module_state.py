"""The shipped modules keep no mutable module-level state: no global or
nonlocal statements, and no module-level name bound to a mutable container
or a state object (lock, thread-local, ...)."""

import ast
import os
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
SHIPPED = ("dbfixlog.py", "dbfixlog_render.py")

MUTABLE_DISPLAYS = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp,
                    ast.SetComp)
# Calls whose result holds mutable state, by their last dotted name part.
MUTABLE_CALLS = {"list", "dict", "set", "bytearray", "local", "Lock", "RLock",
                 "Condition", "Semaphore", "BoundedSemaphore", "Event",
                 "defaultdict", "OrderedDict", "Counter", "deque",
                 "WeakValueDictionary", "WeakKeyDictionary", "WeakSet",
                 "Queue", "StringIO", "BytesIO"}


def _call_name(node):
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _mutable(value):
    if isinstance(value, MUTABLE_DISPLAYS):
        return True
    if isinstance(value, ast.Call) and _call_name(value) in MUTABLE_CALLS:
        return True
    if isinstance(value, ast.Tuple):
        return any(_mutable(v) for v in value.elts)
    return False


def problems(source, filename):
    tree = ast.parse(source, filename)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            found.append("%s:%d: %s %s" % (filename, node.lineno,
                                           type(node).__name__.lower(),
                                           ", ".join(node.names)))
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            if isinstance(node, ast.AugAssign) or (
                    node.value is not None and _mutable(node.value)):
                found.append("%s:%d: mutable module-level value"
                             % (filename, node.lineno))
    return found


class ModuleStateTest(unittest.TestCase):
    def test_shipped_modules_keep_no_mutable_module_state(self):
        for name in SHIPPED:
            with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                source = f.read()
            with self.subTest(file=name):
                self.assertEqual(problems(source, name), [])

    def test_checker_catches_mutable_state(self):
        samples = [
            "x = []", "x = {}", "x = {1}", "x = [i for i in y]",
            "import threading\nx = threading.local()",
            "import threading\n_lock = threading.Lock()",
            "x = dict(a=1)", "x = 0\nx += 1", "a, b = [], 1",
            "def f():\n    global x", "x: list = []",
        ]
        for src in samples:
            with self.subTest(src=src):
                self.assertNotEqual(problems(src, "<sample>"), [])

    def test_checker_allows_constants(self):
        ok = ('X = 1\nY = "a"\nZ = ("a", "b")\nW = frozenset(("a",))\n'
              'import types\nM = types.MappingProxyType({1: 0})\n'
              'def f():\n    d = {}\n    return d\n'
              'class C(object):\n    items = ()\n')
        self.assertEqual(problems(ok, "<sample>"), [])


if __name__ == "__main__":
    unittest.main()

"""Comments, docstrings and test names stand on their own: they never point
at planning documents, their sections or work items."""

import ast
import glob
import io
import os
import re
import tokenize
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FORBIDDEN = re.compile(r"(?<![A-Za-z])(spec|tickets?)(?![A-Za-z])|§", re.IGNORECASE)

# JS and CSS comments; a "//" right after ":" (a URL) is not a comment.
JS_COMMENT = re.compile(r"/\*.*?\*/|(?<![:\\])//[^\n]*", re.DOTALL)
# Test titles in node:test files: test("...", ...).
JS_TEST_NAME = re.compile(r"""\btest\(\s*(["'`])(.*?)\1""")


def python_texts(source):
    """Comments, docstrings and test function names of a Python file."""
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            out.append((tok.start[0], tok.string))
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                out.append((getattr(node, "lineno", 1), doc))
        if (isinstance(node, (ast.FunctionDef, ast.ClassDef))
                and node.name.lower().startswith("test")):
            out.append((node.lineno, node.name))
    return out


def js_texts(source):
    """Comments (and, in test files, test titles) of a JS or CSS file."""
    out = []
    for pattern, group in ((JS_COMMENT, 0), (JS_TEST_NAME, 2)):
        for m in pattern.finditer(source):
            out.append((source.count("\n", 0, m.start()) + 1, m.group(group)))
    return out


def references(path):
    with open(path, encoding="utf-8") as f:
        source = f.read()
    texts = python_texts(source) if path.endswith(".py") else js_texts(source)
    return ["%s:%d: %s" % (os.path.relpath(path, ROOT), line, text.strip()[:80])
            for line, text in texts if FORBIDDEN.search(text)]


def checked_files():
    names = ["dbfixlog.py", "dbfixlog_render.py", "report.js", "report.css"]
    for pattern in ("*.py", "**/*.py", "**/*.js", "**/*.mjs"):
        names += sorted(os.path.relpath(p, ROOT) for p in glob.glob(
            os.path.join(ROOT, "tests", pattern), recursive=True))
    return [os.path.join(ROOT, n) for n in sorted(set(names))]


class NoDocReferencesTest(unittest.TestCase):
    def test_code_and_tests_do_not_reference_planning_documents(self):
        found = []
        for path in checked_files():
            found += references(path)
        self.assertEqual(found, [], "\n".join(found))

    def test_checker_catches_references(self):
        self.assertTrue(FORBIDDEN.search("# see SPEC 3.5"))
        self.assertTrue(FORBIDDEN.search("per the spec"))
        self.assertTrue(FORBIDDEN.search("// ticket 09"))
        self.assertTrue(FORBIDDEN.search("§6.3"))
        self.assertTrue(FORBIDDEN.search("test_matches_spec_example"))
        self.assertFalse(FORBIDDEN.search("specific"))
        self.assertEqual(len(js_texts('a = "x"; // ticket 10\n/* SPEC */')), 2)
        self.assertEqual(js_texts('u = "file://x";'), [])
        self.assertEqual(len(python_texts(
            '"""Doc."""\n# c\ndef test_x():\n    """D."""\n')), 4)


if __name__ == "__main__":
    unittest.main()

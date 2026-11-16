"""scripts/copy_lint.py: a copyX that misses a field of X is flagged; the sources pass it."""
import glob
import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("copy_lint", os.path.join(ROOT, "scripts", "copy_lint.py"))
lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint)

TYPE = "export type T = {\n  // a: the name\n  a: string,\n  b?: Map<string, { x: int, y: int }>,\n  c?: (n: int) => bool,\n}\n"


def copy(fields):
    return "export function copyT(r: T): T {\n  return {\n    " + " ".join(f"{f}: r.{f}," for f in fields) + "\n  }\n}\n"


class CopyLint(unittest.TestCase):
    def test_a_complete_copy_passes(self):
        self.assertEqual(lint.problems("x.tov", TYPE + copy(["a", "b", "c"])), [])
        one = "export type T = { a: string, b?: Map<string, int[]>, c?: bool }\n"
        self.assertEqual(lint.problems("x.tov", one + copy(["a", "b", "c"])), [])

    def test_a_missing_or_unknown_field_is_flagged(self):
        got = lint.problems("x.tov", TYPE + copy(["a", "c"]))
        self.assertEqual([(line, msg) for line, _, msg in got], [(7, "copyT does not copy T's b")])
        self.assertEqual(len(lint.problems("x.tov", TYPE + copy(["a", "b", "c", "d"]))), 1)
        self.assertEqual(len(lint.problems("x.tov", copy(["a"]))), 1)

    def test_the_sources_pass(self):
        seen = 0
        for path in glob.glob(os.path.join(ROOT, "src", "**", "*.tov"), recursive=True):
            text = open(path).read()
            seen += text.count("\nexport function copy")
            self.assertEqual(lint.problems(path, text), [], path)
        self.assertGreater(seen, 20)


if __name__ == "__main__":
    unittest.main()

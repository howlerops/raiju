"""scripts/fetch_lint.py: a fetch() in src/ without a timeout is flagged; the sources pass it."""
import glob
import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("fetch_lint", os.path.join(ROOT, "scripts", "fetch_lint.py"))
lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint)


def flagged(text):
    return [line for line, _, _ in lint.problems("x.tov", text)]


class FetchLint(unittest.TestCase):
    def test_a_call_without_a_signal_is_flagged(self):
        self.assertEqual(flagged('const r = await fetch(url, { method: "POST", body: b })\n'), [1])
        self.assertEqual(flagged("x()\nconst r = try await fetch(METADATA, { headers: h })\n"), [2])

    def test_a_call_with_a_signal_passes(self):
        self.assertEqual(flagged("const r = await fetch(url, { headers: h, signal: dl.controller.signal })\n"), [])
        # arguments over several lines
        self.assertEqual(flagged("const r = await fetch(\n  url,\n  { headers: h, signal: s },\n)\n"), [])

    def test_a_marked_call_passes(self):
        self.assertEqual(flagged("const r = await fetch(url) // fetch-timeout: none (a local socket)\n"), [])

    def test_definitions_comments_strings_and_other_names_are_not_calls(self):
        src = "\n".join([
            "  fetch(req, server) {",
            "  async fetch(req) {",
            "function fetch(u: string): void {}",
            "// fetch(url) in a comment",
            "const s = \"fetch(url)\"",
            "const js = `fetch(base).then(f)`",
            "x.fetch(url)",
            "prefetch(url)",
            "fetchAll(url)",
        ])
        self.assertEqual(flagged(src), [])

    def test_the_sources_pass(self):
        files = sorted(glob.glob(os.path.join(ROOT, "src", "*.tov")) + glob.glob(os.path.join(ROOT, "src", "providers", "*.tov")))
        bad = []
        for f in files:
            with open(f) as fh:
                for line, _, _ in lint.problems(f, fh.read()):
                    bad.append(f"{os.path.relpath(f, ROOT)}:{line}")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()

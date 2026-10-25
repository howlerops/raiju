"""scripts/gen_config_doc.py: the Tov type parser, the walk from Config, and docs/config-reference.md being up to date.

Usage: python3 -m unittest tests/test_gen_config_doc.py
"""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import gen_config_doc as g  # noqa: E402


def parse(src):
    m = g.DECL.search(src)
    return g.Parser(src, m.end()).type()


class ParserTest(unittest.TestCase):
    def test_record_fields_and_comments(self):
        t = parse("""export type A = {
  // the first
  // over two lines
  a?: string,
  b: int, // after it
  c?: Map<string, B>,
  d?: (string | B)[],
  e?: { x?: bool },
}""")
        self.assertIsInstance(t, g.Rec)
        names = [(f[0], f[1], f[3]) for f in t.fields]
        self.assertEqual(names, [("a", True, "the first over two lines"), ("b", False, "after it"), ("c", True, ""), ("d", True, ""), ("e", True, "")])
        self.assertEqual(g.show(t.fields[2][2]), "map of object")
        self.assertIsInstance(t.fields[3][2], g.Arr)
        self.assertIsInstance(t.fields[4][2], g.Rec)

    def test_comment_before_the_closing_brace_is_not_lost(self):
        t = parse("type A = { a?: int,\n  // b's comment\n  b?: int }")
        self.assertEqual([f[3] for f in t.fields], ["", "b's comment"])

    def test_unions_and_literals(self):
        t = parse('type S = "a" | "b"')
        self.assertEqual(g.show(t), '"a" | "b"')

    def test_mentions(self):
        doc = "grant_type is client_credentials. aud is audience; kid is key_id."
        self.assertEqual(g.mentions(doc, "grant_type"), "grant_type is client_credentials.")
        self.assertEqual(g.mentions(doc, "kid"), "kid is key_id.")
        self.assertEqual(g.mentions(doc, "client_id"), "")


class WalkTest(unittest.TestCase):
    def test_nested_paths(self):
        types = {
            "Config": (parse("type Config = { p?: Map<string, P>, l?: L[] }"), "", "src/config.tov"),
            "P": (parse("type P = { keys?: K[] }"), "a provider", "src/config.tov"),
            "K": (parse("type K = { value?: string }"), "", "src/config.tov"),
            "L": (parse("type L = { n: int, back?: L }"), "", "src/config.tov"),
        }
        w = g.Walker(types)
        for name, _o, t, c in types["Config"][0].fields:
            w.field(name, t, c, frozenset({"Config"}), 1)
        paths = [r[0] for r in w.rows]
        self.assertEqual(paths, ["p", "p.<name>.keys", "p.<name>.keys[].value", "l", "l[].n", "l[].back"])
        self.assertEqual(w.rows[0][2], "a provider")


class ReferenceTest(unittest.TestCase):
    def test_reference_is_up_to_date(self):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "gen_config_doc.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_every_compat_key_is_in_the_reference(self):
        text = open(os.path.join(ROOT, "docs", "config-reference.md")).read()
        lists, notes, renames = g.compat_lists()
        for prefix, keys in lists.items():
            for k in keys:
                if k == "$schema":
                    continue
                path = f"{prefix}.{k}" if prefix else k
                self.assertIn(f"`{path}`", text, path)
        for p in list(notes) + list(renames):
            self.assertIn(f"`{p}`", text, p)

    def test_security_keys_are_described(self):
        text = open(os.path.join(ROOT, "docs", "config-reference.md")).read()
        rows = {line.split("|")[1].strip().strip("`"): line.split("|")[3].strip() for line in text.split("\n") if line.startswith("| `")}
        for key in ["setup_token", "encryption_key", "client.enforce_auth_on_inference", "client.allowed_origins", "client.max_request_body_size_mb", "server.header_timeout_seconds", "server.shutdown_grace_seconds"]:
            self.assertTrue(rows.get(key), f"{key} has no description")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Flags a record copy function that does not list every field of its type.

`export function copyX(r: X): X { return { a: r.a, ... } }` (src/config.tov, "copies of records") builds a new
record field by field, because the pinned Tov has no spread. A field added to X and not to copyX would be dropped
without an error wherever the copy is used (every config save goes through copyConfig), so each copyX defined in
the file of its type is checked against that type here.

Usage: scripts/copy_lint.py FILE...   (exit 1 when a copy is flagged)
"""
import re
import sys

CODE = "L0002"

_OPEN, _CLOSE = "{[(<", "}])>"


def _block(text, start):
    """The text between the brace at start and its match, comments removed, and the index of the match."""
    depth, i, out = 0, start, []
    while i < len(text):
        if text.startswith("//", i):
            i = text.find("\n", i)
            if i < 0:
                break
            continue
        c = text[i]
        if c in _OPEN:
            depth += 1
        elif c in _CLOSE and not (c == ">" and text[i - 1] == "="):
            depth -= 1
            if depth == 0:
                return "".join(out[1:]), i
        out.append(c)
        i += 1
    return "".join(out[1:]), len(text)


def _names(body):
    """The field names of a record type's or a record literal's body."""
    parts, depth, cur = [], 0, ""
    for i, c in enumerate(body):
        if c in _OPEN:
            depth += 1
        elif c in _CLOSE and not (c == ">" and body[i - 1] == "="):
            depth -= 1
        if c in ",\n" and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += c
    parts.append(cur)
    names = []
    for p in parts:
        m = re.match(r"\s*([A-Za-z_]\w*)\??\s*:", p)
        if m:
            names.append(m.group(1))
    return names


def problems(path, text):
    """(line, col, message) for each copyX in text whose fields are not exactly those of type X in text."""
    out = []
    for m in re.finditer(r"^export function copy(\w+)\(r: (\w+)\): (\w+) \{\n\s*return ", text, re.M):
        name = m.group(2)
        if m.group(1) != name or m.group(3) != name or text[m.end()] != "{":
            continue
        line = text.count("\n", 0, m.start()) + 1
        t = re.search(r"^(?:export )?type " + name + r"\s*=\s*\{", text, re.M)
        if t is None:
            out.append((line, 1, f"copy{name}: type {name} is not defined in this file"))
            continue
        want = _names(_block(text, t.end() - 1)[0])
        have = _names(_block(text, m.end())[0])
        missing = [f for f in want if f not in have]
        extra = [f for f in have if f not in want]
        if missing:
            out.append((line, 1, f"copy{name} does not copy {name}'s " + ", ".join(missing)))
        if extra:
            out.append((line, 1, f"copy{name} lists " + ", ".join(extra) + f", not in {name}"))
    return out


def main(argv):
    bad = 0
    for path in argv:
        for line, col, msg in problems(path, open(path).read()):
            print(f"{CODE} {path}:{line}:{col} {msg}")
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

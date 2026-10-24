#!/usr/bin/env python3
"""Flags outbound fetch() calls in the gateway's sources that have no timeout.

The runtime's fetch has no default timeout, so a call without an abort signal can hang on a stalled peer for
as long as the connection stays up, holding the request, its descriptors and its memory. Every fetch( call in
src/ passes `signal:` (usually deadline(ms).controller.signal from src/deadline.tov). A call that must not time
out says so with a `fetch-timeout: none` comment on its line.

Comments, strings and template literals (the UI's embedded JavaScript) are skipped, and so are method
definitions named fetch (Bun.serve's `fetch(req) {`).

Usage: scripts/fetch_lint.py FILE...   (exit 1 when a call is flagged)
"""
import sys

CODE = "L0001"


def _skip_string(text, i, quote):
    # i is at the opening quote; returns the index after the closing one
    n = len(text)
    i += 1
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == quote:
            return i + 1
        if quote != "`" and c == "\n":
            return i + 1
        i += 1
    return n


def _code_mask(text):
    """The text with comments, strings and template literals blanked out (lengths and newlines kept)."""
    out = list(text)
    n = len(text)
    i = 0
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
        elif c in "\"'`":
            j = _skip_string(text, i, c)
        else:
            i += 1
            continue
        for k in range(i, j):
            if out[k] != "\n":
                out[k] = " "
        i = j
    return "".join(out)


def _ident(c):
    return c.isalnum() or c in "_$"


def problems(path, text):
    """[(line, col, message)] for each fetch( call without a signal."""
    code = _code_mask(text)
    lines = text.split("\n")
    found = []
    n = len(code)
    i = code.find("fetch")
    while i >= 0:
        before = code[i - 1] if i > 0 else " "
        j = i + 5
        while j < n and code[j] in " \t":
            j += 1
        if not _ident(before) and before != "." and not (i + 5 < n and _ident(code[i + 5])) and j < n and code[j] == "(":
            # the arguments, to the matching parenthesis
            depth = 0
            k = j
            while k < n:
                if code[k] == "(":
                    depth += 1
                elif code[k] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            after = k + 1
            while after < n and code[after] in " \t\r\n":
                after += 1
            head = code[max(0, i - 9):i]
            is_def = (after < n and code[after] == "{") or head.rstrip().endswith("function") or (after < n and code[after] == ":")
            line = code.count("\n", 0, i) + 1
            col = i - (code.rfind("\n", 0, i) + 1) + 1
            src_line = lines[line - 1] if line - 1 < len(lines) else ""
            args = text[j:k + 1]
            if not is_def and "signal" not in args and "fetch-timeout: none" not in src_line:
                found.append((line, col, "fetch() without a timeout: pass signal: deadline(ms).controller.signal (src/deadline.tov), or mark the line `fetch-timeout: none`"))
        i = code.find("fetch", i + 5)
    return found


def main(argv):
    bad = 0
    for path in argv:
        with open(path) as f:
            text = f.read()
        for line, col, msg in problems(path, text):
            print(f"{CODE} {path}:{line}:{col} {msg}")
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

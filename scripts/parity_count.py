#!/usr/bin/env python3
"""Count the status column of docs/parity.md and keep its Summary table current.

Usage:
  scripts/parity_count.py            print counts per section and in total
  scripts/parity_count.py --values   also list every distinct status cell
  scripts/parity_count.py --write    rewrite the generated block in "## Summary"
  scripts/parity_count.py --check    exit 1 if the generated block is out of date

Every markdown table inside sections (a) to (i) is read. Its status column is
the one whose header is "Raiju status". The status is the first word of the
cell (done, partial, missing, out-of-scope, n/a); anything in parentheses
after it is a qualifier. Rows whose qualifier is "Raiju-only" are extras and
are not parity rows. Any other status value stops the script with an error.

The generated block sits between the markers in the Summary section. Only the
text between the markers is rewritten, so the prose around it is kept.
Running --write twice changes nothing.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "parity.md"
START = "<!-- parity-count:start -->"
END = "<!-- parity-count:end -->"
STATUSES = ["done", "partial", "missing", "out-of-scope", "n/a"]
SECTION_RE = re.compile(r"^## \(([a-i])\) (.*)$")
SEP_RE = re.compile(r"^\|(\s*:?-+:?\s*\|)+\s*$")


def fail(msg):
    raise SystemExit("parity_count: " + msg)


def read_rows(lines):
    """Yield (section_key, section_title, status_cell, line_no) for each table row."""
    section = None
    title = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        m = SECTION_RE.match(line)
        if m:
            section, title = m.group(1), m.group(2).strip()
        elif line.startswith("## "):
            section = None
        if section and line.startswith("|") and i + 1 < len(lines) and SEP_RE.match(lines[i + 1]):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            if "Raiju status" not in header:
                fail(f"table at line {i + 1} has no 'Raiju status' column")
            col = header.index("Raiju status")
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if len(cells) != len(header):
                    fail(f"line {i + 1} has {len(cells)} cells, header has {len(header)}")
                yield section, title, cells[col], i + 1
                i += 1
            continue
        i += 1


def classify(cell):
    """Return (status, is_extra) for a status cell, or stop on an unknown value."""
    base = cell.split("(")[0].strip().lower()
    if base not in STATUSES:
        fail(f"unknown status {cell!r}")
    return base, "Raiju-only" in cell


def tally(lines):
    sections = {}
    values = {}
    for key, title, cell, _ in read_rows(lines):
        values[cell] = values.get(cell, 0) + 1
        s = sections.setdefault(key, {"title": title, "counts": {k: 0 for k in STATUSES}, "extras": 0})
        status, extra = classify(cell)
        if extra:
            s["extras"] += 1
        else:
            s["counts"][status] += 1
    return sections, values


def totals(sections):
    t = {k: 0 for k in STATUSES}
    extras = 0
    for s in sections.values():
        for k in STATUSES:
            t[k] += s["counts"][k]
        extras += s["extras"]
    return t, extras


def block(sections):
    t, extras = totals(sections)
    parity = sum(t.values())
    rows = []
    for key in sorted(sections):
        s = sections[key]
        c = s["counts"]
        n = sum(c.values())
        rows.append(
            f"| ({key}) {s['title']} | {c['done']} | {c['partial']} | {c['missing']} | "
            f"{c['out-of-scope']} | {c['n/a']} | {n} | {s['extras']} |"
        )
    rows.append(
        f"| **Total** | **{t['done']}** | **{t['partial']}** | **{t['missing']}** | "
        f"**{t['out-of-scope']}** | **{t['n/a']}** | **{parity}** | **{extras}** |"
    )
    head = (
        f"Parity rows (one per feature or route family): **{parity}**. Status counts: "
        f"done {t['done']}, partial {t['partial']}, missing {t['missing']}, "
        f"out-of-scope {t['out-of-scope']}, n/a {t['n/a']}. "
        f"Raiju-only extras (not parity items, listed for context): {extras}."
    )
    table = [
        "| Section | done | partial | missing | out-of-scope | n/a | Parity rows | Raiju-only extras |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ] + rows
    return head + "\n\n" + "\n".join(table)


def replace_block(text, new):
    if text.count(START) != 1 or text.count(END) != 1:
        fail("the Summary markers must each appear exactly once")
    a = text.index(START) + len(START)
    b = text.index(END)
    if b < a:
        fail("end marker comes before start marker")
    return text[:a] + "\n" + new + "\n" + text[b:]


def main(argv):
    text = DOC.read_text(encoding="utf8")
    sections, values = tally(text.split("\n"))
    if "--values" in argv:
        for cell in sorted(values):
            print(f"{values[cell]:4d}  {cell}")
        print()
    if "--write" not in argv and "--check" not in argv:
        for key in sorted(sections):
            s = sections[key]
            c = s["counts"]
            print(f"({key}) {s['title']}: " + ", ".join(f"{k} {c[k]}" for k in STATUSES)
                  + f", extras {s['extras']}")
        t, extras = totals(sections)
        print("total: " + ", ".join(f"{k} {t[k]}" for k in STATUSES)
              + f", parity rows {sum(t.values())}, extras {extras}")
    updated = replace_block(text, block(sections))
    if "--write" in argv:
        if updated != text:
            DOC.write_text(updated, encoding="utf8")
            print("parity_count: Summary updated")
        else:
            print("parity_count: Summary already current")
    if "--check" in argv:
        if updated != text:
            print("parity_count: Summary is out of date; run make parity-count", file=sys.stderr)
            return 1
        print("parity_count: Summary is current")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

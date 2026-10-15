#!/usr/bin/env python3
"""Write src/guard_gitleaks_data.tov from the upstream gitleaks rule set.

Usage: TOV=/path/to/tov scripts/gen_gitleaks.py GITLEAKS_CHECKOUT VERSION

GITLEAKS_CHECKOUT is a gitleaks clone checked out at the release tag VERSION
(for example v8.30.1). The script reads config/gitleaks.toml and LICENSE from it.
Each rule with a regex becomes one line of a tab-separated table:

    id  entropy  secretGroup  keywords(JSON array)  description  regex

Rules without a regex (path-only rules) are skipped. So are rules whose regex the
Raiju RE2 engine (src/regex.tov) cannot compile; the check runs the engine on
every pattern, in all three forms guard_regex.tov builds, with the patterns
passed to a small Tov program. Skipped rules are listed in the generated header.

Tov cannot read files at build time, so the table is compiled in as a template
literal, as scripts/gen_pricing.py does. Re-run this on upgrade.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "guard_gitleaks_data.tov"
DEFAULT_TOV = ROOT / "build" / "tov" / "target" / "release" / "tov"

# Compiles each pattern the way guard_regex.tov does (src, \A(?:src), \A(?:src)\z)
# and prints "FAIL <index> <message>" for each pattern that does not compile.
PROBE = """import {{ readFileSync }} from "node:fs"
import {{ compileRegex }} from "{regex}"

function check(src: string): string {{
  try {{
    compileRegex(src)
    compileRegex("\\\\A(?:" + src + ")")
    compileRegex("\\\\A(?:" + src + ")\\\\z")
    return ""
  }} catch (e) {{
    return e.message
  }}
}}

function main(): void {{
  const text = try readFileSync(process.argv[2]!, "utf8")
  const pats = try JSON.parse(text) as string[]
  for (let i = 0; i < pats.length; i += 1) {{
    const msg = check(pats[i]!)
    if (msg !== "") console.log("FAIL " + i + " " + msg)
  }}
  console.log("done " + pats.length)
}}

try main()
"""


def tov_template(body):
    # Inside a template literal only backslash, backtick and "${" need escaping.
    out = body.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    return "`" + out + "`"


def engine_failures(tov, patterns):
    """Indices of patterns that the Raiju RE2 engine rejects."""
    if not patterns:
        return set()
    with tempfile.TemporaryDirectory() as tmp:
        probe = pathlib.Path(tmp) / "probe.tov"
        pats = pathlib.Path(tmp) / "patterns.json"
        probe.write_text(PROBE.format(regex=(ROOT / "src" / "regex.tov").as_posix()), encoding="utf-8")
        pats.write_text(json.dumps(patterns), encoding="utf-8")
        res = subprocess.run([tov, "run", str(probe), str(pats)], capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit("tov run failed:\n%s%s" % (res.stdout, res.stderr))
    bad = set()
    done = False
    for line in res.stdout.splitlines():
        if line.startswith("FAIL "):
            idx, _, msg = line[5:].partition(" ")
            bad.add(int(idx))
            print("  engine rejects pattern %d: %s" % (int(idx), msg))
        elif line.startswith("done "):
            done = True
    if not done:
        raise SystemExit("probe did not finish:\n%s%s" % (res.stdout, res.stderr))
    return bad


def number(value):
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SystemExit("entropy is not a number: %r" % (value,))
    return str(value)


def field(value, rule_id):
    s = str(value)
    if "\t" in s or "\n" in s or "\r" in s:
        raise SystemExit("%s: field contains a tab or newline" % rule_id)
    return s


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    checkout = pathlib.Path(sys.argv[1])
    version = sys.argv[2]
    tov = os.environ.get("TOV", str(DEFAULT_TOV))
    config = tomllib.loads((checkout / "config" / "gitleaks.toml").read_text(encoding="utf-8"))
    license_text = (checkout / "LICENSE").read_text(encoding="utf-8").strip()

    rules = config["rules"]
    ids = [r["id"] for r in rules]
    if len(set(ids)) != len(ids):
        raise SystemExit("duplicate rule ids in gitleaks.toml")

    candidates = []
    skipped = []
    for r in rules:
        if not r.get("regex"):
            skipped.append((r["id"], "no regex (path-only rule)"))
        else:
            candidates.append(r)

    bad = engine_failures(tov, [r["regex"] for r in candidates])
    kept = []
    for i, r in enumerate(candidates):
        if i in bad:
            skipped.append((r["id"], "RE2 engine rejects the regex"))
        else:
            kept.append(r)

    lines = []
    for r in kept:
        lines.append("\t".join([
            field(r["id"], r["id"]),
            number(r.get("entropy")),
            str(r.get("secretGroup", 0)),
            json.dumps(r.get("keywords", []), ensure_ascii=False),
            field(r["description"], r["id"]),
            field(r["regex"], r["id"]),
        ]))

    header = [
        "// Generated by scripts/gen_gitleaks.py from gitleaks %s (config/gitleaks.toml). Do not edit." % version,
        "// Columns, tab-separated: id, entropy (empty when unset), secretGroup, keywords (JSON array),",
        "// description, regex. guard_secrets.tov reads them; the engine matches the whole regex.",
        "//",
        "// %d of %d rules are in the table. Skipped at generation:" % (len(kept), len(rules)),
    ]
    if skipped:
        for rid, why in skipped:
            header.append("//   %s: %s" % (rid, why))
    else:
        header.append("//   none")
    header.append("//")
    header.append("// gitleaks is distributed under the following license:")
    for ln in license_text.split("\n"):
        header.append(("// " + ln).rstrip())
    header.append("")

    body = "\n".join(lines) + "\n"
    OUT.write_text(
        "\n".join(header) + "export const GITLEAKS_DATA: string = " + tov_template(body) + "\n",
        encoding="utf-8",
    )
    print("wrote %s: %d of %d rules" % (OUT, len(kept), len(rules)))
    print("skipped %d: %s" % (len(skipped), ", ".join(rid for rid, _ in skipped) or "none"))


main()

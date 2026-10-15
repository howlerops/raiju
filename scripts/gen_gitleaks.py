#!/usr/bin/env python3
"""Write src/guard_gitleaks_data.tov from the upstream gitleaks rule set.

Usage: TOV=/path/to/tov scripts/gen_gitleaks.py GITLEAKS_CHECKOUT VERSION

GITLEAKS_CHECKOUT is a gitleaks clone checked out at the release tag VERSION
(for example v8.30.1). The script reads config/gitleaks.toml and LICENSE from it.
Each rule with a regex becomes one line of a tab-separated table:

    id  entropy  secretGroup  keywords(JSON array)  description  regex  allowlists(JSON array)

The global allowlist is a JSON object in GITLEAKS_ALLOWLIST. An allowlist is
{target, all, regexes, stopwords}: target is gitleaks' regexTarget, all is set for
condition AND. Paths and commits are dropped: a prompt has neither, so an OR
allowlist keeps its regexes and stopwords, and an AND allowlist with paths can never
match a prompt and is left out.

Rules without a regex (path-only rules) are skipped. So are rules whose regex the
Raiju RE2 engine (src/regex.tov) cannot compile; the check runs the engine on
every pattern, in all three forms guard_regex.tov builds, with the patterns
passed to a small Tov program. Allowlist regexes the engine cannot compile are
dropped (an OR allowlist then allows less, an AND allowlist is left out).

Literal values that look like credentials (a run of 20 or more letters and digits)
are not written to the file: gitleaks' gcp-api-key allowlist is a list of such
keys, and a repository should not hold them. Skipped rules and allowlist entries
are listed in the generated header.

Tov cannot read files at build time, so the table is compiled in as a template
literal, as scripts/gen_pricing.py does. Re-run this on upgrade.
"""
import json
import os
import pathlib
import re
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


def literal_value(s):
    """True for a value that looks like a credential: a run of 20 or more letters and digits."""
    for run in re.findall(r"[A-Za-z0-9_-]{20,}", s):
        if re.search(r"[0-9]", run) and re.search(r"[A-Za-z]", run):
            return True
    return False


def allow_list(a, label, notes):
    """The allowlist as the engine applies it, or None when it cannot change a prompt finding."""
    cond = a.get("condition", "OR")
    if cond not in ("OR", "AND"):
        raise SystemExit("%s: unknown condition %r" % (label, cond))
    if cond == "AND" and (a.get("paths") or a.get("commits")):
        notes.append("%s: AND allowlist with paths (a prompt has no path)" % label)
        return None
    regexes = []
    stopwords = []
    lost = 0
    for x in a.get("regexes", []):
        if literal_value(x):
            lost += 1
        else:
            regexes.append(x)
    for x in a.get("stopwords", []):
        if literal_value(x):
            lost += 1
        else:
            stopwords.append(x)
    if lost:
        notes.append("%s: %d literal credential-like values not written" % (label, lost))
        if cond == "AND":
            return None
    if not regexes and not stopwords:
        return None
    return {
        "target": a.get("regexTarget", ""),
        "all": cond == "AND",
        "regexes": regexes,
        "stopwords": stopwords,
    }


def drop_failing(allow, bad_regex, notes, label):
    """Removes regexes the engine rejects; an AND allowlist that loses one is left out."""
    if allow is None:
        return None
    keep = [x for x in allow["regexes"] if x not in bad_regex]
    if len(keep) != len(allow["regexes"]):
        notes.append("%s: %d regexes the engine rejects not written" % (label, len(allow["regexes"]) - len(keep)))
        if allow["all"]:
            return None
        allow["regexes"] = keep
    if not allow["regexes"] and not allow["stopwords"]:
        return None
    return allow


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

    # Allowlists: every regex goes through the engine once, in one probe.
    notes = []
    labelled = [("global", config.get("allowlist"))]
    for r in kept:
        for n, a in enumerate(r.get("allowlists", [])):
            labelled.append(("%s allowlist %d" % (r["id"], n + 1), a))
    pending = []
    for label, a in labelled:
        if a is not None:
            pending.append((label, allow_list(a, label, notes)))
    every = sorted({x for _, al in pending if al is not None for x in al["regexes"]})
    bad_regex = set(every[i] for i in engine_failures(tov, every))
    allow_for = {}
    global_allow = None
    for label, al in pending:
        al = drop_failing(al, bad_regex, notes, label)
        if label == "global":
            global_allow = al
        else:
            allow_for[label] = al

    lines = []
    for r in kept:
        allows = []
        for n in range(len(r.get("allowlists", []))):
            al = allow_for.get("%s allowlist %d" % (r["id"], n + 1))
            if al is not None:
                allows.append(al)
        lines.append("\t".join([
            field(r["id"], r["id"]),
            number(r.get("entropy")),
            str(r.get("secretGroup", 0)),
            json.dumps(r.get("keywords", []), ensure_ascii=False),
            field(r["description"], r["id"]),
            field(r["regex"], r["id"]),
            json.dumps(allows, ensure_ascii=False, separators=(",", ":")),
        ]))

    header = [
        "// Generated by scripts/gen_gitleaks.py from gitleaks %s (config/gitleaks.toml). Do not edit." % version,
        "// Columns, tab-separated: id, entropy (empty when unset), secretGroup, keywords (JSON array),",
        "// description, regex, allowlists (JSON array of {target, all, regexes, stopwords}).",
        "// guard_secrets.tov reads them. GITLEAKS_ALLOWLIST is the global allowlist, in the same form.",
        "//",
        "// %d of %d rules are in the table. Skipped at generation:" % (len(kept), len(rules)),
    ]
    if skipped:
        for rid, why in skipped:
            header.append("//   %s: %s" % (rid, why))
    else:
        header.append("//   none")
    header.append("// Allowlists, in part or whole, not written at generation:")
    if notes:
        for note in notes:
            header.append("//   " + note)
    else:
        header.append("//   none")
    header.append("//")
    header.append("// gitleaks is distributed under the following license:")
    for ln in license_text.split("\n"):
        header.append(("// " + ln).rstrip())
    header.append("")

    body = "\n".join(lines) + "\n"
    allow_text = json.dumps(global_allow if global_allow is not None else {"target": "", "all": False, "regexes": [], "stopwords": []}, ensure_ascii=False, separators=(",", ":")) + "\n"
    OUT.write_text(
        "\n".join(header)
        + "export const GITLEAKS_DATA: string = " + tov_template(body) + "\n"
        + "export const GITLEAKS_ALLOWLIST: string = " + tov_template(allow_text) + "\n",
        encoding="utf-8",
    )
    print("wrote %s: %d of %d rules" % (OUT, len(kept), len(rules)))
    print("skipped %d: %s" % (len(skipped), ", ".join(rid for rid, _ in skipped) or "none"))
    for note in notes:
        print("allowlist: " + note)


main()

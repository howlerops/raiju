#!/usr/bin/env python3
"""Writes docs/config-reference.md: every config.json key Raiju reads, from the types in src/.

It walks the Config type in src/config.tov and every type it names (in any src/*.tov file), and lists each key
with its type and the comment written above it (or after it on the same line). It then adds the Bifrost keys that
src/config_compat.tov knows (the *Keys() lists: names Raiju maps on load) and its notes table (keys that are read
and not applied), so a key the loader accepts is never missing from the reference.

Usage:
  scripts/gen_config_doc.py            rewrite docs/config-reference.md
  scripts/gen_config_doc.py --check    exit 1 when the file is out of date, or a top-level key has no description

A new top-level key needs a comment above it in Config, or an entry in SECTION_NOTES below.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "config-reference.md")

# A short description for the top-level sections whose field in Config has no comment of its own.
SECTION_NOTES = {
    "client": "Gateway-wide request handling: logging, auth on inference, CORS, body limits, header handling and MCP defaults (Bifrost's client section).",
    "providers": "Providers by name (openai, anthropic, a custom name, ...): their keys, network settings and quirks.",
    "governance": "Virtual keys, budgets, rate limits, teams, customers, users, roles, routing rules and admin auth.",
    "cache": "The exact-match response cache.",
    "pricing": "Price overrides by model, on top of the built-in table and pricing sync.",
    "prompt_cache": "The gateway's prompt-cache breakpoints (Anthropic-style cache_control).",
    "health": "Provider health checks and the key and provider cool-down after failures.",
    "guardrails": "PII and secret redaction and the other guardrails, on requests and answers.",
    "logs_store": "The request log store (files under the app dir; /api/logs reads it).",
    "otel": "OpenTelemetry traces and metrics export (OTLP over HTTP or gRPC).",
    "mcp": "The MCP gateway: client connections, tool execution, tool groups and code mode.",
    "plugins": "Plugins in Bifrost's format: built-in names, WebAssembly files or URLs, with their config.",
    "semantic_cache": "The semantic cache: embedding model, threshold and where entries are kept.",
    "pricing_sync": "Periodic download of the pricing datasheet.",
    "secrets": "Secret references resolved when the config loads (env, files, cloud secret managers).",
    "audit": "The tamper-evident audit log of management actions.",
    "alerts": "Alert rules and the channels they notify.",
    "session_affinity": "Sticky routing of a session to one key or provider.",
    "complexity_router": "Routing by prompt complexity tiers.",
    "log_exports": "Periodic export of request logs to object storage.",
    "exporters": "Streaming log exporters (Kafka, HTTP sinks, ...).",
    "cluster": "Several Raiju nodes sharing usage, state and configuration (docs/operations.md when present).",
    "oidc": "Sign-in to the web UI and API with an OpenID Connect provider.",
    "mcp_server": "Raiju's own MCP server at /mcp, which serves the gateway's tools to MCP clients.",
}

# Types whose keys are documented elsewhere: the row says where instead of listing them.
ELSEWHERE = {
    "CrewPriorsFile": "the priors file format, see docs/crew-routing.md",
    "CrewClassifierFile": "the classifier file format, see docs/crew-routing.md",
}

# config_compat.tov's key lists, and the config path each one is under. A list the generator does not know fails the
# run, so a new list gets its path here.
COMPAT_LISTS = {
    "topKeys": "",
    "clientKeys": "client",
    "oauth2ServerKeys": "client.oauth2_server_config",
    "providerKeys": "providers.<name>",
    "clusterKeys": "cluster",
    "clusterFeedKeys": "cluster.feed",
    "governanceKeys": "governance",
    "serverKeys": "server",
    "signInThrottleKeys": "server.sign_in_throttle",
    "mcpKeys": "mcp",
    "toolManagerKeys": "mcp.tool_manager_config",
    "keyChildKeys": "providers.<name>.keys[]",
}
# providerChildKeys(section) returns the keys of providers.<name>.<section>
COMPAT_SECTIONED = {"providerChildKeys": "providers.<name>.{section}"}

# What config_compat does with the Bifrost keys that have no rename note and no entry in its notes table.
COMPAT_NOTES = {
    "version": "Accepted (Bifrost's file version); no effect.",
    "source_of_truth": "Accepted (Bifrost's config-store setting); no effect: Raiju's source of truth is the file.",
    "env_label": "Accepted (Bifrost's environment label); no effect.",
    "guardrails_config": "Bifrost's guardrails, translated into `guardrails` when the config loads and merged with it (never saved back).",
    "server.read_buffer_size": "Accepted; no Raiju counterpart (the command line takes -host and -port).",
    "governance.complexity_analyzer_config": "Bifrost's complexity analyzer, read into `complexity_router`.",
    "mcp.tool_manager_config": "Bifrost's MCP runtime settings: each one is moved to the Raiju key named in its row when that key is unset (the Raiju key wins).",
    "mcp.tool_manager_config.code_mode_binding_level": "Read as `mcp.code_mode_binding_level`.",
    "mcp.tool_manager_config.code_mode_limits": "Read as `mcp.code_mode_limits`.",
    "mcp.tool_manager_config.max_instructions_per_client": "Read as `mcp.max_instructions_per_client`.",
    "mcp.tool_manager_config.oauth_private_allowlist": "Read as `mcp.oauth_private_allowlist`.",
    "mcp.tool_manager_config.max_agent_depth": "Read as `client.mcp_agent_depth`.",
    "mcp.tool_manager_config.disable_auto_tool_inject": "Read as `client.mcp_disable_auto_tool_inject`.",
}

MAX_DEPTH = 9


# ---------------------------------------------------------------- parsing Tov type declarations

class Rec:
    def __init__(self, fields):
        self.fields = fields  # [(name, optional, type, comment)]


class Ref:
    def __init__(self, name, args):
        self.name = name
        self.args = args


class Arr:
    def __init__(self, elem):
        self.elem = elem


class Union:
    def __init__(self, parts):
        self.parts = parts


class Lit:
    def __init__(self, text):
        self.text = text


class Opaque:
    def __init__(self, text):
        self.text = text


class Parser:
    def __init__(self, text, pos):
        self.t = text
        self.i = pos

    def ws(self, comments=None):
        """Skips blanks and comments; collects // comment lines into comments when given."""
        t = self.t
        while self.i < len(t):
            c = t[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif t.startswith("//", self.i):
                j = t.find("\n", self.i)
                j = len(t) if j < 0 else j
                if comments is not None:
                    comments.append(t[self.i + 2:j].strip())
                self.i = j
            elif t.startswith("/*", self.i):
                j = t.find("*/", self.i + 2)
                self.i = len(t) if j < 0 else j + 2
            else:
                break

    def peek(self):
        self.ws()
        return self.t[self.i] if self.i < len(self.t) else ""

    def ident(self):
        self.ws()
        m = re.compile(r"[A-Za-z_$][A-Za-z0-9_$.]*").match(self.t, self.i)
        if not m:
            return None
        self.i = m.end()
        return m.group(0)

    def type(self):
        self.ws()
        if self.peek() == "|":
            self.i += 1
        parts = [self.postfix()]
        while self.peek() == "|":
            self.i += 1
            parts.append(self.postfix())
        return parts[0] if len(parts) == 1 else Union(parts)

    def postfix(self):
        base = self.primary()
        while True:
            self.ws()
            if self.t.startswith("[]", self.i):
                self.i += 2
                base = Arr(base)
            else:
                return base

    def primary(self):
        c = self.peek()
        if c == "{":
            return self.record()
        if c in "\"'":
            j = self.t.index(c, self.i + 1)
            lit = self.t[self.i:j + 1]
            self.i = j + 1
            return Lit(lit)
        if c == "(":
            start = self.i
            depth = 0
            while self.i < len(self.t):
                ch = self.t[self.i]
                depth += ch == "("
                depth -= ch == ")"
                self.i += 1
                if depth == 0:
                    break
            self.ws()
            if self.t.startswith("=>", self.i):
                self.i += 2
                self.type()
                return Opaque("function")
            inner = Parser(self.t[start + 1:self.i - 1], 0).type()
            return inner
        name = self.ident()
        if name is None:
            raise SyntaxError(f"type expected at {self.t[self.i:self.i + 40]!r}")
        args = []
        if self.peek() == "<":
            self.i += 1
            args.append(self.type())
            while self.peek() == ",":
                self.i += 1
                args.append(self.type())
            if self.peek() != ">":
                raise SyntaxError("> expected")
            self.i += 1
        return Ref(name, args)

    def record(self):
        self.i += 1  # {
        fields = []
        while True:
            comments = []
            self.ws(comments)
            if self.i >= len(self.t):
                raise SyntaxError("unclosed record")
            if self.t[self.i] == "}":
                self.i += 1
                return Rec(fields)
            name = self.ident()
            if name is None:
                if self.t[self.i] in "\"'":
                    q = self.t[self.i]
                    j = self.t.index(q, self.i + 1)
                    name = self.t[self.i + 1:j]
                    self.i = j + 1
                else:
                    raise SyntaxError(f"field expected at {self.t[self.i:self.i + 40]!r}")
            if name == "readonly" and self.peek() not in "?:":
                name = self.ident()
            opt = False
            if self.peek() == "?":
                opt = True
                self.i += 1
            if self.peek() != ":":
                raise SyntaxError(f": expected after {name}")
            self.i += 1
            ftype = self.type()
            # a comment on the same line, after the comma
            j = self.i
            while j < len(self.t) and self.t[j] in " \t":
                j += 1
            if j < len(self.t) and self.t[j] in ",;":
                j += 1
                self.i = j
                while j < len(self.t) and self.t[j] in " \t":
                    j += 1
            if self.t.startswith("//", j):
                e = self.t.find("\n", j)
                e = len(self.t) if e < 0 else e
                comments.append(self.t[j + 2:e].strip())
                self.i = e
            fields.append((name, opt, ftype, " ".join(c for c in comments if c)))
            # the separator, if the type ended before it on another line (comments stay for the next field)
            j = self.i
            while j < len(self.t) and self.t[j] in " \t\r\n":
                j += 1
            if j < len(self.t) and self.t[j] in ",;":
                self.i = j + 1


DECL = re.compile(r"^(export\s+)?type\s+([A-Za-z_][A-Za-z0-9_]*)\s*(<[^=]*>)?\s*=\s*", re.M)


def read_types():
    types = {}
    src = os.path.join(ROOT, "src")
    files = sorted(os.path.join(src, f) for f in os.listdir(src) if f.endswith(".tov"))
    prov = os.path.join(src, "providers")
    if os.path.isdir(prov):
        files += sorted(os.path.join(prov, f) for f in os.listdir(prov) if f.endswith(".tov"))
    for path in files:
        text = open(path, encoding="utf-8").read()
        for m in DECL.finditer(text):
            name = m.group(2)
            # the comment block right above the declaration
            lines = text[:m.start()].split("\n")
            if lines and lines[-1].strip() == "":
                lines.pop()
            doc = []
            while lines and lines[-1].strip().startswith("//"):
                doc.insert(0, lines.pop().strip()[2:].strip())
            try:
                t = Parser(text, m.end()).type()
            except (SyntaxError, ValueError, IndexError):
                continue
            rel = os.path.relpath(path, ROOT)
            if name in types and types[name][2] != rel:
                # the same name in two modules: keep the config module's
                if not rel.endswith("config.tov"):
                    continue
            types[name] = (t, " ".join(doc), rel)
    return types


# ---------------------------------------------------------------- config_compat key lists

def compat_lists():
    text = open(os.path.join(ROOT, "src", "config_compat.tov"), encoding="utf-8").read()
    out = {}
    for m in re.finditer(r"^function (\w+Keys)\(([^)]*)\): string\[\] \{(.*?)^\}", text, re.M | re.S):
        name, body = m.group(1), m.group(3)
        if name in COMPAT_SECTIONED:
            for sm in re.finditer(r'if \(\w+ === "(\w+)"\) return \[(.*?)\]', body, re.S):
                prefix = COMPAT_SECTIONED[name].format(section=sm.group(1))
                out[prefix] = re.findall(r'"([^"]+)"', sm.group(2))
            continue
        if name not in COMPAT_LISTS:
            raise SystemExit(f"gen_config_doc: config_compat.tov has a key list {name}() this script does not place; add it to COMPAT_LISTS")
        rm = re.search(r"return \[(.*?)\]", body, re.S)
        out[COMPAT_LISTS[name]] = re.findall(r'"([^"]+)"', rm.group(1)) if rm else []
    notes = {}
    nm = re.search(r"function noteTable\(\).*?const pairs: string\[\]\[\] = \[(.*?)^  \]", text, re.M | re.S)
    consts = dict(re.findall(r'^const (\w+) = "([^"]*)"', text, re.M))
    if nm:
        for pm in re.finditer(r'\["([^"]+)",\s*(?:"((?:[^"\\]|\\.)*)"|(\w+))\]', nm.group(1)):
            notes[pm.group(1).replace("providers.*", "providers.<name>")] = pm.group(2) if pm.group(2) is not None else consts.get(pm.group(3), "")
    # the renames, from the startup notes: config: "cluster_config" read as "cluster"
    renames = {}
    for rm in re.finditer(r'"([a-z_.$]+)" (?:is )?read as "([a-z_.]+)"', text):
        if rm.group(1) != rm.group(2):
            renames.setdefault(rm.group(1), rm.group(2))
    return out, notes, renames


# ---------------------------------------------------------------- walking Config

def show(t):
    if isinstance(t, Rec):
        return "object"
    if isinstance(t, Arr):
        inner = show(t.elem)
        return f"({inner})[]" if isinstance(t.elem, Union) else inner + "[]"
    if isinstance(t, Union):
        return " | ".join(show(p) for p in t.parts)
    if isinstance(t, Lit):
        return t.text
    if isinstance(t, Opaque):
        return t.text
    if t.name in ("Map", "Record") and len(t.args) == 2:
        return f"map of {show(t.args[1])}"
    if t.name in ("int", "f64", "number", "bool", "string", "u8", "i64"):
        return {"f64": "number", "i64": "int", "u8": "int"}.get(t.name, t.name)
    return "object" if t.args == [] else t.name


class Walker:
    def __init__(self, types):
        self.types = types
        self.rows = []  # (path, type, description)

    def resolve(self, t, seen):
        """The named type behind a reference, with its doc, or None for a scalar."""
        if isinstance(t, Ref) and t.name in self.types and t.name not in seen:
            decl, doc, _ = self.types[t.name]
            return decl, doc, t.name
        return None

    def display(self, t):
        """The type column: aliases of scalars and string-literal unions are shown resolved."""
        if isinstance(t, Ref) and t.name in self.types:
            decl = self.types[t.name][0]
            if isinstance(decl, (Union, Lit)) or (isinstance(decl, Ref) and decl.name in ("string", "int", "f64", "bool")):
                return show(decl)
        if isinstance(t, Arr):
            inner = self.display(t.elem)
            return f"({inner})[]" if "|" in inner else inner + "[]"
        if isinstance(t, Union):
            return " | ".join(self.display(p) for p in t.parts)
        if isinstance(t, Ref) and t.name in ("Map", "Record") and len(t.args) == 2:
            return "map of " + self.display(t.args[1])
        return show(t)

    def walk(self, rec, prefix, seen, depth, parent_doc):
        for name, _opt, ftype, comment in rec.fields:
            path = f"{prefix}.{name}" if prefix else name
            self.field(path, ftype, comment or mentions(parent_doc, name), seen, depth)

    def field(self, path, ftype, comment, seen, depth):
        doc = comment
        children = []  # (suffix, record, type doc, seen)
        self.collect(ftype, "", seen, children)
        if not doc:
            for _suffix, _rec, tdoc, _seen in children:
                if tdoc:
                    doc = tdoc
                    break
        elsewhere = [n for n in self.names(ftype) if n in ELSEWHERE]
        if elsewhere:
            doc = doc + " (" + ELSEWHERE[elsewhere[0]] + ")" if doc else ELSEWHERE[elsewhere[0]].capitalize() + "."
        self.rows.append((path, self.display(ftype), doc))
        if depth >= MAX_DEPTH:
            return
        for suffix, rec, tdoc, s2 in children:
            # the keys below are described by the sentences of the type's comment (or this key's) that name them
            self.walk(rec, path + suffix, s2, depth + 1, " ".join(x for x in (tdoc, comment) if x))

    def names(self, t):
        if isinstance(t, Ref):
            out = [t.name]
            for a in t.args:
                out += self.names(a)
            return out
        if isinstance(t, Arr):
            return self.names(t.elem)
        if isinstance(t, Union):
            return [n for p in t.parts for n in self.names(p)]
        return []

    def collect(self, t, suffix, seen, out):
        """The records a field's type holds, with the path suffix each one's keys go under."""
        if isinstance(t, Rec):
            out.append((suffix, t, "", seen))
        elif isinstance(t, Arr):
            self.collect(t.elem, suffix + "[]", seen, out)
        elif isinstance(t, Union):
            for p in t.parts:
                self.collect(p, suffix, seen, out)
        elif isinstance(t, Ref):
            if t.name in ("Map", "Record") and len(t.args) == 2:
                self.collect(t.args[1], suffix + ".<name>", seen, out)
                return
            if t.name in ELSEWHERE:
                return
            r = self.resolve(t, seen)
            if r is None:
                return
            decl, doc, name = r
            if isinstance(decl, Rec):
                out.append((suffix, decl, doc, seen | {name}))
            else:
                before = len(out)
                self.collect(decl, suffix, seen | {name}, out)
                if doc and len(out) > before:
                    s, rec, d, s2 = out[before]
                    out[before] = (s, rec, d or doc, s2)


def compat_note(path, notes, renames):
    """What happens to a Bifrost key on load: its note, its rename, or an entry of COMPAT_NOTES."""
    if path in notes:
        n = notes[path]
        return n[0].upper() + n[1:] + "."
    if path in renames:
        return f"Read as `{renames[path]}`."
    if path in COMPAT_NOTES:
        return COMPAT_NOTES[path]
    inner = [f"`{k}` is read as `{v}`" for k, v in sorted(renames.items()) if k.startswith(path + ".")]
    if inner:
        return "; ".join(inner) + "."
    if path in COMPAT_NOTES:
        return COMPAT_NOTES[path]
    return "Read on load (config_compat.tov); the startup log says what it became."


def mentions(doc, name):
    """The sentences of a type's comment that name a key, for a key with no comment of its own."""
    if not doc:
        return ""
    word = re.compile(r"(?<![\w.])" + re.escape(name) + r"(?![\w])")
    picked = [s.rstrip(";") for s in sentences(doc) if word.search(s)]
    return " ".join(picked[:2])


def sentences(doc):
    """A comment cut after each . or ; that is followed by a space, outside parentheses."""
    out, depth, start = [], 0, 0
    for i, c in enumerate(doc):
        depth += c == "("
        depth -= c == ")" and depth > 0
        if c in ".;" and depth == 0 and (i + 1 == len(doc) or doc[i + 1] == " "):
            out.append(doc[start:i + 1].strip())
            start = i + 1
    if doc[start:].strip():
        out.append(doc[start:].strip())
    return out


def esc(s):
    return s.replace("|", "\\|").replace("\n", " ")


def generate():
    types = read_types()
    if "Config" not in types or not isinstance(types["Config"][0], Rec):
        raise SystemExit("gen_config_doc: no Config record in src/config.tov")
    w = Walker(types)
    config = types["Config"][0]
    top_docs = {}
    for name, _opt, ftype, comment in config.fields:
        at = len(w.rows)
        w.field(name, ftype, comment or SECTION_NOTES.get(name, ""), frozenset({"Config"}), 1)
        # the field's comment, else SECTION_NOTES, else the comment above its type
        top_docs[name] = w.rows[at][2]
    lists, notes, renames = compat_lists()
    typed = {r[0] for r in w.rows}

    # the Bifrost names config_compat reads that are not keys of the typed config
    compat_rows = []
    for prefix, keys in lists.items():
        for k in keys:
            path = f"{prefix}.{k}" if prefix else k
            if path not in typed and k != "$schema":
                compat_rows.append(path)
    for p in list(notes) + list(renames):
        if p not in typed and p not in compat_rows:
            compat_rows.append(p)

    problems = [n for n, d in top_docs.items() if not d]
    lines = []
    lines.append("# Configuration reference")
    lines.append("")
    lines.append("<!-- Generated by scripts/gen_config_doc.py from the types in src/ and src/config_compat.tov. Do not edit by hand: run `make config-doc`. -->")
    lines.append("")
    lines.append("Every key of `config.json` that Raiju reads. The file format is Bifrost's, so a Bifrost config loads as it is;")
    lines.append("Bifrost names that Raiju maps on load are listed at the end. Values written `env.NAME` are read from the")
    lines.append("environment when the config loads. `<name>` stands for a key you choose (a provider's name, a map key), and `[]`")
    lines.append("for each element of a list. Descriptions are the comments in the source; defaults are given there when a key")
    lines.append("has one. The command-line flags (`-app-dir`, `-config`, `-host`, `-port`, `-workers`, `-server`, `-mode`,")
    lines.append("`-healthcheck`) are in the README.")
    lines.append("")
    keyed = len(w.rows)
    described = sum(1 for r in w.rows if r[2])
    lines.append(f"{keyed} keys ({described} with a description), and {len(compat_rows)} Bifrost keys read through config_compat.")
    lines.append("")
    lines.append("## Sections")
    lines.append("")
    for name, _opt, _t, _c in config.fields:
        lines.append(f"- [`{name}`](#{name}): {esc(top_docs[name])}")
    lines.append("")
    by_top = {}
    for path, typ, doc in w.rows:
        top = re.split(r"[.\[]", path, maxsplit=1)[0]
        by_top.setdefault(top, []).append((path, typ, doc))
    for name, _opt, _t, _c in config.fields:
        lines.append(f"## {name}")
        lines.append("")
        if top_docs[name]:
            lines.append(top_docs[name])
            lines.append("")
        lines.append("| Key | Type | Description |")
        lines.append("|---|---|---|")
        for path, typ, doc in by_top.get(name, []):
            note = notes.get(path)
            d = doc
            if note:
                d = (d + " " if d else "") + f"Not applied: {path.split('.')[-1]} {note}."
            lines.append(f"| `{esc(path)}` | {esc(typ)} | {esc(d)} |")
        lines.append("")
    lines.append("## Bifrost keys read through config_compat")
    lines.append("")
    lines.append("These are Bifrost names that `src/config_compat.tov` reads: most are rewritten on load to the Raiju key")
    lines.append("that holds the same setting (for example `cluster_config` to `cluster`, `alerting` to `alerts`), and the")
    lines.append("ones with a note are read and not applied. The startup log says what each file's keys became.")
    lines.append("")
    lines.append("| Key | Note |")
    lines.append("|---|---|")
    for p in sorted(compat_rows):
        lines.append(f"| `{esc(p)}` | {esc(compat_note(p, notes, renames))} |")
    lines.append("")
    return "\n".join(lines), problems


def main():
    check = "--check" in sys.argv[1:]
    text, problems = generate()
    if problems:
        print("gen_config_doc: top-level keys with no description (add a comment above the key in Config, or SECTION_NOTES): " + ", ".join(problems), file=sys.stderr)
        sys.exit(1)
    if check:
        old = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if old != text:
            print("docs/config-reference.md is out of date; run make config-doc and commit it", file=sys.stderr)
            sys.exit(1)
        print("config-doc: up to date")
        return
    open(OUT, "w", encoding="utf-8").write(text)
    print(f"wrote {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    main()

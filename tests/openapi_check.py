#!/usr/bin/env python3
# Checks docs/openapi/management.yaml against the routes the gateway serves.
#
# 1. The spec is valid OpenAPI 3.1 (openapi-spec-validator when installed) and every $ref resolves.
# 2. Every operation in the spec is served: a gateway started here answers its method and path
#    with something other than 405 or the generic "no route" 404.
# 3. Every /api, /mcp, /health, /ready, /metrics and /v1/mcp/tool/execute path the source names (string
#    literals in src/*.tov) that the gateway serves is listed in the spec.
#
# Usage: python3 tests/openapi_check.py [path/to/raiju]   (default: build/raiju)
import glob
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

try:
    import yaml
except ImportError:
    sys.exit("openapi-check needs PyYAML (pip install pyyaml)")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "docs", "openapi", "management.yaml")
BIN = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "raiju")
PORTS = [p for p in range(18190, 18200) if p != 18193]  # 18193 is the e2e UDP beacon port
METHODS = ["GET", "POST", "PUT", "DELETE"]
GENERIC_404 = re.compile(r"no route|no such route")
CANDIDATE = re.compile(r'["`](/(?:api/[^"`\s]*|mcp[^"`\s]*|v1/mcp/tool/execute|health|ready|metrics))')
PARAM = re.compile(r"\{[^}]+\}")
# Known bug, listed in the ledger's LIMITS: GET /api/mcp/virtual answers every method with 200
# (ops.virtualView ignores the method). Remove an entry when the route rejects the other methods.
KNOWN_ANY_METHOD = set()


def refs_resolve(node, root, where, problems):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref":
                cur = root
                for part in v.lstrip("#/").split("/"):
                    if not isinstance(cur, dict) or part not in cur:
                        problems.append("%s: unresolved $ref %s" % (where, v))
                        return
                    cur = cur[part]
            else:
                refs_resolve(v, root, where, problems)
    elif isinstance(node, list):
        for v in node:
            refs_resolve(v, root, where, problems)


def source_candidates():
    found = set()
    for path in glob.glob(os.path.join(ROOT, "src", "*.tov")) + glob.glob(os.path.join(ROOT, "src", "providers", "*.tov")):
        with open(path, encoding="utf8") as f:
            text = f.read().replace("\\", "")  # the UI page is embedded with escaped quotes
        for m in CANDIDATE.finditer(text):
            p = m.group(1)
            p = p.split("${")[0].split("?")[0].rstrip("/")
            if p in ("", "/api"):
                continue
            found.add(p)
    return sorted(found)


def is_generic(status, body):
    return status == 404 and GENERIC_404.search(body) is not None


def served(status, body):
    return status != 405 and not is_generic(status, body)


def template_regex(template):
    # /api/x/{id} matches /api/x/<one segment>; the literal parts are escaped
    out = ""
    last = 0
    for m in PARAM.finditer(template):
        out += re.escape(template[last:m.start()]) + "[^/]+"
        last = m.end()
    out += re.escape(template[last:])
    return re.compile("^" + out + "$")


def free_port():
    for port in PORTS:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            s.close()
            return port
        except OSError:
            s.close()
    sys.exit("no free port in 18190-18199")


def wait_ready(port, proc):
    for _ in range(100):
        if proc.poll() is not None:
            sys.exit("the gateway exited at startup (see its log)")
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            c.request("GET", "/health")
            if c.getresponse().status == 200:
                return
        except OSError:
            time.sleep(0.1)
    sys.exit("the gateway did not answer /health")


SETUP_TOKEN = "openapi-check-setup"


def probe(port, method, path):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    body = None if method == "GET" else ""
    c.request(method, path, body=body, headers={"content-type": "application/json", "x-bifrost-setup-token": SETUP_TOKEN})
    r = c.getresponse()
    data = r.read(4096).decode("utf8", "replace")
    c.close()
    return r.status, data


def main():
    problems = []
    with open(SPEC, encoding="utf8") as f:
        spec = yaml.safe_load(f)

    try:
        from openapi_spec_validator import validate
        validate(spec)
        print("spec: valid OpenAPI %s" % spec["openapi"])
    except ImportError:
        print("spec: openapi-spec-validator not installed; skipped schema validation")
    except Exception as e:  # the validator's message names the failing node
        problems.append("spec: invalid OpenAPI: %s" % str(e).splitlines()[0])
    refs_resolve(spec, spec, "spec", problems)

    spec_ops = []
    templates = []
    for path, item in spec["paths"].items():
        templates.append(path)
        for m in item:
            if m.upper() in METHODS:
                spec_ops.append((m.upper(), path))
            else:
                problems.append("%s %s: method %s is not one the probe covers" % (m.upper(), path, m))
    cands = source_candidates()

    if not os.path.exists(BIN):
        sys.exit("no gateway binary at %s (run make build)" % BIN)
    port = free_port()
    workdir = tempfile.mkdtemp(prefix="raiju-openapi-")
    cfg = os.path.join(workdir, "config.json")
    with open(cfg, "w", encoding="utf8") as f:
        # /api is locked without an admin (Bifrost's setup lock): the probes send this setup token
        json.dump({"setup_token": SETUP_TOKEN, "providers": {}, "pricing_sync": {"url": "http://127.0.0.1:9"}}, f)
    log = open(os.path.join(workdir, "gateway.log"), "w")
    proc = subprocess.Popen([BIN, "-port", str(port), "-host", "127.0.0.1", "-config", cfg], stderr=log, stdout=log)
    try:
        wait_ready(port, proc)

        # 2. every spec operation is served by its method
        missing = []
        for method, path in spec_ops:
            concrete = PARAM.sub("probe-id", path)
            status, body = probe(port, method, concrete)
            if not served(status, body):
                missing.append("%s %s -> %d %s" % (method, path, status, body[:80]))
        for m in missing:
            problems.append("spec lists a route the gateway does not serve: " + m)

        # 3. every source-named route the gateway serves is in the spec
        extra = []
        served_cands = 0
        for p in cands:
            concrete = p
            hit = False
            for method in METHODS:
                status, body = probe(port, method, concrete)
                if served(status, body) or status == 405:
                    hit = True
                    break
            if not hit:
                continue
            served_cands += 1
            if not any(template_regex(t).match(p) for t in templates):
                extra.append(p)
        for p in extra:
            problems.append("gateway serves a path the spec does not list: " + p)

        # 4. no method is served on a listed path that the spec leaves out
        listed = set(spec_ops)
        for path in templates:
            concrete = PARAM.sub("probe-id", path)
            for method in METHODS:
                if (method, path) in listed:
                    continue
                status, body = probe(port, method, concrete)
                # a 404 proves little here: handlers answer a specific 404 for ids they cannot find
                # on methods they do not serve, so only a non-404, non-405 answer counts as served
                if status not in (404, 405) and (method, path) not in KNOWN_ANY_METHOD:
                    problems.append("gateway answers %s %s (%d) but the spec does not list it" % (method, path, status))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        shutil.rmtree(workdir, ignore_errors=True)

    print("operations: %d in the spec, %d paths; source route literals: %d, served: %d"
          % (len(spec_ops), len(templates), len(cands), served_cands))
    if problems:
        for p in problems:
            print("FAIL " + p)
        print("openapi-check: %d problem(s)" % len(problems))
        sys.exit(1)
    print("openapi-check: ok")


if __name__ == "__main__":
    main()

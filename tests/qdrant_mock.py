"""A minimal Qdrant REST mock for e2e: collections, upsert, query (cosine, must-filter) and delete."""
import json, math, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

COLS = {}
CALLS = []

def cos(a, b):
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return 0.0 if na == 0 or nb == 0 else sum(x * y for x, y in zip(a, b)) / (na * nb)

def ok(cond, payload):
    if "range" in cond:
        v = payload.get(cond["key"])
        return v is not None and all(not (op == "gt" and not v > x) for op, x in cond["range"].items())
    return payload.get(cond["key"]) == cond["match"]["value"]

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def reply(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def handle_any(self):
        n = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        path = self.path.split("?")[0]
        CALLS.append({"method": self.command, "path": path})
        parts = path.strip("/").split("/")
        if path == "/_calls": return self.reply(200, CALLS)
        if len(parts) < 2 or parts[0] != "collections": return self.reply(404, {})
        ns = parts[1]
        if len(parts) == 2 and self.command == "PUT":
            if ns in COLS: return self.reply(409, {"status": {"error": "exists"}})
            COLS[ns] = {}; return self.reply(200, {"result": True})
        col = COLS.get(ns)
        if col is None: return self.reply(404, {"status": {"error": "no collection"}})
        op = "/".join(parts[2:])
        if op == "points" and self.command == "PUT":
            for p in body["points"]: col[p["id"]] = p
            return self.reply(200, {"result": {"status": "completed"}})
        if op == "points/query":
            best = None
            for p in col.values():
                if not all(ok(c, p["payload"]) for c in body.get("filter", {}).get("must", [])): continue
                s = cos(body["query"], p["vector"])
                if s >= body.get("score_threshold", 0) and (best is None or s > best[0]): best = (s, p)
            pts = [] if best is None else [{"id": best[1]["id"], "score": best[0], "payload": best[1]["payload"]}]
            return self.reply(200, {"result": {"points": pts}})
        if op == "points/delete":
            for i in body.get("points", []): col.pop(i, None)
            return self.reply(200, {"result": {"status": "completed"}})
        return self.reply(404, {})
    do_GET = do_PUT = do_POST = do_DELETE = handle_any

ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()

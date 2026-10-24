"""A minimal Pinecone index mock for e2e: upsert, top-1 query with a $and metadata filter
($gt and $eq), delete by ids, and describe_index_stats. Checks the Api-Key header."""
import json, math, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KEY = "pc-key"
NS = {}     # namespace -> {id: {"values": [...], "metadata": {...}}}
CALLS = []

def cos(a, b):
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return 0.0 if na == 0 or nb == 0 else sum(x * y for x, y in zip(a, b)) / (na * nb)

def ok(cond, meta):
    for key, op in cond.items():
        have = meta.get(key)
        for o, want in op.items():
            if o == "$gt" and not (have is not None and have > want): return False
            if o == "$eq" and have != want: return False
    return True

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def reply(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(b))); self.end_headers()
        self.wfile.write(b)
    def handle_any(self):
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b""
        path = self.path.split("?")[0]
        CALLS.append({"method": self.command, "path": path})
        if path == "/_calls": return self.reply(200, CALLS)
        if self.headers.get("api-key") != KEY: return self.reply(401, {"error": {"message": "invalid api key"}})
        body = json.loads(raw or b"{}")
        if path == "/describe_index_stats":
            return self.reply(200, {"namespaces": {k: {"vectorCount": len(v)} for k, v in NS.items()}, "dimension": 0, "totalVectorCount": sum(len(v) for v in NS.values())})
        if path == "/vectors/upsert":
            ns = NS.setdefault(body.get("namespace", ""), {})
            for v in body["vectors"]:
                ns[v["id"]] = {"values": v["values"], "metadata": v.get("metadata", {})}
            return self.reply(200, {"upsertedCount": len(body["vectors"])})
        if path == "/query":
            ns = NS.get(body.get("namespace", ""), {})
            flt = body.get("filter", {}).get("$and", [])
            best = None
            for vid, v in ns.items():
                if not all(ok(c, v["metadata"]) for c in flt): continue
                s = cos(body["vector"], v["values"])
                if best is None or s > best[0]: best = (s, vid, v)
            matches = [] if best is None else [{"id": best[1], "score": best[0], "metadata": best[2]["metadata"]}]
            return self.reply(200, {"matches": matches, "namespace": body.get("namespace", "")})
        if path == "/vectors/delete":
            ns = NS.get(body.get("namespace", ""), {})
            for vid in body.get("ids", []): ns.pop(vid, None)
            # a delete by metadata filter: each field's $eq
            flt = body.get("filter")
            if flt:
                for vid in [vid for vid, v in ns.items() if all(v["metadata"].get(k) == c.get("$eq") for k, c in flt.items())]:
                    ns.pop(vid)
            return self.reply(200, {})
        return self.reply(404, {"error": {"message": "no route"}})
    do_GET = do_PUT = do_POST = do_DELETE = handle_any

ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()

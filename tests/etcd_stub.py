#!/usr/bin/env python3
"""A minimal etcd v3 JSON gateway for the leader-lock tests (cluster_config.leader_lock).

Leases expire on their own when they are not kept alive, and the keys attached to an expired lease
are deleted, as in etcd. Implements the calls the lock uses: lease grant, keepalive and revoke, and
the transaction that creates a key under a lease only when it is absent (otherwise it reads the key).
GET /__state lists the leases and keys, for the tests.

Usage: tests/etcd_stub.py <port>
"""
import base64, json, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

lock = threading.Lock()
leases = {}  # lease id (str) -> expiry (seconds, monotonic)
ttls = {}    # lease id (str) -> ttl (seconds)
kv = {}      # key (str) -> {"value": str, "lease": str}
next_id = [1000]


def now():
    return time.monotonic()


def expire():
    t = now()
    for lid in [i for i, at in leases.items() if at <= t]:
        del leases[lid]
        del ttls[lid]
        for k in [k for k, v in kv.items() if v["lease"] == lid]:
            del kv[k]


def b64d(s):
    return base64.b64decode(s).decode()


def b64e(s):
    return base64.b64encode(s.encode()).decode()


def key_out(k):
    return {"key": b64e(k), "value": b64e(kv[k]["value"]), "lease": kv[k]["lease"]}


def put(key, value, lease):
    if lease != "0" and lease not in leases:
        return None
    kv[key] = {"value": value, "lease": lease}
    return {}


def handle(path, req):
    """Returns (status, body) for one call."""
    with lock:
        expire()
        if path == "/v3/lease/grant":
            lid = str(next_id[0])
            next_id[0] += 1
            ttl = int(req.get("TTL", 0))
            leases[lid] = now() + ttl
            ttls[lid] = ttl
            return 200, {"ID": lid, "TTL": str(ttl)}
        if path == "/v3/lease/keepalive":
            lid = str(req.get("ID", ""))
            if lid not in leases:
                return 200, {"result": {"ID": lid, "TTL": "0"}}
            leases[lid] = now() + ttls[lid]
            return 200, {"result": {"ID": lid, "TTL": str(ttls[lid])}}
        if path == "/v3/lease/revoke":
            lid = str(req.get("ID", ""))
            leases.pop(lid, None)
            ttls.pop(lid, None)
            for k in [k for k, v in kv.items() if v["lease"] == lid]:
                del kv[k]
            return 200, {}
        if path == "/v3/kv/put":
            r = put(b64d(req["key"]), b64d(req.get("value", "")), str(req.get("lease", "0")))
            if r is None:
                return 400, {"error": "requested lease not found", "code": 5}
            return 200, {"header": {}}
        if path == "/v3/kv/range":
            k = b64d(req["key"])
            hits = [key_out(x) for x in kv if x == k]
            return 200, {"kvs": hits, "count": str(len(hits))}
        if path == "/v3/kv/txn":
            ok = True
            for c in req.get("compare", []):
                # the lock compares create_revision: 0 means the key is absent
                if c.get("target") != "CREATE" or c.get("result") != "EQUAL" or str(c.get("create_revision", "0")) != "0":
                    return 400, {"error": "unsupported compare"}
                if b64d(c["key"]) in kv:
                    ok = False
            responses = []
            for op in req.get("success" if ok else "failure", []):
                if "request_put" in op:
                    p = op["request_put"]
                    r = put(b64d(p["key"]), b64d(p.get("value", "")), str(p.get("lease", "0")))
                    if r is None:
                        return 400, {"error": "requested lease not found", "code": 5}
                    responses.append({"response_put": {}})
                elif "request_range" in op:
                    k = b64d(op["request_range"]["key"])
                    hits = [key_out(x) for x in kv if x == k]
                    responses.append({"response_range": {"kvs": hits, "count": str(len(hits))}})
            return 200, {"succeeded": ok, "responses": responses}
        if path == "/__state":
            return 200, {"leases": sorted(leases), "keys": {k: {"value": v["value"], "lease": v["lease"]} for k, v in kv.items()}}
    return 404, {"error": "not found"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        status, body = handle(self.path, {})
        self.reply(status, body)

    def do_POST(self):
        n = int(self.headers.get("content-length", "0") or 0)
        raw = self.rfile.read(n).decode() if n else "{}"
        try:
            req = json.loads(raw or "{}")
        except ValueError:
            return self.reply(400, {"error": "bad json"})
        status, body = handle(self.path, req)
        self.reply(status, body)

    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler)
    srv.serve_forever()

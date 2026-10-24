"""A minimal Weaviate REST and GraphQL mock for e2e: schema classes and their properties, objects (create, replace,
delete, batch delete by a where-filter), and a nearVector query with cosine distance and where-filters (And of
GreaterThan and Equal)."""
import json, math, re, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KEY = "wv-key"
CLASSES = {}   # class name -> {uuid: {"vector": [...], "props": {...}}}
PROPS = {}     # class name -> [property names]
CALLS = []

def cos(a, b):
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return 0.0 if na == 0 or nb == 0 else sum(x * y for x, y in zip(a, b)) / (na * nb)

OP = re.compile(r'\{path:\["([^"]+)"\],operator:(\w+),(valueNumber|valueText):("(?:[^"\\]|\\.)*"|[-0-9.eE+]+)\}')

def matches(props, ops):
    for field, op, kind, raw in ops:
        want = json.loads(raw)
        have = props.get(field)
        if op == "GreaterThan" and not (have is not None and have > want): return False
        if op == "Equal" and have != want: return False
    return True

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def reply(self, code, obj=None):
        b = b"" if obj is None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(b))); self.end_headers()
        self.wfile.write(b)
    def handle_any(self):
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b""
        path = self.path.split("?")[0]
        CALLS.append({"method": self.command, "path": path})
        if path == "/_calls": return self.reply(200, CALLS)
        if self.headers.get("authorization") != "Bearer " + KEY: return self.reply(401, {"error": [{"message": "unauthorized"}]})
        body = json.loads(raw or b"{}")
        parts = path.strip("/").split("/")
        if path == "/v1/schema" and self.command == "POST":
            cls = body["class"]
            if cls in CLASSES: return self.reply(422, {"error": [{"message": f"class name {cls} already exists"}]})
            CLASSES[cls] = {}
            PROPS[cls] = [p["name"] for p in body.get("properties", [])]
            return self.reply(200, body)
        if len(parts) == 3 and parts[:2] == ["v1", "schema"] and self.command == "GET":
            if parts[2] not in CLASSES: return self.reply(404, {"error": [{"message": "class not found"}]})
            return self.reply(200, {"class": parts[2], "properties": [{"name": n} for n in PROPS.get(parts[2], [])]})
        if len(parts) == 4 and parts[:2] == ["v1", "schema"] and parts[3] == "properties" and self.command == "POST":
            if parts[2] not in CLASSES: return self.reply(404, {"error": [{"message": "class not found"}]})
            PROPS.setdefault(parts[2], []).append(body["name"])
            return self.reply(200, body)
        if path == "/v1/batch/objects" and self.command == "DELETE":
            m = body["match"]
            cls, where = m["class"], m["where"]
            conds = where.get("operands", [where])
            if any(c["path"][0] not in PROPS.get(cls, []) for c in conds):
                return self.reply(422, {"error": [{"message": "no such prop"}]})
            gone = [oid for oid, o in CLASSES.get(cls, {}).items() if all(o["props"].get(c["path"][0]) == c["valueText"] for c in conds)]
            for oid in gone: CLASSES[cls].pop(oid)
            return self.reply(200, {"match": m, "results": {"matches": len(gone), "successful": len(gone), "failed": 0, "limit": 10000}})
        if path == "/v1/objects" and self.command == "POST":
            cls = body["class"]
            if cls not in CLASSES: return self.reply(422, {"error": [{"message": f"class {cls} not found"}]})
            if body["id"] in CLASSES[cls]: return self.reply(422, {"error": [{"message": f"id {body['id']} already exists"}]})
            CLASSES[cls][body["id"]] = {"vector": body["vector"], "props": body["properties"]}
            return self.reply(200, body)
        if len(parts) == 4 and parts[:2] == ["v1", "objects"]:
            cls, oid = parts[2], parts[3]
            if self.command == "PUT":
                CLASSES.setdefault(cls, {})[oid] = {"vector": body["vector"], "props": body["properties"]}
                return self.reply(200, body)
            if self.command == "DELETE":
                if CLASSES.get(cls, {}).pop(oid, None) is None: return self.reply(404, {"error": [{"message": "not found"}]})
                return self.reply(204)
        if path == "/v1/graphql" and self.command == "POST":
            q = body["query"]
            m = re.search(r"Get \{ (\w+)\(nearVector: \{vector: \[([^\]]*)\], distance: ([-0-9.eE]+)\}, where: (\{.*\}), limit: (\d+)\)", q)
            if not m: return self.reply(200, {"errors": [{"message": "unsupported query"}]})
            cls, vec, dist, where, limit = m.group(1), [float(x) for x in m.group(2).split(",") if x], float(m.group(3)), m.group(4), int(m.group(5))
            ops = OP.findall(where)
            hits = []
            for oid, o in CLASSES.get(cls, {}).items():
                if not matches(o["props"], ops): continue
                d = 1.0 - cos(vec, o["vector"])
                if d <= dist: hits.append((d, oid, o))
            hits.sort(key=lambda t: t[0])
            objs = [{"p": o["props"].get("p"), "_additional": {"id": oid, "distance": d}} for d, oid, o in hits[:limit]]
            return self.reply(200, {"data": {"Get": {cls: objs}}})
        return self.reply(404, {"error": [{"message": "no route"}]})
    do_GET = do_PUT = do_POST = do_DELETE = handle_any

ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()

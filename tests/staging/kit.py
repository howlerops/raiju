"""Shared parts of the staging checks (tests/staging/*.py): settings from the environment, HTTP over plain or TLS
connections, raw request heads for the body checks, the cluster signatures, statistics and the PASS/FAIL report.

Everything here is standard-library Python. The pure functions (parsing, statistics, verdicts, the SVG chart) are
unit-tested by tests/test_staging.py; the rest talks to a deployed gateway and is exercised by the runbook
(docs/staging-validation.md).

Settings (each script also takes them as flags; a flag wins):
  RAIJU_BASE_URL         the gateway as clients reach it (https://raiju-staging.example.com, or the ALB name)
  RAIJU_ADMIN_TOKEN      a management credential, sent as Authorization: Bearer (an admin API key or session token)
  RAIJU_ADMIN_USER / RAIJU_ADMIN_PASSWORD   or sign in with these for a session token
  RAIJU_VKS              comma-separated virtual keys; the first is the main one, the others act as other tenants
  RAIJU_MODEL            provider/model the inference checks use (default openai/gpt-4o-mini)
  RAIJU_NODE_URLS        comma-separated main-port URLs of each node (cluster checks; reachable inside the VPC)
  RAIJU_CLUSTER_SECRET   the cluster secret (signs the peer requests the listener check sends)
  RAIJU_CLUSTER_PORT     the cluster listener's port (default 7946)
  RAIJU_CLUSTER_URLS     or each node's cluster listener URL, in RAIJU_NODE_URLS order (when the ports differ)
  RAIJU_METRICS_TOKEN    the bearer token for /metrics (server.metrics_token), when set
  RAIJU_CA_FILE          a CA bundle for a private certificate (the system store otherwise; TLS is always verified)
  RAIJU_RESULTS_DIR      where results.jsonl is appended (default: none)
"""
import hashlib
import hmac
import http.client
import json
import math
import os
import re
import socket
import ssl
import sys
import time
import urllib.parse

DEFAULT_MODEL = "openai/gpt-4o-mini"
# the gateway's answer when the request-body budget is full (server.tov busyResponse)
BUSY_TEXT = "reading too many request bodies at once"


# ---------------------------------------------------------------- settings

def split_list(text):
    """A comma or whitespace separated list, without empty items."""
    return [p for p in re.split(r"[,\s]+", text or "") if p]


def norm_url(url):
    """A base URL without its trailing slash; http:// is added to a bare host[:port]."""
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    return url.rstrip("/")


class Settings:
    def __init__(self, env=None, **over):
        env = os.environ if env is None else env
        self.base_url = norm_url(over.get("base_url") or env.get("RAIJU_BASE_URL") or env.get("BASE_URL") or "")
        self.admin_token = over.get("admin_token") or env.get("RAIJU_ADMIN_TOKEN", "")
        self.admin_user = env.get("RAIJU_ADMIN_USER", "")
        self.admin_password = env.get("RAIJU_ADMIN_PASSWORD", "")
        self.vks = split_list(over.get("vks") or env.get("RAIJU_VKS", ""))
        self.model = over.get("model") or env.get("RAIJU_MODEL") or DEFAULT_MODEL
        self.node_urls = [norm_url(u) for u in split_list(over.get("node_urls") or env.get("RAIJU_NODE_URLS", ""))]
        self.cluster_secret = over.get("cluster_secret") or env.get("RAIJU_CLUSTER_SECRET", "")
        self.cluster_port = int(over.get("cluster_port") or env.get("RAIJU_CLUSTER_PORT") or 7946)
        self.cluster_urls = [norm_url(u) for u in split_list(env.get("RAIJU_CLUSTER_URLS", ""))]
        self.metrics_token = env.get("RAIJU_METRICS_TOKEN", "")
        self.ca_file = env.get("RAIJU_CA_FILE", "")
        self.results_dir = over.get("results_dir") or env.get("RAIJU_RESULTS_DIR", "")

    def secrets(self):
        """Values masked in anything printed."""
        return [s for s in [self.admin_token, self.admin_password, self.cluster_secret, self.metrics_token] + self.vks if s]


def add_common_args(ap):
    ap.add_argument("--base-url", help="the gateway (RAIJU_BASE_URL)")
    ap.add_argument("--admin-token", help="management bearer token (RAIJU_ADMIN_TOKEN)")
    ap.add_argument("--vks", help="comma-separated virtual keys (RAIJU_VKS)")
    ap.add_argument("--model", help="provider/model for inference (RAIJU_MODEL)")
    ap.add_argument("--results-dir", help="append results.jsonl here (RAIJU_RESULTS_DIR)")
    return ap


def settings_from(args):
    over = {k: getattr(args, k, None) for k in ("base_url", "admin_token", "vks", "model", "results_dir", "node_urls", "cluster_secret", "cluster_port")}
    return Settings(**{k: v for k, v in over.items() if v})


# ---------------------------------------------------------------- reporting

def mask(text, secrets):
    text = str(text)
    for s in sorted((s for s in secrets if s and len(s) >= 4), key=len, reverse=True):
        text = text.replace(s, "***")
    return text


def fmt_num(v):
    if isinstance(v, float):
        if v != v:  # NaN
            return "n/a"
        return f"{v:.3f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:.0f}"
    return str(v)


def format_line(status, name, numbers, detail=""):
    """One result line: `PASS name: k=v k=v (detail)`."""
    nums = " ".join(f"{k}={fmt_num(v)}" for k, v in numbers.items())
    tail = f" ({detail})" if detail else ""
    return f"{status} {name}: {nums}{tail}".rstrip()


class Report:
    """Collects results; each prints one line at once. exit_code() is 1 when a check failed."""

    def __init__(self, settings=None, out=None):
        self.secrets = settings.secrets() if settings else []
        self.results_dir = settings.results_dir if settings else ""
        self.out = out or sys.stdout
        self.results = []

    def add(self, name, ok, numbers=None, detail=""):
        status = "PASS" if ok is True else ("SKIP" if ok is None else "FAIL")
        numbers = numbers or {}
        line = mask(format_line(status, name, numbers, detail), self.secrets)
        print(line, file=self.out, flush=True)
        rec = {"check": name, "status": status, "numbers": numbers, "detail": mask(detail, self.secrets), "time": time.time()}
        self.results.append(rec)
        if self.results_dir:
            os.makedirs(self.results_dir, exist_ok=True)
            with open(os.path.join(self.results_dir, "results.jsonl"), "a") as f:
                f.write(json.dumps(rec) + "\n")
        return ok

    def note(self, text):
        print(mask(text, self.secrets), file=self.out, flush=True)

    def failed(self):
        return [r for r in self.results if r["status"] == "FAIL"]

    def exit_code(self):
        return 1 if self.failed() else 0


# ---------------------------------------------------------------- statistics

def percentile(values, p):
    """The p-th percentile (0-100) by linear interpolation; NaN for no values."""
    xs = sorted(values)
    if not xs:
        return float("nan")
    if len(xs) == 1:
        return float(xs[0])
    k = (len(xs) - 1) * p / 100.0
    lo = math.floor(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def slope(points):
    """Least-squares slope of [(x, y)]; 0 with fewer than two distinct x."""
    n = len(points)
    if n < 2:
        return 0.0
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    den = sum((p[0] - mx) ** 2 for p in points)
    if den == 0:
        return 0.0
    return sum((p[0] - mx) * (p[1] - my) for p in points) / den


# ---------------------------------------------------------------- sizes and metrics

UNITS = {"": 1, "b": 1, "k": 1000, "kb": 1024, "ki": 1024, "kib": 1024, "m": 1000 ** 2, "mb": 1024 ** 2, "mi": 1024 ** 2,
         "mib": 1024 ** 2, "g": 1000 ** 3, "gb": 1024 ** 3, "gi": 1024 ** 3, "gib": 1024 ** 3}


def parse_size(text):
    """Bytes from "123456", "512Mi", "64KB", "1.5 GiB", "VmRSS:  204800 kB" (kB as in /proc is 1024). The last size on
    the line counts (`kubectl top pod` prints the name and the CPU first). None when no number."""
    found = [m for m in re.finditer(r"(?<![\w.-])(\d+(?:\.\d+)?)\s*([a-zA-Z]*)(?![\w.])", str(text))]
    if not found:
        return None
    m = found[-1]
    unit = m.group(2).lower()
    if unit not in UNITS:
        return None
    return int(float(m.group(1)) * UNITS[unit])


def parse_duration(text):
    """Seconds from "90", "90s", "30m", "24h", "1h30m"."""
    text = str(text).strip().lower()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    parts = re.findall(r"(\d+(?:\.\d+)?)([smhd])", text)
    if not parts or "".join(n + u for n, u in parts) != text:
        raise ValueError(f"bad duration {text!r}")
    return sum(float(n) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[u] for n, u in parts)


def parse_weights(text):
    """"chat:30,stream:30,body:40" as {name: weight}; a name without a weight counts 1."""
    out = {}
    for part in split_list(text):
        k, _, w = part.partition(":")
        out[k] = float(w) if w else 1.0
    return out


def parse_mix(text):
    """A body-size mix "64K:50,1M:30,8M:15,50M:5" as [(bytes, weight)]; K/M/G are binary here (64K = 65536)."""
    out = []
    for part in split_list(text):
        size, _, w = part.partition(":")
        m = re.fullmatch(r"(\d+(?:\.\d+)?)([KMG]?)", size.strip(), re.I)
        if not m:
            raise ValueError(f"bad size {size!r} in mix {text!r}")
        n = int(float(m.group(1)) * {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}[m.group(2).lower()])
        out.append((n, float(w) if w else 1.0))
    if not out:
        raise ValueError("empty mix")
    return out


def metric_sum(text, name, labels=None):
    """The sum of every sample of metric `name` in Prometheus text (whose labels include `labels`); None if absent."""
    total, seen = 0.0, False
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+(\S+)", line)
        if not m or m.group(1) != name:
            continue
        if labels:
            have = dict(re.findall(r'(\w+)="((?:[^"\\]|\\.)*)"', m.group(2) or ""))
            if any(have.get(k) != v for k, v in labels.items()):
                continue
        try:
            total += float(m.group(3))
            seen = True
        except ValueError:
            pass
    return total if seen else None


# ---------------------------------------------------------------- bodies

def chat_body(size, model=DEFAULT_MODEL, max_tokens=1):
    """A chat request of exactly `size` bytes (a long user message of 'a's)."""
    pre = ('{"model":%s,"max_tokens":%d,"messages":[{"role":"user","content":"' % (json.dumps(model), max_tokens)).encode()
    post = b'"}]}'
    fill = size - len(pre) - len(post)
    if fill < 0:
        raise ValueError(f"size {size} is below the smallest chat body ({len(pre) + len(post)})")
    return pre + b"a" * fill + post


def is_busy(status, body):
    """The body budget's refusal (503 with its message), not an upstream's 503."""
    if status != 503:
        return False
    text = body.decode("utf8", "replace") if isinstance(body, (bytes, bytearray)) else str(body)
    return BUSY_TEXT in text


def status_of(head):
    """The status code of a raw HTTP response head (bytes), or 0."""
    m = re.match(rb"HTTP/\d(?:\.\d)?\s+(\d{3})", head or b"")
    return int(m.group(1)) if m else 0


# ---------------------------------------------------------------- cluster signatures

def hmac_hex(secret, text):
    return hmac.new(secret.encode(), text.encode(), hashlib.sha256).hexdigest()


def leader_headers(secret, ts_ms=None):
    """The headers of a signed GET /api/cluster/leader (cluster.tov signRequest: "GET <path> <ts>")."""
    t = str(int(time.time() * 1000) if ts_ms is None else ts_ms)
    return {"x-raiju-cluster-ts": t, "x-raiju-cluster-sig": hmac_hex(secret, "GET /api/cluster/leader " + t)}


def peer_post_headers(secret, route, body, ts_ms=None):
    """The headers of a signed peer POST (cluster.tov peerHeaders): the body's HMAC, the time and the head signature."""
    t = str(int(time.time() * 1000) if ts_ms is None else ts_ms)
    n = len(body.encode() if isinstance(body, str) else body)
    raw = body if isinstance(body, str) else body.decode("utf8", "replace")
    return {"x-raiju-cluster-sig": hmac_hex(secret, raw), "x-raiju-cluster-ts": t,
            "x-raiju-cluster-head": hmac_hex(secret, "POST %s %s %d" % (route, t, n))}


def cluster_url(settings, node_url):
    """A node's cluster listener: its RAIJU_CLUSTER_URLS entry, else its main URL with RAIJU_CLUSTER_PORT."""
    if node_url in settings.node_urls and len(settings.cluster_urls) == len(settings.node_urls):
        return settings.cluster_urls[settings.node_urls.index(node_url)]
    return with_port(node_url, settings.cluster_port)


def with_port(url, port):
    """url with its port replaced (the cluster listener of a node given by its main-port URL)."""
    u = urllib.parse.urlsplit(norm_url(url))
    host = u.hostname or ""
    if ":" in host:
        host = "[" + host + "]"
    return urllib.parse.urlunsplit((u.scheme, f"{host}:{port}", u.path, "", "")).rstrip("/")


# ---------------------------------------------------------------- HTTP

_CTX = {}


def ssl_context(ca_file=""):
    if ca_file not in _CTX:
        ctx = ssl.create_default_context(cafile=ca_file or None)
        _CTX[ca_file] = ctx
    return _CTX[ca_file]


def _conn(url, timeout, ca_file=""):
    u = urllib.parse.urlsplit(url)
    port = u.port or (443 if u.scheme == "https" else 80)
    if u.scheme == "https":
        return http.client.HTTPSConnection(u.hostname, port, timeout=timeout, context=ssl_context(ca_file)), u
    return http.client.HTTPConnection(u.hostname, port, timeout=timeout), u


def request(method, url, body=None, headers=None, timeout=60, ca_file=""):
    """One request; (status, lower-cased headers, body bytes). Status 0 and the error text in the body when the
    connection failed or timed out."""
    data = body
    if body is not None and not isinstance(body, (bytes, bytearray, str)):
        data = json.dumps(body)
    if isinstance(data, str):
        data = data.encode()
    h = {"content-type": "application/json"} if data is not None else {}
    h.update(headers or {})
    try:
        c, u = _conn(url, timeout, ca_file)
        path = (u.path or "/") + ("?" + u.query if u.query else "")
        try:
            c.request(method, path, body=data, headers=h)
            r = c.getresponse()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
        finally:
            c.close()
    except Exception as e:
        return 0, {}, f"{type(e).__name__}: {e}".encode()


def jload(b):
    try:
        return json.loads(b)
    except (ValueError, TypeError):
        return None


class Gateway:
    """A gateway at base_url with the kit's credentials."""

    def __init__(self, base_url, settings):
        self.base = norm_url(base_url)
        self.s = settings
        self._token = settings.admin_token

    def admin_headers(self):
        if not self._token and self.s.admin_user and self.s.admin_password:
            st, _, b = request("POST", self.base + "/api/session/login", {"username": self.s.admin_user, "password": self.s.admin_password}, ca_file=self.s.ca_file)
            if st == 200:
                self._token = (jload(b) or {}).get("token", "")
        return {"authorization": "Bearer " + self._token} if self._token else {}

    def api(self, method, path, body=None, timeout=60):
        return request(method, self.base + path, body, self.admin_headers(), timeout, self.s.ca_file)

    def infer(self, path, body, vk=None, headers=None, timeout=120):
        h = {"x-bf-vk": vk if vk is not None else (self.s.vks[0] if self.s.vks else "")}
        h.update(headers or {})
        return request("POST", self.base + path, body, h, timeout, self.s.ca_file)

    def get(self, path, headers=None, timeout=30):
        return request("GET", self.base + path, None, headers, timeout, self.s.ca_file)


def open_socket(url, timeout=30, ca_file=""):
    """A connected socket (TLS for https) to url's host, and the Host header value."""
    u = urllib.parse.urlsplit(norm_url(url))
    port = u.port or (443 if u.scheme == "https" else 80)
    s = socket.create_connection((u.hostname, port), timeout=timeout)
    if u.scheme == "https":
        s = ssl_context(ca_file).wrap_socket(s, server_hostname=u.hostname)
    host = u.hostname if u.port is None else f"{u.hostname}:{u.port}"
    return s, host


def raw_head(method, path, host, headers):
    """A request head as bytes (headers in order, no body)."""
    lines = [f"{method} {path} HTTP/1.1", f"Host: {host}"] + [f"{k}: {v}" for k, v in headers.items()]
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


# ---------------------------------------------------------------- names

def run_id():
    return time.strftime("%m%d%H%M%S") + "-" + os.urandom(2).hex()


def names_found(listing, names):
    """Which of names appear as "name" in a /api/governance/virtual-keys answer (dict or list)."""
    rows = listing.get("virtual_keys", []) if isinstance(listing, dict) else (listing or [])
    have = {r.get("name") for r in rows if isinstance(r, dict)}
    return [n for n in names if n in have]


def vk_rows(listing, prefix):
    rows = listing.get("virtual_keys", []) if isinstance(listing, dict) else (listing or [])
    return [r for r in rows if isinstance(r, dict) and str(r.get("name", "")).startswith(prefix)]


def cleanup_vks(gw, prefix):
    """Deletes the virtual keys whose names start with prefix (the run's own); the number deleted."""
    st, _, b = gw.api("GET", "/api/governance/virtual-keys")
    if st != 200:
        return 0
    n = 0
    for r in vk_rows(jload(b) or {}, prefix):
        rid = r.get("id")
        if rid:
            ds, _, _ = gw.api("DELETE", "/api/governance/virtual-keys/" + urllib.parse.quote(str(rid), safe=""))
            n += ds in (200, 204)
    return n

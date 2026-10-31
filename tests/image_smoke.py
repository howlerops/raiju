#!/usr/bin/env python3
"""Boot smoke of the Docker image, run the way the Helm chart runs it: a read-only root filesystem with /tmp as
a tmpfs and /app/data as a writable volume, the image's non-root user (65532), every capability dropped and no
privilege escalation, the chart's arguments and a setup token from BIFROST_SETUP_TOKEN. It checks that /health
and /ready answer, that `raiju -healthcheck` passes inside the container, that the management API is locked to
the setup token, that a chat completion reaches a mock upstream (a small HTTP server here, reached from the
container through host.docker.internal) and comes back, that the process runs as 65532 and cannot write the
root filesystem while /app/data and /tmp take writes, and that SIGTERM stops it cleanly (exit 0).

Usage: tests/image_smoke.py [IMAGE]           (default raiju:ci; CI runs it after building the image)
       tests/image_smoke.py --binary build/raiju
The second form runs the same HTTP checks against a local binary (ports 18386 and 18387) without Docker, to try
the script and its config where Docker is missing; the container-only checks are skipped. Exits 1 when a check
fails and prints the gateway's log.
"""
import argparse, http.server, json, os, shutil, signal, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request, uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UID = "65532"
# the local form's ports (the e2e range of this check)
LOCAL_GW_PORT, LOCAL_MOCK_PORT = 18386, 18387
MOCK_ANSWER = "pong from the image smoke mock"
# not a real credential: the mock only checks that the gateway forwards it
UPSTREAM_KEY = "smoke-" + "upstream-key"


def smoke_config(mock_base_url):
    """The gateway's config.json: one OpenAI provider at the mock, logging on (so /ready covers the log store)."""
    return {
        "client": {"enable_logging": True, "drop_excess_requests": False, "allowed_origins": []},
        "providers": {
            "openai": {
                "keys": [{"name": "smoke", "value": UPSTREAM_KEY, "models": [], "weight": 1.0}],
                "network_config": {"base_url": mock_base_url, "max_retries": 0},
            }
        },
    }


def chart_args(port, workers):
    """The container arguments of deploy/helm/raiju/templates/deployment.yaml."""
    return ["-app-dir", "/app/data", "-host", "0.0.0.0", "-port", str(port), "-workers", str(workers)]


def docker_run_args(name, image, data_dir, setup_token, workers):
    """`docker run` with the chart's pod and container security context and volumes."""
    return [
        "docker", "run", "-d", "--name", name,
        "--read-only",                                   # securityContext.readOnlyRootFilesystem
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m",      # the tmp emptyDir
        "-v", f"{data_dir}:/app/data",                   # the data volume
        "--user", f"{UID}:{UID}",                        # runAsUser, runAsGroup
        "--cap-drop", "ALL",                             # capabilities.drop
        "--security-opt", "no-new-privileges",           # allowPrivilegeEscalation: false
        "--add-host", "host.docker.internal:host-gateway",
        "-e", f"BIFROST_SETUP_TOKEN={setup_token}",
        "-p", "127.0.0.1::8080",
        image, *chart_args(8080, workers),
    ]


class Mock:
    """An OpenAI-shaped upstream: POST .../chat/completions answers MOCK_ANSWER and records what came in."""

    def __init__(self, host, port):
        self.seen = []
        mock = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                mock.seen.append({"path": self.path, "auth": self.headers.get("Authorization", ""), "body": body.decode("utf-8", "replace")})
                if not self.path.endswith("/chat/completions"):
                    self.send_response(404)
                    self.end_headers()
                    return
                req = json.loads(body or b"{}")
                out = json.dumps({
                    "id": "chatcmpl-smoke", "object": "chat.completion", "created": int(time.time()), "model": req.get("model", ""),
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": MOCK_ANSWER}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8},
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.server = http.server.ThreadingHTTPServer((host, port), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def call(method, url, body=None, headers=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, str(e)


class Smoke:
    def __init__(self):
        self.failed = []

    def check(self, name, ok, detail=""):
        print(f"{'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f": {detail}"), flush=True)
        if not ok:
            self.failed.append(name)
        return ok

    def wait_for(self, name, url, timeout):
        """Polls url until it answers 200; returns whether it did."""
        deadline = time.time() + timeout
        last = (0, "")
        while time.time() < deadline:
            last = call("GET", url, timeout=3)
            if last[0] == 200:
                break
            time.sleep(0.5)
        return self.check(name, last[0] == 200, last)

    def http_checks(self, base, mock, setup_token):
        """What a client and an operator see: health, readiness, the setup lock, a chat through the mock."""
        if not self.wait_for("/health answers 200", base + "/health", 60):
            return False
        self.wait_for("/ready answers 200", base + "/ready", 30)
        s, b = call("GET", base + "/api/session/is-auth-enabled")
        info = json.loads(b) if s == 200 else {}
        self.check("the setup token from BIFROST_SETUP_TOKEN is seen", info.get("setup_token_configured") is True and info.get("setup_required") is True, (s, b[:200]))
        s, b = call("GET", base + "/api/providers")
        self.check("/api is locked without the setup token", s in (401, 403), (s, b[:200]))
        s, b = call("GET", base + "/api/providers", headers={"X-Bifrost-Setup-Token": setup_token})
        self.check("/api opens to the setup token", s == 200 and "openai" in b, (s, b[:200]))
        before = len(mock.seen)
        s, b = call("POST", base + "/v1/chat/completions", {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "ping"}]}, timeout=30)
        try:
            content = json.loads(b)["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            content = ""
        self.check("a chat completion comes back from the mock upstream", s == 200 and content == MOCK_ANSWER, (s, b[:300]))
        calls = mock.seen[before:]
        self.check("the upstream got the request with the provider key", len(calls) == 1 and calls[0]["auth"] == f"Bearer {UPSTREAM_KEY}" and '"gpt-4o-mini"' in calls[0]["body"],
                   [(c["path"], c["auth"][:20]) for c in calls])
        return True


def docker(*args, check=False, timeout=60):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, check=check)


def run_image(image, workers):
    smoke = Smoke()
    setup_token = "smoke-setup-" + uuid.uuid4().hex[:16]
    name = "raiju-smoke-" + uuid.uuid4().hex[:8]
    data = tempfile.mkdtemp(prefix="raiju-smoke-")
    # the mock listens on every address of the runner so the container reaches it through the bridge's gateway
    mock = Mock("0.0.0.0", 0)
    started = False
    try:
        with open(os.path.join(data, "config.json"), "w") as f:
            json.dump(smoke_config(f"http://host.docker.internal:{mock.port}"), f, indent=2)
        # the chart's fsGroup makes the volume the image user's; here the folder is given to it
        r = subprocess.run(["sudo", "-n", "chown", "-R", f"{UID}:{UID}", data], capture_output=True, text=True)
        if r.returncode != 0:
            os.chmod(data, 0o777)
            os.chmod(os.path.join(data, "config.json"), 0o666)
        r = subprocess.run(docker_run_args(name, image, data, setup_token, workers), capture_output=True, text=True, timeout=120)
        if not smoke.check("the container starts", r.returncode == 0, r.stderr.strip()):
            return 1
        started = True
        port = docker("port", name, "8080/tcp").stdout.strip().splitlines()[0].rsplit(":", 1)[1]
        base = f"http://127.0.0.1:{port}"

        inspect = json.loads(docker("inspect", name).stdout)[0]
        smoke.check("the root filesystem is read-only", inspect["HostConfig"]["ReadonlyRootfs"] is True, inspect["HostConfig"].get("ReadonlyRootfs"))
        image_user = json.loads(docker("image", "inspect", image).stdout)[0]["Config"].get("User", "")
        smoke.check("the image's USER is the numeric non-root user", image_user == f"{UID}:{UID}", image_user)

        if smoke.http_checks(base, mock, setup_token):
            r = docker("exec", name, "/usr/local/bin/raiju", "-healthcheck")
            smoke.check("raiju -healthcheck passes inside the container", r.returncode == 0, (r.returncode, r.stdout + r.stderr))
            r = docker("exec", name, "cat", "/proc/1/status")
            uids = [l.split()[1:] for l in r.stdout.splitlines() if l.startswith(("Uid:", "Gid:"))]
            smoke.check("the gateway runs as 65532, not root", len(uids) == 2 and all(v == UID for ids in uids for v in ids), uids)
            r = docker("exec", name, "/bin/sh", "-c", "echo x > /usr/local/bin/smoke-probe")
            smoke.check("the root filesystem cannot be written", r.returncode != 0, r.returncode)
            r = docker("exec", name, "/bin/sh", "-c", "echo x > /app/data/.smoke-probe && rm /app/data/.smoke-probe && echo x > /tmp/.smoke-probe && rm /tmp/.smoke-probe")
            smoke.check("/app/data and /tmp take writes", r.returncode == 0, r.stderr.strip())
            r = docker("exec", name, "ls", "/app/data")
            smoke.check("the gateway keeps its state in /app/data", "config.json" in r.stdout.split(), r.stdout.split())
            # the image's HEALTHCHECK as Docker runs it (first probe after 30 s)
            health, deadline = "", time.time() + 75
            while time.time() < deadline and health != "healthy":
                health = docker("inspect", "-f", "{{.State.Health.Status}}", name).stdout.strip()
                if health == "unhealthy":
                    break
                time.sleep(2)
            smoke.check("Docker reports the container healthy", health == "healthy", health)

        r = docker("stop", "-t", "40", name, timeout=90)
        code = docker("inspect", "-f", "{{.State.ExitCode}}", name).stdout.strip()
        smoke.check("SIGTERM stops the gateway cleanly (exit 0)", r.returncode == 0 and code == "0", (r.returncode, code))
    finally:
        if started and smoke.failed:
            print("---- container log ----")
            logs = docker("logs", name)
            print((logs.stdout + logs.stderr)[-20000:])
        if started:
            docker("rm", "-f", name)
        mock.close()
        subprocess.run(["sudo", "-n", "rm", "-rf", data], capture_output=True)
        shutil.rmtree(data, ignore_errors=True)
    return report(smoke)


def run_binary(binary, workers):
    smoke = Smoke()
    setup_token = "smoke-setup-" + uuid.uuid4().hex[:16]
    data = tempfile.mkdtemp(prefix="raiju-smoke-")
    mock = Mock("127.0.0.1", LOCAL_MOCK_PORT)
    log = open(os.path.join(data, "gateway.log"), "w+")
    env = {k: v for k, v in os.environ.items() if k not in ("BIFROST_HOST", "RAIJU_CONFIG", "APP_DIR", "PORT")}
    env["BIFROST_SETUP_TOKEN"] = setup_token
    proc = None
    try:
        with open(os.path.join(data, "config.json"), "w") as f:
            json.dump(smoke_config(f"http://127.0.0.1:{mock.port}"), f, indent=2)
        args = chart_args(LOCAL_GW_PORT, workers)
        args[args.index("/app/data")] = data
        args[args.index("0.0.0.0")] = "127.0.0.1"
        proc = subprocess.Popen([binary, *args], stdout=log, stderr=subprocess.STDOUT, env=env)
        base = f"http://127.0.0.1:{LOCAL_GW_PORT}"
        if smoke.http_checks(base, mock, setup_token):
            r = subprocess.run([binary, "-healthcheck", "-port", str(LOCAL_GW_PORT)], capture_output=True, text=True, timeout=30, env=env)
            smoke.check("raiju -healthcheck passes", r.returncode == 0, (r.returncode, r.stdout + r.stderr))
            smoke.check("the gateway keeps its state in the app dir", os.path.exists(os.path.join(data, "config.json")))
        proc.send_signal(signal.SIGTERM)
        try:
            code = proc.wait(timeout=40)
        except subprocess.TimeoutExpired:
            code = None
        smoke.check("SIGTERM stops the gateway cleanly (exit 0)", code == 0, code)
    finally:
        if proc and proc.poll() is None:
            proc.kill()
            proc.wait()
        if smoke.failed:
            log.seek(0)
            print("---- gateway log ----")
            print(log.read()[-20000:])
        log.close()
        mock.close()
        shutil.rmtree(data, ignore_errors=True)
    return report(smoke)


def report(smoke):
    if smoke.failed:
        print(f"image smoke: {len(smoke.failed)} failed: {', '.join(smoke.failed)}")
        return 1
    print("image smoke: all passed")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("image", nargs="?", default="raiju:ci")
    p.add_argument("--binary", help="run against this local binary instead of the image (no Docker)")
    # two workers, so the workers' share folder in /tmp is made on the tmpfs
    p.add_argument("--workers", type=int, default=2)
    a = p.parse_args()
    if a.binary:
        return run_binary(a.binary, a.workers)
    if shutil.which("docker") is None:
        print("image smoke: docker is not installed")
        return 1
    return run_image(a.image, a.workers)


if __name__ == "__main__":
    sys.exit(main())

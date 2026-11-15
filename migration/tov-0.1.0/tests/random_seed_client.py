"""Drives random_seed.tov (patch 0021): python3 random_seed_client.py BINARY. Prints "ok" and "FAIL" lines."""
import os
import socket
import subprocess
import sys
import time

BIN = sys.argv[1]


def once(env):
    out = subprocess.run([BIN], env={**os.environ, "ONCE": "1", **env}, capture_output=True, text=True, timeout=10).stdout
    return out.strip()


def first_draws(env):
    """Starts the 4-worker server and returns each worker's first draw, by pid."""
    e = {k: v for k, v in os.environ.items() if k not in ("ONCE", "TOV_SEED")}
    p = subprocess.Popen([BIN], env={**e, **env}, stdout=subprocess.PIPE, text=True)
    try:
        port = int(p.stdout.readline().split()[1])
        firsts = {}
        deadline = time.time() + 10
        while len(firsts) < 4 and time.time() < deadline:
            # a new connection each time, so the kernel spreads them over the workers
            s = socket.create_connection(("127.0.0.1", port), timeout=5)
            s.sendall(b"GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
            data = b""
            while True:
                c = s.recv(4096)
                if not c:
                    break
                data += c
            s.close()
            pid, draw = data.split(b"\r\n\r\n", 1)[1].split()
            firsts.setdefault(pid, draw)
        return firsts
    finally:
        p.terminate()
        p.wait(timeout=10)


a, b = once({}), once({})
print("ok two processes draw different numbers" if a != b and a.startswith("draw") else f"FAIL same draw without TOV_SEED: {a} {b}")
s1, s2 = once({"TOV_SEED": "42"}), once({"TOV_SEED": "42"})
print("ok TOV_SEED=<n> fixes the seed" if s1 == s2 and s1.startswith("draw") else f"FAIL TOV_SEED=42 gave {s1} and {s2}")
print("ok another TOV_SEED draws otherwise" if once({"TOV_SEED": "43"}) != s1 else "FAIL TOV_SEED=43 drew as 42")
f = first_draws({})
print("ok each worker draws its own numbers" if len(f) == 4 and len(set(f.values())) == 4 else f"FAIL workers' first draws: {f}")
g = first_draws({"TOV_SEED": "42"})
print("ok with TOV_SEED each worker still draws its own numbers" if len(g) == 4 and len(set(g.values())) == 4 else f"FAIL workers' first draws under TOV_SEED: {g}")

"""Drives worker_respawn (patch 0019). Usage: worker_respawn_client.py BINARY OUTDIR [BINARY_WITHOUT_PLAIN_ALLOC]
(Linux: reads /proc). BINARY is built with TV_PLAIN_ALLOC. Prints an "ok" or "FAIL" line per check."""
import os, signal, subprocess, sys, time, urllib.request

BIN, OUT = sys.argv[1], sys.argv[2]


def children(pid):
    # the program forks from a thread other than the main one, so read every thread's children
    kids = []
    try:
        for t in os.listdir(f"/proc/{pid}/task"):
            kids += [int(x) for x in open(f"/proc/{pid}/task/{t}/children").read().split()]
    except OSError:
        pass
    return sorted(kids)


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def get(port):
    try:
        return urllib.request.urlopen(f"http://127.0.0.1:{port}/pid", timeout=3).status
    except Exception:
        return 0


def wait_new(pid, old, timeout):
    """Seconds until the supervisor has two workers again with one not in `old`, or None."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        kids = children(pid)
        if len(kids) == 2 and any(k not in old for k in kids):
            return time.time() - t0
        time.sleep(0.05)
    return None


def check(ok, name, detail=""):
    print(f"ok {name}" if ok else f"FAIL {name} {detail}")


out_path = os.path.join(OUT, "worker_respawn.out")
err_path = os.path.join(OUT, "worker_respawn.err")
p = subprocess.Popen([BIN], stdout=open(out_path, "w"), stderr=open(err_path, "w"))
port = 0
for _ in range(100):
    time.sleep(0.05)
    text = open(out_path).read()
    if "listening " in text:
        port = int(text.split("listening ")[1].split()[0])
        break
if not port:
    p.kill()
    raise SystemExit("FAIL the server did not start")
check("plain true" in open(out_path).read(), "Bun.plainAlloc() is true with TV_PLAIN_ALLOC")
if len(sys.argv) > 3:
    r = subprocess.run([sys.argv[3]], env={**os.environ, "PLAIN_ONLY": "1"}, capture_output=True, text=True, timeout=10)
    check("plain false" in r.stdout, "Bun.plainAlloc() is false without it", r.stdout)
try:
    for _ in range(40):
        if len(children(p.pid)) == 2:
            break
        time.sleep(0.05)
    first = children(p.pid)
    check(len(first) == 2, "two workers start", first)
    victim, other = first[0], first[1]
    os.kill(victim, signal.SIGKILL)
    # it died within a second of starting: replaced after a 1 s pause
    took = wait_new(p.pid, first, 5)
    check(took is not None and alive(p.pid), "a worker killed by SIGKILL is replaced and the supervisor keeps running", took)
    check(alive(other) and other in children(p.pid), "the other worker keeps running")
    check(all(get(port) == 200 for _ in range(6)), "requests are served after the respawn")
    # killed again soon after it started: the pause doubles to 2 s
    second = children(p.pid)
    fresh = [k for k in second if k not in first][0]
    os.kill(fresh, signal.SIGKILL)
    took = wait_new(p.pid, second, 6)
    check(took is not None and took >= 1.5, "a worker that keeps dying soon after it starts is replaced after a longer pause", took)
    check(all(get(port) == 200 for _ in range(6)), "the remaining worker serves while one waits out its pause")
    err = open(err_path).read()
    check("killed by signal 9; restarting it in 1 s" in err and "restarting it in 2 s" in err, "each respawn is logged with its pause", err[-400:])
    # a stop signal while a slot waits out its 4 s pause stops the supervisor promptly
    third = children(p.pid)
    fresh = [k for k in third if k not in second][0]
    os.kill(fresh, signal.SIGKILL)
    time.sleep(0.3)
    t0 = time.time()
    p.send_signal(signal.SIGTERM)
    try:
        p.wait(3)
        stopped = time.time() - t0
    except subprocess.TimeoutExpired:
        stopped = None
    check(stopped is not None and stopped < 2.5 and not any(alive(k) for k in third), "SIGTERM during a pause stops the supervisor and its workers", stopped)
except Exception as e:
    print(f"FAIL the checks stopped early: {e!r}")
finally:
    if p.poll() is None:
        p.kill()
        p.wait()

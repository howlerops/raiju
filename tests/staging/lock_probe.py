#!/usr/bin/env python3
"""File-lock probes for a shared volume (EFS or NFS), run on a host or task that mounts the gateway's data
directory. They take the same lock the gateway takes (flock(2) on config.json.flock; Python's fcntl.flock is the
same call, which the Linux NFS client turns into a lock the server holds) and make the upgrade bridge's directory.

  lock_probe.py hold LOCKFILE [--seconds N]    take the lock and keep it (print the pid; kill -9 it to test release)
  lock_probe.py wait LOCKFILE [--timeout S]    wait for the lock and print how long it took (run beside a holder)
  lock_probe.py skew DIR [--samples 5]         this host's clock minus the file server's (via a new file's mtime)
  lock_probe.py legacy CONFIG [--age S] [--base-url URL]
        make CONFIG.lock as the wave 25 release would (an empty directory, mtime moved back by --age, or forward
        with a negative age to play a writer whose clock runs ahead), then time a config change through the
        gateway: it waits until the directory is 10 s old by the gateway's clock (LEGACY_STALE_MS) or answers 503
        after the 15 s lock wait. Prints the expected and the measured time.

Each prints PASS/FAIL lines like the other staging checks where there is a verdict (wait, legacy).
"""
import argparse
import fcntl
import os
import statistics
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kit  # noqa: E402

STALE_S = 10.0  # filelock.tov LEGACY_STALE_MS
WAIT_S = 15.0  # filelock.tov LOCK_WAIT_MS


def legacy_expectation(age_s, gateway_skew_s=0.0, stale_s=STALE_S, wait_s=WAIT_S):
    """What a config change does while an empty legacy lock directory exists whose mtime is age_s old by the file
    server's clock, on a gateway whose clock is gateway_skew_s ahead of that server: ("ok", seconds until the
    directory counts as stale) or ("503", wait_s) when that is past the lock wait."""
    due = max(0.0, stale_s - age_s - gateway_skew_s)
    return ("ok", due) if due < wait_s else ("503", wait_s)


def legacy_verdict(expect, status, took, tolerance):
    kind, due = expect
    if kind == "503":
        return status == 503 and abs(took - due) <= tolerance
    return status in (200, 201) and took >= due - tolerance and took <= due + tolerance + 2.0


def cmd_hold(a):
    fd = os.open(a.lockfile, os.O_RDWR | os.O_CREAT, 0o600)
    t0 = time.time()
    fcntl.flock(fd, fcntl.LOCK_EX)
    print(f"holding {a.lockfile} (waited {time.time() - t0:.2f} s); pid {os.getpid()}; kill -9 {os.getpid()} to test the release", flush=True)
    end = time.time() + a.seconds if a.seconds else None
    while end is None or time.time() < end:
        time.sleep(1)
    return 0


def cmd_wait(a):
    rep = kit.Report()
    fd = os.open(a.lockfile, os.O_RDWR | os.O_CREAT, 0o600)
    t0 = time.time()
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.time() - t0 > a.timeout:
                rep.add("lock.wait", False, {"waited_s": round(time.time() - t0, 2)}, "still held at the timeout")
                return 1
            time.sleep(0.05)
    took = time.time() - t0
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
    rep.add("lock.wait", a.max_wait is None or took <= a.max_wait, {"waited_s": round(took, 2), "max_wait_s": a.max_wait if a.max_wait is not None else "n/a"})
    return rep.exit_code()


def skew_once(d):
    fd, p = tempfile.mkstemp(prefix=".raiju-skew-", dir=d)
    try:
        before = time.time()
        os.write(fd, b"x")
        os.fsync(fd)
        os.close(fd)
        after = time.time()
        return (before + after) / 2 - os.stat(p).st_mtime
    finally:
        os.unlink(p)


def cmd_skew(a):
    vals = [skew_once(a.dir) for _ in range(a.samples)]
    med = statistics.median(vals)
    print(f"clock skew (this host minus the file server): median {med:+.3f} s over {a.samples} samples, range {min(vals):+.3f} .. {max(vals):+.3f} s", flush=True)
    return 0


def cmd_legacy(a):
    s = kit.Settings(base_url=a.base_url) if a.base_url else kit.Settings()
    rep = kit.Report(s)
    d = a.config + ".lock"
    os.mkdir(d)
    now = time.time()
    os.utime(d, (now - a.age, now - a.age))
    expect = legacy_expectation(a.age, a.gateway_skew)
    if not s.base_url:
        rep.note(f"made {d} (mtime {a.age:+.1f} s); expected: {expect[0]} after {expect[1]:.1f} s. Remove it with rmdir when done.")
        return 0
    try:
        gw = kit.Gateway(s.base_url, s)
        name = "stg-" + kit.run_id() + "-legacy"
        t0 = time.time()
        st, _, _ = gw.api("POST", "/api/governance/virtual-keys", {"name": name}, timeout=40)
        took = time.time() - t0
        ok = legacy_verdict(expect, st, took, a.tolerance)
        rep.add("lock.legacy_bridge", ok, {"age_s": a.age, "expected": expect[0], "expected_s": round(expect[1], 1), "status": st, "took_s": round(took, 2)})
        kit.cleanup_vks(gw, name)
    finally:
        try:
            os.rmdir(d)
        except OSError:
            pass  # taken over and removed by the gateway, or not empty
    return rep.exit_code()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hold")
    h.add_argument("lockfile")
    h.add_argument("--seconds", type=float, default=0)
    w = sub.add_parser("wait")
    w.add_argument("lockfile")
    w.add_argument("--timeout", type=float, default=300)
    w.add_argument("--max-wait", type=float, default=None, help="FAIL when the wait took longer")
    k = sub.add_parser("skew")
    k.add_argument("dir")
    k.add_argument("--samples", type=int, default=5)
    g = sub.add_parser("legacy")
    g.add_argument("config", help="the gateway's config.json on the shared volume")
    g.add_argument("--age", type=float, default=0.0)
    g.add_argument("--gateway-skew", type=float, default=0.0, help="the gateway host's clock minus the file server's (lock_probe.py skew there)")
    g.add_argument("--tolerance", type=float, default=1.5)
    g.add_argument("--base-url", default="")
    a = ap.parse_args(argv)
    return {"hold": cmd_hold, "wait": cmd_wait, "skew": cmd_skew, "legacy": cmd_legacy}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())

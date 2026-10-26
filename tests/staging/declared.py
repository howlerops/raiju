#!/usr/bin/env python3
"""Declared lengths (re-audit 6 P1-A, re-audit 5 P1-B): attacker requests declare --declared-mb in Content-Length and
then send nothing (or --rate-kbps), reconnecting as soon as they are answered; meanwhile an outsider tenant posts
1 MB and 4 MB bodies in a loop. The outsider must not be refused by the body budget (503 "reading too many request
bodies") more than --max-outsider-busy times, and every attacker request must be answered within --max-hold.

Usage: tests/staging/declared.py [--seconds 60] [--declared-mb 12] [--rate-kbps 0] [--max-outsider-busy 0]
RAIJU_VKS: every key but the last is an attacker (use 2 to 4 keys, of one tenant or of several), the last one is the
outsider (another tenant). Bodies go to --body-model (staging-discard/none: read whole, answered 400, no provider).
"""
import argparse
import collections
import os
import select
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kit  # noqa: E402


def attacker(url, vk, declared, rate_bps, stop, ends, held, lock, ca_file):
    while time.time() < stop:
        try:
            s, host = kit.open_socket(url, timeout=30, ca_file=ca_file)
            s.sendall(kit.raw_head("POST", "/v1/chat/completions", host, {"content-type": "application/json", "content-length": str(declared), "x-bf-vk": vk}))
            t0, sent, code, step = time.time(), 0, None, 0.25
            while time.time() < stop:
                pending = getattr(s, "pending", lambda: 0)()
                if pending or select.select([s], [], [], step if rate_bps == 0 else 0)[0]:
                    try:
                        d = s.recv(4096)
                    except OSError:
                        d = b""
                    code = kit.status_of(d) if d else 0
                    break
                if rate_bps > 0:
                    n = min(int(rate_bps * step), declared - sent - 1)
                    if n > 0:
                        s.sendall(b"a" * n)
                        sent += n
                    time.sleep(step)
            with lock:
                ends[code] += 1
                if code not in (None, 503):
                    held.append(time.time() - t0)
            s.close()
            if code == 503:
                time.sleep(0.05)
        except OSError as e:
            with lock:
                ends[type(e).__name__] += 1
            time.sleep(0.05)


def outsider(gw, vk, model, stop, res):
    bodies = {"1MB": kit.chat_body(1 << 20, model), "4MB": kit.chat_body(4 << 20, model)}
    while time.time() < stop:
        for name, body in bodies.items():
            st, _, b = gw.infer("/v1/chat/completions", body, vk=vk, timeout=60)
            res[name][("busy" if kit.is_busy(st, b) else str(st))] += 1
        time.sleep(0.2)


def verdict(res, held, max_busy, max_hold):
    busy = sum(c.get("busy", 0) for c in res.values())
    total = sum(sum(c.values()) for c in res.values())
    longest = max(held) if held else 0.0
    ok = total > 0 and busy <= max_busy and longest <= max_hold
    return ok, {"outsider_requests": total, "outsider_busy_503": busy, "attacker_longest_hold_s": round(longest, 1), "max_hold_s": max_hold}


def main(argv=None):
    ap = kit.add_common_args(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--declared-mb", type=float, default=12.0)
    ap.add_argument("--rate-kbps", type=float, default=0.0)
    ap.add_argument("--max-outsider-busy", type=int, default=0)
    ap.add_argument("--max-hold", type=float, default=630.0, help="an admitted attacker request must be answered within this (the 600 s body ceiling)")
    ap.add_argument("--body-model", default="staging-discard/none")
    a = ap.parse_args(argv)
    s = kit.settings_from(a)
    rep = kit.Report(s)
    if not s.base_url or len(s.vks) < 2:
        rep.add("declared", False, {}, "needs RAIJU_BASE_URL and at least two virtual keys in RAIJU_VKS (attackers, then the outsider)")
        return rep.exit_code()
    gw = kit.Gateway(s.base_url, s)
    stop = time.time() + a.seconds
    ends, held, lock = collections.Counter(), [], threading.Lock()
    ts = [threading.Thread(target=attacker, args=(s.base_url, vk, int(a.declared_mb * 1048576), a.rate_kbps * 1024, stop, ends, held, lock, s.ca_file), daemon=True)
          for vk in s.vks[:-1]]
    for t in ts:
        t.start()
        time.sleep(0.2)
    time.sleep(1.0)
    res = {"1MB": collections.Counter(), "4MB": collections.Counter()}
    outsider(gw, s.vks[-1], a.body_model, stop, res)
    for t in ts:
        t.join(15)
    ok, nums = verdict(res, held, a.max_outsider_busy, a.max_hold)
    nums.update({"attackers": len(ts), "declared_mb": a.declared_mb, "rate_kbps": a.rate_kbps})
    detail = "outsider " + "; ".join(f"{k}: {dict(v)}" for k, v in res.items()) + f"; attacker answers {dict((str(k), v) for k, v in ends.items())}"
    rep.add("declared", ok, nums, detail)
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())

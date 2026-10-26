#!/usr/bin/env python3
"""Trickled bodies (re-audit 4 P1-E, re-audit 3 P1-D): one tenant declares a big body, sends --fast-mb at once and
then one byte every 2 s; the gateway must cut it (408 or a close) within --max-hold seconds (body_rate_grace_seconds
10 + body_rate_window_seconds 30 by default), and meanwhile another tenant's 200 KB chats must not be refused by the
body budget. A second check trickles without any credential to /mcp, which must be answered within --max-hold too.

Usage: tests/staging/trickle.py [--fast-mb 8] [--declared-mb 40] [--max-hold 60] [--outsider-kb 200]
Needs two virtual keys of different tenants in RAIJU_VKS (keys with different customers or teams, or keys with
neither): the first trickles, the second is the outsider. The outsider's chats go to --body-model
(staging-discard/none by default: read whole, answered 400, no provider called).
"""
import argparse
import os
import socket
import ssl
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kit  # noqa: E402


def trickle(url, path, declared, fast, max_secs, headers, ca_file=""):
    """Sends a head declaring `declared` bytes, `fast` bytes at once, then a byte every 2 s until the gateway answers
    or closes. (seconds until then, status (0: closed without an answer, -1: still open at max_secs), bytes sent)."""
    s, host = kit.open_socket(url, timeout=30, ca_file=ca_file)
    h = {"content-type": "application/json", "content-length": str(declared)}
    h.update(headers)
    s.sendall(kit.raw_head("POST", path, host, h))
    t0 = time.time()
    sent = 0
    chunk = b"a" * 65536
    try:
        while sent < fast:
            n = min(len(chunk), fast - sent)
            s.sendall(chunk[:n])
            sent += n
        s.settimeout(0.05)
        while time.time() - t0 < max_secs:
            try:
                d = s.recv(4096)
                return time.time() - t0, kit.status_of(d) if d else 0, sent
            except (socket.timeout, ssl.SSLWantReadError):
                pass
            s.sendall(b"a")
            sent += 1
            end = time.time() + 2.0
            while time.time() < end:
                try:
                    d = s.recv(4096)
                    return time.time() - t0, kit.status_of(d) if d else 0, sent
                except (socket.timeout, ssl.SSLWantReadError):
                    pass
        return time.time() - t0, -1, sent
    except OSError:
        return time.time() - t0, 0, sent
    finally:
        s.close()


def outsider_loop(gw, vk, model, size, stop, out):
    body = kit.chat_body(size, model)
    while time.time() < stop:
        st, _, b = gw.infer("/v1/chat/completions", body, vk=vk, timeout=60)
        out.append((st, kit.is_busy(st, b)))
        time.sleep(1.0)


def verdict(cut_s, status, max_hold, outsider):
    """The trickler must be answered or closed within max_hold; no outsider chat may be refused by the budget."""
    busy = sum(1 for _, b in outsider if b)
    # 408 (or a close) is the rate rule cutting it; a 503 means it was refused at admission and nothing was tested
    ok = status in (408, 0) and cut_s <= max_hold and busy == 0 and len(outsider) > 0
    return ok, {"cut_after_s": round(cut_s, 1), "status": status, "max_hold_s": max_hold, "outsider_requests": len(outsider), "outsider_busy_503": busy}


def main(argv=None):
    ap = kit.add_common_args(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    ap.add_argument("--fast-mb", type=float, default=8.0)
    ap.add_argument("--declared-mb", type=float, default=40.0, help="under server.max_buffered_body_mb (48), or it is refused 503 unread")
    ap.add_argument("--max-hold", type=float, default=60.0)
    ap.add_argument("--outsider-kb", type=int, default=200)
    ap.add_argument("--body-model", default="staging-discard/none")
    ap.add_argument("--skip-unchecked", action="store_true", help="skip the /mcp trickle without a credential")
    a = ap.parse_args(argv)
    s = kit.settings_from(a)
    rep = kit.Report(s)
    if not s.base_url or len(s.vks) < 2:
        rep.add("trickle", False, {}, "needs RAIJU_BASE_URL and two virtual keys of different tenants in RAIJU_VKS")
        return rep.exit_code()
    gw = kit.Gateway(s.base_url, s)
    stop = time.time() + a.max_hold + 15
    outsider = []
    t = threading.Thread(target=outsider_loop, args=(gw, s.vks[1], a.body_model, a.outsider_kb * 1024, stop, outsider), daemon=True)
    t.start()
    cut, status, sent = trickle(s.base_url, "/v1/chat/completions", int(a.declared_mb * 1048576), int(a.fast_mb * 1048576),
                                a.max_hold + 10, {"x-bf-vk": s.vks[0]}, s.ca_file)
    t.join(a.max_hold + 30)
    ok, nums = verdict(cut, status, a.max_hold, outsider)
    nums["sent_mb"] = round(sent / 1048576, 2)
    rep.add("trickle.checked", ok, nums, "outsider statuses " + ",".join(sorted({str(st) for st, _ in outsider})))
    if not a.skip_unchecked:
        cut, status, sent = trickle(s.base_url, "/mcp", 48 * 1048576, 1048576, a.max_hold + 10, {}, s.ca_file)
        ok = None if status == 404 else (status != -1 and cut <= a.max_hold)
        rep.add("trickle.unchecked_mcp", ok, {"answered_after_s": round(cut, 1), "status": status, "max_hold_s": a.max_hold},
                "the MCP server is off (no /mcp)" if status == 404 else "")
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())

"""Linux native worker replay: real GC, adopted listeners, private state, respawn and stop."""
import collections
import concurrent.futures
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def wait_for(predicate, description, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.05)
    raise AssertionError(description)


def children(pid):
    found = set()
    for task in Path(f"/proc/{pid}/task").glob("*/children"):
        try:
            found.update(map(int, task.read_text().split()))
        except FileNotFoundError:
            pass
    return found


def main():
    binary, probe, output = sys.argv[1:]
    path = Path(output)
    env = {**os.environ, "LD_PRELOAD": probe, "TOV_SEED": "42"}
    process = None
    known = set()
    with path.open("w") as log:
        try:
            process = subprocess.Popen([binary], stdout=log, stderr=log, env=env)

            def records():
                return path.read_text().splitlines()

            ports = wait_for(
                lambda: next((list(map(int, row.split()[1:])) for row in records()
                              if row.startswith("listening ")), None),
                "supervisor did not publish its two listener ports")
            assert len(ports) == 2 and ports[0] != ports[1] and all(ports), ports
            known = wait_for(lambda: children(process.pid) if len(children(process.pid)) == 2 else None,
                             "supervisor did not start exactly two workers")

            def collected(pids):
                counts = collections.Counter(int(row.split()[1]) for row in records()
                                             if row.startswith("collected "))
                return all(counts[pid] >= 2 for pid in pids)

            # Require a worker-local creation GC and a completed idle GC before HTTP traffic.
            # A forked VM cannot satisfy the independent per-worker VM/collector lifecycle.
            wait_for(lambda: collected(known), "workers did not complete real post-start idle GC")
            draws = {}

            def request(port):
                with HTTP.open(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                    assert response.status == 200
                    pid, supervisor, identity, draw = map(int, response.read().split())
                    assert supervisor == identity == process.pid, (pid, supervisor, identity)
                    assert draws.setdefault(pid, draw) == draw
                    return pid

            for port in ports:
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                    responses = set(pool.map(request, [port] * 24))
                assert responses == known, (port, responses, known)
            assert len(set(draws.values())) == 2, "fixed seed was not derived independently per worker"
            print("ok clean workers complete real GC and serve both inherited port-0 listeners")

            for pid in known:
                bootstrap_files = 0
                for fd in Path(f"/proc/{pid}/fd").iterdir():
                    try:
                        target = os.readlink(fd)
                        if "tov-worker-" not in target and not target.startswith("socket:"):
                            continue
                        flags = next(row.split()[1] for row in
                                     Path(f"/proc/{pid}/fdinfo/{fd.name}").read_text().splitlines()
                                     if row.startswith("flags:"))
                        assert int(flags, 8) & os.O_CLOEXEC, (pid, fd.name, target)
                        bootstrap_files += "tov-worker-" in target
                    except FileNotFoundError:
                        pass
                assert bootstrap_files == 1, "bootstrap manifest must be closed; only load mapping remains"
            print("ok imported listeners and private state descriptors are close-on-exec")

            victim = min(known)
            os.kill(victim, signal.SIGKILL)
            survivors = known - {victim}
            replacement = wait_for(lambda: next(iter(children(process.pid) - known), None),
                                   "killed worker was not replaced")
            known = survivors | {replacement}
            wait_for(lambda: collected({replacement}), "replacement worker did not complete real idle GC")
            for port in ports:
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                    responses = set(pool.map(request, [port] * 24))
                assert responses == known, (responses, known)
            print("ok replacement worker replays fresh VM and retains supervisor identity and listeners")
            assert draws[replacement] == draws[victim], "fixed seed did not reproduce the replaced worker slot"
            print("ok fixed seed derives independent reproducible per-slot streams")

            process.send_signal(signal.SIGTERM)
            assert process.wait(timeout=8) == 0, path.read_text()
            assert not any(Path(f"/proc/{pid}").exists() for pid in known), "worker survived supervisor stop"
            print("ok supervisor SIGTERM gracefully stops clean workers")
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for pid in known:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"FAIL clean workers: {error}")
        raise

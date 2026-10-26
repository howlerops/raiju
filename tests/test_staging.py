"""The staging validation kit (tests/staging, docs/staging-validation.md): its pure parts (parsing, statistics, the
cluster signatures, the verdicts, the chart, the check plan), the workflow that runs it (workflow_dispatch only,
secrets from the "staging" environment) and the throwaway terraform stack (deploy/terraform/examples/staging; its
terraform test runs when TERRAFORM names a terraform binary, 1.7 or later).

Nothing here reaches a network: the checks themselves need a deployed gateway.

Usage: python3 -m unittest tests/test_staging.py
"""
import hashlib
import hmac
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests", "staging"))

import body_soak  # noqa: E402
import cluster_check  # noqa: E402
import creates  # noqa: E402
import dcr_flood  # noqa: E402
import declared  # noqa: E402
import kit  # noqa: E402
import lock_probe  # noqa: E402
import run as runner  # noqa: E402
import smoke_check  # noqa: E402
import trickle  # noqa: E402

SECRET = "s" * 40  # a placeholder cluster secret (32 bytes or more, as the gateway wants)


class SettingsTest(unittest.TestCase):
    def test_lists_and_urls(self):
        self.assertEqual(kit.split_list(" a, b ,,c d"), ["a", "b", "c", "d"])
        self.assertEqual(kit.split_list(""), [])
        self.assertEqual(kit.norm_url("gw.example.com:8080/"), "http://gw.example.com:8080")
        self.assertEqual(kit.norm_url("https://gw.example.com/"), "https://gw.example.com")
        self.assertEqual(kit.norm_url(" "), "")

    def test_from_environment_and_flags(self):
        env = {"RAIJU_BASE_URL": "https://gw.example.com/", "RAIJU_VKS": "sk-bf-a,sk-bf-b", "RAIJU_NODE_URLS": "10.0.1.5:8080 10.0.2.6:8080",
               "RAIJU_CLUSTER_URLS": "10.0.1.5:7000,10.0.2.6:7001", "RAIJU_ADMIN_TOKEN": "tok-example"}
        s = kit.Settings(env)
        self.assertEqual(s.base_url, "https://gw.example.com")
        self.assertEqual(s.vks, ["sk-bf-a", "sk-bf-b"])
        self.assertEqual(s.model, kit.DEFAULT_MODEL)
        self.assertEqual(s.node_urls, ["http://10.0.1.5:8080", "http://10.0.2.6:8080"])
        self.assertEqual(s.cluster_port, 7946)
        self.assertEqual(kit.cluster_url(s, "http://10.0.2.6:8080"), "http://10.0.2.6:7001")
        self.assertIn("tok-example", s.secrets())
        s2 = kit.Settings(env, base_url="http://other:1", model="openai/x")
        self.assertEqual((s2.base_url, s2.model), ("http://other:1", "openai/x"))
        s3 = kit.Settings({"RAIJU_NODE_URLS": "10.0.1.5:8080"})
        self.assertEqual(kit.cluster_url(s3, "http://10.0.1.5:8080"), "http://10.0.1.5:7946")

    def test_with_port(self):
        self.assertEqual(kit.with_port("http://10.0.1.5:8080", 7946), "http://10.0.1.5:7946")
        self.assertEqual(kit.with_port("https://gw.example.com", 7946), "https://gw.example.com:7946")
        self.assertEqual(kit.with_port("http://[fd00::5]:8080", 7946), "http://[fd00::5]:7946")


class ParsingTest(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(kit.parse_size("VmRSS:\t  204800 kB"), 204800 * 1024)
        self.assertEqual(kit.parse_size("512Mi"), 512 * 1048576)
        self.assertEqual(kit.parse_size("1.5 GiB"), int(1.5 * 1024 ** 3))
        self.assertEqual(kit.parse_size("209715200"), 209715200)
        self.assertEqual(kit.parse_size("12 parsecs"), None)
        self.assertEqual(kit.parse_size("none"), None)

    def test_durations(self):
        self.assertEqual(kit.parse_duration("90"), 90)
        self.assertEqual(kit.parse_duration("30m"), 1800)
        self.assertEqual(kit.parse_duration("24h"), 86400)
        self.assertEqual(kit.parse_duration("1h30m"), 5400)
        with self.assertRaises(ValueError):
            kit.parse_duration("soon")
        with self.assertRaises(ValueError):
            kit.parse_duration("5mx")

    def test_mix_and_weights(self):
        self.assertEqual(kit.parse_mix("64K:40,1M:30,50M"), [(65536, 40.0), (1048576, 30.0), (50 * 1048576, 1.0)])
        with self.assertRaises(ValueError):
            kit.parse_mix("64Q:1")
        with self.assertRaises(ValueError):
            kit.parse_mix("")
        self.assertEqual(kit.parse_weights("chat:30,stream,body:2.5"), {"chat": 30.0, "stream": 1.0, "body": 2.5})
        for name, mix in body_soak.MIXES.items():
            self.assertTrue(kit.parse_mix(mix), name)

    def test_metrics(self):
        text = "\n".join([
            "# HELP bifrost_upstream_requests_total x",
            'bifrost_upstream_requests_total{provider="openai",model="a"} 3',
            'bifrost_upstream_requests_total{provider="anthropic",model="b"} 4',
            "process_resident_memory_bytes 1.048576e+08",
            "bifrost_upstream_requests_total_other 9",
        ])
        self.assertEqual(kit.metric_sum(text, "bifrost_upstream_requests_total"), 7)
        self.assertEqual(kit.metric_sum(text, "bifrost_upstream_requests_total", {"provider": "openai"}), 3)
        self.assertEqual(kit.metric_sum(text, "process_resident_memory_bytes"), 104857600)
        self.assertIsNone(kit.metric_sum(text, "missing"))

    def test_chat_body_has_the_exact_size(self):
        for n in (200, 65536, 1048576):
            b = kit.chat_body(n, "openai/gpt-4o-mini")
            self.assertEqual(len(b), n)
            d = json.loads(b)
            self.assertEqual(d["model"], "openai/gpt-4o-mini")
        with self.assertRaises(ValueError):
            kit.chat_body(10)

    def test_busy_and_status(self):
        busy = b'{"error":{"message":"the gateway is reading too many request bodies at once (server.max_buffered_body_mb); retry shortly"}}'
        self.assertTrue(kit.is_busy(503, busy))
        self.assertFalse(kit.is_busy(503, b'{"error":{"message":"upstream unavailable"}}'))
        self.assertFalse(kit.is_busy(400, busy))
        self.assertEqual(kit.status_of(b"HTTP/1.1 408 Request Timeout\r\n"), 408)
        self.assertEqual(kit.status_of(b""), 0)
        self.assertEqual(kit.status_of(b"garbage"), 0)

    def test_rss_output(self):
        self.assertAlmostEqual(body_soak.parse_rss_output("VmRSS: 102400 kB\nVmRSS: 204800 kB\n"), 200.0)
        self.assertAlmostEqual(body_soak.parse_rss_output("raiju-1  3m  180Mi\n"), 180.0)
        self.assertIsNone(body_soak.parse_rss_output("no data"))


class SignatureTest(unittest.TestCase):
    """The headers must match what the gateway checks (src/cluster.tov requestText, headText, sign)."""

    def test_leader(self):
        h = kit.leader_headers(SECRET, 1800000000000)
        self.assertEqual(h["x-raiju-cluster-ts"], "1800000000000")
        want = hmac.new(SECRET.encode(), b"GET /api/cluster/leader 1800000000000", hashlib.sha256).hexdigest()
        self.assertEqual(h["x-raiju-cluster-sig"], want)

    def test_peer_post(self):
        body = '{"x":"é"}'
        h = kit.peer_post_headers(SECRET, "/api/cluster/logs", body, 1800000000000)
        self.assertEqual(h["x-raiju-cluster-sig"], hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest())
        n = len(body.encode())
        self.assertEqual(n, 10)
        self.assertEqual(h["x-raiju-cluster-head"], hmac.new(SECRET.encode(), f"POST /api/cluster/logs 1800000000000 {n}".encode(), hashlib.sha256).hexdigest())


class StatsAndReportTest(unittest.TestCase):
    def test_percentile_and_slope(self):
        self.assertEqual(kit.percentile([5, 1, 3], 50), 3)
        self.assertEqual(kit.percentile([1, 2, 3, 4], 100), 4)
        self.assertAlmostEqual(kit.percentile([0, 10], 25), 2.5)
        self.assertNotEqual(kit.percentile([], 50), kit.percentile([], 50))  # NaN
        self.assertAlmostEqual(kit.slope([(0, 1), (1, 3), (2, 5)]), 2.0)
        self.assertEqual(kit.slope([(1, 1)]), 0.0)
        self.assertEqual(kit.slope([(1, 1), (1, 5)]), 0.0)

    def test_report(self):
        with tempfile.TemporaryDirectory() as d:
            s = kit.Settings({"RAIJU_ADMIN_TOKEN": "tok-example-123", "RAIJU_RESULTS_DIR": d})
            out = io.StringIO()
            rep = kit.Report(s, out)
            rep.add("a.check", True, {"n": 3, "ms": 1.25})
            rep.add("b.check", None, {}, "nothing to check")
            self.assertEqual(rep.exit_code(), 0)
            rep.add("c.check", False, {"lost": 2}, "token tok-example-123 leaked")
            self.assertEqual(rep.exit_code(), 1)
            lines = out.getvalue().splitlines()
            self.assertEqual(lines[0], "PASS a.check: n=3 ms=1.25")
            self.assertTrue(lines[1].startswith("SKIP b.check"))
            self.assertEqual(lines[2], "FAIL c.check: lost=2 (token *** leaked)")
            with open(os.path.join(d, "results.jsonl")) as f:
                text = f.read()
            rows = [json.loads(l) for l in text.splitlines()]
            self.assertEqual([r["status"] for r in rows], ["PASS", "SKIP", "FAIL"])
            self.assertNotIn("tok-example-123", text)

    def test_names(self):
        listing = {"virtual_keys": [{"id": "1", "name": "stg-x-1"}, {"id": "2", "name": "other"}, {"id": "3", "name": "stg-x-2", "description": "updated stg-x-2"}]}
        self.assertEqual(kit.names_found(listing, ["stg-x-1", "stg-x-9"]), ["stg-x-1"])
        self.assertEqual([r["id"] for r in kit.vk_rows(listing, "stg-x-")], ["1", "3"])
        self.assertEqual(kit.names_found([{"name": "a"}], ["a"]), ["a"])


class VerdictTest(unittest.TestCase):
    def test_creates(self):
        ok, n = creates.verdict(["a", "b"], {"u1": ["a", "b"], "u2": ["a", "b"]}, ["1"], {"u1": ["1"], "u2": ["1"]}, 0, 0)
        self.assertTrue(ok)
        self.assertEqual((n["lost"], n["lost_updates"]), (0, 0))
        ok, n = creates.verdict(["a", "b"], {"u1": ["a", "b"], "u2": ["a"]}, ["1"], {"u1": ["1"], "u2": []}, 0, 0)
        self.assertFalse(ok)
        self.assertEqual((n["lost"], n["lost_updates"]), (1, 1))
        self.assertFalse(creates.verdict(["a"], {"u": ["a"]}, [], {"u": []}, 2, 1)[0])  # too many refused
        self.assertTrue(creates.verdict(["a"], {"u": ["a"]}, [], {"u": []}, 1, 1)[0])
        self.assertFalse(creates.verdict([], {"u": []}, [], {"u": []}, 0, 0)[0])  # nothing acknowledged

    def test_creates_reads_a_config_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.json")
            with open(p, "w") as f:
                json.dump({"governance": {"virtual_keys": [{"id": "1", "name": "stg-r-1", "description": "updated stg-r-1"}, {"id": "2", "name": "stg-r-2"}]}}, f)
            self.assertEqual(creates.names_in_file(p, ["stg-r-1", "stg-r-2", "stg-r-3"], "stg-r-"), (["stg-r-1", "stg-r-2"], ["1"]))

    def test_soak(self):
        flat = [(t * 60.0, 60 + (t % 3)) for t in range(100)]
        ok, n, why = body_soak.soak_verdict(flat, 512, 32)
        self.assertTrue(ok, why)
        self.assertLess(abs(n["growth_2nd_half_mb"]), 2)
        leak = [(t * 60.0, 60 + t * 1.5) for t in range(100)]
        ok, n, why = body_soak.soak_verdict(leak, 512, 32)
        self.assertFalse(ok)
        self.assertGreater(n["growth_2nd_half_mb"], 32)
        high = [(t * 60.0, 480.0) for t in range(10)]
        self.assertFalse(body_soak.soak_verdict(high, 512, 32)[0])  # flat but past 90% of the limit
        oom = [(t * 60.0, 300.0 if t != 50 else 25.0) for t in range(100)]
        ok, n, why = body_soak.soak_verdict(oom, 512, 32)
        self.assertFalse(ok)
        self.assertEqual(n["restarts"], 1)
        self.assertFalse(body_soak.soak_verdict([(0, 50), (60, None), (120, 50)], 512, 32)[0])  # too few samples
        self.assertFalse(body_soak.soak_verdict(flat, 512, 32, requests=100, errors=5)[0])  # 5% errors

    def test_restarts(self):
        self.assertEqual(body_soak.restarts([50, 60, 70, 20, 30, 80, 25]), [3, 6])
        self.assertEqual(body_soak.restarts([50, None, 45, 48]), [])
        self.assertEqual(body_soak.restarts([10, 4]), [])  # a small fall is noise

    def test_chart_is_svg(self):
        svg = body_soak.svg_chart([(0, 50.0), (3600, 60.0), (7200, None), (10800, 55.0)], 512, "RSS <test> & co")
        root = ET.fromstring(svg)
        self.assertTrue(root.tag.endswith("svg"))
        self.assertIn("limit 512", svg)
        self.assertIn("3.0 h", svg)
        ET.fromstring(body_soak.svg_chart([], 512))

    def test_trickle(self):
        ok, n = trickle.verdict(40.2, 408, 60, [(400, False), (400, False)])
        self.assertTrue(ok)
        self.assertFalse(trickle.verdict(40.2, -1, 60, [(400, False)])[0])  # never cut
        self.assertFalse(trickle.verdict(75, 408, 60, [(400, False)])[0])  # cut too late
        self.assertFalse(trickle.verdict(40, 408, 60, [(503, True)])[0])  # the outsider was refused
        self.assertFalse(trickle.verdict(40, 408, 60, [])[0])
        self.assertFalse(trickle.verdict(0.0, 503, 60, [(400, False)])[0])  # refused at admission: nothing tested

    def test_declared(self):
        from collections import Counter
        res = {"1MB": Counter({"400": 10}), "4MB": Counter({"400": 9, "busy": 1})}
        self.assertFalse(declared.verdict(res, [10.0], 0, 630)[0])
        self.assertTrue(declared.verdict(res, [10.0], 1, 630)[0])
        self.assertFalse(declared.verdict({"1MB": Counter({"400": 3})}, [700.0], 0, 630)[0])

    def test_dcr(self):
        from collections import Counter
        ok, n = dcr_flood.verdict(Counter({201: 9, 429: 5000}), Counter({201: 4}), [3.0, 4.0, 10.0], 500, 302)
        self.assertTrue(ok)
        self.assertFalse(dcr_flood.verdict(Counter({201: 900}), Counter({201: 450}), [3.0], 500, 302)[0])  # no limit
        self.assertFalse(dcr_flood.verdict(Counter({201: 9, 429: 50}), Counter(), [3.0, None], 500, 302)[0])  # health failed
        self.assertFalse(dcr_flood.verdict(Counter({201: 9, 429: 50}), Counter(), [900.0], 500, 302)[0])  # health slow
        self.assertFalse(dcr_flood.verdict(Counter({201: 9, 429: 50}), Counter(), [3.0], 500, 400)[0])  # authorize lost
        self.assertFalse(dcr_flood.verdict(Counter({201: 60, 429: 50}), Counter({201: 30}), [3.0], 500, 302)[0])  # forged XFF believed

    def test_leaders(self):
        a, b = "http://a", "http://b"
        rounds = [{a: {"node": "a", "leader": True}, b: {"node": "b", "leader": False}},
                  {a: None, b: {"node": "b", "leader": True}},
                  {a: {"node": "a", "leader": True}, b: {"node": "b", "leader": True}},
                  {a: {"node": "a", "leader": True}, b: {"node": "b", "leader": False}}]
        s = cluster_check.leaders_summary(rounds)
        self.assertEqual(s, {"rounds": 4, "rounds_not_one_leader": 1, "rounds_node_unreachable": 1, "converged": True})
        self.assertFalse(cluster_check.leaders_summary(rounds[:2])["converged"])
        self.assertFalse(cluster_check.leaders_summary([])["converged"])

    def test_legacy_lock(self):
        self.assertEqual(lock_probe.legacy_expectation(0), ("ok", 10.0))
        self.assertEqual(lock_probe.legacy_expectation(6), ("ok", 4.0))
        self.assertEqual(lock_probe.legacy_expectation(30), ("ok", 0.0))
        self.assertEqual(lock_probe.legacy_expectation(-8), ("503", 15.0))  # a writer whose clock runs ahead
        self.assertEqual(lock_probe.legacy_expectation(0, gateway_skew_s=4), ("ok", 6.0))
        self.assertTrue(lock_probe.legacy_verdict(("ok", 10.0), 201, 10.05, 1.5))
        self.assertFalse(lock_probe.legacy_verdict(("ok", 10.0), 201, 0.1, 1.5))  # taken over too early
        self.assertFalse(lock_probe.legacy_verdict(("ok", 10.0), 503, 15.0, 1.5))
        self.assertTrue(lock_probe.legacy_verdict(("503", 15.0), 503, 15.02, 1.5))

    def test_smoke_helpers(self):
        import datetime
        now = datetime.datetime(2026, 10, 26, tzinfo=datetime.timezone.utc)
        self.assertAlmostEqual(smoke_check.cert_days_left("Nov  5 00:00:00 2026 GMT", now), 10.0)
        evs = smoke_check.sse_events('data: {"a":1}\n\ndata: [DONE]\n\n')
        self.assertEqual(evs, [{"a": 1}])


class PlanTest(unittest.TestCase):
    def test_plan(self):
        steps = runner.plan("all,soak,smoke", {}, "out", "2h")
        self.assertEqual([c for c, _ in steps], ["smoke", "creates", "trickle", "declared", "dcr", "soak"])
        self.assertEqual(dict(steps)["soak"], ["body_soak.py", "--duration", "2h", "--out", os.path.join("out", "soak")])
        b = dict(runner.plan("bridge", {"RAIJU_OLD_URL": "http://o", "RAIJU_NEW_URL": "http://n"}, "o", "1m"))["bridge"]
        self.assertEqual(b, ["bridge.py", "--old-url", "http://o", "--new-url", "http://n"])
        with self.assertRaises(ValueError):
            runner.plan("smoke,rm", {}, "o", "1m")
        for _, argv in runner.plan(",".join(runner.KNOWN), {}, "o", "1m"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, "tests", "staging", argv[0])), argv[0])

    def test_summary(self):
        md = runner.summary_md([{"check": "smoke.health", "status": "PASS", "numbers": {"status": 200}}], {"smoke": 0})
        self.assertIn("| smoke.health | PASS | status=200 |", md)
        self.assertIn("| smoke | 0 |", md)

    def test_nothing_runs_without_a_base_url(self):
        env = {k: v for k, v in os.environ.items() if k not in ("RAIJU_BASE_URL", "BASE_URL")}
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "staging", "run.py"), "--checks", "all", "--out", os.path.join(d, "r")],
                               env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(p.returncode, 1)
            self.assertIn("nothing was run", p.stdout)
            self.assertFalse(os.path.exists(os.path.join(d, "r")))

    def test_scripts_answer_help(self):
        for f in sorted(os.listdir(os.path.join(ROOT, "tests", "staging"))):
            if f.endswith(".py") and f != "kit.py":
                p = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "staging", f), "--help"], capture_output=True, text=True, timeout=60)
                self.assertEqual(p.returncode, 0, f + ": " + p.stderr)


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, ".github", "workflows", "staging.yml")) as f:
            self.text = f.read()
        self.wf = yaml.safe_load(self.text)

    def test_manual_only(self):
        on = self.wf.get("on", self.wf.get(True))  # YAML 1.1 reads a bare `on` key as True
        self.assertEqual(list(on), ["workflow_dispatch"])
        inputs = on["workflow_dispatch"]["inputs"]
        self.assertTrue(inputs["base_url"]["required"])
        self.assertTrue(inputs["checks"]["required"])
        self.assertNotIn("schedule", on)

    def test_environment_and_guard(self):
        job = self.wf["jobs"]["staging"]
        self.assertEqual(job["environment"], "staging")
        self.assertIn("inputs.base_url != ''", job["if"])
        self.assertEqual(self.wf["permissions"], {"contents": "read"})
        for name in ("RAIJU_ADMIN_TOKEN", "RAIJU_VKS", "RAIJU_CLUSTER_SECRET"):
            self.assertEqual(job["env"][name], "${{ secrets.%s }}" % name)
        run_steps = [s.get("run", "") for s in job["steps"]]
        self.assertTrue(any("tests/staging/run.py" in r for r in run_steps))
        # inputs reach the shell through the environment, never spliced into a script
        for r in run_steps:
            self.assertNotIn("${{", r)
        self.assertTrue(any(s.get("uses", "").startswith("actions/upload-artifact") for s in job["steps"]))


class TerraformStagingTest(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(ROOT, "deploy", "terraform", "examples", "staging")
        with open(os.path.join(self.dir, "main.tf")) as f:
            self.main = f.read()
        with open(os.path.join(self.dir, "variables.tf")) as f:
            self.vars = f.read()

    def test_throwaway(self):
        self.assertIn('source = "../../modules/aws-ecs"', self.main)
        self.assertRegex(self.main, r"expires_at\s*=\s*timeadd\(time_static\.created\.rfc3339")
        self.assertEqual(len(re.findall(r"recovery_window_in_days = 0", self.main)), 2)
        self.assertIn("terraform destroy", self.main)
        self.assertRegex(self.vars, r'variable "ttl_hours" \{[^}]*default\s*=\s*48')

    def test_cluster_option_and_memory(self):
        self.assertIn("task_count = var.cluster ? 3 : 1", self.main)
        self.assertIn("cluster_enabled    = var.cluster", self.main)
        self.assertRegex(self.vars, r'variable "memory" \{[^}]*default\s*=\s*512\b')
        self.assertIn("efs_enabled         = true", self.main)

    def test_no_secret_values_in_the_config(self):
        self.assertIn('setup_token = "env.BIFROST_SETUP_TOKEN"', self.main)
        self.assertIn('secret      = "env.RAIJU_CLUSTER_SECRET"', self.main)

    @unittest.skipUnless(os.environ.get("TERRAFORM"), "set TERRAFORM to a terraform binary to run the example's terraform test")
    def test_terraform_test(self):
        tf = os.environ["TERRAFORM"]
        with tempfile.TemporaryDirectory() as data:
            env = {**os.environ, "TF_DATA_DIR": data}
            try:
                init = subprocess.run([tf, "init", "-backend=false", "-input=false", "-no-color"], cwd=self.dir, env=env, capture_output=True, text=True)
                self.assertEqual(init.returncode, 0, init.stdout + init.stderr)
                for args in (["validate", "-no-color"], ["test", "-no-color"]):
                    r = subprocess.run([tf] + args, cwd=self.dir, env=env, capture_output=True, text=True)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            finally:
                lock = os.path.join(self.dir, ".terraform.lock.hcl")
                if os.path.exists(lock):
                    os.remove(lock)


if __name__ == "__main__":
    unittest.main()

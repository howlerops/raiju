"""The shipped deployments: the Dockerfile, docker-compose.yml and the Helm chart (rendered with `helm template`).

They must persist what Raiju writes (config.json on every API change, the MCP OAuth state, logs/ and logs/audit/,
the workers' share folder in /tmp), probe liveness on /health and readiness on /ready, drain within the kill
timeout, and give the process the memory measured under load. The Helm checks need helm (HELM, or helm on PATH)
and are skipped without it, unless REQUIRE_HELM is set (CI). DEPLOY_ROOT points the checks at another checkout
(default: this one).

Usage: python3 -m unittest tests/test_deploy.py
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = os.environ.get("DEPLOY_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHART = os.path.join(ROOT, "deploy", "helm", "raiju")
HELM = os.environ.get("HELM") or shutil.which("helm")


def mebibytes(q):
    """A Kubernetes memory quantity in MiB."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(Ki|Mi|Gi|K|M|G)?", str(q))
    n, unit = float(m.group(1)), m.group(2) or ""
    return n * {"": 1 / 1048576, "Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "K": 1000 / 1048576, "M": 1e6 / 1048576, "G": 1e9 / 1048576}[unit]


class DockerfileTest(unittest.TestCase):
    def setUp(self):
        self.text = open(os.path.join(ROOT, "Dockerfile")).read()

    def test_healthcheck_runs_the_binary(self):
        m = re.search(r"^HEALTHCHECK\b(.*?)CMD\s+(\[.*?\])", self.text, re.M | re.S)
        self.assertIsNotNone(m, "the image has no HEALTHCHECK")
        self.assertEqual(json.loads(m.group(2))[:2], ["/usr/local/bin/raiju", "-healthcheck"])

    def test_bases_are_pinned_by_digest(self):
        args = dict(re.findall(r"^ARG (\w+)=(\S+)", self.text, re.M))
        froms = re.findall(r"^FROM\s+(\S+)", self.text, re.M)
        self.assertTrue(froms)
        for f in froms:
            image = re.sub(r"\$\{(\w+)\}", lambda m: args.get(m.group(1), ""), f)
            self.assertRegex(image, r":[\w.-]+@sha256:[0-9a-f]{64}$", f"FROM {f} is not pinned by tag and digest")

    def test_no_piped_installer(self):
        code = "\n".join(l for l in self.text.split("\n") if not l.lstrip().startswith("#"))
        self.assertIsNone(re.search(r"curl[^\n]*\|\s*sh", code), "an installer is piped into a shell")
        self.assertIn("sha256sum -c", code, "the downloaded rustup-init is not checked")

    def test_cmd_binds_every_address(self):
        m = re.search(r"^CMD\s+(\[.*\])", self.text, re.M)
        cmd = json.loads(m.group(1))
        self.assertEqual(cmd[cmd.index("-host") + 1], "0.0.0.0")
        self.assertEqual(len(re.findall(r"^WORKDIR /app/data$", self.text, re.M)), 1)

    def test_app_data_is_the_working_directory(self):
        self.assertIsNotNone(re.search(r"^WORKDIR /app/data$", self.text, re.M), "the runtime's WORKDIR is not /app/data")


class ComposeTest(unittest.TestCase):
    def setUp(self):
        self.doc = yaml.safe_load(open(os.path.join(ROOT, "docker-compose.yml")))
        self.raiju = self.doc["services"]["raiju"]

    def test_app_data_is_a_named_volume(self):
        mounts = [v for v in self.raiju.get("volumes", []) if str(v).split(":")[1:2] == ["/app/data"]]
        self.assertEqual(len(mounts), 1, self.raiju.get("volumes"))
        source = mounts[0].split(":")[0]
        self.assertIn(source, self.doc.get("volumes") or {}, "/app/data is not a named volume")
        self.assertFalse(mounts[0].endswith(":ro"))

    def test_binds_every_address(self):
        cmd = self.raiju["command"]
        self.assertEqual(cmd[cmd.index("-host") + 1], "0.0.0.0")

    def test_nothing_read_only_inside_app_data(self):
        for v in self.raiju.get("volumes", []):
            parts = str(v).split(":")
            self.assertFalse(len(parts) > 2 and parts[1].startswith("/app/data/") and parts[2] == "ro", f"{v} makes a file in /app/data read-only")

    def test_the_config_is_seeded_once(self):
        seed = self.doc["services"]["raiju-config"]
        self.assertEqual(self.raiju["depends_on"]["raiju-config"]["condition"], "service_completed_successfully")
        script = seed["command"][0]
        with tempfile.TemporaryDirectory() as d:
            data, src = os.path.join(d, "data"), os.path.join(d, "seed")
            os.makedirs(data)
            os.makedirs(src)
            open(os.path.join(src, "config.json"), "w").write('{"from": "seed"}')
            run = lambda: subprocess.run(["sh", "-c", script.replace("/app/data", data).replace("/app/seed", src)], check=True, capture_output=True)
            run()
            self.assertEqual(open(os.path.join(data, "config.json")).read(), '{"from": "seed"}')
            open(os.path.join(data, "config.json"), "w").write('{"from": "api"}')
            run()
            self.assertEqual(open(os.path.join(data, "config.json")).read(), '{"from": "api"}', "a saved config was overwritten")


class HelmPresentTest(unittest.TestCase):
    def test_helm_is_there_when_required(self):
        # CI sets REQUIRE_HELM, so the chart checks never pass by being skipped
        if os.environ.get("REQUIRE_HELM"):
            self.assertTrue(HELM, "REQUIRE_HELM is set and helm is not installed")


@unittest.skipUnless(HELM, "helm is not installed (set HELM)")
class HelmTest(unittest.TestCase):
    def render(self, *sets, ok=True):
        args = [HELM, "template", "r", CHART]
        for s in sets:
            args += ["--set", s]
        p = subprocess.run(args, capture_output=True, text=True)
        if not ok:
            self.assertNotEqual(p.returncode, 0, "the chart rendered: " + " ".join(sets))
            return p.stderr
        self.assertEqual(p.returncode, 0, p.stderr)
        return [d for d in yaml.safe_load_all(p.stdout) if d]

    def kind(self, docs, kind, name=None):
        found = [d for d in docs if d["kind"] == kind and (name is None or d["metadata"]["name"] == name)]
        self.assertTrue(found, f"no {kind} {name or ''}")
        return found[0]

    def pod(self, docs):
        return self.kind(docs, "Deployment")["spec"]["template"]["spec"]

    def test_lint(self):
        p = subprocess.run([HELM, "lint", CHART], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_data_volume_is_a_writable_claim(self):
        docs = self.render()
        pod = self.pod(docs)
        c = pod["containers"][0]
        data = [m for m in c["volumeMounts"] if m["mountPath"] == "/app/data"]
        self.assertEqual(len(data), 1)
        self.assertFalse(data[0].get("readOnly", False), "/app/data is mounted read-only")
        vol = [v for v in pod["volumes"] if v["name"] == data[0]["name"]][0]
        self.assertEqual(vol["persistentVolumeClaim"]["claimName"], "r-raiju-data")
        pvc = self.kind(docs, "PersistentVolumeClaim", "r-raiju-data")
        self.assertEqual(pvc["metadata"]["annotations"]["helm.sh/resource-policy"], "keep")
        self.assertEqual(pod["securityContext"]["fsGroup"], 65532)
        # a ReadWriteOnce claim cannot move to a new pod while the old one runs
        self.assertEqual(self.kind(docs, "Deployment")["spec"]["strategy"]["type"], "Recreate")

    def test_tmp_is_an_empty_dir(self):
        pod = self.pod(self.render())
        tmp = [m for m in pod["containers"][0]["volumeMounts"] if m["mountPath"] == "/tmp"]
        self.assertEqual(len(tmp), 1, "no /tmp mount under a read-only root filesystem")
        vol = [v for v in pod["volumes"] if v["name"] == tmp[0]["name"]][0]
        self.assertIn("emptyDir", vol)

    def test_probes_are_split(self):
        c = self.pod(self.render())["containers"][0]
        self.assertEqual(c["livenessProbe"]["httpGet"]["path"], "/health")
        self.assertEqual(c["readinessProbe"]["httpGet"]["path"], "/ready")

    def test_drain_fits_in_the_kill_timeout(self):
        pod = self.pod(self.render())
        cmd = pod["containers"][0]["lifecycle"]["preStop"]["exec"]["command"]
        self.assertEqual(cmd[0], "/bin/sleep")
        # the preStop sleep, server.shutdown_delay_seconds (0), shutdown_grace_seconds (25) and about 5 s to flush
        self.assertGreaterEqual(pod["terminationGracePeriodSeconds"], int(cmd[1]) + 0 + 25 + 5)
        err = self.render("terminationGracePeriodSeconds=30", ok=False)
        self.assertIn("terminationGracePeriodSeconds", err)
        err = self.render("config.server.shutdown_grace_seconds=60", ok=False)
        self.assertIn("shutdown_grace_seconds", err)
        pod = self.pod(self.render("config.server.shutdown_grace_seconds=60", "terminationGracePeriodSeconds=75"))
        self.assertEqual(pod["terminationGracePeriodSeconds"], 75)
        self.assertNotIn("lifecycle", self.pod(self.render("preStopSleepSeconds=0"))["containers"][0])

    def test_memory_is_sized_from_the_measurements(self):
        res = self.pod(self.render())["containers"][0]["resources"]
        # one worker: 40 to 60 MB under load, about 170 KB per open stream (the soak); room for 2,000 streams
        self.assertGreaterEqual(mebibytes(res["limits"]["memory"]), 64 + 2000 * 0.17)
        self.assertGreaterEqual(mebibytes(res["requests"]["memory"]), 64)

    def test_init_container_seeds_the_config(self):
        pod = self.pod(self.render())
        init = pod["initContainers"][0]
        self.assertEqual(init["env"][0], {"name": "CONFIG_MODE", "value": "ifAbsent"})
        script = init["command"][2]
        with tempfile.TemporaryDirectory() as d:
            data, src = os.path.join(d, "data"), os.path.join(d, "seed")
            os.makedirs(data)
            os.makedirs(src)
            open(os.path.join(src, "config.json"), "w").write("seed-1")
            run = lambda mode: subprocess.run(["sh", "-c", script.replace("/app/data", data).replace("/app/seed", src)], env={**os.environ, "CONFIG_MODE": mode}, check=True, capture_output=True)
            run("ifAbsent")
            self.assertEqual(open(os.path.join(data, "config.json")).read(), "seed-1")
            open(os.path.join(data, "config.json"), "w").write("saved by the API")
            run("ifAbsent")
            self.assertEqual(open(os.path.join(data, "config.json")).read(), "saved by the API")
            run("always")
            self.assertEqual(open(os.path.join(data, "config.json")).read(), "seed-1")
        always = self.pod(self.render("configMode=always"))["initContainers"][0]
        self.assertEqual(always["env"][0]["value"], "always")
        self.assertIn("configMode", self.render("configMode=sometimes", ok=False))

    def test_replicas_need_shareable_storage(self):
        err = self.render("replicaCount=3", ok=False)
        self.assertIn("ReadWriteOnce", err)
        self.assertIn("ReadWriteOnce", self.render("autoscaling.enabled=true", ok=False))
        docs = self.render("replicaCount=3", "persistence.enabled=false", "configMode=always")
        pod = self.pod(docs)
        self.assertIn("emptyDir", [v for v in pod["volumes"] if v["name"] == "data"][0])
        self.assertEqual(self.kind(docs, "Deployment")["spec"]["strategy"]["type"], "RollingUpdate")
        self.assertFalse([d for d in docs if d["kind"] == "PersistentVolumeClaim"])
        docs = self.render("replicaCount=3", "persistence.accessModes[0]=ReadWriteMany")
        self.assertEqual(self.kind(docs, "PersistentVolumeClaim")["spec"]["accessModes"], ["ReadWriteMany"])
        docs = self.render("persistence.existingClaim=mine")
        self.assertEqual([v for v in self.pod(docs)["volumes"] if v["name"] == "data"][0]["persistentVolumeClaim"]["claimName"], "mine")
        self.assertFalse([d for d in docs if d["kind"] == "PersistentVolumeClaim"])

    def config(self, docs):
        return json.loads(self.kind(docs, "ConfigMap")["data"]["config.json"])

    def test_cluster_config_sync_default(self):
        self.assertNotIn("cluster", self.config(self.render()))
        on = ["config.cluster.enabled=true", "config.cluster.secret=env.RAIJU_CLUSTER_SECRET"]
        shared = self.config(self.render(*on, "replicaCount=2", "persistence.accessModes[0]=ReadWriteMany"))
        self.assertEqual(shared["cluster"]["config_sync"], "file")
        own = self.config(self.render(*on, "replicaCount=2", "persistence.enabled=false"))
        self.assertEqual(own["cluster"]["config_sync"], "pull")
        kept = self.config(self.render(*on, "config.cluster.config_sync=off"))
        self.assertEqual(kept["cluster"]["config_sync"], "off")
        off = self.config(self.render("config.cluster.enabled=false"))
        self.assertNotIn("config_sync", off["cluster"])

    def test_binds_every_address(self):
        args = self.pod(self.render())["containers"][0]["args"]
        self.assertEqual(args[args.index("-host") + 1], "0.0.0.0")

    def test_setup_token_from_a_secret(self):
        env = self.pod(self.render())["containers"][0]["env"]
        self.assertNotIn("BIFROST_SETUP_TOKEN", [e["name"] for e in env])
        env = self.pod(self.render("setupToken.existingSecret=raiju-setup"))["containers"][0]["env"]
        tok = [e for e in env if e["name"] == "BIFROST_SETUP_TOKEN"]
        self.assertEqual(tok[0]["valueFrom"]["secretKeyRef"], {"name": "raiju-setup", "key": "BIFROST_SETUP_TOKEN"})

    def test_peers_service(self):
        self.assertFalse([d for d in self.render() if d["kind"] == "Service" and d["metadata"]["name"].endswith("-peers")])
        svc = self.kind(self.render("peers.headlessService=true"), "Service", "r-raiju-peers")
        self.assertEqual(svc["spec"]["clusterIP"], "None")
        self.assertTrue(svc["spec"]["publishNotReadyAddresses"])
        self.assertEqual([p["name"] for p in svc["spec"]["ports"]], ["http"])

    def test_cluster_secret_from_a_secret(self):
        # clustering on needs a secret, and never one written into the ConfigMap
        self.assertIn("cluster.secret.existingSecret", self.render("config.cluster.enabled=true", ok=False))
        self.assertIn("env.NAME reference", self.render("config.cluster.enabled=true", "config.cluster.secret=plain-text-secret", ok=False))
        docs = self.render("config.cluster.enabled=true", "cluster.secret.existingSecret=raiju-cluster")
        self.assertEqual(self.config(docs)["cluster"]["secret"], "env.RAIJU_CLUSTER_SECRET")
        env = self.pod(docs)["containers"][0]["env"]
        sec = [e for e in env if e["name"] == "RAIJU_CLUSTER_SECRET"]
        self.assertEqual(sec[0]["valueFrom"]["secretKeyRef"], {"name": "raiju-cluster", "key": "RAIJU_CLUSTER_SECRET"})
        # an env.NAME reference of the operator's own is kept
        kept = self.render("config.cluster.enabled=true", "config.cluster.secret=env.MY_SECRET")
        self.assertEqual(self.config(kept)["cluster"]["secret"], "env.MY_SECRET")

    def test_cluster_listener(self):
        docs = self.render("config.cluster.enabled=true", "cluster.secret.existingSecret=raiju-cluster")
        cl = self.config(docs)["cluster"]
        self.assertEqual((cl["listen_port"], cl["bind"]), (7946, "0.0.0.0"))
        self.assertNotIn("serve_metrics", cl)
        ports = {p["name"]: p["containerPort"] for p in self.pod(docs)["containers"][0]["ports"]}
        self.assertEqual(ports, {"http": 8080, "cluster": 7946})
        # the peers Service targets the cluster port; the public Service does not carry it
        peers = self.kind(docs, "Service", "r-raiju-peers")
        self.assertEqual([(p["name"], p["port"]) for p in peers["spec"]["ports"]], [("cluster", 7946)])
        self.assertEqual(peers["metadata"]["labels"]["app.kubernetes.io/component"], "peers")
        self.assertEqual([p["port"] for p in self.kind(docs, "Service", "r-raiju")["spec"]["ports"]], [8080])
        # listenPort 0 keeps the peer routes on the main port
        off = self.render("config.cluster.enabled=true", "cluster.secret.existingSecret=raiju-cluster", "cluster.listenPort=0")
        self.assertNotIn("listen_port", self.config(off)["cluster"])
        self.assertEqual([p["name"] for p in self.pod(off)["containers"][0]["ports"]], ["http"])
        self.assertFalse([d for d in off if d["kind"] == "Service" and d["metadata"]["name"].endswith("-peers")])
        # without clustering no cluster port is opened
        self.assertEqual([p["name"] for p in self.pod(self.render())["containers"][0]["ports"]], ["http"])

    def test_metrics_token_and_port(self):
        self.assertNotIn("server", self.config(self.render()))
        docs = self.render("metricsToken.existingSecret=raiju-metrics", "serviceMonitor.enabled=true")
        self.assertEqual(self.config(docs)["server"]["metrics_token"], "env.RAIJU_METRICS_TOKEN")
        env = self.pod(docs)["containers"][0]["env"]
        self.assertEqual([e for e in env if e["name"] == "RAIJU_METRICS_TOKEN"][0]["valueFrom"]["secretKeyRef"], {"name": "raiju-metrics", "key": "RAIJU_METRICS_TOKEN"})
        ep = self.kind(docs, "ServiceMonitor")["spec"]["endpoints"][0]
        self.assertEqual((ep["port"], ep["bearerTokenSecret"]), ("http", {"name": "raiju-metrics", "key": "RAIJU_METRICS_TOKEN"}))
        # serveMetrics: scraped on the cluster port, through the peers Service
        on = self.render("config.cluster.enabled=true", "cluster.secret.existingSecret=raiju-cluster", "cluster.serveMetrics=true", "serviceMonitor.enabled=true")
        self.assertTrue(self.config(on)["cluster"]["serve_metrics"])
        sm = self.kind(on, "ServiceMonitor")["spec"]
        self.assertEqual(sm["endpoints"][0]["port"], "cluster")
        self.assertEqual(sm["selector"]["matchExpressions"], [{"key": "app.kubernetes.io/component", "operator": "In", "values": ["peers"]}])
        self.assertEqual(self.kind(on, "Deployment")["spec"]["template"]["metadata"]["annotations"]["prometheus.io/port"], "7946")


if __name__ == "__main__":
    unittest.main()

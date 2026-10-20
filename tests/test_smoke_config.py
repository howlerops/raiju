"""Unit tests for tests/smoke.py's config builder: which providers are configured from the environment, the
models each uses, and that no credential value reaches the config."""
import importlib.util
import io
import json
import pathlib
import unittest
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("smoke", ROOT / "tests" / "smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)

# fixture values are assembled so nothing here looks like a live credential
FAKE = "fixture-" + "not-a-key"
SA = json.dumps({"type": "service_account", "project_id": "sa-proj", "client_email": "e2e@test.iam.gserviceaccount.com", "private_key": "pem-" + "fixture"})


def files(mapping):
    def read(path):
        if path not in mapping:
            raise OSError(path)
        return mapping[path]
    return read


class BuildConfig(unittest.TestCase):
    def test_no_credentials_configures_nothing(self):
        cfg, extra, plan, skipped = smoke.build_config({}, "/tmp/logs")
        self.assertEqual(cfg["providers"], {})
        self.assertEqual(plan, {})
        self.assertEqual(extra, {})
        self.assertEqual(set(skipped), {p[0] for p in smoke.PROVIDERS})
        self.assertEqual(skipped["bedrock"], "no AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY")

    def test_main_skips_cleanly_without_credentials(self):
        saved = dict(smoke.os.environ)
        try:
            for v in [n for p in smoke.PROVIDERS for n in p[1]]:
                smoke.os.environ.pop(v, None)
            out = io.StringIO()
            with redirect_stdout(out):
                code = smoke.main()
        finally:
            smoke.os.environ.clear()
            smoke.os.environ.update(saved)
        self.assertEqual(code, 0)
        self.assertIn("nothing failed", out.getvalue())
        self.assertNotIn("FAIL", out.getvalue())

    def test_keys_are_env_references_never_values(self):
        env = {v: FAKE + "-" + v for p in smoke.PROVIDERS for v in p[1] if v != "GOOGLE_APPLICATION_CREDENTIALS"}
        env["AZURE_OPENAI_ENDPOINT"] = "https://example.openai.azure.com"
        env["AZURE_OPENAI_DEPLOYMENT"] = "dep-chat"
        env["GOOGLE_APPLICATION_CREDENTIALS"] = "/sa.json"
        cfg, extra, plan, skipped = smoke.build_config(env, "/tmp/logs", files({"/sa.json": SA}))
        self.assertEqual(skipped, {})
        text = json.dumps(cfg)
        self.assertNotIn(FAKE, text)
        self.assertNotIn("pem-fixture", text)
        ps = cfg["providers"]
        self.assertEqual(ps["openai"]["keys"][0]["value"], "env.OPENAI_API_KEY")
        self.assertEqual(ps["bedrock"]["keys"][0]["bedrock_key_config"], {"access_key": "env.AWS_ACCESS_KEY_ID", "secret_key": "env.AWS_SECRET_ACCESS_KEY", "region": "us-east-1"})
        self.assertEqual(ps["azure"]["keys"][0]["azure_key_config"]["endpoint"], "env.AZURE_OPENAI_ENDPOINT")
        self.assertEqual(ps["vertex"]["keys"][0]["vertex_key_config"], {"project_id": "sa-proj", "region": "us-central1", "auth_credentials": "env." + smoke.VERTEX_CREDS_VAR})
        # the service account JSON goes to the gateway's environment only
        self.assertEqual(extra, {smoke.VERTEX_CREDS_VAR: SA})

    def test_models_defaults_and_overrides(self):
        env = {"OPENAI_API_KEY": FAKE, "ANTHROPIC_API_KEY": FAKE, "GROQ_API_KEY": FAKE, "MISTRAL_API_KEY": FAKE,
               "SMOKE_OPENAI_MODEL": "gpt-4o-mini", "SMOKE_OPENAI_EMBED_MODEL": "off", "SMOKE_MISTRAL_MODEL": "-"}
        cfg, _, plan, skipped = smoke.build_config(env, "/tmp/logs")
        self.assertEqual(plan["openai"], {"model": "openai/gpt-4o-mini", "embed": "", "native": "responses"})
        self.assertEqual(plan["anthropic"], {"model": "anthropic/claude-haiku-4-5", "embed": "", "native": "messages"})
        self.assertEqual(plan["groq"]["model"], "groq/openai/gpt-oss-20b")
        self.assertNotIn("mistral", plan)
        self.assertIn("SMOKE_MISTRAL_MODEL", skipped["mistral"])
        self.assertNotIn("mistral", cfg["providers"])

    def test_cloud_options(self):
        env = {"AWS_ACCESS_KEY_ID": FAKE, "AWS_SECRET_ACCESS_KEY": FAKE, "AWS_SESSION_TOKEN": FAKE, "AWS_REGION": "eu-west-1",
               "AZURE_OPENAI_API_KEY": FAKE, "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com", "AZURE_OPENAI_DEPLOYMENT": "dep-chat",
               "AZURE_OPENAI_EMBED_DEPLOYMENT": "dep-embed", "AZURE_OPENAI_API_VERSION": "2025-01-01-preview"}
        cfg, _, plan, _ = smoke.build_config(env, "/tmp/logs")
        bk = cfg["providers"]["bedrock"]["keys"][0]["bedrock_key_config"]
        self.assertEqual((bk["region"], bk["session_token"]), ("eu-west-1", "env.AWS_SESSION_TOKEN"))
        self.assertEqual(plan["bedrock"], {"model": "bedrock/amazon.nova-micro-v1:0", "embed": "bedrock/amazon.titan-embed-text-v2:0", "native": "converse"})
        self.assertEqual(plan["azure"], {"model": "azure/dep-chat", "embed": "azure/dep-embed", "native": ""})
        self.assertEqual(cfg["providers"]["azure"]["keys"][0]["azure_key_config"]["api_version"], "2025-01-01-preview")

    def test_vertex_needs_a_service_account(self):
        env = {"GOOGLE_APPLICATION_CREDENTIALS": "/user.json"}
        _, extra, plan, skipped = smoke.build_config(env, "/tmp/logs", files({"/user.json": json.dumps({"type": "authorized_user"})}))
        self.assertNotIn("vertex", plan)
        self.assertIn("service account", skipped["vertex"])
        self.assertEqual(extra, {})
        _, _, _, skipped = smoke.build_config({"GOOGLE_APPLICATION_CREDENTIALS": "/missing.json"}, "/tmp/logs", files({}))
        self.assertIn("not a readable JSON file", skipped["vertex"])
        noproj = json.dumps({"type": "service_account"})
        _, _, plan, skipped = smoke.build_config(env, "/tmp/logs", files({"/user.json": noproj}))
        self.assertIn("VERTEX_PROJECT", skipped["vertex"])
        _, _, plan, _ = smoke.build_config({**env, "VERTEX_PROJECT": "p2", "VERTEX_REGION": "europe-west4", "SMOKE_VERTEX_MODEL": "gemini-2.5-flash"}, "/tmp/logs", files({"/user.json": noproj}))
        self.assertEqual(plan["vertex"], {"model": "vertex/gemini-2.5-flash", "embed": "vertex/text-embedding-005", "native": "genai"})

    def test_large_payload_threshold_is_low_and_logging_on(self):
        cfg, _, _, _ = smoke.build_config({}, "/tmp/logs")
        lpo = cfg["large_payload_optimization"]
        self.assertTrue(lpo["enabled"])
        self.assertEqual(lpo["request_threshold_bytes"], smoke.LARGE_THRESHOLD)
        self.assertLess(lpo["prefetch_size_bytes"], lpo["request_threshold_bytes"])
        self.assertEqual(cfg["logs_store"], {"enabled": True, "dir": "/tmp/logs", "content_logging": False})

    def test_report_masks_secrets(self):
        rep = smoke.Report([FAKE, "", "abc"])
        out = io.StringIO()
        with redirect_stdout(out):
            rep.line("FAIL", "openai", "chat", "401 bad key " + FAKE)
        self.assertNotIn(FAKE, out.getvalue())
        self.assertIn("***", out.getvalue())
        self.assertEqual(rep.counts["FAIL"], 1)


if __name__ == "__main__":
    unittest.main()

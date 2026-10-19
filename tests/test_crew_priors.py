"""Unit tests for scripts/crew_priors.py: priors fit, credibility, IRT, frontier and the classifier file.

The classifier checks use the hash vectors and tokenisation of src/taskclass.tov (L151).
"""
import contextlib
import importlib.util
import io
import json
import math
import os
import pathlib
import random
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("crew_priors", ROOT / "scripts" / "crew_priors.py")
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)

ROLES = ["worker", "checker"]
REF = {"worker": "a", "checker": "a"}
CANDS = ["a", "b", "c", "d"]
TRUE_Q0 = 0.40
TRUE_DELTA = {
    ("worker", "b"): 0.10, ("worker", "c"): -0.05, ("worker", "d"): 0.02,
    ("checker", "b"): 0.06, ("checker", "c"): 0.02, ("checker", "d"): -0.10,
}


def synthetic_rows(seed=7, tasks=400, noise=0.02, cls="bug-fix", cands=CANDS, delta=TRUE_DELTA):
    rng = random.Random(seed)
    rows = []
    for t in range(tasks):
        crew = {s: rng.choice(cands) for s in ROLES}
        q = TRUE_Q0 + sum(delta.get((s, crew[s]), 0.0) for s in ROLES) + rng.gauss(0, noise)
        q = min(max(q, 0.0), 1.0)
        rows.append({"task": f"t{t}", "cls": cls, "crew": crew, "q": q, "cost": 0.01, "bench": "bench-x"})
    return rows


def metadata(log_prices):
    """Metadata rows with only the input price set (the other columns blank)."""
    out = {}
    for c, lp in log_prices.items():
        out[c] = {"candidate": c, "log_input_price": repr(lp), "log_output_price": "",
                  "release_date": "", "context_length": "", "open_weights": "", "reasoning": "",
                  "provider": ""}
    return out


class HashTest(unittest.TestCase):
    def test_fnv1a_vectors(self):
        vectors = {"": (0x811C9DC5, 40389), "a": (0xE40C292C, 10540), "foobar": (0xBF9CF968, 63848),
                   "fix crash": (0x19F848EB, 18667), "bug-fix": (0x583FB213, 242195)}
        for text, (h, bucket) in vectors.items():
            self.assertEqual(cp.fnv1a32(text.encode("utf-8")), h, text)
            self.assertEqual(cp.bucket_of(text), bucket, text)

    def test_buckets_are_18_bits(self):
        for text in ["x", "longer feature string", "label:bug", "verb:fix"]:
            self.assertLess(cp.bucket_of(text), 262144)


class TokenTest(unittest.TestCase):
    def test_words_are_ascii_runs_lowered(self):
        words = [w for w, _ in cp._words("Fix-the BUG, 2nd_try")]
        self.assertEqual(words, ["fix", "the", "bug", "2nd", "try"])

    def test_non_ascii_bytes_separate(self):
        self.assertEqual([w for w, _ in cp._words("café au")], ["caf", "au"])

    def test_bigrams_join_adjacent_words(self):
        feats = cp.hashed_features("fix crash")
        self.assertIn(cp.bucket_of("fix crash"), feats)
        self.assertIn(cp.bucket_of("fix"), feats)

    def test_named_features(self):
        self.assertEqual(cp.named_features("", [" Bug ", "", "bug"]), ["label:bug"])
        text = "Some context.\n- Add retries to the client\nWe fix it later"
        named = cp.named_features(text, [])
        self.assertIn("verb:add", named)
        self.assertNotIn("verb:fix", named)
        self.assertIn("has:code", cp.named_features("```a``` and ```b```", []))
        self.assertIn("has:stacktrace", cp.named_features(
            "Traceback (most recent call last)\n  File \"x.py\", line 3", []))


class CredibilityTest(unittest.TestCase):
    def test_eq10_behaviour(self):
        self.assertEqual(cp.credibility(0, 0.2, 1.2), 0.0)
        zs = [cp.credibility(n, 0.2, 1.2) for n in (1, 5, 20, 200, 5000)]
        self.assertEqual(zs, sorted(zs))
        self.assertGreater(zs[-1], 0.99)
        # Z = nI / (nI + s^-2): a larger prior scale trusts the cell more
        self.assertGreater(cp.credibility(10, 0.2, 1.2), cp.credibility(10, 0.2, 0.3))
        self.assertAlmostEqual(cp.credibility(10, 0.2, 1.2), 2.0 / (2.0 + 1 / 1.44))

    def test_blend_is_convex_combination(self):
        self.assertAlmostEqual(cp.blend(0.3, 0.1, 0, 0.2, 1.2), 0.1)
        self.assertAlmostEqual(cp.blend(0.3, 0.1, 10 ** 6, 0.2, 1.2), 0.3, places=3)
        z = cp.credibility(25, 0.2, 1.2)
        self.assertAlmostEqual(cp.blend(0.3, 0.1, 25, 0.2, 1.2), z * 0.3 + (1 - z) * 0.1)


class FitTest(unittest.TestCase):
    def test_recovers_role_effects(self):
        priors = cp.fit_priors(synthetic_rows(), REF, irt=False)
        self.assertEqual(cp.validate_priors(priors), [])
        self.assertAlmostEqual(priors["baseline"]["bug-fix"], TRUE_Q0, delta=0.03)
        for cell in priors["cells"]:
            key = (cell["role"], cell["candidate"])
            if cell["candidate"] == "a":
                self.assertEqual(cell["delta"], 0.0)
                continue
            self.assertAlmostEqual(cell["delta"], TRUE_DELTA[key], delta=0.03, msg=str(key))

    def test_counts_are_distinct_tasks(self):
        rows = synthetic_rows(tasks=120)
        priors = cp.fit_priors(rows, REF, irt=False)
        cell = next(c for c in priors["cells"] if c["role"] == "worker" and c["candidate"] == "b")
        expected = len({r["task"] for r in rows if r["crew"]["worker"] == "b"})
        self.assertEqual(cell["n"], expected)
        self.assertGreater(cell["info"], 0.0)
        self.assertLessEqual(cell["info"], 0.25)

    def test_day_zero_candidate_is_placed_by_metadata(self):
        rows = synthetic_rows(tasks=400)
        # metadata tracks the average true effect: b 0.08, c -0.015, d -0.04, and e (no rows) 0.10
        log_prices = {"a": -3.0, "b": -3.0 + 5 * 0.08, "c": -3.0 - 5 * 0.015, "d": -3.0 - 5 * 0.04,
                      "e": -3.0 + 5 * 0.10}
        priors = cp.fit_priors(rows, REF, meta=metadata(log_prices), irt=False)
        e_cells = [c for c in priors["cells"] if c["candidate"] == "e"]
        self.assertTrue(e_cells)
        for cell in e_cells:
            self.assertEqual(cell["n"], 0)
            self.assertEqual(cell["info"], 0.0)
        worker_e = next(c for c in e_cells if c["role"] == "worker")["delta"]
        self.assertGreater(worker_e, 0.02)
        self.assertLess(worker_e, 0.15)

    def test_leaderboard_moment_pulls_prediction(self):
        rows = synthetic_rows(tasks=400)
        extra = []
        rng = random.Random(3)
        for t in range(6):
            extra.append({"task": f"e{t}", "cls": "bug-fix", "crew": {"worker": "e", "checker": "e"},
                          "q": 0.5, "cost": 0.01, "bench": "bench-x"})
        rows = rows + extra
        board = [{"bench": "bench-x", "cand": "e", "score": 0.9, "cls": "bug-fix"}]

        def uniform_e(priors):
            q0 = priors["baseline"]["bug-fix"]
            return q0 + sum(c["delta"] for c in priors["cells"]
                            if c["candidate"] == "e" and c["class"] == "bug-fix")

        without = uniform_e(cp.fit_priors(rows, REF, irt=False))
        with_board = uniform_e(cp.fit_priors(rows, REF, board=board, irt=False))
        self.assertLess(abs(with_board - 0.9), abs(without - 0.9))
        self.assertGreater(with_board, without)

    def test_interactions_when_both_off_diagonal_cells_measured(self):
        rows = synthetic_rows(tasks=300)
        priors = cp.fit_priors(rows, REF, use_inter=True, irt=False)
        self.assertEqual(cp.validate_priors(priors), [])
        self.assertTrue(all(i["roles"] == ["worker", "checker"] for i in priors["interactions"]))

    def test_irt_orders_candidates(self):
        if not cp.HAVE_IRT:
            self.skipTest("numpy and scipy are not installed")
        rng = random.Random(11)
        lg = {"a": -1.0, "b": 0.0, "c": 1.0, "d": 2.0}
        rows = []
        for t in range(600):
            zt = rng.gauss(0, 1)
            m = rng.choice(list(lg))
            p = 1 / (1 + math.exp(-(lg[m] - zt)))
            rows.append({"task": f"t{t}", "cls": "bug-fix", "crew": {"worker": m, "checker": m},
                         "q": 1.0 if rng.random() < p else 0.0, "cost": 0.0, "bench": ""})
        priors = cp.fit_priors(rows, REF, irt=True, irt_scales=(1.2,))
        l = {m: priors["irt"]["bug-fix"][m]["l"] for m in lg}
        self.assertLess(l["a"], l["b"])
        self.assertLess(l["b"], l["c"])
        self.assertLess(l["c"], l["d"])
        for m in lg:
            self.assertGreater(priors["irt"]["bug-fix"][m]["kappa"], 0)

    def test_fallback_irt_uses_logit_of_mean(self):
        rows = synthetic_rows(tasks=50)
        for r in rows:
            r["crew"] = {"worker": "b", "checker": "b"}
        saved = cp.HAVE_IRT
        cp.HAVE_IRT = False
        try:
            priors = cp.fit_priors(rows, REF, irt=True)
        finally:
            cp.HAVE_IRT = saved
        entry = priors["irt"]["bug-fix"]["b"]
        mean = sum(r["q"] for r in rows) / len(rows)
        self.assertAlmostEqual(entry["l"], math.log(mean / (1 - mean)), places=4)
        self.assertEqual(entry["kappa"], 1.0)


class FrontierTest(unittest.TestCase):
    def priors(self):
        cells = []
        effects = {"a": (0.0, 0.0), "b": (0.10, 0.05), "c": (0.13, 0.07)}
        for m, (dw, dc) in effects.items():
            cells.append({"class": "bug-fix", "role": "worker", "candidate": m, "delta": dw, "n": 9, "info": 0.2})
            cells.append({"class": "bug-fix", "role": "checker", "candidate": m, "delta": dc, "n": 9, "info": 0.2})
        return {"version": 1, "baseline": {"bug-fix": 0.3}, "cells": cells, "interactions": [], "irt": {}}

    def pool(self, alpha=1.0):
        prices = {"a": 1e-6, "b": 8e-6, "c": 60e-6}
        return {"candidates": [{"id": m, "input_price": p * alpha, "output_price": 2 * p * alpha}
                               for m, p in prices.items()],
                "profiles": {"bug-fix": {"worker": {"calls": 10, "input_tokens": 8000, "output_tokens": 500},
                                         "checker": {"calls": 3, "input_tokens": 4000, "output_tokens": 300}}}}

    def test_frontier_is_concave_and_nondecreasing(self):
        res = cp.class_frontier(self.priors(), self.pool(), "bug-fix")
        vs = res["frontier"]
        self.assertGreaterEqual(len(vs), 2)
        for a, b in zip(vs, vs[1:]):
            self.assertGreaterEqual(b["quality"], a["quality"])
        slopes = [(b["quality"] - a["quality"]) / (b["cost"] - a["cost"]) for a, b in zip(vs, vs[1:])]
        self.assertEqual(slopes, sorted(slopes, reverse=True))

    def test_knee_invariant_to_price_rescaling(self):
        base = cp.class_frontier(self.priors(), self.pool(1.0), "bug-fix")
        scaled = cp.class_frontier(self.priors(), self.pool(7.0), "bug-fix")
        k0, k1 = base["knee"], scaled["knee"]
        self.assertIsNotNone(k0)
        self.assertAlmostEqual(k1["quality"], k0["quality"], places=12)
        self.assertAlmostEqual(k1["cost"], 7.0 * k0["cost"], places=12)
        self.assertAlmostEqual(k1["lambda"] * 7.0, k0["lambda"], places=9)
        self.assertEqual(k1["crew_below"], k0["crew_below"])

    def test_knee_lambda_is_a_supporting_slope(self):
        res = cp.class_frontier(self.priors(), self.pool(), "bug-fix")
        k = res["knee"]
        self.assertGreater(k["lambda"], 0)
        self.assertGreaterEqual(k["cost"], res["range"]["lo"])
        self.assertLessEqual(k["cost"], res["range"]["hi"])


CLASS_WORDS = {
    "bug-fix": ["crash", "error", "regression", "broken", "panic", "leak", "fails", "wrong"],
    "open-ended": ["feature", "design", "refactor", "support", "improve", "migrate", "proposal", "redesign"],
    "other": ["readme", "typo", "changelog", "license", "badge", "emoji", "dependency", "bump"],
}
FILLER = ["the", "a", "when", "on", "with", "in", "after", "users", "server", "config", "page"]


def make_text(rng, cls):
    words = [rng.choice(CLASS_WORDS[cls]) for _ in range(3)] + [rng.choice(FILLER) for _ in range(4)]
    rng.shuffle(words)
    return " ".join(words)


def classifier_data(seed=5, per_class=120):
    rng = random.Random(seed)
    data = []
    for cls in CLASS_WORDS:
        for _ in range(per_class):
            labels = [cls] if rng.random() < 0.3 else []
            data.append((make_text(rng, cls), labels, cls))
    rng.shuffle(data)
    return data


class ClassifierTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = classifier_data()
        cls.model = cp.train_classifier(cls.data, epochs=8)

    def test_file_validates(self):
        self.assertEqual(cp.validate_classifier(self.model), [])

    def test_accuracy_on_fresh_texts(self):
        rng = random.Random(99)
        hits = 0
        total = 0
        for cls in CLASS_WORDS:
            for _ in range(40):
                total += 1
                if cp.classify(self.model, make_text(rng, cls))["top"] == cls:
                    hits += 1
        self.assertGreater(hits / total, 0.9)

    def test_round_trip_through_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "crew-classifier.json"
            path.write_text(json.dumps(self.model), encoding="utf-8")
            loaded = cp.load_classifier(str(path))
        text = "crash in the server after the feature update"
        self.assertEqual(cp.classify(loaded, text, ["bug-fix"]), cp.classify(self.model, text, ["bug-fix"]))

    def test_weights_are_int8_and_pruned(self):
        small = cp.train_classifier(self.data, max_weights=40, epochs=4)
        for c in small["classes"]:
            self.assertLessEqual(len(small["weights"][c]) + len(small["named"][c]), 40)
            for _, q in small["weights"][c]:
                self.assertTrue(-128 <= q <= 127 and q != 0)
        self.assertEqual(cp.validate_classifier(small), [])

    def test_posterior_is_a_distribution_with_floor(self):
        v = cp.classify(self.model, "", [])
        self.assertAlmostEqual(sum(v["posterior"].values()), 1.0, places=9)
        for p in v["posterior"].values():
            self.assertGreaterEqual(p, self.model["floor"] * min(self.model["prior"].values()) - 1e-12)

    def test_uncertain_decision(self):
        model = dict(self.model)
        model["uncertain_below"] = 1.0
        self.assertEqual(cp.classify(model, "crash", [])["decision"], model["uncertain_class"])

    def test_validator_rejects_bad_files(self):
        bad = json.loads(json.dumps(self.model))
        cls = bad["classes"][0]
        bad["weights"][cls] = [[262144, 3]]
        self.assertTrue(cp.validate_classifier(bad))
        bad = json.loads(json.dumps(self.model))
        bad["weights"][cls] = [[1, 0]]
        self.assertTrue(cp.validate_classifier(bad))
        bad = json.loads(json.dumps(self.model))
        bad["named"][cls] = {"bug": 5}
        self.assertTrue(cp.validate_classifier(bad))
        bad = json.loads(json.dumps(self.model))
        bad["weights"][cls] = [[i, 1] for i in range(2001)]
        self.assertTrue(any("2000" in e for e in cp.validate_classifier(bad)))
        bad = json.loads(json.dumps(self.model))
        bad["prior"][cls] = 0.9
        self.assertTrue(cp.validate_classifier(bad))

    def test_validator_rejects_oversize_file(self):
        self.assertTrue(cp.validate_classifier(self.model, size=cp.MAX_FILE_BYTES + 1))


class CliTest(unittest.TestCase):
    def test_fit_and_frontier_commands(self):
        rows = synthetic_rows(tasks=120)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            mat = tmp / "matrix.csv"
            with open(mat, "w", encoding="utf-8") as f:
                f.write("task_id,class,crew,quality,cost_usd,benchmark\n")
                for r in rows:
                    crew = ";".join(f"{s}={r['crew'][s]}" for s in ROLES)
                    f.write(f"{r['task']},bug-fix,{crew},{r['q']:.6f},0.01,bench-x\n")
            out = tmp / "priors.json"
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = cp.main(["fit-priors", "--matrix", str(mat), "--reference", "worker=a,checker=a",
                              "--no-irt", "--out", str(out)])
            self.assertEqual(rc, 0)
            priors = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(cp.validate_priors(priors), [])
            pool = tmp / "pool.json"
            pool.write_text(json.dumps({"candidates": [{"id": m, "input_price": 1e-6 * (i + 1),
                                                        "output_price": 2e-6 * (i + 1)}
                                                       for i, m in enumerate(CANDS)],
                                        "profiles": {"bug-fix": {
                                            "worker": {"calls": 5, "input_tokens": 1000, "output_tokens": 100},
                                            "checker": {"calls": 2, "input_tokens": 800, "output_tokens": 50}}}}),
                            encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cp.main(["frontier", "--priors", str(out), "--pool", str(pool)])
            self.assertEqual(rc, 0)
            self.assertIn("bug-fix", json.loads(buf.getvalue()))
            clf = tmp / "train.csv"
            with open(clf, "w", encoding="utf-8", newline="") as f:
                f.write("text,labels,class\n")
                for text, labels, c in classifier_data(per_class=30):
                    f.write(f"\"{text}\",\"{','.join(labels)}\",{c}\n")
            cfile = tmp / "classifier.json"
            with contextlib.redirect_stderr(io.StringIO()):
                rc = cp.main(["train-classifier", "--data", str(clf), "--out", str(cfile), "--epochs", "3"])
            self.assertEqual(rc, 0)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cp.main(["validate", str(cfile)]), 0)


if __name__ == "__main__":
    unittest.main()


class ClassifierParityFixtureTest(unittest.TestCase):
    """tests/fixtures/crew_classifier_parity.json is also checked by src/taskclass.tov: both sides must give its verdicts."""

    def test_fixture_verdicts(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "crew_classifier_parity.json")
        with open(path, encoding="utf-8") as f:
            fx = json.load(f)
        for case in fx["cases"]:
            v = cp.classify(fx["classifier"], case["text"], case["labels"])
            self.assertEqual(v["decision"], case["decision"])
            for k, p in case["posterior"].items():
                self.assertAlmostEqual(v["posterior"][k], p, places=9)

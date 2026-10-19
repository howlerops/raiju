#!/usr/bin/env python3
"""Offline priors and classifier training for crew routing (docs/crew-routing.md).

Usage:
  scripts/crew_priors.py fit-priors --matrix EVAL.csv --reference worker=a,planner=b,checker=a
        [--metadata META.csv] [--leaderboard BOARD.csv] [--interactions] [--out crew-priors.json]
  scripts/crew_priors.py train-classifier --data TRAIN.csv [--out crew-classifier.json]
  scripts/crew_priors.py frontier --priors crew-priors.json --pool POOL.json [--class bug-fix]
  scripts/crew_priors.py validate FILE.json

Inputs (UTF-8 CSV with a header row):
  evaluation matrix: task_id, class, crew, quality, cost_usd[, benchmark]
      crew is "role=candidate;role=candidate;..." with every role of the reference.
      quality is in [0, 1] (a success probability, or a review score divided by 10).
  metadata: candidate, log_input_price, log_output_price, release_date, context_length,
      open_weights, reasoning, provider. Prices are natural logs of USD per token; blanks are
      missing values. release_date is YYYY, YYYY-MM or YYYY-MM-DD.
  leaderboard: benchmark, candidate, score[, class]. score is the published success rate.
  training: text, labels (comma-separated, may be empty), class.
  pool (JSON): {"candidates": [{"id", "input_price", "output_price"}],
                "profiles": {class: {role: {"calls", "input_tokens", "output_tokens"}}}}
      prices are USD per token, the same units as the pricing table.

The priors model per class c is Q(m; c) = q0(c) + sum_s delta_s(m_s; c) (role additivity,
Assumption 1), with optional pairwise interactions. The fit maximises the Bernoulli
quasi-likelihood of the crew outcomes plus nllp times the leaderboard moment conditions
(eq. 7, learning from label proportions), with a Gaussian prior on each role effect centred
on the metadata regression (eq. 6). Per-candidate IRT logits (eq. 8) are fitted on the
uniform crews (one candidate in every role) by marginal likelihood with Gauss-Hermite
quadrature when numpy and scipy are installed. Without them the logit of the class mean is
used with kappa = 1.
"""
import argparse
import csv
import json
import math
import random
import re
import sys

try:
    import numpy as np
    from numpy.polynomial.hermite_e import hermegauss
    from scipy.optimize import minimize
    from scipy.special import expit, logsumexp
    HAVE_IRT = True
except ImportError:
    HAVE_IRT = False

EPS = 1e-6
NLLP = 30.0                  # penalty weight of the leaderboard moments (paper, Sec. 3.2)
TAU_DELTA = 0.25             # prior sd of a role effect around the metadata prediction
TAU_INTER = 0.05             # prior sd of a pairwise interaction
META_RIDGE = 1.0             # ridge on the metadata regression (standardised features)
G_NODES = 41                 # Gauss-Hermite nodes (paper, Appendix E)
IRT_LOGK_SD = 0.3            # log kappa ~ N(0, 0.3^2)
IRT_GAMMA_MEAN = -3.0        # guessing logit gamma ~ N(-3, 1.5^2), g = 0.5 sigmoid(gamma)
IRT_GAMMA_SD = 1.5
IRT_SCALE_DEFAULT = 1.2      # prior scale of the level-2 intercept when no validation split exists
PRIOR_FILE_VERSION = 1
CLASSIFIER_VERSION = 1


class ToolError(Exception):
    pass


# ---------------------------------------------------------------- shared helpers

def fnv1a32(data):
    """FNV-1a, 32 bit, over bytes."""
    h = 0x811C9DC5
    for b in data:
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def credibility(n, info, prior_scale):
    """Eq. 10 weight Z = n I / (n I + prior_scale^-2). Z is 0 with no tasks and tends to 1 as n grows."""
    if n <= 0 or info <= 0:
        return 0.0
    a = n * info
    return a / (a + 1.0 / (prior_scale * prior_scale))


def blend(own, prior, n, info, prior_scale):
    """Credibility blend of a cell's own estimate with its prior (the gateway's update rule)."""
    z = credibility(n, info, prior_scale)
    return z * own + (1.0 - z) * prior


def _solve(a, b):
    """Solve a x = b by Gaussian elimination with partial pivoting (small dense systems)."""
    n = len(b)
    m = [list(row) + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-300:
            raise ToolError("singular system in the fit")
        m[c], m[piv] = m[piv], m[c]
        pv = m[c][c]
        for r in range(c + 1, n):
            f = m[r][c] / pv
            if f:
                rr, rc = m[r], m[c]
                for k in range(c, n + 1):
                    rr[k] -= f * rc[k]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (m[i][n] - sum(m[i][k] * x[k] for k in range(i + 1, n))) / m[i][i]
    return x


def _ridge(xs, ys, lam):
    """Ridge regression with an unpenalised first column (the intercept)."""
    p = len(xs[0])
    a = [[0.0] * p for _ in range(p)]
    b = [0.0] * p
    for x, y in zip(xs, ys):
        for i in range(p):
            b[i] += x[i] * y
            for j in range(p):
                a[i][j] += x[i] * x[j]
    for i in range(1, p):
        a[i][i] += lam
    return _solve(a, b)


def _logit(p):
    p = min(max(p, 0.01), 0.99)
    return math.log(p / (1 - p))


# ---------------------------------------------------------------- input parsing

def _read_csv(path, required):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [c for c in required if reader.fieldnames is None or c not in reader.fieldnames]
        if missing:
            raise ToolError(f"{path}: missing column(s) {', '.join(missing)}")
        return [{k: (v or "").strip() for k, v in rec.items() if k is not None} for rec in reader]


def parse_crew(text):
    """'worker=a;planner=b' -> {'worker': 'a', 'planner': 'b'}."""
    crew = {}
    for part in text.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ToolError(f"crew entry {part!r} is not role=candidate")
        role, cand = (x.strip() for x in part.split("=", 1))
        if not role or not cand:
            raise ToolError(f"crew entry {part!r} has an empty role or candidate")
        if role in crew:
            raise ToolError(f"crew {text!r} repeats role {role!r}")
        crew[role] = cand
    if not crew:
        raise ToolError("empty crew")
    return crew


def parse_reference(text):
    ref = {}
    for part in text.split(","):
        part = part.strip()
        if "=" not in part:
            raise ToolError(f"--reference entry {part!r} is not role=candidate")
        role, cand = (x.strip() for x in part.split("=", 1))
        ref[role] = cand
    if not ref:
        raise ToolError("--reference is empty")
    return ref


def read_matrix(path):
    rows = []
    for i, rec in enumerate(_read_csv(path, ["task_id", "class", "crew", "quality", "cost_usd"]), start=2):
        try:
            q = float(rec["quality"])
            cost = float(rec["cost_usd"])
        except ValueError:
            raise ToolError(f"{path}:{i}: quality and cost_usd must be numbers")
        if not (0.0 <= q <= 1.0) or not math.isfinite(cost) or cost < 0:
            raise ToolError(f"{path}:{i}: quality must be in [0, 1] and cost_usd >= 0")
        if not rec["class"]:
            raise ToolError(f"{path}:{i}: empty class")
        rows.append({"task": rec["task_id"], "cls": rec["class"], "crew": parse_crew(rec["crew"]),
                     "q": q, "cost": cost, "bench": rec.get("benchmark", "")})
    if not rows:
        raise ToolError(f"{path}: no rows")
    return rows


_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$")


def _release_year(text):
    m = _DATE_RE.match(text)
    if not m:
        return None
    year = int(m.group(1))
    month = int(m.group(2) or 1)
    return year + (month - 1) / 12.0


def _truthy(text):
    t = text.strip().lower()
    if t in ("1", "true", "yes", "y"):
        return 1.0
    if t in ("0", "false", "no", "n"):
        return 0.0
    return None


def read_metadata(path):
    out = {}
    for rec in _read_csv(path, ["candidate"]):
        out[rec["candidate"]] = rec
    return out


def meta_features(meta):
    """Feature vectors x_m for the metadata regression (eq. 6). Returns (names, {candidate: vector})."""
    cands = sorted(meta)
    numeric = {}
    for col in ("log_input_price", "log_output_price", "release_year", "log_context_length"):
        vals = {}
        for c in cands:
            raw = meta[c].get(col, "")
            if col == "release_year":
                v = _release_year(raw) if raw else None
            elif col == "log_context_length":
                try:
                    v = math.log(float(raw)) if raw and float(raw) > 0 else None
                except ValueError:
                    raise ToolError(f"metadata: bad context_length for {c}")
            else:
                try:
                    v = float(raw) if raw else None
                except ValueError:
                    raise ToolError(f"metadata: bad {col} for {c}")
            vals[c] = v
        numeric[col] = vals
    binary = {}
    for col in ("open_weights", "reasoning"):
        binary[col] = {c: _truthy(meta[c].get(col, "")) for c in cands}
    providers = sorted({meta[c].get("provider", "") for c in cands} - {""})[1:]
    stats = {}
    for col, vals in numeric.items():
        seen = [v for v in vals.values() if v is not None]
        mean = sum(seen) / len(seen) if seen else 0.0
        sd = math.sqrt(sum((v - mean) ** 2 for v in seen) / len(seen)) if len(seen) > 1 else 0.0
        stats[col] = (mean, sd if sd > 1e-9 else 1.0)
    names = ["intercept"] + list(numeric) + list(binary) + [f"missing:{c}" for c in list(numeric) + list(binary)]
    names += [f"provider:{p}" for p in providers]
    feats = {}
    for c in cands:
        x = [1.0]
        miss = []
        for col in numeric:
            v = numeric[col][c]
            if v is None:
                x.append(0.0)
                miss.append(1.0)
            else:
                mean, sd = stats[col]
                x.append((v - mean) / sd)
                miss.append(0.0)
        for col in binary:
            v = binary[col][c]
            x.append(0.0 if v is None else v)
            miss.append(1.0 if v is None else 0.0)
        x += miss
        prov = meta[c].get("provider", "")
        x += [1.0 if prov == p else 0.0 for p in providers]
        feats[c] = x
    return names, feats


def read_leaderboard(path, rows):
    recs = _read_csv(path, ["benchmark", "candidate", "score"])
    bench_class = {}
    for r in rows:
        if r["bench"]:
            bench_class.setdefault(r["bench"], {}).setdefault(r["cls"], 0)
            bench_class[r["bench"]][r["cls"]] += 1
    out = []
    for i, rec in enumerate(recs, start=2):
        try:
            s = float(rec["score"])
        except ValueError:
            raise ToolError(f"{path}:{i}: score must be a number")
        if not (0.0 <= s <= 1.0):
            raise ToolError(f"{path}:{i}: score must be in [0, 1] (a rate, not a percentage)")
        cls = rec.get("class", "")
        if not cls:
            counts = bench_class.get(rec["benchmark"], {})
            if not counts:
                print(f"crew_priors: leaderboard benchmark {rec['benchmark']!r} has no class; skipped",
                      file=sys.stderr)
                continue
            cls = max(sorted(counts), key=lambda k: counts[k])
        out.append({"bench": rec["benchmark"], "cand": rec["candidate"], "score": s, "cls": cls})
    return out


# ---------------------------------------------------------------- the role-additive fit

def _pairs_for(crew, roles, ref, index, allowed):
    out = [(0, 1.0)]
    for s in roles:
        m = crew[s]
        if m != ref[s]:
            out.append((index[("d", s, m)], 1.0))
    for key in allowed:
        s, t, a, b = key
        if crew[s] == a and crew[t] == b:
            out.append((index[("i", s, t, a, b)], 1.0))
    return out


def _allowed_interactions(crows, roles, ref):
    """Pairs (s, t, a, b) whose two off-diagonal cells (a at s, b at t) and (b at s, a at t) are both measured."""
    seen = set()
    for r in crows:
        crew = r["crew"]
        for i, s in enumerate(roles):
            for t in roles[i + 1:]:
                a, b = crew[s], crew[t]
                if a != ref[s] and b != ref[t]:
                    seen.add((s, t, a, b))
    out = []
    for key in sorted(seen):
        s, t, a, b = key
        if a != b and (s, t, b, a) in seen:
            out.append(key)
    return out


def _value(beta, rows, mu, pinv):
    total = 0.0
    for pairs, y, w in rows:
        eta = 0.0
        for j, v in pairs:
            eta += beta[j] * v
        if eta <= EPS:
            p = EPS
        elif eta >= 1 - EPS:
            p = 1 - EPS
        else:
            p = eta
        total -= w * (y * math.log(p) + (1 - y) * math.log(1 - p))
    for j in range(len(beta)):
        d = beta[j] - mu[j]
        total += 0.5 * pinv[j] * d * d
    return total


def _eval(beta, rows, mu, pinv):
    """Objective, gradient and Hessian of the quasi-likelihood with the Gaussian priors."""
    p = len(beta)
    total = 0.0
    g = [0.0] * p
    h = [[0.0] * p for _ in range(p)]
    for pairs, y, w in rows:
        eta = 0.0
        for j, v in pairs:
            eta += beta[j] * v
        if eta <= EPS or eta >= 1 - EPS:
            pc = EPS if eta <= EPS else 1 - EPS
            total -= w * (y * math.log(pc) + (1 - y) * math.log(1 - pc))
            continue
        total -= w * (y * math.log(eta) + (1 - y) * math.log(1 - eta))
        d1 = w * (eta - y) / (eta * (1 - eta))
        d2 = w * (y / (eta * eta) + (1 - y) / ((1 - eta) * (1 - eta)))
        for j, vj in pairs:
            g[j] += d1 * vj
            hj = h[j]
            for k, vk in pairs:
                hj[k] += d2 * vj * vk
    for j in range(p):
        d = beta[j] - mu[j]
        total += 0.5 * pinv[j] * d * d
        g[j] += pinv[j] * d
        h[j][j] += pinv[j]
    return total, g, h


def _newton(beta, rows, mu, pinv, max_iter=100):
    beta = list(beta)
    f, g, h = _eval(beta, rows, mu, pinv)
    for _ in range(max_iter):
        d = _solve(h, [-x for x in g])
        slope = sum(gi * di for gi, di in zip(g, d))
        if slope >= 0:
            d = [-x for x in g]
            slope = -sum(x * x for x in g)
        step = 1.0
        while True:
            trial = [b + step * di for b, di in zip(beta, d)]
            ft = _value(trial, rows, mu, pinv)
            if ft <= f + 1e-4 * step * slope or step < 1e-10:
                break
            step *= 0.5
        beta = trial
        f, g, h = _eval(beta, rows, mu, pinv)
        if max(abs(x) for x in g) < 1e-8:
            break
    return beta


def _fit_class(crows, moms, roles, ref, mu_cand, tau_d, tau_i, use_inter, nllp):
    """Fit one class. Returns (index, beta, allowed, q0) with index mapping parameter keys to positions."""
    cands = set()
    for r in crows:
        for s in roles:
            if r["crew"][s] != ref[s]:
                cands.add(r["crew"][s])
    for m, _, _ in moms:
        cands.add(m)
    names = [("q0",)]
    for s in roles:
        for m in sorted(cands):
            if m != ref[s]:
                names.append(("d", s, m))
    allowed = _allowed_interactions(crows, roles, ref) if use_inter else []
    names += [("i",) + key for key in allowed]
    index = {key: j for j, key in enumerate(names)}
    mean_q = sum(r["q"] for r in crows) / len(crows) if crows else 0.5
    mu = [mean_q]
    pinv = [1.0]
    for key in names[1:]:
        if key[0] == "d":
            mu.append(mu_cand.get(key[2], 0.0))
            pinv.append(1.0 / (tau_d * tau_d))
        else:
            mu.append(0.0)
            pinv.append(1.0 / (tau_i * tau_i))
    rows = []
    for r in crows:
        rows.append((_pairs_for(r["crew"], roles, ref, index, allowed), r["q"], 1.0))
    for m, s_val, _ in moms:
        crew = {s: m for s in roles}
        rows.append((_pairs_for(crew, roles, ref, index, []), s_val, nllp))
    beta = _newton([mean_q] + [0.0] * (len(names) - 1), rows, mu, pinv)
    return index, beta, allowed


def _row_p(pairs, beta):
    eta = sum(beta[j] * v for j, v in pairs)
    return min(max(eta, 0.01), 0.99)


def _ridge_meta(feats, targets):
    keys = sorted(targets)
    xs = [feats[m] for m in keys]
    ys = [targets[m] for m in keys]
    if len(keys) == 0:
        return {}
    w = _ridge(xs, ys, META_RIDGE)
    return {m: sum(a * b for a, b in zip(feats[m], w)) for m in feats}


def fit_priors(rows, reference, meta=None, board=None, use_inter=False, prior_sd=TAU_DELTA,
               inter_sd=TAU_INTER, nllp=NLLP, irt=True, irt_scales=(0.3, IRT_SCALE_DEFAULT)):
    """Build the priors object (version 1) from parsed matrix rows, metadata and leaderboard rows."""
    roles = list(reference)
    ref = dict(reference)
    for r in rows:
        if set(r["crew"]) != set(roles):
            raise ToolError(f"task {r['task']}: crew roles {sorted(r['crew'])} differ from --reference {roles}")
    classes = sorted({r["cls"] for r in rows})
    cands = set()
    for r in rows:
        cands.update(r["crew"].values())
    feats = {}
    if meta:
        _, feats = meta_features(meta)
        cands.update(meta)
    moms = []
    for b in board or []:
        cands.add(b["cand"])
        moms.append(b)
    cands = sorted(cands)

    by_class = {c: [r for r in rows if r["cls"] == c] for c in classes}
    # pass 1: weakly regularised fit, no metadata prior, gives the regression targets
    pass1 = {}
    for c in classes:
        cm = [(b["cand"], b["score"], b["cls"]) for b in moms if b["cls"] == c]
        index, beta, _ = _fit_class(by_class[c], cm, roles, ref, {}, 1.0, 1.0, False, nllp)
        pass1[c] = (index, beta)
    targets = {}
    weights = {}
    for c in classes:
        index, beta = pass1[c]
        counts = _role_counts(by_class[c], roles, ref)
        for s in roles:
            for m in cands:
                key = ("d", s, m)
                if key in index and counts.get((s, m), 0) > 0 and m in feats:
                    n = counts[(s, m)]
                    targets[m] = targets.get(m, 0.0) + n * beta[index[key]]
                    weights[m] = weights.get(m, 0.0) + n
    targets = {m: targets[m] / weights[m] for m in targets if weights.get(m, 0) > 0}
    mu_cand = _ridge_meta(feats, targets) if (feats and len(targets) >= 2) else {}

    # pass 2: prior centred on the metadata prediction
    fits = {}
    for c in classes:
        cm = [(b["cand"], b["score"], b["cls"]) for b in moms if b["cls"] == c]
        index, beta, allowed = _fit_class(by_class[c], cm, roles, ref, mu_cand, prior_sd, inter_sd,
                                          use_inter, nllp)
        fits[c] = (index, beta, allowed)

    baseline = {}
    cells = []
    interactions = []
    irt_out = {}
    for c in classes:
        index, beta, allowed = fits[c]
        q0 = min(max(beta[0], 0.0), 1.0)
        baseline[c] = round(q0, 6)
        crows = by_class[c]
        counts = {}
        info_sum = {}
        task_sets = {}
        for r in crows:
            pairs = _pairs_for(r["crew"], roles, ref, index, allowed)
            p = _row_p(pairs, beta)
            for s in roles:
                key = (s, r["crew"][s])
                task_sets.setdefault(key, set()).add(r["task"])
                info_sum[key] = info_sum.get(key, 0.0) + p * (1 - p)
                counts.setdefault(key, 0)
                counts[key] += 1
        for s in roles:
            for m in cands:
                if m == ref[s]:
                    delta = 0.0
                elif ("d", s, m) in index:
                    delta = beta[index[("d", s, m)]]
                else:
                    delta = mu_cand.get(m, 0.0)
                n = len(task_sets.get((s, m), ()))
                rows_n = counts.get((s, m), 0)
                info = info_sum.get((s, m), 0.0) / rows_n if rows_n else 0.0
                cells.append({"class": c, "role": s, "candidate": m, "delta": round(delta, 6),
                              "n": n, "info": round(info, 6)})
        for key in allowed:
            s, t, a, b = key
            interactions.append({"class": c, "roles": [s, t], "a": a, "b": b,
                                 "value": round(beta[index[("i",) + key]], 6)})
        if irt:
            irt_out[c] = _irt_for_class(c, crows, roles, ref, cands, q0, cells, irt_scales)
        else:
            irt_out[c] = {}
    cells.sort(key=lambda x: (x["class"], roles.index(x["role"]), x["candidate"]))
    return {"version": PRIOR_FILE_VERSION, "baseline": baseline, "cells": cells,
            "interactions": interactions, "irt": irt_out}


def _role_counts(crows, roles, ref):
    counts = {}
    for r in crows:
        for s in roles:
            counts[(s, r["crew"][s])] = counts.get((s, r["crew"][s]), 0) + 1
    return counts


# ---------------------------------------------------------------- level 2: IRT with guessing

def _uniform_obs(crows, roles):
    obs = []
    for r in crows:
        vals = set(r["crew"].values())
        if len(vals) == 1:
            obs.append((r["task"], next(iter(vals)), r["q"]))
    return obs


def _irt_for_class(c, crows, roles, ref, cands, q0, cells, scales):
    """Per-candidate logit l and discrimination kappa for one class (the sequential layer's prior)."""
    delta_sum = {m: 0.0 for m in cands}
    for cell in cells:
        if cell["class"] == c:
            delta_sum[cell["candidate"]] += cell["delta"]
    ell0 = {m: _logit(q0 + delta_sum[m]) for m in cands}
    obs = _uniform_obs(crows, roles)
    out = {m: {"l": round(ell0[m], 6), "kappa": 1.0} for m in cands}
    if not obs:
        return out
    if not HAVE_IRT:
        means = {}
        for _, m, y in obs:
            means.setdefault(m, []).append(y)
        for m, ys in means.items():
            out[m] = {"l": round(_logit(sum(ys) / len(ys)), 6), "kappa": 1.0}
        return out
    fitted = fit_irt(obs, cands, ell0, scales)
    for m, (ell, kappa) in fitted.items():
        out[m] = {"l": round(float(ell), 6), "kappa": round(float(kappa), 6)}
    return out


def _irt_data(obs, cands, ell0, scale, z, logw, binary):
    tasks = sorted({t for t, _, _ in obs}, key=str)
    tindex = {t: i for i, t in enumerate(tasks)}
    cindex = {m: i for i, m in enumerate(cands)}
    ot = np.array([tindex[t] for t, _, _ in obs], dtype=int)
    om = np.array([cindex[m] for _, m, _ in obs], dtype=int)
    oy = np.array([y for _, _, y in obs], dtype=float)
    return {"ot": ot, "om": om, "oy": oy, "nt": len(tasks), "M": len(cands), "binary": binary,
            "z": z, "logw": logw, "ell0": np.array([ell0[m] for m in cands], dtype=float), "scale": scale}


def _irt_value_grad(theta, d, prior):
    ot, om, oy, nt, m_count, binary = d["ot"], d["om"], d["oy"], d["nt"], d["M"], d["binary"]
    z, logw = d["z"], d["logw"]
    ell = theta[:m_count]
    logk = theta[m_count:2 * m_count]
    k = np.exp(logk)
    if binary:
        gam = theta[2 * m_count]
        sg = expit(gam)
        g = 0.5 * sg
    else:
        g = 0.0
    s = expit(ell[om][:, None] - (k[om])[:, None] * z[None, :])
    p = np.clip(g + (1 - g) * s, 1e-12, 1 - 1e-12)
    y = oy[:, None]
    ll_terms = y * np.log(p) + (1 - y) * np.log1p(-p)
    big = np.zeros((nt, z.size))
    np.add.at(big, ot, ll_terms)
    a_mat = big + logw[None, :]
    lt = logsumexp(a_mat, axis=1)
    val = float(lt.sum())
    grad = np.zeros_like(theta)
    if prior:
        ell0, scale = d["ell0"], d["scale"]
        val += -0.5 * float(np.sum((ell - ell0) ** 2)) / scale ** 2
        val += -0.5 * float(np.sum(logk ** 2)) / IRT_LOGK_SD ** 2
        grad[:m_count] -= (ell - ell0) / scale ** 2
        grad[m_count:2 * m_count] -= logk / IRT_LOGK_SD ** 2
        if binary:
            val += -0.5 * (gam - IRT_GAMMA_MEAN) ** 2 / IRT_GAMMA_SD ** 2
            grad[2 * m_count] -= (gam - IRT_GAMMA_MEAN) / IRT_GAMMA_SD ** 2
    r_mat = np.exp(a_mat - lt[:, None])
    dldp = (y - p) / (p * (1 - p))
    w_mat = r_mat[ot] * (dldp * (1 - g) * s * (1 - s))
    grad[:m_count] += np.bincount(om, weights=w_mat.sum(axis=1), minlength=m_count)
    grad[m_count:2 * m_count] += np.bincount(
        om, weights=(w_mat * (-z[None, :]) * k[om][:, None]).sum(axis=1), minlength=m_count)
    if binary:
        wg = r_mat[ot] * (dldp * (1 - s))
        grad[2 * m_count] += float(wg.sum()) * 0.5 * sg * (1 - sg)
    return val, grad


def _irt_start(d):
    m_count = d["M"]
    x0 = [float(v) for v in d["ell0"]] + [0.0] * m_count
    if d["binary"]:
        x0.append(IRT_GAMMA_MEAN)
    return np.array(x0)


def _irt_fit_once(d):
    res = minimize(_neg_pair, _irt_start(d), args=(d,), jac=True,
                   method="L-BFGS-B", options={"maxiter": 300})
    return res.x


def _neg_pair(th, d):
    val, grad = _irt_value_grad(th, d, True)
    return -val, -grad


def _split_tasks(obs):
    val_tasks = {t for t, _, _ in obs if fnv1a32(str(t).encode("utf-8")) % 5 == 0}
    train = [o for o in obs if o[0] not in val_tasks]
    val = [o for o in obs if o[0] in val_tasks]
    return train, val


def fit_irt(obs, cands, ell0, scales):
    """Fit (l, kappa) per candidate by marginal likelihood over the task difficulties (eq. 9).

    The prior scale of l is picked from `scales` by the marginal likelihood on a held-out fifth of the
    tasks; without a validation split the default scale is used.
    Returns {candidate: (l, kappa)} for the candidates with uniform-crew rows.
    """
    z, w = hermegauss(G_NODES)
    logw = np.log(w / w.sum())
    binary = all(y in (0.0, 1.0) for _, _, y in obs)
    train, val = _split_tasks(obs)
    chosen = IRT_SCALE_DEFAULT if IRT_SCALE_DEFAULT in scales else scales[-1]
    if len(scales) > 1 and train and val:
        best = None
        for scale in scales:
            dtr = _irt_data(train, cands, ell0, scale, z, logw, binary)
            theta = _irt_fit_once(dtr)
            dva = _irt_data(val, cands, ell0, scale, z, logw, binary)
            score, _ = _irt_value_grad(theta, dva, False)
            if best is None or score > best[0]:
                best = (score, scale)
        chosen = best[1]
    d = _irt_data(obs, cands, ell0, chosen, z, logw, binary)
    theta = _irt_fit_once(d)
    m_count = len(cands)
    seen = {m for _, m, _ in obs}
    out = {}
    for j, m in enumerate(cands):
        if m in seen:
            out[m] = (float(theta[j]), float(math.exp(theta[m_count + j])))
    return out


# ---------------------------------------------------------------- validation of the priors file

def validate_priors(obj):
    """Return a list of problems with a priors object (empty when it is valid)."""
    errs = []
    if not isinstance(obj, dict):
        return ["priors file is not an object"]
    if obj.get("version") != PRIOR_FILE_VERSION:
        errs.append(f"version must be {PRIOR_FILE_VERSION}")
    base = obj.get("baseline")
    if not isinstance(base, dict) or not base:
        errs.append("baseline must be a non-empty object")
        base = {}
    for c, q in base.items():
        if not _is_num(q) or not (0 <= q <= 1):
            errs.append(f"baseline[{c}] must be in [0, 1]")
    seen = set()
    for i, cell in enumerate(obj.get("cells", [])):
        if not isinstance(cell, dict):
            errs.append(f"cells[{i}] is not an object")
            continue
        key = (cell.get("class"), cell.get("role"), cell.get("candidate"))
        if key in seen:
            errs.append(f"cells[{i}] repeats {key}")
        seen.add(key)
        if cell.get("class") not in base:
            errs.append(f"cells[{i}] class {cell.get('class')!r} has no baseline")
        if not isinstance(cell.get("role"), str) or not isinstance(cell.get("candidate"), str):
            errs.append(f"cells[{i}] needs string role and candidate")
        if not _is_num(cell.get("delta")) or not math.isfinite(cell["delta"]):
            errs.append(f"cells[{i}] delta must be finite")
        if not isinstance(cell.get("n"), int) or cell["n"] < 0:
            errs.append(f"cells[{i}] n must be a count")
        if not _is_num(cell.get("info")) or not (0 <= cell["info"] <= 0.25):
            errs.append(f"cells[{i}] info must be in [0, 0.25]")
    for i, it in enumerate(obj.get("interactions", [])):
        if not isinstance(it, dict) or it.get("class") not in base:
            errs.append(f"interactions[{i}] class has no baseline")
            continue
        roles = it.get("roles")
        if not isinstance(roles, list) or len(roles) != 2 or roles[0] == roles[1]:
            errs.append(f"interactions[{i}] needs two distinct roles")
        if not _is_num(it.get("value")) or not math.isfinite(it["value"]):
            errs.append(f"interactions[{i}] value must be finite")
    irt = obj.get("irt", {})
    if not isinstance(irt, dict):
        errs.append("irt must be an object")
        irt = {}
    for c, per in irt.items():
        if c not in base:
            errs.append(f"irt[{c}] has no baseline")
            continue
        for m, v in per.items():
            if not isinstance(v, dict) or not _is_num(v.get("l")) or not _is_num(v.get("kappa")) or v["kappa"] <= 0:
                errs.append(f"irt[{c}][{m}] needs numeric l and kappa > 0")
    return errs


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


# ---------------------------------------------------------------- frontier (Prop. 1, Def. 6)

def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def class_frontier(priors, pool, cls):
    """Class frontier under role additivity: the upper concave envelope of the crew points (Prop. 1).

    Returns None when the pool has no candidate with a prior in every role.
    """
    profiles = pool["profiles"].get(cls)
    if not profiles:
        raise ToolError(f"pool has no profile for class {cls!r}")
    roles = list(profiles)
    cells = {(x["role"], x["candidate"]): x["delta"] for x in priors["cells"] if x["class"] == cls}
    q0 = priors["baseline"][cls]
    price = {c["id"]: (float(c["input_price"]), float(c["output_price"])) for c in pool["candidates"]}
    cands = sorted(m for m in price if all((s, m) in cells for s in roles))
    if not cands:
        return None
    cost = {}
    delta = {}
    for s in roles:
        pr = profiles[s]
        for m in cands:
            pin, pout = price[m]
            cost[(s, m)] = pr["calls"] * (pr["input_tokens"] * pin + pr["output_tokens"] * pout)
            delta[(s, m)] = cells[(s, m)]

    lams = {0.0}
    for s in roles:
        for i in cands:
            for j in cands:
                if cost[(s, i)] != cost[(s, j)]:
                    lam = (delta[(s, i)] - delta[(s, j)]) / (cost[(s, i)] - cost[(s, j)])
                    if lam > 0:
                        lams.add(lam)
    lams = sorted(lams)
    grid = list(lams)
    grid += [(a + b) / 2 for a, b in zip(lams, lams[1:])]
    grid.append(lams[-1] * 2 + 1.0)

    points = {}
    for lam in grid:
        crew = {}
        for s in roles:
            crew[s] = max(cands, key=lambda m: (round(delta[(s, m)] - lam * cost[(s, m)], 12),
                                                -round(cost[(s, m)], 12)))
        total_c = sum(cost[(s, crew[s])] for s in roles)
        total_q = q0 + sum(delta[(s, crew[s])] for s in roles)
        points.setdefault((round(total_c, 12), round(total_q, 12)), crew)
    pts = []
    for p in sorted(points, key=lambda p: (p[0], -p[1])):
        if not pts or p[0] != pts[-1][0]:
            pts.append(p)
    hull = []
    for p in pts:
        while len(hull) >= 2 and _cross(hull[-2], hull[-1], p) >= 0:
            hull.pop()
        hull.append(p)
    best = max(range(len(hull)), key=lambda i: (hull[i][1], -i))
    hull = hull[:best + 1]
    vertices = [{"cost": c, "quality": q, "crew": points[(c, q)]} for c, q in hull]

    singles = {m: (sum(cost[(s, m)] for s in roles), q0 + sum(delta[(s, m)] for s in roles)) for m in cands}
    b_lo = min(v[0] for v in singles.values())
    b_hi = max(v[0] for v in singles.values())
    result = {"class": cls, "roles": roles, "baseline": q0,
              "range": {"lo": b_lo, "hi": b_hi}, "frontier": vertices, "knee": None}
    if b_hi <= b_lo:
        return result
    f0 = _frontier_at(vertices, b_lo)
    f1 = _frontier_at(vertices, b_hi)
    u0, u1 = math.log(b_lo), math.log(b_hi)
    slope = (f1 - f0) / (u1 - u0)
    cand_b = sorted({b_lo, b_hi} | {v["cost"] for v in vertices if b_lo <= v["cost"] <= b_hi})
    best_b = None
    best_g = None
    for b in cand_b:
        u = math.log(b)
        g = _frontier_at(vertices, b) - f0 - (f1 - f0) * (u - u0) / (u1 - u0)
        if best_g is None or g > best_g + 1e-12:
            best_b, best_g = b, g
    lam = slope / best_b
    lower = [v for v in vertices if v["cost"] <= best_b]
    upper = [v for v in vertices if v["cost"] >= best_b]
    result["knee"] = {"cost": best_b, "quality": _frontier_at(vertices, best_b), "lambda": lam,
                      "crew_below": lower[-1]["crew"] if lower else None,
                      "crew_above": upper[0]["crew"] if upper else None}
    return result


def _frontier_at(vertices, b):
    if b < vertices[0]["cost"]:
        return 0.0
    if b >= vertices[-1]["cost"]:
        return vertices[-1]["quality"]
    for a, c in zip(vertices, vertices[1:]):
        if a["cost"] <= b <= c["cost"]:
            if c["cost"] == a["cost"]:
                return max(a["quality"], c["quality"])
            t = (b - a["cost"]) / (c["cost"] - a["cost"])
            return a["quality"] + t * (c["quality"] - a["quality"])
    return vertices[-1]["quality"]


# ---------------------------------------------------------------- classifier (stdlib)
#
# Matches src/taskclass.tov (L151): ASCII word tokens, presence features, FNV-1a 32 buckets of 18 bits,
# named features, int8 weights, temperature and floor. The file layout is docs/crew-routing.md
# "Classifier file".

BUCKETS = 262144
BUCKET_MASK = BUCKETS - 1
MAX_FILE_BYTES = 1048576
CLASSIFIER_MAX_NONZERO = 2000
SKIP_BEFORE = (32, 9, 45, 42, 35, 62)            # space, tab, - * # >
SENTENCE_END = (46, 33, 63, 10, 13)              # . ! ? line feed, carriage return
VERBS = ("add", "support", "implement", "refactor", "rename", "document", "fix", "crash", "error", "regression")
NAMED_PREFIXES = ("label:", "has:", "verb:")


def _is_alnum(c):
    return 48 <= c <= 57 or 65 <= c <= 90 or 97 <= c <= 122


def _sentence_start(b, pos):
    j = pos - 1
    while j >= 0 and b[j] in SKIP_BEFORE:
        j -= 1
    if j < 0:
        return True
    return b[j] in SENTENCE_END


def _words(text):
    """(lowered word, starts a sentence) for each maximal run of ASCII letters and digits."""
    b = text.encode("utf-8")
    out = []
    start = -1
    for i, c in enumerate(b):
        if _is_alnum(c):
            if start < 0:
                start = i
        elif start >= 0:
            out.append((b[start:i].decode("ascii").lower(), _sentence_start(b, start)))
            start = -1
    if start >= 0:
        out.append((b[start:].decode("ascii").lower(), _sentence_start(b, start)))
    return out


def bucket_of(feature):
    """Hash bucket of a feature string: FNV-1a 32 over its UTF-8 bytes, masked to 18 bits."""
    return fnv1a32(feature.encode("utf-8")) & BUCKET_MASK


def _frame_like(t):
    if not t.endswith(")"):
        return False
    op = t.find("(")
    if op < 0:
        return False
    inner = t[op + 1:-1]
    for i in range(len(inner) - 1):
        if inner[i] == ":" and "0" <= inner[i + 1] <= "9":
            return True
    return False


def _has_stacktrace(text):
    for line in text.split("\n"):
        t = line.strip()
        if t.startswith("Traceback (most recent call last)"):
            return True
        if t.startswith('File "') and '", line ' in t:
            return True
        if t.startswith("at ") and _frame_like(t):
            return True
        if t.startswith("Caused by: ") or t.startswith("Exception in thread"):
            return True
        if t.startswith("panic: ") or (t.startswith("goroutine ") and " [running]:" in t):
            return True
        if t.startswith("thread '") and "' panicked at" in t:
            return True
    return False


def hashed_features(text):
    """Distinct buckets of the text's unigrams and bigrams (presence)."""
    ws = [w for w, _ in _words(text)]
    out = set()
    for i, w in enumerate(ws):
        out.add(bucket_of(w))
        if i + 1 < len(ws):
            out.add(bucket_of(w + " " + ws[i + 1]))
    return out


def named_features(text, labels):
    """label:<name>, has:stacktrace, has:code and verb:<v> features of a task (distinct, in order)."""
    out = []
    for raw in labels:
        lab = raw.strip().lower()
        if lab and "label:" + lab not in out:
            out.append("label:" + lab)
    if _has_stacktrace(text):
        out.append("has:stacktrace")
    if text.count("```") >= 2:
        out.append("has:code")
    for w, initial in _words(text):
        if initial and w in VERBS and "verb:" + w not in out:
            out.append("verb:" + w)
    return out


def _parse_labels(text):
    return [x.strip().lower() for x in text.split(",") if x.strip()]


def read_training(path):
    rows = []
    for i, rec in enumerate(_read_csv(path, ["text", "labels", "class"]), start=2):
        if not rec["class"]:
            raise ToolError(f"{path}:{i}: empty class")
        rows.append((rec["text"], _parse_labels(rec["labels"]), rec["class"]))
    if not rows:
        raise ToolError(f"{path}: no rows")
    return rows


def doc_features(text, labels):
    """Feature keys of one task: int buckets (hashed) and str names (named), each with value 1."""
    feats = {b: 1.0 for b in hashed_features(text)}
    for n in named_features(text, labels):
        feats[n] = 1.0
    return feats


def _softmax(scores):
    top = max(scores)
    e = [math.exp(s - top) for s in scores]
    t = sum(e)
    return [x / t for x in e]


def _train_sgd(docs, labels, k, epochs, lr, l1, l2, seed):
    w = [dict() for _ in range(k)]
    bias = [0.0] * k
    rng = random.Random(seed)
    order = list(range(len(docs)))
    for ep in range(epochs):
        rng.shuffle(order)
        eta = lr / (1.0 + ep)
        for i in order:
            x = docs[i]
            scores = [bias[c] + sum(w[c].get(j, 0.0) for j in x) for c in range(k)]
            p = _softmax(scores)
            for c in range(k):
                g = p[c] - (1.0 if labels[i] == c else 0.0)
                if abs(g) < 1e-12:
                    continue
                bias[c] -= eta * g
                wc = w[c]
                for j in x:
                    old = wc.get(j, 0.0)
                    wc[j] = old - eta * (g + l2 * old)
        shrink = eta * l1
        for c in range(k):
            wc = w[c]
            for j in list(wc):
                val = wc[j]
                if val > shrink:
                    wc[j] = val - shrink
                elif val < -shrink:
                    wc[j] = val + shrink
                else:
                    del wc[j]
    return w, bias


def _quantise(weights, max_nonzero):
    """Keep the largest max_nonzero weights of a class (hashed and named together) and quantise to int8."""
    out = {}
    for c, wc in weights.items():
        top = sorted(wc.items(), key=lambda kv: (-abs(kv[1]), str(kv[0])))[:max_nonzero]
        top = [(j, v) for j, v in top if v != 0.0]
        peak = max((abs(v) for _, v in top), default=0.0)
        scale = peak / 127.0 if peak > 0 else 1.0
        hashed, named = [], {}
        for j, v in top:
            q = max(-128, min(127, int(round(v / scale))))
            if q == 0:
                continue
            if isinstance(j, int):
                hashed.append([j, q])
            else:
                named[j] = q
        hashed.sort()
        out[c] = {"scale": scale, "weights": hashed, "named": named}
    return out


class _Scorer:
    """Scores with a classifier object in file form (the same arithmetic as src/taskclass.tov)."""

    def __init__(self, model):
        self.classes = model["classes"]
        self.temperature = model["temperature"]
        self.floor = model["floor"]
        self.prior = [model["prior"][c] for c in self.classes]
        self.per = []
        for c in self.classes:
            self.per.append((model["bias"][c], model["scale"][c],
                             {b: q for b, q in model["weights"].get(c, [])},
                             dict(model.get("named", {}).get(c, {}))))

    def posterior(self, feats):
        scores = []
        for bias, scale, hashed, named in self.per:
            s = bias
            for key in feats:
                q = hashed.get(key) if isinstance(key, int) else named.get(key)
                if q is not None:
                    s += scale * q
            scores.append(s)
        p = _softmax([s / self.temperature for s in scores])
        return [(1 - self.floor) * p[i] + self.floor * self.prior[i] for i in range(len(self.classes))]


def classify(model, text, labels=()):
    """Verdict for one task: posterior per class, top class, and the decision (uncertain_class when unsure)."""
    post = _Scorer(model).posterior(doc_features(text, list(labels)))
    best = max(range(len(post)), key=lambda i: post[i])
    top = model["classes"][best]
    decision = model["uncertain_class"] if post[best] < model["uncertain_below"] else top
    return {"decision": decision, "top": top, "posterior": dict(zip(model["classes"], post))}


def train_classifier(data, max_weights=CLASSIFIER_MAX_NONZERO, epochs=15, lr=0.2, l1=2e-4, l2=1e-6,
                     holdout=0.2, seed=1, uncertain_below=0.5, uncertain_class=None):
    """Train, prune to max_weights non-zero weights per class, quantise to int8 and calibrate on a held-out split."""
    classes = sorted({c for _, _, c in data})
    if len(classes) < 2:
        raise ToolError("the training data needs at least two classes")
    if uncertain_class is None:
        uncertain_class = "open-ended" if "open-ended" in classes else classes[-1]
    if uncertain_class not in classes:
        raise ToolError(f"uncertain class {uncertain_class!r} is not a class of the data")
    cindex = {c: i for i, c in enumerate(classes)}
    split = [holdout > 0 and fnv1a32(str(i).encode("utf-8")) % 10000 < holdout * 10000
             for i in range(len(data))]
    train = [i for i in range(len(data)) if not split[i]]
    if not train:
        raise ToolError("no training rows after the holdout split")
    docs = [doc_features(data[i][0], data[i][1]) for i in train]
    labels = [cindex[data[i][2]] for i in train]
    weights, bias = _train_sgd(docs, labels, len(classes), epochs, lr, l1, l2, seed)
    counts = {c: 0 for c in classes}
    for _, _, c in data:
        counts[c] += 1
    prior = {c: counts[c] / len(data) for c in classes}
    quant = _quantise({classes[i]: weights[i] for i in range(len(classes))}, max_weights)
    model = {"version": CLASSIFIER_VERSION, "buckets": BUCKETS, "hash": "fnv1a32", "classes": classes,
             "prior": {c: round(prior[c], 6) for c in classes},
             "temperature": 1.0, "floor": 0.01, "uncertain_below": uncertain_below,
             "uncertain_class": uncertain_class,
             "bias": {classes[i]: round(bias[i], 6) for i in range(len(classes))},
             "scale": {c: quant[c]["scale"] for c in classes},
             "weights": {c: quant[c]["weights"] for c in classes},
             "named": {c: quant[c]["named"] for c in classes}}
    held = [i for i in range(len(data)) if split[i]]
    if held:
        scored = [(cindex[data[i][2]], doc_features(data[i][0], data[i][1])) for i in held]
        best = None
        for t in [0.1 * (1.1 ** j) for j in range(50)]:
            for eps in (0.0, 0.01, 0.02, 0.05, 0.1):
                model["temperature"], model["floor"] = t, eps
                scorer = _Scorer(model)
                nll = 0.0
                for y, feats in scored:
                    nll -= math.log(max(scorer.posterior(feats)[y], 1e-12))
                if best is None or nll < best[0]:
                    best = (nll, t, eps)
        model["temperature"], model["floor"] = round(best[1], 6), best[2]
    return model


def validate_classifier(obj, size=None):
    errs = []
    if size is not None and size > MAX_FILE_BYTES:
        errs.append(f"file is {size} bytes, over the {MAX_FILE_BYTES} byte limit")
    if not isinstance(obj, dict):
        return errs + ["classifier file is not an object"]
    if obj.get("version") != CLASSIFIER_VERSION:
        errs.append(f"version must be {CLASSIFIER_VERSION}")
    if obj.get("buckets") != BUCKETS:
        errs.append(f"buckets must be {BUCKETS}")
    if obj.get("hash") != "fnv1a32":
        errs.append("hash must be fnv1a32")
    classes = obj.get("classes")
    if not isinstance(classes, list) or len(classes) < 2 or len(set(classes)) != len(classes) or not all(
            isinstance(c, str) and c for c in classes):
        return errs + ["classes must be at least two distinct non-empty names"]
    prior = obj.get("prior")
    if not isinstance(prior, dict) or set(prior) != set(classes):
        errs.append("prior must have one entry per class")
    elif any(not _is_num(prior[c]) or not (0 <= prior[c] <= 1) for c in classes):
        errs.append("prior values must be from 0 to 1")
    elif abs(sum(prior.values()) - 1.0) > 1e-3:
        errs.append("prior must sum to 1")
    t = obj.get("temperature")
    if not _is_num(t) or t <= 0:
        errs.append("temperature must be above 0")
    f = obj.get("floor")
    if not _is_num(f) or not (0 <= f < 1):
        errs.append("floor must be at least 0 and below 1")
    ub = obj.get("uncertain_below")
    if not _is_num(ub) or not (0 <= ub <= 1):
        errs.append("uncertain_below must be from 0 to 1")
    if obj.get("uncertain_class") not in classes:
        errs.append("uncertain_class is not one of the classes")
    bias = obj.get("bias")
    scale = obj.get("scale")
    if not isinstance(bias, dict) or set(bias) != set(classes) or not all(_is_num(bias[c]) for c in classes):
        errs.append("bias must have a number per class")
    if not isinstance(scale, dict) or set(scale) != set(classes) or not all(
            _is_num(scale[c]) and scale[c] > 0 for c in classes):
        errs.append("scale must have a positive number per class")
    weights = obj.get("weights", {})
    named = obj.get("named", {})
    if not isinstance(weights, dict) or not set(weights) <= set(classes):
        errs.append("weights must be keyed by class names")
        weights = {}
    if not isinstance(named, dict) or not set(named) <= set(classes):
        errs.append("named must be keyed by class names")
        named = {}
    for c in classes:
        pairs = weights.get(c, [])
        nm = named.get(c, {})
        if not isinstance(pairs, list) or not isinstance(nm, dict):
            errs.append(f"weights.{c} and named.{c} have the wrong shape")
            continue
        seen = set()
        for pair in pairs:
            if not (isinstance(pair, list) and len(pair) == 2):
                errs.append(f"weights.{c} entries are [bucket, weight] pairs")
                break
            b, q = pair
            if not isinstance(b, int) or isinstance(b, bool) or not (0 <= b < BUCKETS):
                errs.append(f"weights.{c} bucket {b!r} is out of range")
            elif b in seen:
                errs.append(f"weights.{c} bucket {b} is repeated")
            seen.add(b)
            if not isinstance(q, int) or isinstance(q, bool) or not (-128 <= q <= 127) or q == 0:
                errs.append(f"weights.{c} weight {q!r} must be a non-zero int8")
        for key, q in nm.items():
            if not key.startswith(NAMED_PREFIXES):
                errs.append(f"named.{c}.{key} must start with label:, has: or verb:")
            if not isinstance(q, int) or isinstance(q, bool) or not (-128 <= q <= 127) or q == 0:
                errs.append(f"named.{c}.{key} must be a non-zero int8")
        if len(pairs) + len(nm) > CLASSIFIER_MAX_NONZERO:
            errs.append(f"class {c} has more than {CLASSIFIER_MAX_NONZERO} non-zero weights")
    return errs


def load_classifier(path):
    with open(path, "rb") as f:
        raw = f.read()
    if len(raw) > MAX_FILE_BYTES:
        raise ToolError(f"{path}: size {len(raw)} bytes is over the {MAX_FILE_BYTES} byte limit")
    obj = json.loads(raw.decode("utf-8"))
    errs = validate_classifier(obj, len(raw))
    if errs:
        raise ToolError(f"{path}: " + "; ".join(errs))
    return obj


# ---------------------------------------------------------------- CLI

def _write(obj, out):
    text = json.dumps(obj, indent=2, sort_keys=False) + "\n"
    if out == "-":
        sys.stdout.write(text)
    else:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)


def _cmd_fit(args):
    rows = read_matrix(args.matrix)
    reference = parse_reference(args.reference)
    meta = read_metadata(args.metadata) if args.metadata else None
    board = read_leaderboard(args.leaderboard, rows) if args.leaderboard else None
    scales = tuple(float(x) for x in args.irt_scales.split(",") if x.strip())
    priors = fit_priors(rows, reference, meta=meta, board=board, use_inter=args.interactions,
                        prior_sd=args.prior_sd, inter_sd=args.interaction_sd, nllp=args.nllp,
                        irt=not args.no_irt and bool(scales), irt_scales=scales or (IRT_SCALE_DEFAULT,))
    errs = validate_priors(priors)
    if errs:
        raise ToolError("fit produced an invalid priors file: " + "; ".join(errs))
    _write(priors, args.out)
    classes = sorted(priors["baseline"])
    costs = {c: [r["cost"] for r in rows if r["cls"] == c] for c in classes}
    sys.stderr.write(
        f"crew_priors: {len(rows)} rows, {len(classes)} classes, "
        f"{len({c['candidate'] for c in priors['cells']})} candidates, "
        f"{len(board or [])} leaderboard moments, interactions {len(priors['interactions'])}, "
        f"IRT {'numpy' if HAVE_IRT and not args.no_irt else 'logit fallback'}\n")
    for c in classes:
        sys.stderr.write(f"  {c}: baseline {priors['baseline'][c]}, mean cost ${sum(costs[c]) / len(costs[c]):.4f}\n")
    return 0


def _cmd_train(args):
    data = read_training(args.data)
    model = train_classifier(data, max_weights=args.max_weights, epochs=args.epochs,
                             lr=args.lr, l1=args.l1, l2=args.l2, holdout=args.holdout, seed=args.seed,
                             uncertain_below=args.uncertain_below, uncertain_class=args.uncertain_class)
    errs = validate_classifier(model)
    if errs:
        raise ToolError("training produced an invalid classifier file: " + "; ".join(errs))
    _write(model, args.out)
    sys.stderr.write(f"crew_priors: {len(data)} rows, classes {', '.join(model['classes'])}, "
                     f"temperature {model['temperature']}, floor {model['floor']}\n")
    return 0


def _cmd_frontier(args):
    with open(args.priors, encoding="utf-8") as f:
        priors = json.load(f)
    errs = validate_priors(priors)
    if errs:
        raise ToolError(f"{args.priors}: " + "; ".join(errs))
    with open(args.pool, encoding="utf-8") as f:
        pool = json.load(f)
    classes = args.classes or sorted(priors["baseline"])
    out = {}
    for c in classes:
        res = class_frontier(priors, pool, c)
        out[c] = res if res is not None else {"class": c, "error": "no candidate has a prior in every role"}
    _write(out, "-")
    return 0


def _cmd_validate(args):
    with open(args.path, encoding="utf-8") as f:
        obj = json.load(f)
    errs = validate_classifier(obj) if "weights" in obj else validate_priors(obj)
    if errs:
        sys.stdout.write("\n".join(errs) + "\n")
        return 1
    sys.stdout.write("ok\n")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Offline priors and classifier training for crew routing.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit-priors", help="fit the crew priors file")
    f.add_argument("--matrix", required=True, help="evaluation matrix CSV")
    f.add_argument("--reference", required=True, help="reference crew, role=candidate,...")
    f.add_argument("--metadata", help="candidate metadata CSV")
    f.add_argument("--leaderboard", help="leaderboard aggregates CSV")
    f.add_argument("--interactions", action="store_true", help="estimate pairwise interactions")
    f.add_argument("--prior-sd", type=float, default=TAU_DELTA)
    f.add_argument("--interaction-sd", type=float, default=TAU_INTER)
    f.add_argument("--nllp", type=float, default=NLLP, help="weight of each leaderboard moment")
    f.add_argument("--no-irt", action="store_true", help="skip the per-candidate IRT fit")
    f.add_argument("--irt-scales", default="0.3,1.2", help="candidate prior scales of the level-2 intercept")
    f.add_argument("--out", default="-")
    f.set_defaults(run=_cmd_fit)
    t = sub.add_parser("train-classifier", help="train the task classifier")
    t.add_argument("--data", required=True, help="training CSV: text, labels, class")
    t.add_argument("--out", default="-")
    t.add_argument("--max-weights", type=int, default=CLASSIFIER_MAX_NONZERO,
                   help="non-zero weights kept per class (hashed and named together)")
    t.add_argument("--uncertain-below", type=float, default=0.5)
    t.add_argument("--uncertain-class", default=None, help="default open-ended when it is a class")
    t.add_argument("--epochs", type=int, default=15)
    t.add_argument("--lr", type=float, default=0.2)
    t.add_argument("--l1", type=float, default=2e-4)
    t.add_argument("--l2", type=float, default=1e-6)
    t.add_argument("--holdout", type=float, default=0.2, help="fraction held out for calibration")
    t.add_argument("--seed", type=int, default=1)
    t.set_defaults(run=_cmd_train)
    fr = sub.add_parser("frontier", help="print class frontiers and knees for a priors file")
    fr.add_argument("--priors", required=True)
    fr.add_argument("--pool", required=True, help="pool JSON: candidates with prices, class profiles")
    fr.add_argument("--class", dest="classes", action="append")
    fr.set_defaults(run=_cmd_frontier)
    v = sub.add_parser("validate", help="check a priors or classifier file")
    v.add_argument("path")
    v.set_defaults(run=_cmd_validate)
    args = ap.parse_args(argv)
    try:
        return args.run(args)
    except (ToolError, OSError, ValueError, KeyError) as e:
        sys.stderr.write(f"crew_priors: {e}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())

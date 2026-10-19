# Crew routing (Pareto crewing)

Raiju-only feature, not a Bifrost parity item. It implements task-level multi-model routing as
described in S. K. Radha, *Pareto Crewing: Task-Level Multi-Model Routing of Agent Crews*
(AgentField AI, September 2026; `docs/design/model-pool/pareto-crewing.pdf` in Agent-Field/CodeAF).
Section, definition and proposition numbers below refer to that paper.

## The idea in one paragraph

An agent runs a task with several roles (seats), for example worker, planner and checker. A
call-level router picks one model per call and can only express the diagonal of the crew space
(the same model in every role). Pareto crewing picks the whole crew `m = (m1..mn)` once per task,
maximising `L = Q(m; c) - λ C(m; c)` for the task's class `c`, where `Q` is expected task quality
and `C` the route-aware cost of the whole trajectory. Under role additivity the search is a
per-role argmax (Prop. 7); bounded interactions are handled by coordinate ascent (Prop. 8). `λ`
is a single quality-per-dollar knob: the knee of the class frontier by default (Def. 6), or paced
against a per-task budget (eq. 12). After a verifier signal, a Pandora reservation index decides
whether to buy another attempt (Prop. 11), only for classes whose verifier accuracy is above the
threshold of Theorem 2.

## How a caller uses it

- Model name `crew/<pool>` on any chat-shaped route (`/v1/chat/completions`, `/v1/responses`,
  `/anthropic/v1/messages`, ...), with headers:
  - `x-raiju-task-id`: the task (required; calls of one task share the crew).
  - `x-raiju-crew-role`: the role making this call (required; one of the pool's roles).
  - `x-raiju-task-class` (optional): the class, else the classifier runs on the first call's
    text (plus `x-raiju-task-labels`, comma-separated, optional).
  - `x-raiju-task-attempt` (optional): the attempt number, set by the caller after `next`.
- The first call of a task fixes its crew (sticky for the task's lifetime, `task_ttl_seconds`,
  shared across workers and nodes through the cluster state, ns `crew.task`). Each call goes to
  the model and route of its role's seat. Answers carry `x-raiju-crew-candidate`,
  `x-raiju-crew-class` and `x-raiju-crew-attempt`.
- Agents that call providers themselves can ask for the crew instead:
  `POST /api/crews/{pool}/assign {task_id, text, labels?, class?}` returns the crew.
- Outcomes: `POST /api/crews/tasks/{task_id}/outcome {quality (0..1), verifier?: "pass"|"fail",
  attempt?}`. Cost is not sent: the gateway sums the task's own log rows.
- Escalation: `POST /api/crews/tasks/{task_id}/next` returns `{action: "accept"}` or
  `{action: "attempt", attempt, crew}` from the reservation index.

## Configuration (`crews` in config.json)

```json
"crews": {
  "task_ttl_seconds": 86400,
  "pools": [{
    "name": "codeaf",
    "roles": ["worker", "planner", "checker"],
    "classes": ["bug-fix", "open-ended", "other"],
    "uncertain_class": "open-ended",
    "candidates": [
      {"id": "dsv4", "model": "deepseek/deepseek-v4", "route": "api", "roles": ["worker", "planner", "checker"]},
      {"id": "opus-sub", "model": "anthropic/claude-opus-x", "route": "subscription", "subscription": "team-max"},
      {"id": "qwen-local", "model": "ollama/qwen3-coder", "route": "local"}
    ],
    "subscriptions": [{"name": "team-max", "window_hours": 5, "limit_usd": 50, "free_until_fraction": 0.2}],
    "profiles": {"bug-fix": {"worker": {"calls": 40, "input_tokens": 9000, "output_tokens": 700}}},
    "priors": "crew-priors.json",
    "classifier": "crew-classifier.json",
    "operating_point": {"mode": "knee"},
    "sequential": {"enabled": true, "max_attempts": 6, "per_candidate": 2,
                   "verifier_accuracy": {"bug-fix": 0.85}, "tau": 1.6, "omega": 1.5, "omega_base": 0.2},
    "credibility": {"prior_scale": 1.2}
  }]
}
```

- `route`: `api` (list price from the pricing table), `local` (zero marginal cost) or
  `subscription` (list price times `h(φ)`, `φ` the remaining quota fraction of the named
  subscription in its window; `h = 0` for `φ >= free_until_fraction`, rising linearly to 1 at
  `φ = 0`; Def. 4).
- `profiles`: per class and role, the expected calls and tokens per call (Def. 4). Missing
  entries are learned from the task log rows (running means per class and role).
- `operating_point.mode`: `knee` (Def. 6 on the class frontier), `lambda` (fixed `lambda`),
  or `budget` (`budget_usd` per task, step `step`, eq. 12, warm-started at the λ whose
  predicted policy cost equals the budget).

## Priors file (`crew-priors.json`)

```json
{"version": 1,
 "baseline": {"bug-fix": 0.42},
 "cells": [{"class": "bug-fix", "role": "checker", "candidate": "dsv4", "delta": 0.03, "n": 120, "info": 0.21}],
 "interactions": [{"class": "open-ended", "roles": ["planner", "checker"], "a": "dsv4", "b": "opus-sub", "value": 0.08}],
 "irt": {"bug-fix": {"dsv4": {"l": 0.4, "kappa": 1.0}}}}
```

`delta` is the role main effect `q_s(m; c)` against the pool's reference crew (Def. 8), `n` and
`info` the evidence count and mean information behind it (for the credibility blend, eq. 10).
`interactions` are pairwise `I_st` terms (optional). `irt` gives each candidate's logit and
discrimination per class for the sequential layer's within-task posterior (optional; derived
from `Q` when absent). Offline fitting (`scripts/crew_priors.py`) writes this file.

## Learning online

The install's own outcomes blend into the priors by credibility: per (class, role, candidate)
cell, `δ̂ = Z δ_own + (1 − Z) δ_prior`, `Z = n I / (n I + ς^-2)` (eq. 10, Prop. 9). A task outcome
is credited to every role of its crew relative to the reference crew. This is an approximation:
per-role credit from a whole-task outcome is the credit-assignment problem of Prop. 3. Crew-level
means per class are kept too and shown in the UI. State lives in the logs store folder and travels
on the cluster state (ns `crew.cells`).

## Modules

- `src/crewmath.tov`: the formulas (role cost, per-role argmax, coordinate ascent, frontier and
  knee, pacing step, credibility blend, reservation index, verifier threshold, grid posterior).
- `src/taskclass.tov`: the task classifier (hashed uni/bi-gram logistic regression, ≤ 2,000 int8
  weights per class, temperature and prior floor, label features; uncertain → `uncertain_class`).
- `src/crew.tov`: pools, task assignments, routing hook, outcomes, sequential layer, pacing state.
- `scripts/crew_priors.py`: offline fitting of the priors file from evaluation matrices.

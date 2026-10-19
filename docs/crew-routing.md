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
  shared across workers and nodes through the cluster state, ns `crew.task`, key `pool/task_id`).
  Each call goes to the model and route of its role's seat, served as if the caller had named that
  model (fallbacks, governance, budgets and logging are unchanged). Answers carry
  `x-raiju-crew-candidate`, `x-raiju-crew-class` and `x-raiju-crew-attempt`. The attempt is the
  caller's `x-raiju-task-attempt` (default 1), echoed back. Each attempt is a record on the assignment (its crew, and its
  outcome once reported); a call carrying an attempt with a record goes to that record's crew, one without goes to the
  assignment's current crew.
- The classifier reads the first user turn of the request (`messages`, or Responses `input`), or the
  whole body when neither is there. A task id is 1 to 200 letters, digits, `-`, `_`, `.` or `:`.
- A refusal is answered before any upstream call: 400 for a missing or bad `x-raiju-task-id`,
  `x-raiju-crew-role`, `x-raiju-task-class` or `x-raiju-task-attempt`, 404 for an unknown pool.
- Callers that send requests to providers themselves can ask for the crew instead:
  `POST /api/crews/{pool}/assign {task_id, text?, labels?, class?}` returns the assignment (the same
  store as routing; a task keeps the assignment it has until it expires).
- The task's detail: `GET /api/crews/tasks/{task_id}?pool=` returns the assignment, its attempts and
  its calls, with the cost summed from the task's log rows.
- `POST /api/crews/tasks/{task_id}/outcome?pool=` (L154) records an attempt's outcome: `{quality (0..1), verifier?:
  "pass"|"fail", attempt? (default: the task's current one), accuracy? (0.5..1)}`. The attempt's cost is the sum of
  its log rows (`crew_attempt`), not sent. The first outcome of an attempt counts: a repeat answers with the stored one
  (`recorded: false`) and changes nothing. The outcome is credited to the learned evidence (below). A pass, or no
  verifier, completes the task; a fail leaves it open for `next`. 404 for no task in force or an attempt with no
  record; 400 for a bad body.
- `POST /api/crews/tasks/{task_id}/next?pool=` (L154) is the sequential layer: `{action: "accept", reason}` or
  `{action: "attempt", attempt, crew, index}` (Pandora's rule on the within-task posterior, below). Accept completes
  the task. An attempt starts attempt k+1 on the crew it picks: the assignment's crew and attempt move to it, and
  calls carrying attempt k+1 go to it.

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
- As built (L153, L154): `priors` and `classifier` are a file path, resolved against the config file's
  folder, or an inline object. A problem with any field (an unknown role, class or candidate, a
  candidate whose model names no configured provider, a duplicate id, a subscription route with no
  subscription, a role no candidate admits, a priors or classifier file that does not check) stops
  the start, and the log names the field (`crews.pools[0].candidates[0].model: ...`). Defaults:
  `route` `api`; `free_until_fraction` 0.2; `credibility.prior_scale` 1.2; `operating_point.step` 0.5
  (eq. 12). `sequential` (L154): `enabled` (the layer is off when the block is missing or `enabled` is false),
  `max_attempts` 6, `per_candidate` 2 (attempts per crew), `verifier_accuracy` per class (used when no outcome gives
  an accuracy), `tau` 1.6, `omega` 1.5, `omega_base` 0.2 (the within-task model's spreads; defaults as in the example
  above). A candidate's `reasoning_effort` is set on its routed chat body (`reasoning_effort`, which the OpenAI, Anthropic,
  Gemini and Bedrock translators read) when the call is `/v1/chat/completions`. Without `classes` set to
  bug-fix, open-ended and other, a classifier is required.
- A class left out of `weights` or `named` has none (it scores on its bias alone; L154 made the loader accept this).
  An inline classifier object is written back as a file with empty lists for the classes it leaves out.
- Quotas and learned profiles come from the log rows the node holds (the shared day file of its
  workers; the in-memory window of the store). A subscription's spend is the cost of its candidates'
  rows in the window, so another node's spend is not counted unless its logs are shared.
- Log rows carry `task_id`, `crew_pool`, `crew_role`, `crew_class`, `crew_candidate` and
  `crew_attempt`. The learned profile of a class and role is calls per task (rows per task, averaged
  over the tasks) and tokens per call (averaged over the rows).
- The multiplier of a class is the knee's (`lambda_source` says so, `knee (at an end of the frontier)`
  when the knee is an end vertex), a fixed `lambda`, or `budget` (warm start, eq. 12).

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

## Learning online (L154)

The install's own outcomes blend into the priors by credibility (eq. 10, Prop. 9): per (class, role, candidate) cell,
`δ̂ = Z δ_own + (1 − Z) δ_prior`, `Z = n I / (n I + ς^-2)`, with `ς` the config's `credibility.prior_scale`, `n` the
credited outcomes and `I` their mean information `q(1 − q)`. The model uses `δ̂`.

- The reference crew (Def. 8) is the first candidate that admits each role. Its quality is the class baseline, learned
  the same way: the blend of the mean quality of the outcomes whose crew is the reference and the prior baseline.
- A scored attempt's crew gets its quality into the crew's counts (per class, the listing's crew-level means). Each role
  whose candidate is not the reference's gets the attempt's excess over the reference's learned quality as its cell's
  sample. This is the approximation the design names: a whole-task outcome is credited to every role of its crew (the
  credit-assignment problem of Prop. 3). The reference candidate's cells keep their prior.
- Evidence is per writer (a node, or a worker of a node): each writer keeps its counts under its own key `pool/writer`
  on ns `crew.cells` and writes them to `crew-state-<pool>-<writer>.json` in the logs store folder, which it reads back
  at its first use. The model sums the writers' entries, so nothing is counted twice or lost (each writer writes its
  whole counts, not an increment).
- The listing shows, per class, `learned` (the outcomes, the reference quality and each crew's mean) and the learned
  cells (`learned_cells`: prior, `delta_hat`, outcomes, mean excess).

## Pacing (L154)

In budget mode (`operating_point.mode: budget`), a completed task steps the multiplier by eq. 12:
`λ ← λ exp(step · clip(C / budget − 1, −1, 1))`, with `C` the task's cost (every attempt's log rows). A task is complete when
its last outcome has no failed verifier, when `next` accepts, or when its assignment expires; each task is paced once.
The base is the pool's live mean (below), or the class's warm start (eq. 12's `warmStart`) when no writer is live. The
writer's record `{lambda, cost, tasks, updated}` sits on ns `crew.lambda` under `pool/writer` and in its file. The
pool's multiplier is the mean of the records updated within the last ten minutes; the classes use it once any is live
(`lambda_source` says `budget (paced)`). The listing's `pacing` shows the mode, the multiplier and its source, the live
writers, the completed tasks and their mean cost. Outside budget mode the cost statistics are still kept, and no
multiplier is paced.

## The sequential layer (L154)

`next` decides on the task's attempts (paper section 3.4, Prop. 11):

1. Off when the pool's `sequential` block is missing or disabled; accept. Accept also when the task is complete, when
   the attempt budget (`max_attempts`) is used up, when no verifier accuracy is known (the latest outcome's `accuracy`,
   else `sequential.verifier_accuracy` for the class), or when the accuracy is at most 1/2.
2. Theorem 2's threshold: the cheapest frontier crew against the knee crew, with the discordance taken under
   independence (`p10 = p1 (1 − p2)`, `p01 = (1 − p1) p2`). An accuracy at or below it accepts with
   `verifier below threshold`. Without a knee, one vertex or a cost gap, the threshold is 1/2.
3. The boxes are the class frontier's crews and the crews already run. Each box's success probability is the model's
   quality, its logit and discrimination are `priors.irt` for its first role's candidate when present (else
   `logit(p)` and `κ = 1`), and its base model is its first role's candidate's model. The within-task posterior
   (`withinPosterior`) is conditioned on the attempts' pass and fail signals.
4. Pandora's rule (`sequentialStep`): the box with the largest reservation index opens, when its index exceeds the
   answer in hand (the best attempt's posterior) and the box has attempts left (`per_candidate` per crew). Otherwise
   accept with `no further attempt is worth its cost`.

## Classifier file (`crew-classifier.json`)

Read by `src/taskclass.tov` (`loadClassifier`). Without the file the built-in placeholder weights
are used (`defaultClassifier`, hand-set word lists and named weights until L152 trains the file).

```json
{"version": 1, "buckets": 262144, "hash": "fnv1a32",
 "classes": ["bug-fix", "open-ended", "other"],
 "prior": {"bug-fix": 0.4, "open-ended": 0.45, "other": 0.15},
 "temperature": 1.0, "floor": 0.05,
 "uncertain_below": 0.5, "uncertain_class": "open-ended",
 "bias": {"bug-fix": 0.0, "open-ended": 0.0, "other": 0.0},
 "scale": {"bug-fix": 0.1, "open-ended": 0.1, "other": 0.1},
 "weights": {"bug-fix": [[87512, 60]], "open-ended": [[70260, 60]]},
 "named": {"bug-fix": {"label:bug": 40, "has:stacktrace": 40, "verb:fix": 40}, "open-ended": {"verb:add": 40}}}
```

- Features: each distinct word unigram and bigram of the issue text (ASCII letters and digits,
  lowered; every other byte separates words; a bigram is two adjacent words joined by one space),
  hashed with FNV-1a 32 over the UTF-8 bytes and masked to 18 bits. Named features (not hashed):
  `label:<name>` for each task label, `has:stacktrace` (Python, JS, Java, Go or Rust traceback
  lines), `has:code` (a complete ``` fence pair), and `verb:<v>` for add, support, implement,
  refactor, rename, document, fix, crash, error or regression starting the title or a sentence.
  The trainer must use the same tokenisation and hash; test vectors are in `src/taskclass.tov`.
- Scores: `z_c = bias_c + scale_c * sum of the weights present`; `psi = (1 - floor) softmax(z / T)
  + floor * prior`. The decision is the argmax, or `uncertain_class` when the max psi is below
  `uncertain_below`.
- Limits: at most 1 MiB; at most 2,000 non-zero weights per class (hashed and named together);
  each int8 in -128..127 and not 0; buckets 0..262143; named keys start with `label:`, `has:` or
  `verb:`. `weights` and `named` may be left out for a class (it then scores on its bias alone).
  Unknown top-level fields are ignored. Errors name the field that failed.

## Modules

- `src/crewmath.tov`: the formulas (role cost, per-role argmax, coordinate ascent, frontier and
  knee, pacing step, credibility blend, reservation index, verifier threshold, grid posterior).
- `src/taskclass.tov`: the task classifier (hashed uni/bi-gram logistic regression, ≤ 2,000 int8
  weights per class, temperature and prior floor, label features; uncertain → `uncertain_class`).
- `src/crew.tov`: the config check and the pools (L153), the per-pool models (prices, quotas, learned
  profiles, class plans), task assignments on the cluster state, the routing hook (`crewRoute`, called
  from the engine's `serve`), the management routes (`crewsRoute`), the outcome, learning, pacing and
  `next` routes (L154, with `withReasoningEffort` for the routed body).
- `scripts/crew_priors.py`: offline fitting of the priors file from evaluation matrices.

## Limits (as built)

- `reasoning_effort` is applied on `/v1/chat/completions` only. The Responses and Messages routes take a `crew/<pool>`
  model but do not set the candidate's effort. A fallback target inherits the routed candidate's effort.
- Each writer's evidence and pacing record are read back by the same writer id (a node, or node/pid for a worker). A
  restarted worker has a new id: its earlier counts stay in the cluster state while a live copy holds them, and in its
  old file, but the new process does not reload them.
- Two writers can both pace the same expired task at the same moment (the sweep is per process); a task is paced once
  per writer that sees it complete.
- The Theorem 2 discordance is taken under independence, not measured. The within-task model's spreads (`tau`,
  `omega`, `omega_base`) are config values, not fitted.
- The credit to a cell is the whole-task excess (see Learning online); no per-role attribution.
- The sequential layer's box for a crew uses the first role's candidate for its IRT and base model.
- Budget pacing is multiplicative (eq. 12): a multiplier of 0 (the warm start of a frontier with one vertex, or a budget
  above the dearest crew) stays 0 whatever the cost. A pool whose frontier has one vertex does not pace.

// The crew routing screen (docs/crew-routing.md): per pool its candidates and subscriptions, the pacing, and per class
// the frontier with its knee and multiplier, the crew chosen for each role, the call profiles and the learned evidence;
// the learned role effects; and a task lookup. Callers who may write also assign tasks, record outcomes and ask for the
// next attempt. The server checks every request; the forms only follow the caller's permissions.
import { createMemo, createSignal, For, Show } from "solid-js"
import { api, ApiError } from "../api/client"
import { FrontierChart, type FrontierMark } from "../charts"
import { can } from "../perm"
import type { CrewClass, CrewLearnedCell, CrewPool, CrewTaskDetail } from "../api/types"
import { fmtInt, fmtMoney, fmtTime, splitList } from "../fmt"
import { FormError, Guard, Mono, notify, Table, Toolbar, useFormRun, useRun } from "../ui"

type Part = { role?: string; candidate?: string }

const dash = (v: unknown): string => (v === undefined || v === null || v === "" ? "—" : String(v))
// a number, or "—" when the listing has none (null)
const nz = (v: unknown, f: (n: number) => string): string => (typeof v === "number" && Number.isFinite(v) ? f(v) : "—")
const usd = (n: number): string => (n === 0 ? "$0" : n >= 1 ? "$" + n.toFixed(2) : "$" + n.toFixed(4))
const per1M = (n: number): string => "$" + (n * 1e6).toFixed(2)
const pct = (n: number): string => (n * 100).toFixed(1) + "%"
const delta = (n: number): string => (n >= 0 ? "+" : "") + n.toFixed(3)
const lam = (n: number): string => n.toFixed(4)

// role: candidate pairs, in the pool's role order
function crewText(crew: Part[] | undefined | null): string {
  return (crew ?? []).map((x) => (x.role ?? "") + ": " + (x.candidate ?? "")).join(", ")
}

// an id the screen's own element ids can use
const slug = (s: string): string => s.replace(/[^A-Za-z0-9_-]/g, "_")

function sourceText(s: { source?: string; path?: string } | undefined): string {
  if (!s) return "—"
  if (s.source === "file") return "file " + dash(s.path)
  return dash(s.source)
}

function kneeText(k: CrewClass["knee"]): string {
  if (!k) return "none (one vertex, or no cost gap)"
  return `${usd(k.budget ?? 0)} per task, ${pct(k.quality ?? 0)} quality, λ ${lam(k.lambda ?? 0)}${k.endpoint ? " (an end of the frontier)" : ""}`
}

function Pacing(props: { pool: CrewPool }) {
  const p = () => props.pool.pacing
  return (
    <dl class="kv">
      <dt>Mode</dt>
      <dd>{dash(p()?.mode)}</dd>
      <dt>Multiplier λ, paced</dt>
      <dd>
        {nz(p()?.lambda, lam)} <span class="hint">{dash(p()?.lambda_source)}</span>
      </dd>
      <dt>Live writers</dt>
      <dd>{fmtInt(p()?.live_writers ?? 0)}</dd>
      <dt>Tasks completed</dt>
      <dd>{fmtInt(p()?.tasks_completed ?? 0)}</dd>
      <dt>Mean task cost</dt>
      <dd>{nz(p()?.mean_task_cost, usd)}</dd>
      <dt>Budget per task</dt>
      <dd>{nz(p()?.budget_usd, usd)}</dd>
      <dt>Step</dt>
      <dd>{dash(p()?.step)}</dd>
    </dl>
  )
}

function ClassCard(props: { pool: CrewPool; klass: CrewClass }) {
  const c = () => props.klass
  const id = () => "cr-" + slug(props.pool.name) + "-" + slug(c().class ?? "")
  const marks = (): FrontierMark[] => (c().frontier ?? []).map((pt) => ({ label: crewText(pt.crew), cost: pt.cost ?? 0, quality: pt.quality ?? 0 }))
  const current = (): FrontierMark | undefined => {
    const cost = c().cost
    const quality = c().quality
    return typeof cost === "number" && typeof quality === "number" ? { label: crewText(c().crew), cost, quality } : undefined
  }
  const knee = (): FrontierMark | undefined => {
    const k = c().knee
    return k ? { label: "knee", cost: k.budget ?? 0, quality: k.quality ?? 0 } : undefined
  }
  return (
    <section class="crew-class" id={id() + "-class"} aria-labelledby={id() + "-h"}>
      <h3 id={id() + "-h"}>Class {c().class}</h3>
      <dl class="kv">
        <dt>Multiplier λ</dt>
        <dd>
          {nz(c().lambda, lam)} <span class="hint">{dash(c().lambda_source)}</span>
        </dd>
        <dt>Chosen crew, per task</dt>
        <dd>
          {nz(c().cost, usd)}, {nz(c().quality, pct)} quality
        </dd>
        <dt>Knee</dt>
        <dd>{kneeText(c().knee)}</dd>
      </dl>
      <h4>Chosen crew</h4>
      <dl class="kv">
        <For each={c().crew ?? []}>
          {(x) => (
            <>
              <dt>{x.role}</dt>
              <dd>
                <Mono>{x.candidate}</Mono>
              </dd>
            </>
          )}
        </For>
      </dl>
      <FrontierChart
        id={id()}
        title={"Frontier of " + (c().class ?? "")}
        desc="The crews on the class frontier, each at its expected cost per task and expected quality. The knee is the diamond; the crew at the current multiplier is ringed."
        frontier={marks()}
        knee={knee()}
        current={current()}
        costFormat={usd}
        qualityFormat={pct}
      />
      <details class="chart-table">
        <summary>Call profiles</summary>
        <Table cols={["Role", "Calls per task", "Input tokens per call", "Output tokens per call", "Source"]}>
          <For each={c().profiles ?? []}>
            {(pf) => (
              <tr>
                <td>{pf.role}</td>
                <td>{fmtInt(pf.calls ?? 0)}</td>
                <td>{fmtInt(pf.input_tokens ?? 0)}</td>
                <td>{fmtInt(pf.output_tokens ?? 0)}</td>
                <td>{dash(pf.source)}</td>
              </tr>
            )}
          </For>
        </Table>
      </details>
      <h4>Learned</h4>
      <dl class="kv">
        <dt>Outcomes credited</dt>
        <dd>{fmtInt(c().learned?.outcomes ?? 0)}</dd>
        <dt>Mean quality of the outcomes</dt>
        <dd>{nz(c().learned?.mean_quality, pct)}</dd>
        <dt>Reference crew's quality</dt>
        <dd>{nz(c().learned?.reference_quality, pct)}</dd>
      </dl>
      <Show when={(c().learned?.crews ?? []).length > 0}>
        <Table cols={["Crew", "Outcomes", "Mean quality"]}>
          <For each={c().learned?.crews ?? []}>
            {(x) => (
              <tr>
                <td>{crewText(x.crew)}</td>
                <td>{fmtInt(x.outcomes ?? 0)}</td>
                <td>{nz(x.mean_quality, pct)}</td>
              </tr>
            )}
          </For>
        </Table>
      </Show>
    </section>
  )
}

// ---- the learned role effects, sortable ----

type CellKey = "class" | "role" | "candidate" | "prior_delta" | "delta_hat" | "outcomes" | "mean_excess"

const CELL_COLS: { key: CellKey; label: string; text: boolean }[] = [
  { key: "class", label: "Class", text: true },
  { key: "role", label: "Role", text: true },
  { key: "candidate", label: "Candidate", text: true },
  { key: "prior_delta", label: "Prior δ", text: false },
  { key: "delta_hat", label: "Learned δ̂", text: false },
  { key: "outcomes", label: "Outcomes", text: false },
  { key: "mean_excess", label: "Mean excess", text: false },
]

// Text compares as text; a number compares as a number, and a missing number sorts first.
function compareCells(a: CrewLearnedCell, b: CrewLearnedCell, k: CellKey): number {
  const x = a[k]
  const y = b[k]
  if (typeof x === "string" || typeof y === "string") return String(x ?? "").localeCompare(String(y ?? ""))
  if (typeof x !== "number") return typeof y !== "number" ? 0 : -1
  if (typeof y !== "number") return 1
  return x - y
}

function LearnedCells(props: { pool: CrewPool }) {
  const [key, setKey] = createSignal<CellKey>("outcomes")
  const [desc, setDesc] = createSignal(true)
  const rows = () => {
    const sign = desc() ? -1 : 1
    const k = key()
    return [...(props.pool.learned_cells ?? [])].sort((a, b) => sign * compareCells(a, b, k))
  }
  const pick = (k: CellKey) => {
    if (k === key()) {
      setDesc(!desc())
      return
    }
    setKey(k)
    setDesc(!(CELL_COLS.find((c) => c.key === k)?.text ?? false))
  }
  const dir = (k: CellKey): "ascending" | "descending" | "none" => (key() === k ? (desc() ? "descending" : "ascending") : "none")
  return (
    <section aria-labelledby={"cr-cells-" + slug(props.pool.name)}>
      <h3 id={"cr-cells-" + slug(props.pool.name)}>Learned role effects</h3>
      <Show when={rows().length > 0} fallback={<p class="muted">No outcome has been credited to this pool yet. Each cell shows the prior and the blend once one is.</p>}>
        <div class="table-wrap">
          <table class="cr-cells">
            <thead>
              <tr>
                <For each={CELL_COLS}>
                  {(c) => (
                    <th scope="col" aria-sort={dir(c.key)}>
                      <button type="button" class="ghost sort" onClick={() => pick(c.key)}>
                        {c.label}
                        {key() === c.key ? (desc() ? " ↓" : " ↑") : ""}
                      </button>
                    </th>
                  )}
                </For>
              </tr>
            </thead>
            <tbody>
              <For each={rows()}>
                {(r) => (
                  <tr>
                    <td>{dash(r.class)}</td>
                    <td>{dash(r.role)}</td>
                    <td>
                      <Mono>{dash(r.candidate)}</Mono>
                    </td>
                    <td>{delta(r.prior_delta ?? 0)}</td>
                    <td>{delta(r.delta_hat ?? 0)}</td>
                    <td>{fmtInt(r.outcomes ?? 0)}</td>
                    <td>{nz(r.mean_excess, delta)}</td>
                  </tr>
                )}
              </For>
            </tbody>
          </table>
        </div>
      </Show>
    </section>
  )
}

function PoolCard(props: { pool: CrewPool }) {
  const p = () => props.pool
  const sid = () => "cr-pool-" + slug(p().name)
  const subOf = (name: string | undefined) => (p().subscriptions ?? []).find((s) => s.name === name)
  return (
    <section class="card" id={sid()} aria-labelledby={sid() + "-h"}>
      <h2 id={sid() + "-h"}>Pool {p().name}</h2>
      <dl class="kv">
        <dt>Roles</dt>
        <dd>{(p().roles ?? []).join(", ")}</dd>
        <dt>Classes</dt>
        <dd>
          {(p().classes ?? []).join(", ")}; uncertain tasks go to {dash(p().uncertain_class)}
        </dd>
        <dt>Task lifetime</dt>
        <dd>{fmtInt(p().task_ttl_seconds ?? 0)} seconds</dd>
        <dt>Operating point</dt>
        <dd>
          {dash(p().operating_point?.mode)}
          {p().operating_point?.mode === "budget" ? ", budget " + nz(p().operating_point?.budget_usd, usd) + " per task" : ""}
        </dd>
        <dt>Priors</dt>
        <dd>{sourceText(p().priors)}</dd>
        <dt>Classifier</dt>
        <dd>{sourceText(p().classifier)}</dd>
        <dt>Credibility prior scale</dt>
        <dd>{dash(p().credibility?.prior_scale)}</dd>
      </dl>
      <h3>Candidates</h3>
      <Table cols={["Candidate", "Model", "Route", "Admitted roles", "Subscription", "Spent in its window", "φ", "h(φ)", "Price per 1M tokens"]}>
        <For each={p().candidates ?? []}>
          {(cand) => (
            <tr>
              <td>
                <Mono>{cand.id}</Mono>
              </td>
              <td>
                <Mono>{cand.model}</Mono>
              </td>
              <td>{cand.route}</td>
              <td>{(cand.roles ?? []).length > 0 ? (cand.roles ?? []).join(", ") : "any"}</td>
              <td>{cand.subscription || "—"}</td>
              <td>{subOf(cand.subscription) ? `${usd(subOf(cand.subscription)?.spent_usd ?? 0)} of ${usd(subOf(cand.subscription)?.limit_usd ?? 0)}` : "—"}</td>
              <td>{subOf(cand.subscription) ? pct(subOf(cand.subscription)?.phi ?? 0) : "—"}</td>
              <td>{subOf(cand.subscription) ? (subOf(cand.subscription)?.h ?? 0).toFixed(3) : "—"}</td>
              <td>{cand.price?.priced ? `${per1M(cand.price?.input ?? 0)} in, ${per1M(cand.price?.output ?? 0)} out` : "unpriced (cost 0)"}</td>
            </tr>
          )}
        </For>
      </Table>
      <h3>Pacing</h3>
      <Pacing pool={p()} />
      <h3>Classes</h3>
      <For each={p().classes_detail ?? []}>{(k) => <ClassCard pool={p()} klass={k} />}</For>
      <LearnedCells pool={p()} />
    </section>
  )
}

// One task: its assignment in force, its attempts (crew, verifier, quality, cost) and its calls.
function TaskDetail(props: { d: CrewTaskDetail }) {
  const a = () => props.d.assignment
  return (
    <div id="cr-task-detail">
      <h3>Task {props.d.task_id}</h3>
      <Show when={a()} fallback={<p class="muted">No assignment in force (never assigned, or expired). The calls below are the task's log rows.</p>}>
        {(as) => (
          <dl class="kv">
            <dt>Class</dt>
            <dd>{dash(as().class)}</dd>
            <dt>Attempt in force</dt>
            <dd>{fmtInt(as().attempt ?? 0)}</dd>
            <dt>Crew</dt>
            <dd>{crewText(as().crew)}</dd>
            <dt>Multiplier λ at assignment</dt>
            <dd>{nz(as().lambda, lam)}</dd>
            <dt>Assigned</dt>
            <dd>{fmtTime(as().created)}</dd>
            <dt>Completed and paced</dt>
            <dd>{as().paced ? "yes" : "no"}</dd>
            <dt>Expired</dt>
            <dd>{as().expired ? "yes" : "no"}</dd>
            <dt>Class posterior</dt>
            <dd>{(as().posterior ?? []).map((x) => `${x.class} ${pct(x.p ?? 0)}`).join(", ") || "—"}</dd>
          </dl>
        )}
      </Show>
      <dl class="kv">
        <dt>Calls</dt>
        <dd>{fmtInt(props.d.calls)}</dd>
        <dt>Cost</dt>
        <dd>{fmtMoney(props.d.cost)}</dd>
      </dl>
      <h4>Attempts</h4>
      <Table cols={["Attempt", "Crew", "Verifier", "Quality", "Accuracy", "Cost", "Calls"]}>
        <For each={props.d.attempts ?? []}>
          {(t) => (
            <tr>
              <td>{t.attempt}</td>
              <td>{crewText(t.crew)}</td>
              <td>{t.outcome ? (t.outcome?.verifier === "" ? "none" : dash(t.outcome?.verifier)) : "—"}</td>
              <td>{nz(t.outcome?.quality, pct)}</td>
              <td>{nz(t.outcome?.accuracy, pct)}</td>
              <td>{fmtMoney(t.cost)}</td>
              <td>{fmtInt(t.calls)}</td>
            </tr>
          )}
        </For>
      </Table>
      <h4>Calls</h4>
      <Show when={(props.d.rows ?? []).length > 0} fallback={<p class="muted">No calls in the log window.</p>}>
        <Table cols={["Time", "Role", "Candidate", "Attempt", "Model", "Status", "Tokens in / out", "Cost"]}>
          <For each={props.d.rows ?? []}>
            {(r) => (
              <tr>
                <td class="nowrap">{fmtTime(r.ts)}</td>
                <td>{dash(r.role)}</td>
                <td>{dash(r.candidate)}</td>
                <td>{r.attempt}</td>
                <td>
                  <Mono>{r.model}</Mono>
                </td>
                <td>{r.status}</td>
                <td>
                  {fmtInt(r.prompt_tokens)} / {fmtInt(r.completion_tokens)}
                </td>
                <td>{fmtMoney(r.cost)}</td>
              </tr>
            )}
          </For>
        </Table>
      </Show>
    </div>
  )
}

// The task lookup, and for writers the three actions on a task: assign, record an outcome, ask for the next attempt.
function TaskPanel(props: { pools: () => CrewPool[] }) {
  const writer = () => can("Crews", "Create")
  const [pool, setPool] = createSignal(props.pools()[0]?.name ?? "")
  const [taskId, setTaskId] = createSignal("")
  const [detail, setDetail] = createSignal<CrewTaskDetail | undefined>(undefined)
  const look = useFormRun()
  const poolObj = (name: string) => props.pools().find((p) => p.name === name)

  const find = async (id: string, pl: string): Promise<void> => {
    try {
      setDetail(await api.get("/api/crews/tasks/{task_id}", { params: { task_id: id }, query: { pool: pl } }))
    } catch (e) {
      // a 404 is a task the gateway does not hold: say that, rather than the generic "not available" of the client
      setDetail(undefined)
      if (e instanceof ApiError && e.status === 404) throw new Error(`No task ${id} in pool ${pl} (never assigned, or expired).`)
      throw e
    }
  }
  const onLookup = (ev: SubmitEvent) => {
    ev.preventDefault()
    const id = taskId().trim()
    void look.run(async () => {
      if (id === "") throw new Error("Enter a task id.")
      await find(id, pool())
    })
  }

  // assign
  const [aPool, setAPool] = createSignal(props.pools()[0]?.name ?? "")
  const [aTask, setATask] = createSignal("")
  const [aClass, setAClass] = createSignal("")
  const [aText, setAText] = createSignal("")
  const [aLabels, setALabels] = createSignal("")
  const assign = useFormRun()
  const onAssign = (ev: SubmitEvent) => {
    ev.preventDefault()
    void assign.run(async () => {
      const id = aTask().trim()
      const body: Record<string, unknown> = { task_id: id }
      if (aClass() !== "") body.class = aClass()
      if (aText().trim() !== "") body.text = aText()
      const labels = splitList(aLabels())
      if (labels.length > 0) body.labels = labels
      const r = await api.post("/api/crews/{pool}/assign", { params: { pool: aPool() }, body })
      notify(`Task ${id} is class ${String(r.class ?? "")}`, "ok")
      setPool(aPool())
      setTaskId(id)
      setATask("")
      await find(id, aPool())
    })
  }

  // outcome, for the task looked up
  const [quality, setQuality] = createSignal("")
  const [verifier, setVerifier] = createSignal("")
  const [accuracy, setAccuracy] = createSignal("")
  const [attempt, setAttempt] = createSignal("")
  const outcome = useFormRun()
  const onOutcome = (ev: SubmitEvent) => {
    ev.preventDefault()
    void outcome.run(async () => {
      const id = taskId().trim()
      if (id === "") throw new Error("Look up a task first.")
      if (quality().trim() === "" || !Number.isFinite(Number(quality()))) throw new Error("Quality is a number from 0 to 1.")
      const body: Record<string, unknown> = { quality: Number(quality()) }
      if (verifier() !== "") body.verifier = verifier()
      if (attempt().trim() !== "") body.attempt = Number(attempt())
      if (accuracy().trim() !== "") body.accuracy = Number(accuracy())
      const r = await api.post("/api/crews/tasks/{task_id}/outcome", { params: { task_id: id }, query: { pool: pool() }, body })
      notify(r.recorded ? "Outcome recorded" : "That attempt already has an outcome; nothing changed", "ok")
      setQuality("")
      setAccuracy("")
      await find(id, pool())
    })
  }

  // next, for the task looked up
  const next = useRun()
  const askNext = () =>
    void next.run(async () => {
      const id = taskId().trim()
      if (id === "") throw new Error("Look up a task first.")
      const r = await api.post("/api/crews/tasks/{task_id}/next", { params: { task_id: id }, query: { pool: pool() } })
      notify(r.action === "attempt" ? `Attempt ${String(r.attempt)} starts on its crew` : "Accepted: " + String(r.reason ?? ""), "ok")
      await find(id, pool())
    })

  return (
    <section class="card" id="cr-tasks" aria-labelledby="cr-tasks-h">
      <h2 id="cr-tasks-h">Tasks</h2>
      <form class="form-grid" id="cr-task-form" onSubmit={onLookup}>
        <label>
          Pool
          <select id="cr-task-pool" onChange={(e) => setPool(e.currentTarget.value)}>
            <For each={props.pools()}>{(p) => <option value={p.name} selected={p.name === pool()}>{p.name}</option>}</For>
          </select>
        </label>
        <label>
          Task id
          <input id="cr-task-id" value={taskId()} onInput={(e) => setTaskId(e.currentTarget.value)} autocomplete="off" spellcheck={false} />
        </label>
        <div class="actions">
          <button type="submit" class="primary" disabled={look.busy()}>
            Look up
          </button>
        </div>
        <FormError text={look.error()} />
      </form>
      <Show when={detail()}>{(d) => <TaskDetail d={d()} />}</Show>
      <Show when={writer()} fallback={<p class="hint">Your role can read the crews but not assign tasks, record outcomes or ask for the next attempt.</p>}>
        <h3>Assign a task</h3>
        <form class="form-grid" id="cr-assign-form" onSubmit={onAssign}>
          <label>
            Pool
            <select id="cr-assign-pool" onChange={(e) => setAPool(e.currentTarget.value)}>
              <For each={props.pools()}>{(p) => <option value={p.name} selected={p.name === aPool()}>{p.name}</option>}</For>
            </select>
          </label>
          <label>
            Task id
            <input id="cr-assign-task" value={aTask()} onInput={(e) => setATask(e.currentTarget.value)} required autocomplete="off" />
          </label>
          <label>
            Class
            <select id="cr-assign-class" onChange={(e) => setAClass(e.currentTarget.value)}>
              <option value="" selected={aClass() === ""}>Classify from the text</option>
              <For each={poolObj(aPool())?.classes ?? []}>{(k) => <option value={k} selected={k === aClass()}>{k}</option>}</For>
            </select>
          </label>
          <label>
            Task text (for the classifier)
            <input id="cr-assign-text" value={aText()} onInput={(e) => setAText(e.currentTarget.value)} autocomplete="off" />
          </label>
          <label>
            Labels
            <input id="cr-assign-labels" value={aLabels()} onInput={(e) => setALabels(e.currentTarget.value)} placeholder="comma separated" autocomplete="off" />
          </label>
          <div class="actions wide">
            <button type="submit" class="primary" disabled={assign.busy()}>
              Assign
            </button>
          </div>
          <FormError text={assign.error()} />
        </form>
        <h3>Record an outcome for the task looked up</h3>
        <form class="form-grid" id="cr-outcome-form" onSubmit={onOutcome}>
          <label>
            Quality (0 to 1)
            <input id="cr-outcome-quality" type="number" step="any" min="0" max="1" value={quality()} onInput={(e) => setQuality(e.currentTarget.value)} required />
          </label>
          <label>
            Verifier
            <select id="cr-outcome-verifier" onChange={(e) => setVerifier(e.currentTarget.value)}>
              <option value="" selected={verifier() === ""}>None</option>
              <option value="pass" selected={verifier() === "pass"}>Pass</option>
              <option value="fail" selected={verifier() === "fail"}>Fail</option>
            </select>
          </label>
          <label>
            Verifier accuracy (0.5 to 1)
            <input id="cr-outcome-accuracy" type="number" step="any" min="0.5" max="1" value={accuracy()} onInput={(e) => setAccuracy(e.currentTarget.value)} />
          </label>
          <label>
            Attempt (default: the one in force)
            <input id="cr-outcome-attempt" type="number" step="1" min="1" value={attempt()} onInput={(e) => setAttempt(e.currentTarget.value)} />
          </label>
          <div class="actions wide">
            <button type="submit" class="primary" disabled={outcome.busy()}>
              Record outcome
            </button>
          </div>
          <FormError text={outcome.error()} />
        </form>
        <div class="actions">
          <button type="button" id="cr-next" onClick={askNext} disabled={next.busy()}>
            Ask for the next step
          </button>
        </div>
      </Show>
    </section>
  )
}

// The pools are loaded by a memo made outside the loading boundary, so a suspended read does not remount it (and refetch).
function Body(props: { pools: () => CrewPool[] }) {
  return (
    <>
      <Show when={props.pools().length > 0} fallback={<section class="card"><p class="muted">No crew pool is configured. Pools are set under crews in config.json (docs/crew-routing.md).</p></section>}>
        <For each={props.pools()}>{(p) => <PoolCard pool={p} />}</For>
      </Show>
      <TaskPanel pools={props.pools} />
    </>
  )
}

export function Crews() {
  const [version, setVersion] = createSignal(0)
  const pools = createMemo(() => {
    version()
    return api.get("/api/crews").then((r) => r.pools ?? [])
  })
  return (
    <section aria-labelledby="cr-title">
      <Toolbar title="Crews" id="cr-title">
        <button type="button" id="cr-refresh" class="ghost" onClick={() => setVersion((v) => v + 1)}>
          Refresh
        </button>
      </Toolbar>
      <Guard>
        <Body pools={pools} />
      </Guard>
    </section>
  )
}

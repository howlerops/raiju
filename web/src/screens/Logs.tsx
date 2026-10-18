import { createMemo, createSignal, Errored, For, Loading, Show } from "solid-js"
import { api } from "../api/client"
import type { LogEntry } from "../api/types"
import { fmtInt } from "../fmt"
import { ErrP, Toolbar, tf } from "../ui"
import { LogCharts } from "./Charts"
import { LOG_COLS, LogCells, LogDetail } from "./logParts"

const PAGE_SIZE = 25
const PERIOD_MS: Record<string, number> = { "1h": 3600000, "24h": 86400000, "7d": 604800000 }

interface Applied {
  provider: string
  model: string
  status: string
  virtual_key: string
  text: string
  period: string
  from: string
  to: string
  offset: number
}

const EMPTY: Applied = { provider: "", model: "", status: "", virtual_key: "", text: "", period: "", from: "", to: "", offset: 0 }

function LogRow(props: { e: LogEntry }) {
  const [open, setOpen] = createSignal(false)
  const toggle = () => setOpen(!open())
  return (
    <>
      <tr
        class="clickable"
        tabindex="0"
        aria-expanded={tf(open())}
        onClick={toggle}
        onKeyDown={(ev) => {
          if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault()
            toggle()
          }
        }}
      >
        <LogCells e={props.e} />
      </tr>
      <Show when={open()}>
        <tr class="detail">
          <td colspan={LOG_COLS.length}>
            <LogDetail entry={props.e} />
          </td>
        </tr>
      </Show>
    </>
  )
}

export function Logs() {
  const [applied, setApplied] = createSignal<Applied>(EMPTY)
  const [period, setPeriod] = createSignal("")
  let form: HTMLFormElement | undefined

  const page = createMemo(() => {
    const a = applied()
    const query: Record<string, string | number> = { limit: PAGE_SIZE, offset: a.offset }
    for (const k of ["provider", "model", "status", "virtual_key", "text"] as const) if (a[k]) query[k] = a[k]
    if (a.period === "custom") {
      const from = new Date(a.from).getTime()
      const to = new Date(a.to).getTime()
      if (Number.isFinite(from)) query.since = from
      if (Number.isFinite(to)) query.until = to
    } else if (PERIOD_MS[a.period]) {
      query.since = Date.now() - PERIOD_MS[a.period]!
    }
    return api.get("/api/logs", { query })
  })

  // the same filters for the chart routes, over a window (24 hours when none is chosen)
  const chartQuery = createMemo(() => {
    const a = applied()
    const q: Record<string, string | number> = {}
    if (a.provider) q.providers = a.provider
    if (a.model) q.models = a.model
    if (a.status) q.status = a.status
    if (a.virtual_key) q.virtual_key_ids = a.virtual_key
    if (a.text) q.content_search = a.text
    const now = Date.now()
    let start = now - 86400000
    let end = now
    if (a.period === "custom") {
      const from = new Date(a.from).getTime()
      const to = new Date(a.to).getTime()
      if (Number.isFinite(from)) start = from
      if (Number.isFinite(to)) end = to
    } else if (PERIOD_MS[a.period]) {
      start = now - PERIOD_MS[a.period]!
    }
    if (start >= end) start = end - 3600000
    q.start_time = start
    q.end_time = end
    return q
  })

  const filters = createMemo(async () => {
    try {
      return await api.get("/api/logs/filterdata")
    } catch {
      return {}
    }
  })

  const read = (n: string) => ((form?.elements.namedItem(n) as HTMLInputElement | HTMLSelectElement | null)?.value ?? "").trim()
  const apply = (ev: SubmitEvent) => {
    ev.preventDefault()
    setApplied({
      provider: read("provider"),
      model: read("model"),
      status: read("status"),
      virtual_key: read("virtual_key"),
      text: read("text"),
      period: read("period"),
      from: read("from"),
      to: read("to"),
      offset: 0,
    })
  }
  const go = (delta: number) => setApplied((a) => ({ ...a, offset: Math.max(0, a.offset + delta) }))

  const range = () => {
    try {
      const p = page()
      const off = applied().offset
      const from = p.entries.length ? off + 1 : 0
      const to = off + p.entries.length
      return p.total ? from + "–" + to + " of " + fmtInt(p.total) : "no entries"
    } catch {
      return ""
    }
  }
  const hasNext = () => {
    try {
      const p = page()
      return applied().offset + p.entries.length < p.total
    } catch {
      return false
    }
  }

  return (
    <section aria-labelledby="lg-title">
      <Toolbar title="Logs" id="lg-title">
        <span class="hint" id="lg-range" role="status">
          {range()}
        </span>
      </Toolbar>
      <form id="lg-filter" class="card filters" role="search" aria-label="Filter logs" ref={(el) => (form = el)} onSubmit={apply}>
        <label>
          Provider
          <input name="provider" list="lg-providers" autocomplete="off" />
        </label>
        <datalist id="lg-providers">
          <Loading>
            <For each={filters().providers ?? []}>{(n) => <option value={n} />}</For>
          </Loading>
        </datalist>
        <label>
          Model
          <input name="model" list="lg-models" autocomplete="off" />
        </label>
        <datalist id="lg-models">
          <Loading>
            <For each={filters().models ?? []}>{(n) => <option value={n} />}</For>
          </Loading>
        </datalist>
        <label>
          Virtual key
          <select name="virtual_key">
            <option value="">Any</option>
            <Loading>
              <For each={filters().virtual_keys ?? []}>
                {(v) => <option value={v.id}>{v.name ? v.name + " (" + v.id + ")" : v.id}</option>}
              </For>
            </Loading>
          </select>
        </label>
        <label>
          Status
          <select name="status">
            <option value="">Any</option>
            <option value="success">Success</option>
            <option value="error">Error</option>
          </select>
        </label>
        <label>
          Time range
          <select name="period" onChange={(e) => setPeriod(e.currentTarget.value)}>
            <option value="">Any time</option>
            <option value="1h">Last hour</option>
            <option value="24h">Last 24 hours</option>
            <option value="7d">Last 7 days</option>
            <option value="custom">Custom</option>
          </select>
        </label>
        <label id="lg-from-wrap" hidden={period() !== "custom"}>
          From
          <input name="from" type="datetime-local" />
        </label>
        <label id="lg-to-wrap" hidden={period() !== "custom"}>
          To
          <input name="to" type="datetime-local" />
        </label>
        <label>
          Text
          <input name="text" autocomplete="off" placeholder="search" />
        </label>
        <div class="actions">
          <button
            type="button"
            id="lg-clear"
            class="ghost"
            onClick={() => {
              form?.reset()
              setPeriod("")
              setApplied(EMPTY)
            }}
          >
            Clear
          </button>
          <button type="submit" class="primary">
            Apply
          </button>
        </div>
      </form>

      <LogCharts query={chartQuery()} />

      <div class="card" style="padding:0">
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <For each={LOG_COLS}>{(c) => <th scope="col">{c}</th>}</For>
              </tr>
            </thead>
            <tbody id="lg-body">
              <Errored
                fallback={(err) => (
                  <tr>
                    <td colspan={LOG_COLS.length}>
                      <ErrP error={err()} />
                    </td>
                  </tr>
                )}
              >
                <Loading
                  fallback={
                    <tr class="placeholder">
                      <td colspan={LOG_COLS.length}>Loading...</td>
                    </tr>
                  }
                >
                  <Show
                    when={page().entries.length}
                    fallback={
                      <tr class="placeholder">
                        <td colspan={LOG_COLS.length}>{applied().offset ? "No more entries." : "No matching entries."}</td>
                      </tr>
                    }
                  >
                    <For each={page().entries} keyed={(e) => e.id}>
                      {(e) => <LogRow e={e()} />}
                    </For>
                  </Show>
                </Loading>
              </Errored>
            </tbody>
          </table>
        </div>
      </div>
      <div class="pager">
        <button type="button" id="lg-prev" class="ghost" disabled={applied().offset === 0} onClick={() => go(-PAGE_SIZE)}>
          Previous
        </button>
        <button type="button" id="lg-next" class="ghost" disabled={!hasNext()} onClick={() => go(PAGE_SIZE)}>
          Next
        </button>
      </div>
    </section>
  )
}

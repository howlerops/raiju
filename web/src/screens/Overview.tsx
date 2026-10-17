import { createMemo, createSignal, Errored, For, Loading, onSettled, refresh, Show } from "solid-js"
import { api, send } from "../api/client"
import { fmtInt, fmtMoney, fmtMs, fmtPct, num } from "../fmt"
import type { JSX } from "@solidjs/web"
import { ErrP, Card, Mono, Pill, Stat, stateTone, Table, Toolbar } from "../ui"

interface ModelRow {
  model: string
  requests: number
  cost: number
}

// by_model is an object keyed by model; older builds sent an array of rows.
function modelRows(by: unknown): ModelRow[] {
  const rows: ModelRow[] = []
  if (Array.isArray(by)) {
    for (const r of by) {
      const o = r as { model?: string; requests?: unknown; cost?: unknown }
      rows.push({ model: o.model ?? "", requests: num(o.requests), cost: num(o.cost) })
    }
  } else if (by && typeof by === "object") {
    for (const [k, v] of Object.entries(by as Record<string, { requests?: unknown; cost?: unknown }>)) {
      rows.push({ model: k, requests: num(v?.requests), cost: num(v?.cost) })
    }
  }
  return rows.sort((a, b) => b.requests - a.requests)
}

function Guard(props: { children?: JSX.Element }) {
  return (
    <Errored fallback={(err) => <ErrP error={err()} />}>
      <Loading fallback={<p class="muted">Loading...</p>}>{props.children}</Loading>
    </Errored>
  )
}

export function Overview() {
  const [updated, setUpdated] = createSignal("")
  const stats = createMemo(() => api.get("/api/logs/stats", { query: { start_time: Date.now() - 3600000 } }))
  const cache = createMemo(() => api.get("/api/cache"))
  const health = createMemo(() => api.get("/api/health"))
  const mcp = createMemo(() => api.get("/api/mcp"))
  const [metrics, setMetrics] = createSignal("Opening this loads /metrics.")

  const reload = () => {
    refresh(stats)
    refresh(cache)
    refresh(health)
    refresh(mcp)
    setUpdated("Updated " + new Date().toLocaleTimeString())
  }
  onSettled(() => {
    setUpdated("Updated " + new Date().toLocaleTimeString())
    const timer = setInterval(() => {
      if (!document.hidden) reload()
    }, 10000)
    return () => clearInterval(timer)
  })

  const loadMetrics = async (ev: Event) => {
    if (!(ev.currentTarget as HTMLDetailsElement).open) return
    try {
      const r = await send("GET", "/metrics")
      setMetrics(r.text || "(no metrics)")
    } catch (e) {
      setMetrics(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <section aria-labelledby="ov-title">
      <Toolbar title="Overview" id="ov-title">
        <span class="hint" id="ov-updated" role="status">
          {updated()}
        </span>
        <button type="button" class="ghost" id="ov-refresh" onClick={reload}>
          Refresh
        </button>
      </Toolbar>

      <div class="cards" id="ov-stats">
        <Guard>
          {(() => {
            const s = stats() as Record<string, unknown>
            const reqs = num(s.requests)
            return (
              <>
                <Stat label="Requests" value={fmtInt(s.requests)} sub="last hour" />
                <Stat label="Errors" value={fmtInt(s.errors)} sub={reqs ? fmtPct(num(s.errors) / reqs) + " error rate" : "no traffic"} />
                <Stat label="Tokens" value={fmtInt(s.tokens)} sub="last hour" />
                <Stat label="Cost" value={fmtMoney(s.cost)} sub="last hour" />
                <Stat label="Avg latency" value={fmtMs(s.avg_latency_ms)} sub="last hour" />
              </>
            )
          })()}
        </Guard>
      </div>

      <div class="grid">
        <Card title="Models, last hour" id="ov-models-h">
          <div id="ov-models">
            <Guard>
              {(() => {
                const rows = modelRows((stats() as Record<string, unknown>).by_model)
                return (
                  <Show when={rows.length} fallback={<p class="muted">No traffic in the last hour.</p>}>
                    <Table cols={["Model", "Requests", "Cost"]}>
                      <For each={rows} keyed={(r) => r.model}>
                        {(r) => (
                          <tr>
                            <td>
                              <Mono>{r().model || "—"}</Mono>
                            </td>
                            <td>{fmtInt(r().requests)}</td>
                            <td>{fmtMoney(r().cost)}</td>
                          </tr>
                        )}
                      </For>
                    </Table>
                  </Show>
                )
              })()}
            </Guard>
          </div>
        </Card>

        <Card title="Circuit breakers" id="ov-breakers-h">
          <div id="ov-breakers">
            <Guard>
              <Show when={health().targets.length} fallback={<p class="muted">No targets have reported yet.</p>}>
                <Table cols={["Target", "State", "Latency", "Success", "Requests"]}>
                  <For each={health().targets}>
                    {(t) => (
                      <tr>
                        <td class="nowrap">
                          <Mono>{String(t.id ?? "—")}</Mono>
                        </td>
                        <td>
                          <Pill tone={stateTone(t.state)}>{String(t.state ?? "unknown")}</Pill>
                        </td>
                        <td>{t.ewmaMs === undefined ? "—" : fmtMs(t.ewmaMs)}</td>
                        <td>{t.successRate === undefined ? "—" : fmtPct(t.successRate)}</td>
                        <td>{fmtInt(t.requests)}</td>
                      </tr>
                    )}
                  </For>
                </Table>
              </Show>
            </Guard>
          </div>
        </Card>

        <Card title="Response cache" id="ov-cache-h">
          <div id="ov-cache">
            <Guard>
              {(() => {
                const c = cache()
                const hits = num(c.hits)
                const total = hits + num(c.misses)
                return (
                  <dl class="kv">
                    <dt>Status</dt>
                    <dd>
                      <Pill tone={c.enabled ? "ok" : ""}>{c.enabled ? "enabled" : "disabled"}</Pill>
                    </dd>
                    <dt>Entries</dt>
                    <dd>{fmtInt(c.entries)}</dd>
                    <dt>Hits</dt>
                    <dd>{fmtInt(hits)}</dd>
                    <dt>Misses</dt>
                    <dd>{fmtInt(c.misses)}</dd>
                    <dt>Hit rate</dt>
                    <dd>{total ? fmtPct(hits / total) : "—"}</dd>
                  </dl>
                )
              })()}
            </Guard>
          </div>
        </Card>

        <Card title="MCP clients" id="ov-mcp-h">
          <div id="ov-mcp">
            <Guard>
              <Show when={mcp().clients.length} fallback={<p class="muted">No MCP clients configured.</p>}>
                <Table cols={["Client", "Connection", "Tools", "Error"]}>
                  <For each={mcp().clients} keyed={(c) => c.name}>
                    {(c) => (
                      <tr>
                        <td>
                          <Mono>{c().name || "—"}</Mono>
                        </td>
                        <td>
                          <Pill tone={c().connected ? "ok" : "bad"}>{c().connected ? "connected" : "down"}</Pill>
                        </td>
                        <td>{fmtInt(c().tools)}</td>
                        <td>{c().error ? <span class="error">{c().error}</span> : "—"}</td>
                      </tr>
                    )}
                  </For>
                </Table>
              </Show>
            </Guard>
          </div>
        </Card>
      </div>

      <details class="card" id="ov-metrics-box" style="margin-top:14px" onToggle={loadMetrics}>
        <summary>Prometheus metrics</summary>
        <pre class="code" id="ov-metrics">
          {metrics()}
        </pre>
      </details>
    </section>
  )
}

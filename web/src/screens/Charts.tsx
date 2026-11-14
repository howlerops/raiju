// The dashboard charts: the overview's (one /api/logs/dashboard call for a period) and the logs
// screen's (the histogram and ranking routes for the filters in force).
import { createMemo, createSignal } from "solid-js"
import { send } from "../api/client"
import { RankBars, TimeChart, foldSeries } from "../charts"
import { bucketsOf, costSeries, groupSeries, latencySeries, obj, rankRows, requestSeries, tokenSeries } from "../chartData"
import { fmtInt, fmtMoney, fmtMs, num } from "../fmt"
import { Guard } from "../ui"

type Query = Record<string, string | number | boolean | undefined>

async function getJson(path: string, query: Query, timeoutMs?: number): Promise<unknown> {
  return (await send("GET", path, { query, timeoutMs })).data
}

const compact = (n: number): string => {
  const a = Math.abs(n)
  if (a >= 1e9) return +(n / 1e9).toFixed(1) + "B"
  if (a >= 1e6) return +(n / 1e6).toFixed(1) + "M"
  if (a >= 1e4) return +(n / 1e3).toFixed(1) + "k"
  return String(+n.toFixed(2))
}
const money = (n: number): string => "$" + (n >= 100 ? n.toFixed(0) : n >= 1 ? n.toFixed(2) : n.toFixed(4))
const ms = (n: number): string => (n >= 1000 ? +(n / 1000).toFixed(1) + " s" : Math.round(n) + " ms")

const PERIODS: [string, string][] = [
  ["1h", "Last hour"],
  ["24h", "Last 24 hours"],
  ["7d", "Last 7 days"],
]

function Panel(props: { children?: import("@solidjs/web").JSX.Element }) {
  return <div class="card panel bg-base-100 border border-base-300 chart-card">{props.children}</div>
}

// ---- overview ----

// track wraps each read so the overview can tell a reload is still in flight; timeoutMs bounds it.
export function OverviewCharts(props: { tick: () => number; track: <T>(p: Promise<T>) => Promise<T>; timeoutMs: number }) {
  const [period, setPeriod] = createSignal("1h")
  // a zoomed range (epoch ms) replaces the period until it is reset
  const [zoom, setZoom] = createSignal<[number, number] | undefined>(undefined)
  const zoomProps = () => ({ onZoom: (a: number, b: number) => setZoom([a, b]), zoomed: zoom() !== undefined, onReset: () => setZoom(undefined) })
  const range = (): Query => {
    const z = zoom()
    return z ? { start_time: z[0], end_time: z[1] } : { period: period() }
  }
  const dash = createMemo(() => {
    props.tick()
    return props.track(getJson("/api/logs/dashboard", range(), props.timeoutMs))
  })
  const providers = createMemo(() => {
    props.tick()
    return props.track(getJson("/api/logs/rankings/by-dimension", { dimension: "provider", ...range(), limit: 8 }, props.timeoutMs))
  })
  // Derived once per response, so a poll updates the charts below in place instead of rebuilding them.
  const overview = createMemo(() => obj(obj(dash()).overview))
  const req = createMemo(() => bucketsOf(overview().requests))
  const lat = createMemo(() => bucketsOf(overview().latency))
  const tok = createMemo(() => bucketsOf(overview().tokens))
  const cost = createMemo(() => bucketsOf(overview().cost))
  const provCost = createMemo(() => bucketsOf(obj(obj(dash()).provider_usage).cost))
  const reqSeries = createMemo(() => requestSeries(req()))
  const latSeries = createMemo(() => latencySeries(lat()))
  const tokSeries = createMemo(() => tokenSeries(tok()))
  const costOnly = createMemo(() => costSeries(cost()))
  const provSeries = createMemo(() => foldSeries(groupSeries(provCost(), "by_provider")))
  const modelRanks = createMemo(() =>
    rankRows(obj(obj(dash()).model_rankings).rankings, ["provider", "model"], "total_requests", (r) => fmtMoney(r.total_cost) + ", " + fmtInt(r.total_tokens) + " tokens, " + fmtMs(r.avg_latency)),
  )
  const providerRanks = createMemo(() => rankRows(providers(), ["id"], "total_requests", (r) => fmtMoney(r.total_cost) + ", " + num(r.success_rate).toFixed(1) + "% success"))

  return (
    <section aria-labelledby="ov-charts-h" id="ov-charts">
      <div class="toolbar">
        <h2 id="ov-charts-h" style="margin:0">
          Traffic
        </h2>
        <span class="grow"></span>
        <label class="inline">
          Period
          <select class="select select-sm" id="ov-period" onChange={(ev) => {
                setZoom(undefined)
                setPeriod(ev.currentTarget.value)
              }}>
            {PERIODS.map(([v, l]) => (
              <option value={v} ref={(el) => (el.selected = v === "1h")}>
                {l}
              </option>
            ))}
          </select>
        </label>
      </div>
      <Guard>
        <div class="content-grid charts">
          <Panel>
            <TimeChart
              id="ch-requests"
              title="Requests"
              desc="Requests per time bucket, success and errors stacked."
              times={req().times}
              series={reqSeries()}
              kind="bars"
              {...zoomProps()}
              format={fmtInt}
            />
          </Panel>
          <Panel>
            <TimeChart
              id="ch-latency"
              title="Latency"
              desc="Average and percentile latency in milliseconds per time bucket."
              times={lat().times}
              series={latSeries()}
              kind="lines"
              {...zoomProps()}
              format={ms}
            />
          </Panel>
          <Panel>
            <TimeChart
              id="ch-tokens"
              title="Tokens"
              desc="Prompt and completion tokens per time bucket."
              times={tok().times}
              series={tokSeries()}
              kind="bars"
              {...zoomProps()}
              format={compact}
            />
          </Panel>
          <Panel>
            <TimeChart
              id="ch-cost"
              title="Cost"
              desc="Cost in dollars per time bucket."
              times={cost().times}
              series={costOnly()}
              kind="bars"
              {...zoomProps()}
              format={money}
            />
          </Panel>
          <Panel>
            <TimeChart
              id="ch-provider-cost"
              title="Cost by provider"
              desc="Cost in dollars per time bucket, one series per provider."
              times={provCost().times}
              series={provSeries()}
              kind="bars"
              {...zoomProps()}
              format={money}
            />
          </Panel>
          <Panel>
            <RankBars
              id="ch-models"
              title="Top models by requests"
              rows={modelRanks()}
              format={fmtInt}
            />
          </Panel>
          <Panel>
            <RankBars
              id="ch-providers"
              title="Top providers by requests"
              rows={providerRanks()}
              format={fmtInt}
            />
          </Panel>
        </div>
      </Guard>
    </section>
  )
}

// ---- logs ----

const DIMENSIONS: [string, string][] = [
  ["provider", "Provider"],
  ["model", "Model"],
  ["virtual_key", "Virtual key"],
]
const METRICS: [string, string][] = [
  ["cost", "Cost"],
  ["tokens", "Tokens"],
  ["latency", "p95 latency"],
]

// what a screen passes the time charts so a drag selection narrows its filters
export interface ZoomProps {
  onZoom: (start: number, end: number) => void
  zoomed: boolean
  onReset: () => void
}

export function LogCharts(props: { query: Query; zoom?: ZoomProps }) {
  const [dimension, setDimension] = createSignal("provider")
  const [metric, setMetric] = createSignal("cost")

  const base = createMemo(() => ({ ...props.query }))
  const requests = createMemo(() => getJson("/api/logs/histogram", base()))
  const by = createMemo(() => getJson("/api/logs/histogram/" + metric() + "/by-dimension", { ...base(), dimension: dimension() }))
  const ranks = createMemo(() => getJson("/api/logs/rankings/by-dimension", { ...base(), dimension: dimension(), limit: 8 }))

  const dimLabel = () => DIMENSIONS.find((d) => d[0] === dimension())![1]
  const metricLabel = () => METRICS.find((d) => d[0] === metric())![1]

  return (
    <details class="card panel bg-base-100 border border-base-300" id="lg-charts" open>
      <summary>Charts for these filters</summary>
      <div class="filters" style="margin-top:10px">
        <label>
          Break down by
          <select class="select select-sm" id="lg-dim" onChange={(ev) => setDimension(ev.currentTarget.value)}>
            {DIMENSIONS.map(([v, l]) => (
              <option value={v} ref={(el) => (el.selected = v === "provider")}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label>
          Measure
          <select class="select select-sm" id="lg-metric" onChange={(ev) => setMetric(ev.currentTarget.value)}>
            {METRICS.map(([v, l]) => (
              <option value={v} ref={(el) => (el.selected = v === "cost")}>
                {l}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div class="content-grid charts">
        <Panel>
          <Guard>
            {(() => {
              const b = bucketsOf(requests())
              return (
                <TimeChart
                  id="lgc-requests"
                  title="Requests and errors"
                  desc="Requests per time bucket for the filtered logs, success and errors stacked."
                  times={b.times}
                  series={requestSeries(b)}
                  kind="bars"
                  {...props.zoom}
                  format={fmtInt}
                />
              )
            })()}
          </Guard>
        </Panel>
        <Panel>
          <Guard>
            {(() => {
              const b = bucketsOf(by())
              const m = metric()
              const series = m === "cost" ? groupSeries(b, "by_dimension") : m === "tokens" ? groupSeries(b, "by_dimension", "total_tokens") : groupSeries(b, "by_dimension", "p95_latency")
              return (
                <TimeChart
                  id="lgc-by"
                  title={metricLabel() + " by " + dimLabel().toLowerCase()}
                  desc={metricLabel() + " per time bucket, one series per " + dimLabel().toLowerCase() + "."}
                  times={b.times}
                  series={foldSeries(series)}
                  kind={m === "latency" ? "lines" : "bars"}
                  {...props.zoom}
                  format={m === "cost" ? money : m === "tokens" ? compact : ms}
                />
              )
            })()}
          </Guard>
        </Panel>
        <Panel>
          <Guard>
            <RankBars
              id="lgc-rank"
              title={"Top " + dimLabel().toLowerCase() + "s by requests"}
              rows={rankRows(ranks(), ["id"], "total_requests", (r) => fmtMoney(r.total_cost) + ", " + fmtInt(r.total_tokens) + " tokens, " + fmtMs(r.avg_latency))}
              format={fmtInt}
            />
          </Guard>
        </Panel>
      </div>
    </details>
  )
}

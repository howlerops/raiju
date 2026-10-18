// Small SVG charts: stacked bars and lines over time, and ranked bars. No chart library.
// Each chart is an <svg role="img"> with a title and a description, a legend for two or more
// series, a hover readout (also on the arrow keys) and a table of the same numbers.
// Series colours come from --c1..--c6 (categorical, fixed order) and --c-other.
import { createMemo, createSignal, For, onCleanup, Show } from "solid-js"
import { Table } from "./ui"

export interface Series {
  name: string
  values: number[]
}

export const MAX_SERIES = 6

// Keeps the largest series (by total) and folds the rest into "Other", so a colour always names
// the same entity within one chart and the legend stays short.
export function foldSeries(all: Series[], max: number = MAX_SERIES): Series[] {
  if (all.length <= max) return all
  const total = (s: Series) => s.values.reduce((a, b) => a + b, 0)
  const sorted = [...all].sort((a, b) => total(b) - total(a))
  const keep = sorted.slice(0, max - 1)
  const rest = sorted.slice(max - 1)
  const n = all[0]?.values.length ?? 0
  const other: number[] = []
  for (let i = 0; i < n; i++) other.push(rest.reduce((a, s) => a + (s.values[i] ?? 0), 0))
  return [...keep, { name: "Other", values: other }]
}

function color(i: number, name: string): string {
  return name === "Other" ? "var(--c-other)" : "var(--c" + ((i % MAX_SERIES) + 1) + ")"
}

// A rounded-up axis maximum: 1, 2, 2.5, 5 or 10 times a power of ten.
export function niceMax(v: number): number {
  if (!(v > 0)) return 1
  const p = Math.pow(10, Math.floor(Math.log10(v)))
  for (const m of [1, 2, 2.5, 5, 10]) if (v <= m * p) return m * p
  return 10 * p
}

function pad2(n: number): string {
  return n < 10 ? "0" + n : String(n)
}

function timeLabel(t: number, spanMs: number): string {
  const d = new Date(t)
  if (spanMs <= 36 * 3600000) return pad2(d.getHours()) + ":" + pad2(d.getMinutes())
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" })
}

function fullTime(t: number): string {
  return new Date(t).toLocaleString()
}

// the width of an element, kept up to date
function useWidth(initial: number) {
  const [w, setW] = createSignal(initial)
  let ro: ResizeObserver | undefined
  onCleanup(() => ro?.disconnect())
  const ref = (el: HTMLElement) => {
    setW(Math.max(220, Math.floor(el.clientWidth || initial)))
    if (typeof ResizeObserver === "undefined") return
    ro = new ResizeObserver(() => setW(Math.max(220, Math.floor(el.clientWidth || initial))))
    ro.observe(el)
  }
  return { w, ref }
}

export interface TimeChartProps {
  id: string
  title: string
  desc: string
  times: number[]
  series: Series[]
  kind: "bars" | "lines"
  // bars: stack the series (default true)
  stacked?: boolean
  format: (n: number) => string
  height?: number
}

export function TimeChart(props: TimeChartProps) {
  const { w, ref } = useWidth(600)
  const [hover, setHover] = createSignal(-1)
  const H = () => props.height ?? 200
  const ML = 46
  const MR = 8
  const MT = 8
  const MB = 22

  const n = () => props.times.length
  const plotW = () => Math.max(40, w() - ML - MR)
  const plotH = () => H() - MT - MB
  const stacked = () => props.kind === "bars" && props.stacked !== false
  const empty = () => n() === 0 || props.series.every((s) => s.values.every((v) => !(v > 0)))

  const yMax = createMemo(() => {
    let m = 0
    for (let i = 0; i < n(); i++) {
      if (stacked()) m = Math.max(m, props.series.reduce((a, s) => a + (s.values[i] ?? 0), 0))
      else for (const s of props.series) m = Math.max(m, s.values[i] ?? 0)
    }
    return niceMax(m)
  })
  const y = (v: number) => MT + plotH() * (1 - v / yMax())
  const step = () => plotW() / Math.max(1, n())
  const xBar = (i: number) => ML + i * step()
  const xPoint = (i: number) => (n() <= 1 ? ML + plotW() / 2 : ML + (i * plotW()) / (n() - 1))
  const spanMs = () => (n() > 1 ? props.times[n() - 1]! - props.times[0]! : 0)

  const yTicks = () => [0, 0.5, 1].map((f) => f * yMax())
  const xTicks = () => {
    if (n() === 0) return [] as number[]
    const count = Math.min(n(), Math.max(2, Math.floor(plotW() / 90)))
    const out: number[] = []
    for (let k = 0; k < count; k++) out.push(count === 1 ? 0 : Math.round((k * (n() - 1)) / (count - 1)))
    return [...new Set(out)]
  }
  const xAt = (i: number) => (props.kind === "bars" ? xBar(i) + step() / 2 : xPoint(i))

  const bars = createMemo(() => {
    const out: { x: number; y: number; w: number; h: number; c: string; key: string }[] = []
    if (props.kind !== "bars") return out
    const gap = step() > 6 ? 2 : 0
    const bw = Math.max(1, step() - gap)
    const k = props.series.length
    for (let i = 0; i < n(); i++) {
      let base = 0
      props.series.forEach((s, si) => {
        const v = s.values[i] ?? 0
        if (!(v > 0)) return
        if (stacked()) {
          const top = y(base + v)
          const h = Math.max(0, y(base) - top - (base > 0 ? 1 : 0))
          out.push({ x: xBar(i), y: top, w: bw, h, c: color(si, s.name), key: i + ":" + si })
          base += v
        } else {
          const sw = bw / k
          const top = y(v)
          out.push({ x: xBar(i) + si * sw, y: top, w: Math.max(1, sw - 1), h: y(0) - top, c: color(si, s.name), key: i + ":" + si })
        }
      })
    }
    return out
  })

  const lines = createMemo(() =>
    props.kind === "lines"
      ? props.series.map((s, si) => ({
          name: s.name,
          c: color(si, s.name),
          d: s.values.map((v, i) => (i === 0 ? "M" : "L") + xPoint(i).toFixed(1) + " " + y(v ?? 0).toFixed(1)).join(" "),
          pts: n() <= 40 ? s.values.map((v, i) => ({ x: xPoint(i), y: y(v ?? 0), i })) : [],
        }))
      : [],
  )

  const move = (ev: PointerEvent) => {
    const r = (ev.currentTarget as SVGElement).getBoundingClientRect()
    const x = ev.clientX - r.left - ML
    const i = props.kind === "bars" ? Math.floor(x / step()) : Math.round((x / plotW()) * (n() - 1))
    setHover(i >= 0 && i < n() ? i : -1)
  }
  const key = (ev: KeyboardEvent) => {
    if (ev.key === "ArrowRight") setHover(Math.min(n() - 1, hover() + 1))
    else if (ev.key === "ArrowLeft") setHover(Math.max(0, hover() < 0 ? n() - 1 : hover() - 1))
    else if (ev.key === "Escape") setHover(-1)
    else return
    ev.preventDefault()
  }

  const tipLeft = () => {
    const x = xAt(hover())
    return x > w() / 2 ? { right: w() - x + 10 + "px" } : { left: x + 10 + "px" }
  }

  return (
    <figure class="chart" id={props.id} ref={ref}>
      <figcaption>{props.title}</figcaption>
      <Show when={!empty()} fallback={<p class="muted chart-empty">No data in this period.</p>}>
        <Show when={props.series.length > 1}>
          <ul class="legend" aria-label={props.title + " legend"}>
            <For each={props.series} keyed={(s) => s.name}>
              {(s) => (
                <li>
                  <span class="swatch" style={{ background: color(props.series.findIndex((x) => x.name === s().name), s().name) }}></span>
                  {s().name}
                </li>
              )}
            </For>
          </ul>
        </Show>
        <div class="chart-plot">
          <svg
            width={w()}
            height={H()}
            viewBox={"0 0 " + w() + " " + H()}
            role="img"
            aria-labelledby={props.id + "-t " + props.id + "-d"}
            tabindex="0"
            onPointerMove={move}
            onPointerLeave={() => setHover(-1)}
            onKeyDown={key}
            onBlur={() => setHover(-1)}
          >
            <title id={props.id + "-t"}>{props.title}</title>
            <desc id={props.id + "-d"}>{props.desc + " Arrow keys read single points; the table below has every value."}</desc>
            <For each={yTicks()}>
              {(t) => (
                <g>
                  <line class="grid" x1={ML} x2={ML + plotW()} y1={y(t)} y2={y(t)} />
                  <text class="axis" x={ML - 6} y={y(t) + 4} text-anchor="end">
                    {props.format(t)}
                  </text>
                </g>
              )}
            </For>
            <For each={xTicks()}>
              {(i) => (
                <text class="axis" x={Math.min(w() - MR - 14, Math.max(ML + 14, xAt(i)))} y={H() - 6} text-anchor="middle">
                  {timeLabel(props.times[i]!, spanMs())}
                </text>
              )}
            </For>
            <For each={bars()} keyed={(b) => b.key}>
              {(b) => <rect class="bar" x={b().x} y={b().y} width={b().w} height={b().h} fill={b().c} />}
            </For>
            <For each={lines()} keyed={(l) => l.name}>
              {(l) => (
                <g>
                  <path d={l().d} fill="none" stroke={l().c} stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
                  <For each={l().pts} keyed={(p) => p.i}>
                    {(p) => <circle cx={p().x} cy={p().y} r="2.5" fill={l().c} stroke="var(--surface)" stroke-width="1.5" />}
                  </For>
                </g>
              )}
            </For>
            <Show when={hover() >= 0}>
              <line class="cross" x1={xAt(hover())} x2={xAt(hover())} y1={MT} y2={MT + plotH()} />
            </Show>
          </svg>
          <Show when={hover() >= 0}>
            <div class="chart-tip" role="status" style={tipLeft()}>
              <strong>{fullTime(props.times[hover()]!)}</strong>
              <For each={props.series} keyed={(s) => s.name}>
                {(s) => (
                  <div>
                    <span class="swatch" style={{ background: color(props.series.findIndex((x) => x.name === s().name), s().name) }}></span>
                    {s().name}: {props.format(s().values[hover()] ?? 0)}
                  </div>
                )}
              </For>
            </div>
          </Show>
        </div>
        <details class="chart-table">
          <summary>Data table</summary>
          <Table cols={["Time", ...props.series.map((s) => s.name)]}>
            <For each={props.times.map((t, i) => i)}>
              {(i) => (
                <tr>
                  <td class="nowrap">{fullTime(props.times[i]!)}</td>
                  <For each={props.series}>{(s) => <td>{props.format(s.values[i] ?? 0)}</td>}</For>
                </tr>
              )}
            </For>
          </Table>
        </details>
      </Show>
    </figure>
  )
}

export interface RankRow {
  label: string
  value: number
  detail?: string
}

// Ranked horizontal bars. The list is its own text alternative: label, value and detail are text.
export function RankBars(props: { id: string; title: string; rows: RankRow[]; format: (n: number) => string; empty?: string }) {
  const max = () => Math.max(1e-9, ...props.rows.map((r) => r.value))
  return (
    <figure class="chart" id={props.id}>
      <figcaption>{props.title}</figcaption>
      <Show when={props.rows.length} fallback={<p class="muted chart-empty">{props.empty ?? "No data in this period."}</p>}>
        <ol class="rank" aria-label={props.title}>
          <For each={props.rows} keyed={(r) => r.label}>
            {(r, i) => (
              <li>
                <div class="rank-head">
                  <span class="mono rank-label">{r().label || "—"}</span>
                  <span class="rank-value">{props.format(r().value)}</span>
                </div>
                <div class="rank-track" aria-hidden="true">
                  <div class="rank-fill" style={{ width: Math.max(1.5, (100 * r().value) / max()) + "%", background: color(i(), r().label) }}></div>
                </div>
                <Show when={r().detail}>
                  <div class="hint">{r().detail}</div>
                </Show>
              </li>
            )}
          </For>
        </ol>
      </Show>
    </figure>
  )
}

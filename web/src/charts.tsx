// Small SVG charts: stacked bars and lines over time, and ranked bars. No chart library.
// Each chart is an <svg role="img"> with a title and a description, a legend for two or more
// series (each entry a button that hides or shows its series; the axis rescales), a hover
// readout (also on the arrow keys), a drag-to-zoom time range (Shift+arrows then Enter from the
// keyboard) and a table of the same numbers.
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

// The series each chart has switched off, by chart id. Kept at module level so a chart that is
// drawn again after a refetch keeps its toggles.
const [hiddenByChart, setHiddenByChart] = createSignal<Record<string, string[]>>({})

function toggleSeries(id: string, name: string): void {
  setHiddenByChart((m) => {
    const cur = m[id] ?? []
    return { ...m, [id]: cur.includes(name) ? cur.filter((x) => x !== name) : [...cur, name] }
  })
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
  // called with the chosen time range (epoch ms, start inclusive, end exclusive) after a drag
  // selection, or Shift+arrows then Enter; a chart without it cannot be zoomed
  onZoom?: (start: number, end: number) => void
  // true while the screen shows a zoomed range; the reset button then appears
  zoomed?: boolean
  onReset?: () => void
}

export function TimeChart(props: TimeChartProps) {
  const { w, ref } = useWidth(600)
  const [hover, setHover] = createSignal(-1)
  // the selected bucket range [a, b] (a may be above b while dragging), and the drag state
  const [sel, setSel] = createSignal<[number, number] | undefined>(undefined)
  let dragFrom = -1
  let dragX0 = 0
  let dragMoved = false
  const H = () => props.height ?? 200
  const ML = 46
  const MR = 8
  const MT = 8
  const MB = 22

  const n = () => props.times.length
  const hidden = () => hiddenByChart()[props.id] ?? []
  // the series that are drawn; a colour stays with the series' place in the full list
  const shown = () => props.series.filter((s) => !hidden().includes(s.name))
  const colorOf = (s: Series) => color(props.series.findIndex((x) => x.name === s.name), s.name)
  const bucketMs = () => (n() > 1 ? props.times[1]! - props.times[0]! : 60000)
  const plotW = () => Math.max(40, w() - ML - MR)
  const plotH = () => H() - MT - MB
  const stacked = () => props.kind === "bars" && props.stacked !== false
  const empty = () => n() === 0 || props.series.every((s) => s.values.every((v) => !(v > 0)))

  const yMax = createMemo(() => {
    let m = 0
    for (let i = 0; i < n(); i++) {
      if (stacked()) m = Math.max(m, shown().reduce((a, s) => a + (s.values[i] ?? 0), 0))
      else for (const s of shown()) m = Math.max(m, s.values[i] ?? 0)
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
    const k = Math.max(1, shown().length)
    for (let i = 0; i < n(); i++) {
      let base = 0
      shown().forEach((s, si) => {
        const v = s.values[i] ?? 0
        if (!(v > 0)) return
        if (stacked()) {
          const top = y(base + v)
          const h = Math.max(0, y(base) - top - (base > 0 ? 1 : 0))
          out.push({ x: xBar(i), y: top, w: bw, h, c: colorOf(s), key: i + ":" + s.name })
          base += v
        } else {
          const sw = bw / k
          const top = y(v)
          out.push({ x: xBar(i) + si * sw, y: top, w: Math.max(1, sw - 1), h: y(0) - top, c: colorOf(s), key: i + ":" + s.name })
        }
      })
    }
    return out
  })

  const lines = createMemo(() =>
    props.kind === "lines"
      ? shown().map((s) => ({
          name: s.name,
          c: colorOf(s),
          d: s.values.map((v, i) => (i === 0 ? "M" : "L") + xPoint(i).toFixed(1) + " " + y(v ?? 0).toFixed(1)).join(" "),
          pts: n() <= 40 ? s.values.map((v, i) => ({ x: xPoint(i), y: y(v ?? 0), i })) : [],
        }))
      : [],
  )

  const indexAt = (ev: PointerEvent): number => {
    const r = (ev.currentTarget as SVGElement).getBoundingClientRect()
    const x = ev.clientX - r.left - ML
    return props.kind === "bars" ? Math.floor(x / step()) : Math.round((x / plotW()) * (n() - 1))
  }
  const clampIdx = (i: number) => Math.max(0, Math.min(n() - 1, i))
  const zoomable = () => props.onZoom !== undefined && n() > 0

  const move = (ev: PointerEvent) => {
    const i = indexAt(ev)
    setHover(i >= 0 && i < n() ? i : -1)
    if (dragFrom >= 0) {
      if (Math.abs(ev.clientX - dragX0) > 4) dragMoved = true
      if (dragMoved) setSel([dragFrom, clampIdx(i)])
    }
  }
  const down = (ev: PointerEvent) => {
    if (!zoomable() || ev.button !== 0) return
    dragFrom = clampIdx(indexAt(ev))
    dragX0 = ev.clientX
    dragMoved = false
    try {
      ;(ev.currentTarget as SVGElement).setPointerCapture(ev.pointerId)
    } catch {
      // a synthetic pointer cannot be captured; the drag still works inside the plot
    }
  }
  const bounds = (): [number, number] | undefined => {
    const s = sel()
    return s ? [Math.min(s[0], s[1]), Math.max(s[0], s[1])] : undefined
  }
  // a line chart needs two points for a range; a bar chart may take one bucket
  const rangeOk = (b: [number, number]) => props.kind === "bars" || b[0] < b[1]
  const applySel = () => {
    const b = bounds()
    setSel(undefined)
    if (!b || !props.onZoom || !rangeOk(b)) return
    const start = props.times[b[0]]!
    const end = props.times[b[1]]! + (props.kind === "bars" ? bucketMs() : 0)
    if (end > start) props.onZoom(start, end)
  }
  const up = (ev: PointerEvent) => {
    if (dragFrom < 0) return
    const wasDrag = dragMoved
    dragFrom = -1
    dragMoved = false
    try {
      ;(ev.currentTarget as SVGElement).releasePointerCapture(ev.pointerId)
    } catch {
      // nothing was captured
    }
    if (wasDrag) applySel()
    else setSel(undefined)
  }
  const key = (ev: KeyboardEvent) => {
    if (ev.shiftKey && (ev.key === "ArrowRight" || ev.key === "ArrowLeft") && zoomable()) {
      const dir = ev.key === "ArrowRight" ? 1 : -1
      const s = sel()
      if (s) {
        const next = clampIdx(s[1] + dir)
        setSel([s[0], next])
        setHover(next)
      } else {
        const at = hover() < 0 ? (dir > 0 ? 0 : n() - 1) : hover()
        const next = clampIdx(at + dir)
        setSel([at, next])
        setHover(next)
      }
    } else if (ev.key === "Enter" && sel()) applySel()
    else if (ev.key === "ArrowRight") setHover(Math.min(n() - 1, hover() + 1))
    else if (ev.key === "ArrowLeft") setHover(Math.max(0, hover() < 0 ? n() - 1 : hover() - 1))
    else if (ev.key === "Escape") {
      if (sel()) setSel(undefined)
      else setHover(-1)
    } else return
    ev.preventDefault()
  }
  const selLabel = () => {
    const b = bounds()
    if (!b) return ""
    return fullTime(props.times[b[0]]!) + " to " + fullTime(props.times[b[1]]! + (props.kind === "bars" ? bucketMs() : 0))
  }

  const tipLeft = () => {
    const x = xAt(hover())
    return x > w() / 2 ? { right: w() - x + 10 + "px" } : { left: x + 10 + "px" }
  }

  return (
    <figure class="chart" id={props.id} ref={ref}>
      <figcaption>{props.title}</figcaption>
      <Show when={props.zoomed || bounds()}>
        <div class="zoom-bar">
          <Show when={bounds()}>
            <span class="hint" role="status">
              {selLabel()}
            </span>
            <button type="button" class="zoom-apply" disabled={!rangeOk(bounds()!)} onClick={applySel}>
              Zoom to selection
            </button>
          </Show>
          <Show when={props.zoomed && props.onReset}>
            <button type="button" class="ghost zoom-reset" onClick={() => props.onReset!()}>
              Reset zoom
            </button>
          </Show>
        </div>
      </Show>
      <Show when={!empty()} fallback={<p class="muted chart-empty">No data in this period.</p>}>
        <Show when={props.series.length > 1}>
          <ul class="legend" aria-label={props.title + " legend"}>
            <For each={props.series} keyed={(s) => s.name}>
              {(s) => (
                <li>
                  <button
                    type="button"
                    class="legend-toggle"
                    aria-pressed={hidden().includes(s().name) ? "false" : "true"}
                    title={(hidden().includes(s().name) ? "Show " : "Hide ") + s().name}
                    onClick={() => toggleSeries(props.id, s().name)}
                  >
                    <span class="swatch" style={{ background: colorOf(s()) }}></span>
                    {s().name}
                  </button>
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
            onPointerDown={down}
            onPointerMove={move}
            onPointerUp={up}
            onPointerCancel={() => {
              dragFrom = -1
              dragMoved = false
              setSel(undefined)
            }}
            onPointerLeave={() => dragFrom < 0 && setHover(-1)}
            onKeyDown={key}
            onBlur={() => setHover(-1)}
          >
            <title id={props.id + "-t"}>{props.title}</title>
            <desc id={props.id + "-d"}>{props.desc + " Arrow keys read single points; the table below has every value." + (props.onZoom ? " Drag across the chart, or hold Shift with the arrow keys and press Enter, to zoom to a time range." : "")}</desc>
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
            <Show when={bounds()}>
              {(b) => (
                <rect
                  class="sel"
                  x={props.kind === "bars" ? xBar(b()[0]) : xPoint(b()[0])}
                  y={MT}
                  width={Math.max(2, props.kind === "bars" ? (b()[1] - b()[0] + 1) * step() : xPoint(b()[1]) - xPoint(b()[0]))}
                  height={plotH()}
                />
              )}
            </Show>
            <Show when={hover() >= 0}>
              <line class="cross" x1={xAt(hover())} x2={xAt(hover())} y1={MT} y2={MT + plotH()} />
            </Show>
          </svg>
          <Show when={hover() >= 0}>
            <div class="chart-tip" role="status" style={tipLeft()}>
              <strong>{fullTime(props.times[hover()]!)}</strong>
              <For each={shown()} keyed={(s) => s.name}>
                {(s) => (
                  <div>
                    <span class="swatch" style={{ background: colorOf(s()) }}></span>
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

// ---- the crew frontier: cost on a log axis against quality (docs/crew-routing.md) ----

export interface FrontierMark {
  label: string
  cost: number
  quality: number
}

export interface FrontierProps {
  id: string
  title: string
  desc: string
  // the hull vertices of the class frontier
  frontier: FrontierMark[]
  // the uniform crews (one candidate for every role), drawn as a second series when the listing gives them
  uniform?: FrontierMark[]
  // the knee of the frontier (Def. 6)
  knee?: FrontierMark
  // the crew the class's multiplier picks
  current?: FrontierMark
  costFormat: (n: number) => string
  qualityFormat: (n: number) => string
  height?: number
}

// The cost axis is logarithmic, from a power of ten at or below the least positive cost to one at or above the most.
// A free crew (cost 0) sits on the left edge.
export function logCostDomain(costs: number[]): [number, number] {
  const pos = costs.filter((c) => c > 0)
  if (pos.length === 0) return [0.001, 1]
  let lo = Math.min(...pos)
  let hi = Math.max(...pos)
  if (lo === hi) {
    lo = lo / 2
    hi = hi * 2
  }
  return [Math.pow(10, Math.floor(Math.log10(lo))), Math.pow(10, Math.ceil(Math.log10(hi)))]
}

// The quality axis: the range of the points with some room, within 0..1.
export function qualityDomain(qs: number[]): [number, number] {
  if (qs.length === 0) return [0, 1]
  const lo = Math.min(...qs)
  const hi = Math.max(...qs)
  const pad = Math.max(0.02, (hi - lo) * 0.15)
  return [Math.max(0, lo - pad), Math.min(1, hi + pad)]
}

export function FrontierChart(props: FrontierProps) {
  const { w, ref } = useWidth(600)
  // the index of the hovered frontier vertex (in cost order), -1 for none
  const [hover, setHover] = createSignal(-1)
  const H = () => props.height ?? 260
  const ML = 60
  const MR = 12
  const MT = 10
  const MB = 30

  // the frontier in cost order: the arrow keys and the pointer walk it
  const sorted = createMemo(() => [...props.frontier].sort((a, b) => a.cost - b.cost))
  const everything = () => [...props.frontier, ...(props.uniform ?? []), ...(props.knee ? [props.knee] : []), ...(props.current ? [props.current] : [])]
  const xDom = createMemo(() => logCostDomain(everything().map((p) => p.cost)))
  const yDom = createMemo(() => qualityDomain(everything().map((p) => p.quality)))
  const plotW = () => Math.max(40, w() - ML - MR)
  const plotH = () => H() - MT - MB
  const xOf = (c: number): number => {
    const [lo, hi] = xDom()
    const t = (Math.log10(Math.max(c, lo)) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))
    return ML + t * plotW()
  }
  const yOf = (q: number): number => {
    const [lo, hi] = yDom()
    return MT + plotH() * (1 - (q - lo) / (hi - lo))
  }
  const xTicks = createMemo((): number[] => {
    const [lo, hi] = xDom()
    const out: number[] = []
    for (let k = Math.floor(Math.log10(lo)); k <= Math.ceil(Math.log10(hi)); k++) {
      const v = Math.pow(10, k)
      if (v >= lo && v <= hi) out.push(v)
    }
    return out
  })
  const yTicks = createMemo((): number[] => {
    const [lo, hi] = yDom()
    return [0, 0.5, 1].map((f) => lo + f * (hi - lo))
  })
  const frontierPts = createMemo(() => sorted().map((p, i) => ({ key: "f" + i, x: xOf(p.cost), y: yOf(p.quality), i })))
  const uniformPts = createMemo(() => (props.uniform ?? []).map((p, i) => ({ key: "u" + i, x: xOf(p.cost), y: yOf(p.quality) })))

  // the frontier vertex nearest the pointer, by cost
  const nearest = (ev: PointerEvent): number => {
    const r = (ev.currentTarget as SVGElement).getBoundingClientRect()
    const x = ev.clientX - r.left
    let best = -1
    let bestD = Infinity
    sorted().forEach((p, i) => {
      const d = Math.abs(xOf(p.cost) - x)
      if (d < bestD) {
        bestD = d
        best = i
      }
    })
    return best
  }
  const move = (ev: PointerEvent) => setHover(nearest(ev))
  const key = (ev: KeyboardEvent) => {
    const n = sorted().length
    if (ev.key === "ArrowRight" || ev.key === "ArrowUp") setHover(Math.min(n - 1, hover() + 1))
    else if (ev.key === "ArrowLeft" || ev.key === "ArrowDown") setHover(Math.max(0, hover() < 0 ? n - 1 : hover() - 1))
    else if (ev.key === "Escape") setHover(-1)
    else return
    ev.preventDefault()
  }
  const hovered = (): FrontierMark | undefined => (hover() >= 0 && hover() < sorted().length ? sorted()[hover()] : undefined)
  const tipLeft = () => {
    const p = hovered()
    if (!p) return {}
    const x = xOf(p.cost)
    return x > w() / 2 ? { right: w() - x + 10 + "px" } : { left: x + 10 + "px" }
  }
  const kneeXY = () => (props.knee ? { x: xOf(props.knee.cost), y: yOf(props.knee.quality) } : undefined)
  const curXY = () => (props.current ? { x: xOf(props.current.cost), y: yOf(props.current.quality) } : undefined)

  return (
    <figure class="chart" id={props.id} ref={ref}>
      <figcaption>{props.title}</figcaption>
      <Show when={props.frontier.length > 0} fallback={<p class="muted chart-empty">No frontier: the class has no crew to price.</p>}>
        <ul class="legend" aria-label={props.title + " legend"}>
          <li>
            <span class="swatch" style={{ background: "var(--c1)" }}></span>Frontier crew
          </li>
          <Show when={props.knee}>
            <li>
              <span class="swatch" style={{ background: "var(--c2)" }}></span>Knee
            </li>
          </Show>
          <Show when={props.current}>
            <li>
              <span class="swatch" style={{ background: "var(--c4)" }}></span>Crew at the current multiplier
            </li>
          </Show>
          <Show when={(props.uniform ?? []).length > 0}>
            <li>
              <span class="swatch" style={{ background: "var(--c-other)" }}></span>Uniform crew
            </li>
          </Show>
        </ul>
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
            <desc id={props.id + "-d"}>{props.desc + " Arrow keys read the frontier crews one by one; the table below has every value."}</desc>
            <For each={yTicks()}>
              {(t) => (
                <g>
                  <line class="grid" x1={ML} x2={ML + plotW()} y1={yOf(t)} y2={yOf(t)} />
                  <text class="axis" x={ML - 6} y={yOf(t) + 4} text-anchor="end">
                    {props.qualityFormat(t)}
                  </text>
                </g>
              )}
            </For>
            <For each={xTicks()}>
              {(t) => (
                <g>
                  <line class="grid" x1={xOf(t)} x2={xOf(t)} y1={MT} y2={MT + plotH()} />
                  <text class="axis" x={xOf(t)} y={H() - 14} text-anchor="middle">
                    {props.costFormat(t)}
                  </text>
                </g>
              )}
            </For>
            <text class="axis" x={ML + plotW() / 2} y={H() - 2} text-anchor="middle">
              cost per task, log scale
            </text>
            <For each={uniformPts()} keyed={(u) => u.key}>
              {(u) => <circle cx={u().x} cy={u().y} r="3.5" fill="none" stroke="var(--c-other)" stroke-width="1.5" />}
            </For>
            <For each={frontierPts()} keyed={(f) => f.key}>
              {(f) => <circle cx={f().x} cy={f().y} r={f().i === hover() ? 6 : 4} fill="var(--c1)" stroke="var(--surface)" stroke-width="1.5" />}
            </For>
            <Show when={kneeXY()}>
              {(k) => (
                <polygon
                  points={`${k().x},${k().y - 7} ${k().x + 7},${k().y} ${k().x},${k().y + 7} ${k().x - 7},${k().y}`}
                  fill="var(--c2)"
                  stroke="var(--surface)"
                  stroke-width="1"
                />
              )}
            </Show>
            <Show when={curXY()}>
              {(c) => <circle cx={c().x} cy={c().y} r="9" fill="none" stroke="var(--c4)" stroke-width="2.5" />}
            </Show>
            <Show when={hovered()}>
              {(p) => <line class="cross" x1={xOf(p().cost)} x2={xOf(p().cost)} y1={MT} y2={MT + plotH()} />}
            </Show>
          </svg>
          <Show when={hovered()}>
            {(p) => (
              <div class="chart-tip" role="status" style={tipLeft()}>
                <strong>{p().label}</strong>
                <div>Cost: {props.costFormat(p().cost)}</div>
                <div>Quality: {props.qualityFormat(p().quality)}</div>
              </div>
            )}
          </Show>
        </div>
        <details class="chart-table">
          <summary>Data table</summary>
          <Table cols={["Crew", "Kind", "Cost per task", "Quality"]}>
            <For each={sorted()}>
              {(p) => (
                <tr>
                  <td>{p.label}</td>
                  <td>{p.label === props.current?.label ? "frontier, current" : "frontier"}</td>
                  <td>{props.costFormat(p.cost)}</td>
                  <td>{props.qualityFormat(p.quality)}</td>
                </tr>
              )}
            </For>
            <For each={props.uniform ?? []}>
              {(p) => (
                <tr>
                  <td>{p.label}</td>
                  <td>uniform</td>
                  <td>{props.costFormat(p.cost)}</td>
                  <td>{props.qualityFormat(p.quality)}</td>
                </tr>
              )}
            </For>
            <Show when={props.knee}>
              {(k) => (
                <tr>
                  <td>{k().label}</td>
                  <td>knee</td>
                  <td>{props.costFormat(k().cost)}</td>
                  <td>{props.qualityFormat(k().quality)}</td>
                </tr>
              )}
            </Show>
          </Table>
        </details>
      </Show>
    </figure>
  )
}

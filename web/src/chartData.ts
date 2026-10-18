// Turns the log histogram and ranking responses (/api/logs/histogram*, /api/logs/rankings*,
// /api/logs/dashboard) into the series and rows the charts draw.
import type { RankRow, Series } from "./charts"
import { num } from "./fmt"

type Obj = Record<string, unknown>
const obj = (v: unknown): Obj => (v && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : {})
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : [])

export interface Buckets {
  times: number[]
  rows: Obj[]
}

export function bucketsOf(body: unknown): Buckets {
  const rows = arr(obj(body).buckets).map(obj)
  return { times: rows.map((r) => Date.parse(String(r.timestamp ?? "")) || 0), rows }
}

function field(b: Buckets, name: string, label: string): Series {
  return { name: label, values: b.rows.map((r) => num(r[name])) }
}

export function requestSeries(b: Buckets): Series[] {
  return [field(b, "success", "Success"), field(b, "error", "Errors"), field(b, "cancelled", "Cancelled")].filter(
    (s, i) => i < 2 || s.values.some((v) => v > 0),
  )
}

export function latencySeries(b: Buckets): Series[] {
  return [field(b, "avg_latency", "Average"), field(b, "p90_latency", "p90"), field(b, "p95_latency", "p95"), field(b, "p99_latency", "p99")]
}

export function tokenSeries(b: Buckets): Series[] {
  return [field(b, "prompt_tokens", "Prompt"), field(b, "completion_tokens", "Completion")]
}

export function costSeries(b: Buckets): Series[] {
  return [field(b, "total_cost", "Cost")]
}

// One series per key of a per-bucket map (by_model, by_provider, by_dimension). pick reads the
// number out of a value that is an object (tokens, latency) rather than a number (cost).
export function groupSeries(b: Buckets, mapName: string, pick?: string): Series[] {
  const keys: string[] = []
  for (const r of b.rows) for (const k of Object.keys(obj(r[mapName]))) if (!keys.includes(k)) keys.push(k)
  return keys.map((k) => ({
    name: k || "(none)",
    values: b.rows.map((r) => {
      const v = obj(r[mapName])[k]
      return pick ? num(obj(v)[pick]) : num(v)
    }),
  }))
}

export function rankRows(body: unknown, labelKeys: string[], valueKey: string, detail?: (r: Obj) => string): RankRow[] {
  return arr(obj(body).rankings)
    .map(obj)
    .map((r) => {
      let label = ""
      for (const k of labelKeys) if (r[k]) label += (label ? " / " : "") + String(r[k])
      return { label, value: num(r[valueKey]), detail: detail ? detail(r) : undefined }
    })
}

export { obj, arr }

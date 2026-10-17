// Number, time and text formatting shared by the screens.

export function num(v: unknown): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

export function fmtInt(v: unknown): string {
  return num(v).toLocaleString()
}

export function fmtMoney(v: unknown): string {
  return "$" + num(v).toFixed(4)
}

export function fmtMs(v: unknown): string {
  const n = num(v)
  return (n < 10 ? n.toFixed(1) : Math.round(n).toLocaleString()) + " ms"
}

// A fraction (0..1) or a percentage already (>1)
export function fmtPct(fraction: unknown): string {
  let n = num(fraction)
  if (n <= 1) n *= 100
  return n.toFixed(1) + "%"
}

export function fmtTime(ts: unknown): string {
  let n = num(ts)
  if (n > 0 && n < 1e12) n *= 1000
  return n > 0 ? new Date(n).toLocaleString() : "—"
}

export function splitList(s: string): string[] {
  return s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean)
}

export function pretty(v: unknown): string {
  let x = v
  if (typeof x === "string") {
    try {
      x = JSON.parse(x)
    } catch {
      return x as string
    }
  }
  try {
    return JSON.stringify(x, null, 2)
  } catch {
    return String(x)
  }
}

export function contentText(c: unknown): string {
  if (typeof c === "string") return c
  if (Array.isArray(c)) {
    return c.map((p) => (p && typeof (p as { text?: unknown }).text === "string" ? (p as { text: string }).text : "")).join("")
  }
  return ""
}

// The first array in a response body, for list endpoints whose key may vary.
export function listOf<T = unknown>(body: unknown, key: string): T[] {
  if (Array.isArray(body)) return body as T[]
  if (body && typeof body === "object") {
    const o = body as Record<string, unknown>
    const hit = o[key]
    if (Array.isArray(hit)) return hit as T[]
    for (const k of Object.keys(o)) {
      const v = o[k]
      if (Array.isArray(v)) return v as T[]
    }
  }
  return []
}

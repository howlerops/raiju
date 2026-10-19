// The live request feed: a ticketed /ws connection with reconnect and backoff,
// a capped newest-first buffer, and pause/resume.
//
// The socket sends {"type":"log","data":{...}} envelopes. This also accepts
// batched messages (a JSON array of envelopes, or "data" holding an array),
// an optional "node" on the envelope or the entry, and an optional event id.
import { createSignal, type Accessor } from "solid-js"
import { api } from "./api/client"
import type { LogEntry } from "./api/types"

export const LIVE_MAX = 5000

export interface LiveRow extends LogEntry {
  node?: string
}

export type LiveState = "stopped" | "connecting" | "live" | "waiting"

export interface Feed {
  rows: Accessor<LiveRow[]>
  state: Accessor<LiveState>
  waitText: Accessor<string>
  note: Accessor<string>
  paused: Accessor<boolean>
  queued: Accessor<number>
  sawNode: Accessor<boolean>
  nodes: Accessor<string[]>
  gap: Accessor<boolean>
  start: () => void
  stop: () => void
  pause: () => void
  resume: () => void
  clear: () => void
  // new rows prepended by the last flush, for scroll anchoring
  onPrepend: (fn: (n: number) => void) => void
}

function asEntry(v: unknown, node: string | undefined): LiveRow | undefined {
  if (!v || typeof v !== "object") return undefined
  const e = v as Record<string, unknown>
  if (e.id === undefined || e.id === null) return undefined
  const row = e as unknown as LiveRow
  const n = typeof e.node === "string" && e.node ? e.node : node
  return n && row.node !== n ? { ...row, node: n } : row
}

// What one decoded socket message holds.
export interface Parsed {
  rows: LiveRow[]
  // [producer, seq] of each event message, for the resume cursors
  cursors: [string, number][]
  gap: boolean
  resumed: boolean
}

function walk(msg: unknown, inherited: string | undefined, out: Parsed): void {
  if (Array.isArray(msg)) {
    for (const m of msg) walk(m, inherited, out)
    return
  }
  if (!msg || typeof msg !== "object") return
  const m = msg as Record<string, unknown>
  const node = typeof m.node === "string" && m.node ? m.node : inherited
  if (m.type === "gap") {
    out.gap = true
    return
  }
  if (m.type === "resumed") {
    out.resumed = true
    return
  }
  const isEvent = m.type === "log" || (m.type === undefined && m.data !== undefined)
  if (!isEvent) {
    // a batch wrapper: {"events":[...]} or {"type":"batch","data":[...]}
    if (Array.isArray(m.events)) walk(m.events, node, out)
    else if (m.type === "batch" && Array.isArray(m.data)) walk(m.data, node, out)
    return
  }
  const data = m.data
  const list = Array.isArray(data) ? data : [data]
  for (const d of list) {
    const r = asEntry(d, node)
    if (r) out.rows.push(r)
  }
  // id is "<producer>:<seq>"; the producer may hold ":" itself, the seq is after the last one
  if (typeof m.id === "string" && typeof m.seq === "number") {
    const i = m.id.lastIndexOf(":")
    out.cursors.push([i > 0 ? m.id.slice(0, i) : m.id, m.seq])
  }
}

export function parseMessage(msg: unknown): Parsed {
  const out: Parsed = { rows: [], cursors: [], gap: false, resumed: false }
  walk(msg, undefined, out)
  return out
}

// The log entries of one decoded message of any supported shape.
export function entriesOf(msg: unknown): LiveRow[] {
  return parseMessage(msg).rows
}

export function createFeed(): Feed {
  const [rows, setRows] = createSignal<LiveRow[]>([])
  const [state, setState] = createSignal<LiveState>("stopped")
  const [waitText, setWaitText] = createSignal("")
  const [note, setNote] = createSignal("")
  const [paused, setPaused] = createSignal(false)
  const [queued, setQueued] = createSignal(0)
  const [sawNode, setSawNode] = createSignal(false)
  const [nodes, setNodes] = createSignal<string[]>([])
  const [gap, setGap] = createSignal(false)
  // the highest seq seen per producer, sent as since= on a reconnect
  const cursors = new Map<string, number>()

  let want = false
  let retry = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let ws: WebSocket | undefined
  let incoming: LiveRow[] = [] // oldest first, waiting for the next flush
  let held: LiveRow[] = [] // arrived while paused
  let flushTimer: ReturnType<typeof setTimeout> | undefined
  let prepend: (n: number) => void = () => {}
  const seen = new Set<string>()

  const flush = () => {
    flushTimer = undefined
    if (!incoming.length) return
    const batch = incoming
    incoming = []
    // newest first
    const fresh = batch.slice().reverse()
    setRows((old) => {
      const merged = fresh.concat(old)
      if (merged.length > LIVE_MAX) {
        for (let i = LIVE_MAX; i < merged.length; i++) seen.delete(merged[i]!.id)
        merged.length = LIVE_MAX
      }
      return merged
    })
    prepend(fresh.length)
  }

  const accept = (r: LiveRow) => {
    if (seen.has(r.id)) return
    seen.add(r.id)
    if (r.node) {
      setSawNode(true)
      const n = r.node
      if (!nodes().includes(n)) setNodes((l) => [...l, n].sort())
    }
    if (paused()) {
      held.push(r)
      if (held.length > LIVE_MAX) {
        const dropped = held.shift()
        if (dropped) seen.delete(dropped.id)
      }
      setQueued(held.length)
      return
    }
    incoming.push(r)
    if (flushTimer === undefined) flushTimer = setTimeout(flush, 100)
  }

  const onMessage = (text: string) => {
    let msg: unknown
    try {
      msg = JSON.parse(text)
    } catch {
      return
    }
    const p = parseMessage(msg)
    if (p.gap) setGap(true)
    for (const [k, s] of p.cursors) if (s > (cursors.get(k) ?? -1)) cursors.set(k, s)
    for (const r of p.rows) accept(r)
  }

  const scheduleRetry = () => {
    if (!want) return
    const delay = Math.min(30000, 1000 * Math.pow(2, retry))
    retry += 1
    setState("waiting")
    setWaitText("Reconnecting in " + Math.round(delay / 1000) + " s")
    clearTimeout(timer)
    timer = setTimeout(() => {
      timer = undefined
      void connect()
    }, delay)
  }

  const connect = async (): Promise<void> => {
    if (!want) return
    setState("connecting")
    setWaitText("Connecting")
    let ticket = ""
    try {
      const r = await api.post("/api/session/ws-ticket")
      ticket = r && r.ticket ? String(r.ticket) : ""
    } catch (e) {
      setNote("Live feed: " + (e instanceof Error ? e.message : String(e)))
      return scheduleRetry()
    }
    if (!want) return
    if (!ticket) return scheduleRetry()
    const proto = location.protocol === "https:" ? "wss:" : "ws:"
    let url = proto + "//" + location.host + "/ws?batch=1&ticket=" + encodeURIComponent(ticket)
    if (cursors.size) url += "&since=" + [...cursors].map(([k, s]) => k + ":" + s).join(",")
    let sock: WebSocket
    try {
      sock = new WebSocket(url)
    } catch (e) {
      setNote("Live feed: " + (e instanceof Error ? e.message : String(e)))
      return scheduleRetry()
    }
    ws = sock
    sock.onopen = () => {
      retry = 0
      setWaitText("")
      setNote("")
      setState("live")
    }
    sock.onmessage = (ev) => onMessage(String(ev.data))
    sock.onclose = () => {
      if (ws === sock) ws = undefined
      scheduleRetry()
    }
    sock.onerror = () => {}
  }

  return {
    rows,
    state,
    waitText,
    note,
    paused,
    queued,
    sawNode,
    nodes,
    gap,
    start() {
      if (want) return
      want = true
      retry = 0
      void connect()
    },
    stop() {
      want = false
      setState("stopped")
      clearTimeout(timer)
      timer = undefined
      clearTimeout(flushTimer)
      flushTimer = undefined
      if (ws) {
        const s = ws
        ws = undefined
        s.onclose = null
        s.close()
      }
    },
    pause() {
      setPaused(true)
      // anything already received but not shown yet waits with the rest
      held = held.concat(incoming)
      incoming = []
      setQueued(held.length)
    },
    resume() {
      setPaused(false)
      incoming = incoming.concat(held)
      held = []
      setQueued(0)
      flush()
    },
    clear() {
      incoming = []
      held = []
      seen.clear()
      setGap(false)
      setQueued(0)
      setRows([])
    },
    onPrepend(fn) {
      prepend = fn
    },
  }
}

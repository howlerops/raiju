// Public discovery only. A target is fixed for the lifetime of this document.
import { render } from "@solidjs/web"
import { LoadingSkeleton } from "./LoadingSkeleton"
export interface Gateway { id: string; name: string; url: string }
export interface ConsoleConfig { gateways: Gateway[]; defaultGateway?: string }

const SELECTION_KEY = "raiju.console.gateway"
let config: ConsoleConfig | undefined
let selected: Gateway | undefined
let stopped = false
const shutdown = new AbortController()
const cleanups = new Set<() => void>()

function object(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value)
}
function text(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.trim() === value
}
export function canonicalOrigin(value: string): string {
  // Match the native URL parser's strict ASCII authority, not WHATWG repairs.
  const match = /^(https?):\/\/(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)(?::([0-9]+))?\/?$/.exec(value)
  if (!match) throw new Error("Gateway URL requires a strict ASCII DNS, IPv4 or bracketed IPv6 origin. Use punycode for international hostnames.")
  const host = match[2]!
  const port = match[3]
  if (port !== undefined && (!/^[1-9][0-9]{0,4}$/.test(port) || Number(port) > 65535)) throw new Error("Gateway port must be a decimal number from 1 to 65535, without leading zeros.")
  if (!host.startsWith("[")) {
    const dns = host.endsWith(".") ? host.slice(0, -1) : host
    const labels = dns.split(".")
    if (dns.length > 253 || labels.some((label) => !/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/.test(label))) throw new Error("Invalid gateway DNS hostname.")
    const ipv4 = labels.length === 4 && labels.every((label) => /^(?:0|[1-9][0-9]{0,2})$/.test(label) && Number(label) <= 255)
    const numericLast = /^(?:[0-9]+|0[xX][0-9A-Fa-f]+)$/.test(labels[labels.length - 1]!)
    if (!ipv4 && numericLast) throw new Error("IPv4 gateway addresses require four decimal octets, without shorthand, octal or hexadecimal notation.")
    if (ipv4 && host.endsWith(".")) throw new Error("IPv4 gateway addresses must not end with a dot.")
  }
  const url = new URL(value)
  if (!host.startsWith("[") && url.hostname !== host.toLowerCase()) throw new Error("Refusing a gateway hostname that requires URL repair.")
  const loopback = url.hostname === "localhost" || url.hostname === "127.0.0.1" || url.hostname === "[::1]"
  if (url.username || url.password || (url.protocol !== "https:" && !(url.protocol === "http:" && loopback))) {
    throw new Error("Gateway URLs require HTTPS, except loopback HTTP for local preview.")
  }
  return url.origin
}
export function parseConsoleConfig(value: unknown): ConsoleConfig {
  if (!object(value) || Object.keys(value).some((k) => !["gateways", "defaultGateway"].includes(k)) || !Array.isArray(value.gateways) || !value.gateways.length || value.gateways.length > 32) {
    throw new Error("Console configuration needs between 1 and 32 gateways.")
  }
  const ids = new Set<string>(), origins = new Set<string>()
  const gateways = value.gateways.map((item: unknown) => {
    if (!object(item) || Object.keys(item).some((k) => !["id", "name", "url"].includes(k)) || !text(item.id) || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(item.id) || !text(item.name) || Array.from(item.name).length > 100 || /[\u0000-\u001f\u007f-\u009f]/.test(item.name) || !text(item.url)) {
      throw new Error("Every gateway needs only a valid id (1–64 letters, digits, _ or -), name (1–100 characters, no controls), and origin url.")
    }
    const url = canonicalOrigin(item.url)
    if (ids.has(item.id) || origins.has(url)) throw new Error("Gateway ids and origins must be unique.")
    ids.add(item.id); origins.add(url)
    return { id: item.id, name: item.name, url }
  })
  if (value.defaultGateway !== undefined && (!text(value.defaultGateway) || !ids.has(value.defaultGateway))) throw new Error("defaultGateway must name a configured gateway.")
  return { gateways, defaultGateway: value.defaultGateway as string | undefined }
}
// JSON.parse alone silently accepts duplicate keys, which could disagree with a native host.
export function parseConsoleJSON(source: string): ConsoleConfig {
  const value: unknown = JSON.parse(source)
  const stack: { keys?: Set<string>; key: boolean }[] = []
  for (const match of source.matchAll(/"(?:[^"\\]|\\.)*"|[{}\[\],:]/g)) {
    const token = match[0]
    if (token === "{") stack.push({ keys: new Set(), key: true })
    else if (token === "[") stack.push({ key: false })
    else if (token === "}" || token === "]") stack.pop()
    else {
      const frame = stack[stack.length - 1]
      if (token === "," && frame?.keys) frame.key = true
      else if (token.startsWith('"') && frame?.keys && frame.key) {
        const name = JSON.parse(token) as string
        if (frame.keys.has(name)) throw new Error("Duplicate console configuration field: " + name)
        frame.keys.add(name)
        frame.key = false
      }
    }
  }
  return parseConsoleConfig(value)
}
export async function bootstrapGateways(): Promise<void> {
  const response = await fetch("/console.json", { cache: "no-store", credentials: "omit", redirect: "error", signal: AbortSignal.timeout(10000) })
  if (response.status !== 404) {
    if (!response.ok) throw new Error("Cannot load console configuration (HTTP " + response.status + "). No gateway was selected.")
    config = parseConsoleJSON(await response.text())
  }
  let saved: string | null = null
  try { saved = sessionStorage.getItem(SELECTION_KEY) } catch { /* tab-only memory still works */ }
  if (!config) {
    if (saved && saved !== location.origin) throw new Error("The selected gateway is no longer configured. Restore console.json before continuing.")
    selected = { id: "embedded", name: "Local gateway", url: location.origin }
  } else {
    selected = saved ? config.gateways.find((g) => g.url === saved) : config.gateways.find((g) => g.id === config!.defaultGateway) ?? config.gateways[0]
    if (!selected) throw new Error("The selected gateway is no longer configured. No fallback was used.")
    if (!saved) {
      try { sessionStorage.setItem(SELECTION_KEY, selected.url) } catch { /* selection changes report storage failures */ }
    }
  }
}
export function consoleConfig(): ConsoleConfig | undefined { return config }
export function target(): Gateway {
  if (!selected) throw new Error("Console configuration has not loaded.")
  return selected
}
export function targetLabel(): string { return target().name }
export function targetURL(path = "/"): string {
  if (!path.startsWith("/") || path.startsWith("//") || path.includes("\\")) throw new Error("Expected a gateway-relative path.")
  const url = new URL(path, target().url)
  if (url.origin !== target().url) throw new Error("Refusing a link outside the selected gateway.")
  return url.href
}
export function regionalLink(value: string): string {
  const url = new URL(value, target().url)
  if (url.origin !== target().url || url.username || url.password) throw new Error("Gateway returned a consent link outside the selected origin.")
  return url.href
}
export function gatewaySignal(): AbortSignal { return shutdown.signal }
export function isActive(): boolean { return !stopped }
// Stale continuations must never update UI, credentials, or begin a chained mutation.
export function discarded<T>(): Promise<T> { return new Promise<T>(() => {}) }
export function onGatewayLeave(fn: () => void): () => void {
  cleanups.add(fn)
  return () => { cleanups.delete(fn) }
}
export function reloadTarget(): void {
  if (stopped) return
  stopped = true
  shutdown.abort()
  for (const cleanup of cleanups) cleanup()
  const root = document.getElementById("root")
  if (root) {
    root.replaceChildren()
    render(() => LoadingSkeleton({ variant: "page", label: "Reloading gateway context" }), root)
  }
  location.reload()
}
export function switchGateway(id: string): void {
  const next = config?.gateways.find((g) => g.id === id)
  if (!next) throw new Error("Unknown gateway.")
  if (next.url === selected?.url) { location.hash = "overview"; return }
  // Do not switch in memory: disposal by navigation isolates all forms, data, and sockets.
  try { sessionStorage.setItem(SELECTION_KEY, next.url) } catch {
    throw new Error("Allow tab session storage before switching gateways.")
  }
  history.replaceState(null, "", location.pathname + location.search + "#overview")
  reloadTarget()
}
export function apiCredentials(): RequestCredentials {
  return !config && target().url === location.origin ? "same-origin" : "omit"
}

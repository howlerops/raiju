import { createSignal, For, onSettled } from "solid-js"
import { consoleConfig, gatewaySignal, switchGateway, target, type Gateway } from "../gateway"
import { notify, Pill, Toolbar, type Tone } from "../ui"

type Probe = { text: string; tone: Tone }
type Status = { health: Probe; ready: Probe; checked: string }
const checking: Probe = { text: "Checking…", tone: "" }

export function Fleet() {
  const gateways = consoleConfig()!.gateways
  const [states, setStates] = createSignal<Record<string, Status>>({})
  const [busy, setBusy] = createSignal(false)
  let alive = true
  const controller = new AbortController()
  const probe = async (gateway: Gateway, path: "/health" | "/ready"): Promise<Probe> => {
    try {
      // No bearer, virtual key, cookies, or response payload enters the fleet view.
      const response = await fetch(gateway.url + path, {
        credentials: "omit", redirect: "error", cache: "no-store", referrerPolicy: "no-referrer",
        signal: AbortSignal.any([controller.signal, gatewaySignal(), AbortSignal.timeout(6000)]),
      })
      if (response.body) void response.body.cancel()
      if (response.ok) return { text: path === "/health" ? "Healthy" : "Ready", tone: "ok" }
      if (path === "/ready" && response.status === 503) return { text: "Not ready", tone: "bad" }
      if (response.status === 404) return { text: "Not available", tone: "" }
      return { text: "HTTP " + response.status, tone: "bad" }
    } catch {
      return { text: "Unreachable / CORS blocked", tone: "bad" }
    }
  }
  const refresh = async () => {
    if (busy()) return
    setBusy(true)
    await Promise.all(gateways.map(async (gateway) => {
      const [health, ready] = await Promise.all([probe(gateway, "/health"), probe(gateway, "/ready")])
      if (alive && !gatewaySignal().aborted) setStates((old) => ({ ...old, [gateway.id]: { health, ready, checked: new Date().toLocaleTimeString() } }))
    }))
    if (alive) setBusy(false)
  }
  onSettled(() => {
    void refresh()
    const timer = setInterval(() => { if (!document.hidden) void refresh() }, 15000)
    return () => { alive = false; controller.abort(); clearInterval(timer) }
  })
  return (
    <section aria-labelledby="fleet-title">
      <Toolbar title="Fleet health & readiness" id="fleet-title">
        <button class="btn btn-sm" type="button" disabled={busy()} onClick={() => void refresh()}>Refresh health</button>
      </Toolbar>
      <p class="hint">Public health probes only. No inference, logs, provider configuration, credentials, or regional data are aggregated. An unreachable gateway never redirects traffic to another region.</p>
      <div class="cards fleet-summary" aria-label="Fleet summary">
        <div class="bg-base-100 border border-base-300 rounded-box stat"><div class="stat-title">Configured gateways</div><div class="stat-value">{gateways.length}</div><div class="stat-desc">Independent regional targets</div></div>
        <div class="bg-base-100 border border-base-300 rounded-box stat"><div class="stat-title">Ready gateways</div><div class="stat-value">{gateways.filter((gateway) => states()[gateway.id]?.ready.tone === "ok").length}</div><div class="stat-desc">Successful current readiness probes</div></div>
        <div class="bg-base-100 border border-base-300 rounded-box stat"><div class="stat-title">Selected gateway</div><div class="stat-value">{target().name}</div><div class="stat-desc">All regional operations stay here</div></div>
      </div>
      <div class="fleet-grid">
        <For each={gateways}>{(gateway) => (
          <section class="card panel bg-base-100 border border-base-300 fleet-card" aria-label={gateway.name}>
            <h2>{gateway.name}</h2>
            <p class="mono endpoint">{gateway.url}</p>
            <p>Health: <Pill tone={(states()[gateway.id]?.health ?? checking).tone}>{(states()[gateway.id]?.health ?? checking).text}</Pill></p>
            <p>Readiness: <Pill tone={(states()[gateway.id]?.ready ?? checking).tone}>{(states()[gateway.id]?.ready ?? checking).text}</Pill></p>
            <p class="hint" role="status">{states()[gateway.id]?.checked ? "Checked " + states()[gateway.id]!.checked : "Waiting for probes"}</p>
            <button type="button" class="btn btn-sm btn-primary" onClick={() => {
              try { switchGateway(gateway.id) } catch (error) { notify(error instanceof Error ? error.message : String(error), "error") }
            }}>{gateway.url === target().url ? "Open selected gateway" : "Open target"}</button>
          </section>
        )}</For>
      </div>
    </section>
  )
}

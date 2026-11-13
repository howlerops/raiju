import { render } from "@solidjs/web"
import { createSignal, For, Show } from "solid-js"
import { App } from "./App"
import { bootstrapGateways, consoleConfig, switchGateway } from "./gateway"
import { initializeAuth } from "./auth"
import "./style.css"
import "./live.css"

const root = document.getElementById("root")
if (root) {
  root.textContent = "Loading console configuration…"
  void bootstrapGateways().then(() => {
    initializeAuth()
    root.textContent = ""
    render(() => <App />, root)
  }).catch((error: unknown) => {
    root.textContent = ""
    const [recoveryError, setRecoveryError] = createSignal("")
    render(() => (
      <main><section class="card" role="alert">
        <h1>Console configuration unavailable</h1>
        <p class="error">{error instanceof Error ? error.message : String(error)}</p>
        <p>No gateway requests were made. Correct the configuration and reload.</p>
        <button type="button" onClick={() => location.reload()}>Reload configuration</button>
        <Show when={consoleConfig()}>
          <p>The saved target is unavailable. Explicitly choose a configured gateway to reload this tab; nothing is selected automatically.</p>
          <div class="fleet-grid">
            <For each={consoleConfig()?.gateways ?? []}>{(gateway) => (
              <button type="button" class="card" onClick={() => {
                try { switchGateway(gateway.id) } catch (e) { setRecoveryError(e instanceof Error ? e.message : String(e)) }
              }}>
                Select {gateway.name}<br /><span class="mono endpoint">{gateway.url}</span>
              </button>
            )}</For>
          </div>
        </Show>
        <p class="error" role="alert">{recoveryError()}</p>
      </section></main>
    ), root)
  })
}

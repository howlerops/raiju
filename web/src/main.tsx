import { render } from "@solidjs/web"
import { createSignal, For, Show } from "solid-js"
import { App } from "./App"
import { message } from "./api/client"
import { bootstrapGateways, consoleConfig, switchGateway } from "./gateway"
import { initializeAuth } from "./auth"
import { LoadingSkeleton } from "./LoadingSkeleton"
import "./theme"
import "./style.css"
import "./live.css"

const root = document.getElementById("root")
if (root) {
  const stopLoading = render(() => <main><LoadingSkeleton variant="page" label="Loading console configuration" /></main>, root)
  void bootstrapGateways().then(() => {
    initializeAuth()
    stopLoading()
    root.textContent = ""
    render(() => <App />, root)
  }).catch((error: unknown) => {
    stopLoading()
    root.textContent = ""
    const [recoveryError, setRecoveryError] = createSignal("")
    render(() => (
      <main><section class="card panel bg-base-100 border border-base-300" role="alert">
        <h1>Console configuration unavailable</h1>
        <p class="error">{message(error)}</p>
        <p>No gateway requests were made. Correct the configuration and reload.</p>
        <button class="btn btn-sm" type="button" onClick={() => location.reload()}>Reload configuration</button>
        <Show when={consoleConfig()}>
          <p>The saved target is unavailable. Explicitly choose a configured gateway to reload this tab; nothing is selected automatically.</p>
          <div class="fleet-grid">
            <For each={consoleConfig()?.gateways ?? []}>{(gateway) => (
              <button type="button" class="btn h-auto py-4" onClick={() => {
                try { switchGateway(gateway.id) } catch (e) { setRecoveryError(message(e)) }
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

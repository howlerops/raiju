// First-admin setup uses the explicit setup header on both requests, never a
// cross-origin cookie. The setup secret itself is never stored.
import { createSignal, Show } from "solid-js"
import { send, ApiError, message } from "../api/client"
import { target, targetLabel } from "../gateway"

const SETUP_HEADER = "X-Raiju-Setup-Token"

function Instructions() {
  return (
    <div id="setup-help" class="hint">
      <p>
        The setup token is a secret the operator sets on the server: the <code>RAIJU_SETUP_TOKEN</code> environment
        variable, or <code>setup_token</code> at the top level of <code>config.json</code> (a value or an{" "}
        <code>env.NAME</code> reference). Restart the gateway after setting it.
      </p>
      <p>
        API clients send the same value in the <code>{SETUP_HEADER}</code> header. It stops working once an admin account
        exists.
      </p>
    </div>
  )
}

export function Setup(props: { configured: boolean; done: (token: string) => Promise<void> }) {
  const [error, setError] = createSignal("")
  const [busy, setBusy] = createSignal(false)
  const [created, setCreated] = createSignal<{ name: string; token: string } | undefined>(undefined)
  let tokenIn: HTMLInputElement | undefined
  let nameIn: HTMLInputElement | undefined
  let emailIn: HTMLInputElement | undefined

  const submit = async (ev: SubmitEvent) => {
    ev.preventDefault()
    const token = (tokenIn?.value ?? "").trim()
    const name = (nameIn?.value ?? "").trim()
    const email = (emailIn?.value ?? "").trim()
    if (!token || !name) {
      setError("Enter the setup token and a name for the admin account.")
      return
    }
    setError("")
    setBusy(true)
    try {
      // Check the setup secret before creating the account on this same target.
      try {
        await send("POST", "/api/session/setup", { auth: false, quiet: true, headers: { [SETUP_HEADER]: token } })
      } catch (e) {
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) setError("Invalid setup token.")
        else if (e instanceof ApiError && e.status === 409) setError("An admin account exists already. Reload the page and sign in.")
        else setError(message(e))
        return
      }
      const body: Record<string, string> = { name, role: "admin" }
      if (email) body.email = email
      const r = await send("POST", "/api/users", { auth: false, quiet: true, headers: { [SETUP_HEADER]: token }, body })
      const d = (r.data ?? {}) as { name?: string; token?: string }
      if (tokenIn) tokenIn.value = ""
      setCreated({ name: d.name ?? name, token: d.token ?? "" })
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main>
      <section class="card panel bg-base-100 border border-base-300 setup" id="setup">
        <h1>Finish setting up Raiju</h1>
        <p class="hint">Creating the first admin only on <strong>{targetLabel()}</strong> · <span class="mono">{target().url}</span></p>
        <Show
          when={created()}
          fallback={
            <>
              <p class="muted">
                No admin account exists yet, so the management API is locked. Enter the setup token and create the first
                admin account. Setup issues a bearer token; it does not create a password.
              </p>
              <Show
                when={props.configured}
                fallback={
                  <>
                    <p class="error" role="alert" id="setup-unconfigured">
                      No setup token is configured on this server, so setup cannot continue yet.
                    </p>
                    <Instructions />
                  </>
                }
              >
                <form id="setup-form" class="setup-form" onSubmit={(ev) => void submit(ev)}>
                  <label>
                    Setup token
                    <input class="input input-sm" id="setup-token" type="password" autocomplete="off" spellcheck={false} ref={(el) => (tokenIn = el)} />
                  </label>
                  <label>
                    Admin name
                    <input class="input input-sm" id="setup-name" autocomplete="username" spellcheck={false} placeholder="admin" ref={(el) => (nameIn = el)} />
                  </label>
                  <label>
                    Email (optional)
                    <input class="input input-sm" id="setup-email" type="email" autocomplete="email" ref={(el) => (emailIn = el)} />
                  </label>
                  <Show when={error()}>
                    <p class="error" role="alert" id="setup-error">
                      {error()}
                    </p>
                  </Show>
                  <div class="actions">
                    <button type="submit" class="btn btn-sm btn-primary" id="setup-submit" disabled={busy()}>
                      {busy() ? "Creating…" : "Create admin"}
                    </button>
                  </div>
                </form>
                <details>
                  <summary>Where do I find the setup token?</summary>
                  <Instructions />
                </details>
              </Show>
            </>
          }
        >
          {(c) => (
            <div id="setup-done">
              <p>
                The admin account <strong>{c().name}</strong> was created on {targetLabel()}. Its token is shown this once: keep it somewhere safe.
                Continue verifies this bearer token before signing this tab in. No password was created; save the token for future regional sign-ins.
              </p>
              <input id="setup-new-token" class="input input-sm mono" readonly value={c().token} onFocus={(ev) => ev.currentTarget.select()} />
              <Show when={error()}><p class="error" role="alert">{error()}</p></Show>
              <div class="actions">
                <button type="button" class="btn btn-sm btn-primary" id="setup-continue" disabled={busy()} onClick={async () => {
                  setBusy(true)
                  try { await props.done(c().token) } catch (e) { setError(message(e)) }
                  finally { setBusy(false) }
                }}>
                  Continue to the dashboard
                </button>
              </div>
            </div>
          )}
        </Show>
      </section>
    </main>
  )
}

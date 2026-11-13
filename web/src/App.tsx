import { createSignal, For, Match, onSettled, Show, Switch, Errored } from "solid-js"
import { send, ApiError } from "./api/client"
import { clearSignIn, closeSignIn, dialog, openSignIn, setToken, tokenSet } from "./auth"
import { can, me, refreshMe, roleLabel } from "./perm"
import { notify, Toasts, type Tone } from "./ui"
import { consoleConfig, switchGateway, target, targetLabel, targetURL } from "./gateway"
import { Fleet } from "./screens/Fleet"
import { Overview } from "./screens/Overview"
import { Live } from "./screens/Live"
import { Providers } from "./screens/Providers"
import { Keys } from "./screens/Keys"
import { Governance } from "./screens/Governance"
import { Logs } from "./screens/Logs"
import { Mcp } from "./screens/Mcp"
import { McpAccess } from "./screens/McpAccess"
import { VirtualMcp } from "./screens/VirtualMcp"
import { Crews } from "./screens/Crews"
import { Roles } from "./screens/Roles"
import { Config } from "./screens/Config"
import { Playground } from "./screens/Playground"
import { Setup } from "./screens/Setup"

// [id, label, the resource a role needs to see it (any role may open "")]
const VIEWS = [
  ["fleet", "Fleet health", ""],
  ["overview", "Overview", ""],
  ["live", "Live", "Logs"],
  ["providers", "Providers", "ModelProvider"],
  ["keys", "Virtual keys", "VirtualKeys"],
  ["governance", "Budgets & limits", "Governance"],
  ["logs", "Logs", "Logs"],
  ["mcp", "MCP", "MCPGateway"],
  ["mcpaccess", "MCP access", "MCPGateway"],
  ["vmcp", "Virtual MCPs", "MCPGateway"],
  ["crews", "Crews", "Crews"],
  ["roles", "Roles", "RBAC"],
  ["config", "Config", "Settings"],
  ["playground", "Playground", ""],
] as const

type ViewId = (typeof VIEWS)[number][0]

function viewFromHash(): ViewId {
  const h = location.hash.replace(/^#/, "")
  const hit = VIEWS.find((v) => v[0] === h)
  return hit && (hit[0] !== "fleet" || consoleConfig()) ? hit[0] : consoleConfig() ? "fleet" : "overview"
}

const [view, setView] = createSignal<ViewId>(viewFromHash())
const [health, setHealth] = createSignal<{ text: string; tone: Tone }>({ text: "checking", tone: "" })
const [sso, setSso] = createSignal(false)
// the setup lock (no admin account yet): whether the server has a setup token; undefined once an admin exists
const [setup, setSetup] = createSignal<{ configured: boolean } | undefined>(undefined)
// the setup check has answered: until then the dashboard is not rendered, so its calls cannot ask for a sign-in first
const [checked, setChecked] = createSignal(false)

// Asks the gateway whether it is still waiting for its first admin (a public route). True when it is.
async function checkSetup(): Promise<boolean> {
  try {
    const r = await send("GET", "/api/session/is-auth-enabled", { auth: false, quiet: true })
    const d = (r.data ?? {}) as { setup_required?: boolean; setup_token_configured?: boolean }
    if (d.setup_required) {
      setSetup({ configured: !!d.setup_token_configured })
      setChecked(true)
      return true
    }
  } catch {
    // an older gateway without the route: carry on to the dashboard
  }
  setSetup(undefined)
  setChecked(true)
  return false
}

// Whether the sign-in dialog offers SSO (not asked while the setup lock is on: every other /api route is locked then)
function checkSso(): void {
  void send("GET", "/api/oidc/status", { auth: false, quiet: true })
    .then((r) => setSso(!!(r.data as { enabled?: boolean } | undefined)?.enabled))
    .catch(() => {})
}

function setupDone(token: string): void {
  setToken(token)
}

async function checkHealth(): Promise<void> {
  try {
    await send("GET", "/health", { auth: false })
    setHealth({ text: "gateway ok", tone: "ok" })
  } catch (e) {
    const s = e instanceof ApiError && e.status ? "gateway error " + e.status : "gateway unreachable"
    setHealth({ text: s, tone: "bad" })
  }
}

function SignIn() {
  let input: HTMLInputElement | undefined
  let username: HTMLInputElement | undefined
  let password: HTMLInputElement | undefined
  const [error, setError] = createSignal("")
  const [busy, setBusy] = createSignal(false)
  const save = (token: string | undefined) => {
    try { closeSignIn(token) } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  const login = async () => {
    setError("")
    setBusy(true)
    const name = username?.value ?? ""
    const secret = password?.value ?? ""
    try {
      if (!name || !secret) throw new Error("Enter a username and password.")
      const result = await send("POST", "/api/session/login", { auth: false, quiet: true, body: { username: name, password: secret } })
      const token = (result.data as { token?: unknown } | undefined)?.token
      if (typeof token !== "string" || !token) throw new Error("The gateway did not return a session token.")
      if (password) password.value = ""
      save(token)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally { setBusy(false) }
  }
  return (
    <Show when={dialog()}>
      {(d) => (
        <div class="overlay" id="auth" onKeyDown={(ev) => ev.key === "Escape" && !busy() && save(undefined)}>
          <form class="dialog" role="dialog" aria-modal="true" aria-labelledby="auth-title" onSubmit={(ev) => { ev.preventDefault(); save((input?.value ?? "").trim()) }}>
            <h2 id="auth-title">Sign in to {targetLabel()}</h2>
            <p class="mono endpoint">{target().url}</p>
            <p id="auth-msg" class="muted">{d().message}</p>
            <p class="hint">Credentials stay in this tab, scoped to this gateway origin. Changing identity reloads the console and clears page data.</p>
            <label>Admin or session token
              <input id="auth-input" type="password" autocomplete="off" spellcheck={false} ref={(el) => { input = el; queueMicrotask(() => el.focus()) }} />
            </label>
            <details>
              <summary>Sign in with username and password</summary>
              <label>Username<input id="auth-username" autocomplete="username" ref={(el) => (username = el)} /></label>
              <label>Password<input id="auth-password" type="password" autocomplete="current-password" ref={(el) => (password = el)} /></label>
              <button type="button" disabled={busy()} onClick={() => void login()}>{busy() ? "Signing in…" : "Sign in to " + targetLabel()}</button>
            </details>
            <Show when={sso()}>
              <p id="auth-sso">
                <a class="button" href={targetURL("/api/oidc/login")} target={consoleConfig() ? "_blank" : undefined} rel="noopener noreferrer">
                  {consoleConfig() ? "Open regional UI for SSO" : "Sign in with SSO"}
                </a>
                <Show when={consoleConfig()}><span class="hint"> SSO cookies sign in only to the regional UI, not this consolidated console. Use a regional bearer token here.</span></Show>
              </p>
            </Show>
            <Show when={error()}><p class="error" role="alert">{error()}</p></Show>
            <div class="actions">
              <button type="button" class="ghost" id="auth-clear" disabled={busy()} onClick={() => { try { clearSignIn() } catch (e) { setError(String(e)) } }}>Clear saved token</button>
              <button type="button" id="auth-cancel" disabled={busy()} onClick={() => save(undefined)}>Cancel</button>
              <button type="submit" class="primary" disabled={busy()}>Save token</button>
            </div>
          </form>
        </div>
      )}
    </Show>
  )
}

export function App() {
  setView(viewFromHash())
  onSettled(() => {
    let started = false
    const loadTarget = () => {
      if (started || view() === "fleet") return
      started = true
      // The fleet screen never loads regional permissions, logs or configuration.
      void checkSetup().then((locked) => {
        if (locked) return
        void refreshMe()
        checkSso()
      })
    }
    const onHash = () => { setView(viewFromHash()); loadTarget() }
    window.addEventListener("hashchange", onHash)
    loadTarget()
    void checkHealth()
    const timer = setInterval(() => {
      if (!document.hidden) void checkHealth()
    }, 10000)
    const onVis = () => {
      if (!document.hidden) void checkHealth()
    }
    document.addEventListener("visibilitychange", onVis)
    return () => {
      window.removeEventListener("hashchange", onHash)
      document.removeEventListener("visibilitychange", onVis)
      clearInterval(timer)
    }
  })

  return (
    <div class="admin-shell">
      <div class="console-heading">
      <header class="top">
        <div class="brand">
          <span class="logo" aria-hidden="true">
            R
          </span>
          <span>
            Raiju <span class="muted brand-caption">{consoleConfig() ? "Regional console" : "AI gateway"}</span>
          </span>
        </div>
        <div class="top-right">
          <span class="page-context">{VIEWS.find((v) => v[0] === view())?.[1]}</span>
          <span id="health-pill" class={["pill", health().tone]} role="status">
            {health().text}
          </span>
          <Show when={me()}>
            {(m) => (
              <span id="role-pill" class="pill" title="The role of the signed-in caller">
                {roleLabel(m())}
              </span>
            )}
          </Show>
          <button
            type="button"
            id="token-btn"
            class="ghost"
            onClick={() => openSignIn("Enter credentials for " + targetLabel() + " only. Submit a blank token to clear it.")}
          >
            {tokenSet() ? "Regional token: set" : "Sign in"}
          </button>
        </div>
      </header>
      <section class="target-banner" aria-label="Selected gateway">
        <Show when={consoleConfig()}>
          {(config) => <label>Gateway / region
            <select id="gateway-select" value={target().id} onChange={(ev) => {
              try { switchGateway(ev.currentTarget.value) } catch (e) {
                ev.currentTarget.value = target().id
                notify(e instanceof Error ? e.message : String(e), "error")
              }
            }}>
              <For each={config().gateways}>{(gateway) => <option value={gateway.id}>{gateway.name}</option>}</For>
            </select>
          </label>}
        </Show>
        <Show when={consoleConfig()}><a class="button" href="#fleet">Fleet health</a></Show>
        <div><strong>Target: {targetLabel()}</strong><div class="mono endpoint" id="target-endpoint">{target().url}</div></div>
        <p class="hint">Regional admin reads, changes and Playground requests apply only to this target. Fleet health uses public probes only. Switching reloads the page and clears forms, data and sockets. No cross-region fallback or synchronization.</p>
      </section>
      </div>
      <Show when={!checked() && view() !== "fleet"}><main><p role="status">Checking selected gateway…</p></main></Show>

      <Show when={view() !== "fleet" ? setup() : undefined}>{(st) => <Setup configured={st().configured} done={setupDone} />}</Show>

      <Show when={(checked() && !setup()) || view() === "fleet"}>
      <nav class="tabs" aria-label="Sections">
        <span class="nav-caption">WORKSPACE</span>
        <For each={VIEWS}>
          {(v) => (
            <Show when={(v[0] !== "fleet" || consoleConfig()) && (v[2] === "" || can(v[2]))}>
              <a href={"#" + v[0]} data-nav={v[0]} aria-current={view() === v[0] ? "page" : undefined}>
                {v[1]}
              </a>
            </Show>
          )}
        </For>
      </nav>

      <main>
        <Errored
          fallback={(err, reset) => (
            <section class="card">
              <p class="error" role="alert">
                {String((err() as Error)?.message ?? err())}
              </p>
              <button type="button" onClick={reset}>
                Retry
              </button>
            </section>
          )}
        >
          <Switch>
            <Match when={view() === "fleet" && consoleConfig()}>
              <Fleet />
            </Match>
            <Match when={view() === "overview"}>
              <Overview />
            </Match>
            <Match when={view() === "live"}>
              <Live />
            </Match>
            <Match when={view() === "providers"}>
              <Providers />
            </Match>
            <Match when={view() === "keys"}>
              <Keys />
            </Match>
            <Match when={view() === "governance"}>
              <Governance />
            </Match>
            <Match when={view() === "logs"}>
              <Logs />
            </Match>
            <Match when={view() === "mcp"}>
              <Mcp />
            </Match>
            <Match when={view() === "mcpaccess"}>
              <McpAccess />
            </Match>
            <Match when={view() === "vmcp"}>
              <VirtualMcp />
            </Match>
            <Match when={view() === "crews"}>
              <Crews />
            </Match>
            <Match when={view() === "roles"}>
              <Roles />
            </Match>
            <Match when={view() === "config"}>
              <Config />
            </Match>
            <Match when={view() === "playground"}>
              <Playground />
            </Match>
          </Switch>
        </Errored>
      </main>
      </Show>

      <SignIn />
      <Toasts />
    </div>
  )
}

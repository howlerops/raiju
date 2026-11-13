import { createSignal, For, lazy, Loading, Match, onSettled, Show, Switch, Errored } from "solid-js"
import { send, ApiError } from "./api/client"
import { administrationMode, configureAdministrationMode, dialog, dismissSignIn, openSignIn, setToken, tokenSet, verified, setVerified, revokeSession } from "./auth"
import { can, me, refreshMe, roleLabel, verifyToken } from "./perm"
import { notify, Toasts, type Tone } from "./ui"
import { consoleConfig, switchGateway, target, targetLabel, targetURL } from "./gateway"
import { theme, setTheme } from "./theme"
import { LoadingSkeleton } from "./LoadingSkeleton"
const Fleet = lazy(() => import("./screens/Fleet"), { export: "Fleet" })
const Overview = lazy(() => import("./screens/Overview"), { export: "Overview" })
const Live = lazy(() => import("./screens/Live"), { export: "Live" })
const Providers = lazy(() => import("./screens/Providers"), { export: "Providers" })
const Keys = lazy(() => import("./screens/Keys"), { export: "Keys" })
const Governance = lazy(() => import("./screens/Governance"), { export: "Governance" })
const Logs = lazy(() => import("./screens/Logs"), { export: "Logs" })
const Mcp = lazy(() => import("./screens/Mcp"), { export: "Mcp" })
const McpAccess = lazy(() => import("./screens/McpAccess"), { export: "McpAccess" })
const VirtualMcp = lazy(() => import("./screens/VirtualMcp"), { export: "VirtualMcp" })
const Crews = lazy(() => import("./screens/Crews"), { export: "Crews" })
const Roles = lazy(() => import("./screens/Roles"), { export: "Roles" })
const Config = lazy(() => import("./screens/Config"), { export: "Config" })
const Playground = lazy(() => import("./screens/Playground"), { export: "Playground" })
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
const [bootstrapError, setBootstrapError] = createSignal("")

// Asks the gateway whether it is still waiting for its first admin (a public route). True when it is.
async function bootstrap(): Promise<void> {
  setChecked(false)
  setBootstrapError("")
  setVerified(false)
  try {
    const r = await send("GET", "/api/session/is-auth-enabled", { auth: false, quiet: true })
    const d = r.data as { setup_required?: unknown; setup_token_configured?: unknown; is_auth_enabled?: unknown; administration_mode?: unknown } | undefined
    if (r.status !== 200 || !d || typeof d.setup_required !== "boolean" || (d.setup_required && typeof d.setup_token_configured !== "boolean")) throw new Error("Invalid setup status. Access remains locked.")
    const mode = d.administration_mode === undefined ? "native" : d.administration_mode
    if (mode !== "native" && mode !== "loginless") throw new Error("Invalid administration mode. Access remains locked.")
    if (mode === "loginless" && (d.is_auth_enabled !== false || d.setup_required !== false)) throw new Error("Invalid loginless administration status. Access remains locked.")
    configureAdministrationMode(mode)
    setSetup(d.setup_required ? { configured: d.setup_token_configured === true } : undefined)
    if (!d.setup_required) {
      if (mode === "native" && d.is_auth_enabled !== true) throw new Error("Native authentication is disabled on this gateway without explicit loginless administration. Ask an operator to configure access; access remains locked.")
      try { await refreshMe(); setVerified(true) }
      catch (e) { if (mode === "loginless" || !(e instanceof ApiError && e.status === 401)) throw e }
      if (mode === "native") checkSso()
    }
  } catch (e) { setBootstrapError(e instanceof Error ? e.message : String(e)) }
  finally { setChecked(true) }
}

// Whether the sign-in dialog offers SSO (not asked while the setup lock is on: every other /api route is locked then)
function checkSso(): void {
  void send("GET", "/api/oidc/status", { auth: false, quiet: true })
    .then((r) => setSso(!!(r.data as { enabled?: boolean } | undefined)?.enabled))
    .catch(() => {})
}

async function setupDone(token: string): Promise<void> {
  await verifyToken(token)
  setToken(token)
  await bootstrap()
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

function ThemeControls() {
  return <div class="theme-controls" role="group" aria-label="Appearance">
    <span>Appearance</span><div class="join">
      <For each={[
        { value: "system", label: "System", path: "M3 4h18v12H3z M8 21h8 M12 16v5" },
        { value: "light", label: "Light", path: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 2v2 M12 20v2 M2 12h2 M20 12h2 M5 5l1.5 1.5 M17.5 17.5L19 19 M5 19l1.5-1.5 M17.5 6.5L19 5" },
        { value: "dark", label: "Dark", path: "M20.5 13A9 9 0 0 1 11 3.5 9 9 0 1 0 20.5 13Z" },
      ]}>{(option) => <button type="button" class={["btn btn-sm btn-square join-item", theme() === option.value ? "btn-primary" : "btn-ghost"]}
        aria-label={option.label + " theme"} title={option.label + " theme"} aria-pressed={theme() === option.value ? "true" : "false"} onClick={() => setTheme(option.value)}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d={option.path} /></svg>
      </button>}</For>
    </div>
  </div>
}


function SignIn(props: { account?: boolean }) {
  let input: HTMLInputElement | undefined
  let username: HTMLInputElement | undefined
  let password: HTMLInputElement | undefined
  const [error, setError] = createSignal("")
  const [busy, setBusy] = createSignal(false)
  const save = async (token: string) => {
    if (!token) throw new Error("Enter a regional token.")
    await verifyToken(token)
    setToken(token)
    await bootstrap()
  }
  const submit = async (useToken: boolean) => {
    setError(""); setBusy(true)
    try {
      if (useToken) await save((input?.value ?? "").trim())
      else {
        const name = username?.value ?? "", secret = password?.value ?? ""
        if (!name || !secret) throw new Error("Enter a username and password.")
        const r = await send("POST", "/api/session/login", { auth: false, quiet: true, body: { username: name, password: secret } })
        const token = (r.data as { token?: unknown } | undefined)?.token
        if (typeof token !== "string" || !token) throw new Error("The gateway did not return a session token.")
        await save(token)
      }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { if (password) password.value = ""; setBusy(false) }
  }
  const logout = async () => {
    setBusy(true); setError("")
    try {
      await send("POST", "/api/session/logout", { quiet: true })
      revokeSession()
      setToken("")
      await bootstrap()
    } catch (e) {
      // Local sign-out is still possible, but never claim the server revoked it.
      revokeSession()
      notify("Local sign-out only: server logout could not be confirmed. " + String(e), "error")
      try { sessionStorage.setItem("raiju.logout-warning", "Local session cleared; server logout could not be confirmed. " + String(e)) } catch {}
      try { setToken("") } catch (storageError) { setError(String(storageError)) }
    } finally { setBusy(false) }
  }
  return <section id="auth" class="card panel bg-base-100 border border-base-300 auth-card">
    <h1>{props.account ? "Regional account" : "Sign in to " + targetLabel()}</h1>
    <p class="muted">Sign in before accessing gateway administration or Fleet health.</p>
    <p class="hint">Credentials are isolated to this gateway origin and this tab. Changing identity or region reloads the console.</p>
    <form onSubmit={(ev) => { ev.preventDefault(); void submit(false) }}>
      <label>Username<input class="input w-full" id="auth-username" autocomplete="username" ref={(el) => { username = el }} /></label>
      <label>Password<input class="input w-full" id="auth-password" type="password" autocomplete="current-password" ref={(el) => { password = el }} /></label>
      <button class="btn btn-primary" type="submit" id="auth-submit" disabled={busy()}>{busy() ? "Signing in…" : "Sign in to " + targetLabel()}</button>
    </form>
    <details id="auth-token-details"><summary>Use a regional token instead</summary>
      <p class="hint">First-admin setup creates a token, not a password. Use that token here; password sign-in requires an operator-configured password account.</p>
      <form onSubmit={(ev) => { ev.preventDefault(); void submit(true) }}>
        <label>Admin or session token<input class="input w-full" id="auth-input" type="password" autocomplete="off" ref={(el) => { input = el }} /></label>
        <button class="btn btn-primary" type="submit" disabled={busy()}>Use token</button>
      </form>
    </details>
    <Show when={sso()}><p id="auth-sso"><a class="btn btn-outline" href={targetURL("/api/oidc/login")} target={consoleConfig() ? "_blank" : undefined} rel="noopener noreferrer">{consoleConfig() ? "Open regional UI for SSO" : "Sign in with SSO"}</a></p></Show>
    <Show when={consoleConfig()}><p class="hint">Regional SSO cookies do not sign in to a consolidated console. Use native credentials or a regional bearer token here.</p></Show>
    <Show when={error()}><p class="error" role="alert">{error()}</p></Show>
    <Show when={props.account}><button type="button" class="btn" onClick={dismissSignIn}>Close account</button><button type="button" id="signout-btn" class="btn" disabled={busy()} onClick={() => void logout()}>Sign out</button></Show>
  </section>
}

export function App() {
  setView(viewFromHash())
  onSettled(() => {
    const onHash = () => setView(viewFromHash())
    const expired = () => { setVerified(false) }
    window.addEventListener("raiju-session-expired", expired)
    window.addEventListener("hashchange", onHash)
    void bootstrap()
    try {
      const warning = sessionStorage.getItem("raiju.logout-warning")
      if (warning) { notify(warning, "error"); sessionStorage.removeItem("raiju.logout-warning") }
    } catch {}
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
      window.removeEventListener("raiju-session-expired", expired)
      document.removeEventListener("visibilitychange", onVis)
      clearInterval(timer)
    }
  })

  return (
    <>
    <Show when={checked() && !bootstrapError() && !setup() && verified()} fallback={
      <div class="auth-page">
        <Show when={checked()} fallback={<LoadingSkeleton variant="page" label="Checking gateway identity" />}>
          <Show when={!bootstrapError()} fallback={<section class="card panel"><p class="error" role="alert">{bootstrapError()}</p><Show when={administrationMode() === "loginless"}><p class="hint">Loginless administration requires upstream access controls. Access remains locked until this gateway's administrator permissions can be verified.</p></Show><button class="btn" id="auth-retry" onClick={() => void bootstrap()}>Retry connection</button></section>}>
            <Show when={setup()} fallback={
              <Show when={administrationMode() === "native"} fallback={
                <section class="card panel auth-card">
                  <h1>Loginless administration</h1>
                  <p class="error" role="alert">Gateway access could not be verified. Access remains locked.</p>
                  <p class="hint">This gateway requires upstream access controls. Check those controls or ask an operator to restore access.</p>
                  <button class="btn" id="auth-retry" onClick={() => void bootstrap()}>Retry connection</button>
                </section>
              }><SignIn /></Show>
            }>{(st) => <Setup configured={st().configured} done={setupDone} />}</Show>
          </Show>
        </Show>
      </div>
    }>
    <div class="admin-shell">
      <aside class="sidebar" aria-label="Gateway workspace">
        <div class="brand">
          <span class="logo" aria-hidden="true">R</span>
          <span>Raiju <span class="muted brand-caption">{consoleConfig() ? "Regional console" : "AI gateway"}</span></span>
        </div>
        <section class="sidebar-target" aria-label="Selected gateway">
          <Show when={consoleConfig()}>
            {(config) => <label>Gateway / region
              <select class="select select-sm w-full" id="gateway-select" value={target().id} onChange={(ev) => {
                try { switchGateway(ev.currentTarget.value) } catch (e) {
                  ev.currentTarget.value = target().id
                  notify(e instanceof Error ? e.message : String(e), "error")
                }
              }}>
                <For each={config().gateways}>{(gateway) => <option value={gateway.id}>{gateway.name}</option>}</For>
              </select>
            </label>}
          </Show>
          <div class="target-scope"><strong>{targetLabel()}</strong><div class="mono endpoint" id="target-endpoint">{target().url}</div></div>
          <span id="health-pill" class={["badge badge-soft", health().tone === "ok" ? "badge-success" : health().tone === "bad" ? "badge-error" : "badge-neutral"]} role="status">{health().text}</span>
          <details class="target-help"><summary>Regional isolation</summary>
            <p>Admin reads, changes and Playground requests apply only to this target. Fleet health uses public probes only. Switching regions reloads the page and clears forms, data and sockets. No cross-region fallback or synchronization.</p>
          </details>
        </section>
        {/* Shell navigation stays mounted while regional bootstrap or a page is pending. */}
        <nav class="side-nav" aria-label="Sections">
          <span class="nav-caption">WORKSPACE</span>
          <For each={VIEWS}>
            {(v) => (
              <Show when={(v[0] !== "fleet" || consoleConfig()) && (v[2] === "" || can(v[2]))}>
                <a class="btn btn-sm btn-ghost" href={"#" + v[0]} data-nav={v[0]} aria-current={view() === v[0] ? "page" : undefined}>{v[1]}</a>
              </Show>
            )}
          </For>
        </nav>
        <footer class="sidebar-footer">
          <ThemeControls />
          <Show when={administrationMode() === "loginless"} fallback={
            <>
              <Show when={me()}>
                {(m) => <span id="role-pill" class="badge badge-neutral" title="The role of the signed-in caller">{roleLabel(m())}</span>}
              </Show>
              <button type="button" id="token-btn" class="btn btn-sm btn-outline w-full"
                onClick={() => openSignIn("Enter credentials for " + targetLabel() + " only.")}>
                {tokenSet() ? "Regional token: set" : "Sign in"}
              </button>
            </>
          }>
            <div id="loginless-administration" class="loginless-warning" role="note">
              <strong>Loginless administration</strong>
              <p>No native sign-in. Anyone who can reach this gateway has administrator access. Upstream access controls are required.</p>
            </div>
          </Show>
        </footer>
      </aside>
      <header class="console-heading top">
        <span class="page-context"><span class="muted">Workspace / </span>{VIEWS.find((v) => v[0] === view())?.[1]}</span>
      </header>
      <main>
        <Show when={view()} keyed>{(route) =>
        <Errored
          fallback={(err, reset) => (
            <section class="card panel bg-base-100 border border-base-300">
              <p class="error" role="alert">
                {String((err() as Error)?.message ?? err())}
              </p>
              <button class="btn btn-sm" type="button" onClick={reset}>
                Retry
              </button>
            </section>
          )}
        >
          <Loading fallback={<LoadingSkeleton variant="page" label={"Loading " + VIEWS.find((v) => v[0] === route)?.[1]} />}>
          <Show when={VIEWS.find((v) => v[0] === route)?.[2] === "" || can(VIEWS.find((v) => v[0] === route)?.[2] ?? "")} fallback={<section class="card panel"><p role="alert">Your role cannot access this section.</p></section>}>
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
          </Show>
          </Loading>
        </Errored>
        }</Show>
      </main>

      <Show when={administrationMode() === "native" && dialog()}><div class="overlay"><SignIn account /></div></Show>
    </div>
    </Show>
    <Toasts />
    </>
  )
}

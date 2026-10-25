import { createSignal, For, Match, onSettled, Show, Switch, Errored } from "solid-js"
import { api, send, ApiError } from "./api/client"
import { clearSignIn, closeSignIn, dialog, onTokenChange, openSignIn, setToken, tokenSet } from "./auth"
import { can, me, refreshMe, roleLabel } from "./perm"
import { Pill, Toasts, type Tone } from "./ui"
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
  return hit ? hit[0] : "overview"
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
  api
    .get("/api/oidc/status")
    .then((j) => setSso(!!j.enabled))
    .catch(() => {})
}

function setupDone(token: string): void {
  setSetup(undefined)
  setToken(token)
  void refreshMe()
  checkSso()
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
  const submit = (ev: SubmitEvent) => {
    ev.preventDefault()
    closeSignIn((input?.value ?? "").trim())
  }
  return (
    <Show when={dialog()}>
      {(d) => (
        <div class="overlay" id="auth" onKeyDown={(ev) => ev.key === "Escape" && closeSignIn(undefined)}>
          <form class="dialog" role="dialog" aria-modal="true" aria-labelledby="auth-title" onSubmit={submit}>
            <h2 id="auth-title">Admin token</h2>
            <p id="auth-msg" class="muted">
              {d().message}
            </p>
            <label>
              Token
              <input
                id="auth-input"
                type="password"
                autocomplete="off"
                spellcheck={false}
                ref={(el) => {
                  input = el
                  queueMicrotask(() => el.focus())
                }}
              />
            </label>
            <Show when={sso()}>
              <p id="auth-sso">
                <a class="button" href="/api/oidc/login">
                  Sign in with SSO
                </a>
              </p>
            </Show>
            <div class="actions">
              <button type="button" class="ghost" id="auth-clear" onClick={() => clearSignIn()}>
                Clear saved token
              </button>
              <button type="button" id="auth-cancel" onClick={() => closeSignIn(undefined)}>
                Cancel
              </button>
              <button type="submit" class="primary">
                Save
              </button>
            </div>
          </form>
        </div>
      )}
    </Show>
  )
}

export function App() {
  onSettled(() => {
    const onHash = () => setView(viewFromHash())
    window.addEventListener("hashchange", onHash)
    onTokenChange(() => void refreshMe())
    // with no admin account the API is locked: the setup screen comes first, and nothing asks for a sign-in
    void checkSetup().then((locked) => {
      if (locked) return
      void refreshMe()
      checkSso()
    })
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
    <>
      <header class="top">
        <div class="brand">
          <span class="logo" aria-hidden="true">
            R
          </span>
          <span>
            Raiju <span class="muted">gateway</span>
          </span>
        </div>
        <div class="top-right">
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
            onClick={() => openSignIn("Enter the admin token. Submit it blank to clear it.")}
          >
            {tokenSet() ? "Admin token: set" : "Admin token"}
          </button>
        </div>
      </header>

      <Show when={setup()}>{(st) => <Setup configured={st().configured} done={setupDone} />}</Show>

      <Show when={checked() && !setup()}>
      <nav class="tabs" aria-label="Sections">
        <For each={VIEWS}>
          {(v) => (
            <Show when={v[2] === "" || can(v[2])}>
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
    </>
  )
}

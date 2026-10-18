import { createSignal, For, Match, onSettled, Show, Switch, Errored } from "solid-js"
import { api, send, ApiError } from "./api/client"
import { clearSignIn, closeSignIn, dialog, onTokenChange, openSignIn, tokenSet } from "./auth"
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
import { Config } from "./screens/Config"
import { Playground } from "./screens/Playground"

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
    void refreshMe()
    void checkHealth()
    api
      .get("/api/oidc/status")
      .then((j) => setSso(!!j.enabled))
      .catch(() => {})
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
            <Match when={view() === "config"}>
              <Config />
            </Match>
            <Match when={view() === "playground"}>
              <Playground />
            </Match>
          </Switch>
        </Errored>
      </main>

      <SignIn />
      <Toasts />
    </>
  )
}

// Who is connected to MCP through OAuth: the grants of the gateway's own authorization server
// (/api/oauth2/sessions), the per-user sessions (/api/mcp/sessions: OAuth tokens, pending consent
// flows, header credentials) and the per-user headers submission (/api/mcp/per-user-headers/flows).
import { createMemo, createSignal, For, Show } from "solid-js"
import { ApiError, send } from "../api/client"
import { fmtTime } from "../fmt"
import { can } from "../perm"
import { Card, copyText, DangerButton, FormError, Guard, Mono, notify, Pill, Table, Toolbar, useFormRun, useRun, type Tone } from "../ui"

interface Grant {
  id: string
  client_id: string
  client_name: string
  bf_mode: string
  bf_sub: string
  bf_sub_display: string
  scope: string
  created_at: string
  last_used_at?: string
}

interface SessionRow {
  id: string
  kind: string
  auth_kind: string
  auth_mode: string
  virtual_key_id: string
  session_id: string
  mcp_client: { name: string }
  status: string
  expires_at: number
  created_at: number
  has_refresh_token: boolean
  can_reauth: boolean
}

interface Page<T> {
  sessions: T[]
  total_count: number
}

interface Ctl {
  tick: () => number
  bump: () => void
}

const KIND_LABEL: Record<string, string> = { token: "OAuth token", flow: "Pending consent", header: "Header credential" }

function statusTone(s: string): Tone {
  return s === "active" ? "ok" : s === "needs_reauth" ? "warn" : ""
}

async function getPage<T>(path: string, query: Record<string, string | number | undefined>): Promise<Page<T>> {
  const r = await send("GET", path, { query })
  const d = (r.data ?? {}) as Partial<Page<T>>
  return { sessions: d.sessions ?? [], total_count: d.total_count ?? 0 }
}

// ---- OAuth grants of the authorization server ----

function Grants(props: Ctl) {
  const [q, setQ] = createSignal("")
  const grants = createMemo(async () => {
    props.tick()
    try {
      return { page: await getPage<Grant>("/api/oauth2/sessions", { q: q(), limit: 50 }), off: false }
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return { page: { sessions: [], total_count: 0 } as Page<Grant>, off: true }
      throw e
    }
  })
  let input: HTMLInputElement | undefined
  return (
    <Card title="OAuth grants" id="mca-grants-h">
      <p class="hint">
        Clients that signed in to this gateway's own MCP authorization server. Revoking a grant stops its client from refreshing; access tokens already issued last until
        they expire.
      </p>
      <form
        class="inline-form"
        role="search"
        aria-label="Filter OAuth grants"
        onSubmit={(ev) => {
          ev.preventDefault()
          setQ((input?.value ?? "").trim())
        }}
      >
        <label>
          Client or identity
          <input id="mca-grant-q" ref={(el) => (input = el)} autocomplete="off" />
        </label>
        <div class="actions">
          <button type="submit">Filter</button>
        </div>
      </form>
      <div id="mca-grants">
        <Guard>
          <Show
            when={!grants().off}
            fallback={<p class="muted">The authorization server is off. Set client.mcp_server_auth_mode to both or oauth to let MCP clients sign in here.</p>}
          >
            <Show when={grants().page.sessions.length} fallback={<p class="muted">No live grants.</p>}>
              <Table cols={["Client", "Mode", "Identity", "Scope", "Created", "Last used", ""]}>
                <For each={grants().page.sessions} keyed={(g) => g.id}>
                  {(g) => (
                    <tr>
                      <td>{g().client_name || <Mono>{g().client_id}</Mono>}</td>
                      <td>
                        <Pill>{g().bf_mode}</Pill>
                      </td>
                      <td>
                        <Mono>{g().bf_sub_display || g().bf_sub || "—"}</Mono>
                      </td>
                      <td>{g().scope || "—"}</td>
                      <td class="nowrap">{fmtTime(Date.parse(g().created_at))}</td>
                      <td class="nowrap">{g().last_used_at ? fmtTime(Date.parse(g().last_used_at!)) : "never"}</td>
                      <td>
                        <Show when={can("MCPGateway", "Delete")}>
                          <DangerButton
                            label="Revoke"
                            action={async () => {
                              await send("DELETE", "/api/oauth2/sessions/" + encodeURIComponent(g().id))
                              notify("Grant revoked", "ok")
                              props.bump()
                            }}
                          />
                        </Show>
                      </td>
                    </tr>
                  )}
                </For>
              </Table>
              <p class="hint">{grants().page.sessions.length + " of " + grants().page.total_count + " grants"}</p>
            </Show>
          </Show>
        </Guard>
      </div>
    </Card>
  )
}

// ---- per-user sessions ----

function Sessions(props: Ctl) {
  const [kind, setKind] = createSignal("")
  const [link, setLink] = createSignal<{ client: string; url: string } | undefined>(undefined)
  const { busy, run } = useRun()
  const rows = createMemo(() => {
    props.tick()
    return getPage<SessionRow>("/api/mcp/sessions", { kind: kind(), limit: 100 })
  })
  const reauth = (r: SessionRow) =>
    run(async () => {
      const res = await send("POST", "/api/mcp/sessions/" + encodeURIComponent(r.id) + "/reauth")
      const url = String((res.data as { url?: string } | undefined)?.url ?? "")
      setLink({ client: r.mcp_client.name, url })
      props.bump()
    })
  let linkField: HTMLInputElement | undefined
  return (
    <Card title="Per-user sessions" id="mca-sessions-h">
      <p class="hint">
        Callers that connected to an MCP client with their own sign-in or header values. Tokens are never shown. Re-authorize opens a new consent link for the caller; revoking
        removes the stored access.
      </p>
      <div class="filters">
        <label>
          Show
          <select id="mca-kind" onChange={(ev) => setKind(ev.currentTarget.value)}>
            <option value="" ref={(el) => (el.selected = true)}>
              All sessions
            </option>
            <option value="token">OAuth tokens</option>
            <option value="flow">Pending consents</option>
            <option value="header">Header credentials</option>
          </select>
        </label>
      </div>
      <Show when={link()} keyed>
        {(l) => (
          <div class="callout" id="mca-link" role="status">
            <p>
              <strong>{"Consent link for " + l.client}</strong> Send it to the caller; it is the page they approve on.
            </p>
            <div class="secret-row">
              <input readonly aria-label="Consent link" ref={(el) => (linkField = el)} value={location.origin + l.url} />
              <button type="button" onClick={async () => notify((await copyText(location.origin + l.url, linkField)) ? "Link copied" : "Copy failed", "ok")}>
                Copy
              </button>
              <a class="button" href={l.url} target="_blank" rel="noopener">
                Open
              </a>
              <button type="button" class="ghost" onClick={() => setLink(undefined)}>
                Close
              </button>
            </div>
          </div>
        )}
      </Show>
      <div id="mca-sessions">
        <Guard>
          <Show when={rows().sessions.length} fallback={<p class="muted">No sessions.</p>}>
            <Table cols={["MCP client", "Kind", "Identity", "Status", "Expires", "Created", ""]}>
              <For each={rows().sessions} keyed={(r) => r.id}>
                {(r) => (
                  <tr>
                    <td>
                      <Mono>{r().mcp_client.name}</Mono>
                    </td>
                    <td>{KIND_LABEL[r().kind] ?? r().kind}</td>
                    <td>
                      <Mono>{r().virtual_key_id ? "key " + r().virtual_key_id : r().session_id ? "session " + r().session_id : "—"}</Mono>
                    </td>
                    <td>
                      <Pill tone={statusTone(r().status)}>{r().status.replace("_", " ")}</Pill>
                    </td>
                    <td class="nowrap">{r().expires_at ? fmtTime(r().expires_at) : "—"}</td>
                    <td class="nowrap">{fmtTime(r().created_at)}</td>
                    <td>
                      <Show when={can("MCPGateway", "Update") || can("MCPGateway", "Delete")}>
                        <span class="row-actions">
                          <Show when={r().can_reauth && can("MCPGateway", "Update")}>
                            <button type="button" class="ghost" disabled={busy()} onClick={() => reauth(r())}>
                              Re-authorize
                            </button>
                          </Show>
                          <Show when={can("MCPGateway", "Delete")}>
                            <DangerButton
                              label="Revoke"
                              action={async () => {
                                await send("DELETE", "/api/mcp/sessions/" + encodeURIComponent(r().id))
                                notify("Session revoked", "ok")
                                props.bump()
                              }}
                            />
                          </Show>
                        </span>
                      </Show>
                    </td>
                  </tr>
                )}
              </For>
            </Table>
            <p class="hint">{rows().sessions.length + " of " + rows().total_count + " sessions"}</p>
          </Show>
        </Guard>
      </div>
    </Card>
  )
}

// ---- per-user headers ----

interface HeaderClient {
  name: string
  keys: string[]
}

interface Flow {
  id: string
  expires_at: number
  mcp_client: { name: string }
  virtual_key: { id: string }
  required_header_keys: string[]
  submitted_keys: string[]
  has_active_credential: boolean
}

async function headerClients(): Promise<{ clients: HeaderClient[]; keys: { id: string; name: string }[] }> {
  const [cl, vk] = await Promise.all([send("GET", "/api/mcp/clients"), send("GET", "/api/governance/virtual-keys")])
  const clients = ((cl.data as { clients?: { name: string; auth_type?: string; per_user_header_keys?: string[] }[] })?.clients ?? [])
    .filter((c) => c.auth_type === "per_user_headers")
    .map((c) => ({ name: c.name, keys: c.per_user_header_keys ?? [] }))
  const keys = ((vk.data as { virtual_keys?: { id: string; name?: string }[] })?.virtual_keys ?? []).map((k) => ({ id: k.id, name: k.name ?? "" }))
  return { clients, keys }
}

function Headers(props: Ctl) {
  const data = createMemo(headerClients)
  const [flow, setFlow] = createSignal<Flow | undefined>(undefined)
  const open = useFormRun()
  const submit = useFormRun()

  const openFlow = (ev: SubmitEvent) => {
    ev.preventDefault()
    const f = ev.currentTarget as HTMLFormElement
    const client = (f.elements.namedItem("client") as HTMLSelectElement).value
    const vk = (f.elements.namedItem("vk") as HTMLSelectElement).value
    void open.run(async () => {
      const made = await send("POST", "/api/mcp/per-user-headers/flows", { body: { mcp_client_name: client, virtual_key_id: vk } })
      const id = String((made.data as { id?: string }).id)
      const got = await send("GET", "/api/mcp/per-user-headers/flows/" + encodeURIComponent(id))
      setFlow(got.data as Flow)
    })
  }
  const sendValues = (ev: SubmitEvent) => {
    ev.preventDefault()
    const f = ev.currentTarget as HTMLFormElement
    const cur = flow()
    if (!cur) return
    const headers: Record<string, string> = {}
    for (const k of cur.required_header_keys) {
      const v = (f.elements.namedItem("h:" + k) as HTMLInputElement).value
      if (v) headers[k] = v
    }
    void submit.run(async () => {
      await send("PUT", "/api/mcp/per-user-headers/flows/" + encodeURIComponent(cur.id), { body: { headers } })
      notify("Header values saved for " + cur.virtual_key.id, "ok")
      setFlow(undefined)
      props.bump()
    })
  }

  return (
    <Card title="Per-user headers" id="mca-headers-h">
      <p class="hint">
        An MCP client with auth type per_user_headers needs each virtual key to hand in its own header values. Open a submission for a key, then enter the values (they are
        checked against the MCP server before they are stored).
      </p>
      <div id="mca-headers">
        <Guard>
          <Show when={data().clients.length} fallback={<p class="muted">No MCP client uses per-user headers. Add one with auth type per_user_headers.</p>}>
            <Show when={can("MCPGateway", "Create")} fallback={<p class="muted">Your role cannot open header submissions.</p>}>
              <form class="inline-form" id="mca-hdr-open" aria-label="Open a headers submission" onSubmit={openFlow}>
                <label>
                  MCP client
                  <select name="client">
                    <For each={data().clients} keyed={(c) => c.name}>
                      {(c) => <option value={c().name}>{c().name}</option>}
                    </For>
                  </select>
                </label>
                <label>
                  Virtual key
                  <select name="vk" required>
                    <For each={data().keys} keyed={(k) => k.id}>
                      {(k) => <option value={k().id}>{k().name ? k().name + " (" + k().id + ")" : k().id}</option>}
                    </For>
                  </select>
                </label>
                <div class="actions">
                  <button type="submit" class="primary" disabled={open.busy()}>
                    Open submission
                  </button>
                </div>
                <FormError text={open.error()} />
              </form>
            </Show>
          </Show>
          <Show when={flow()} keyed>
            {(f) => (
              <form class="card" id="mca-hdr-flow" aria-label="Header values" onSubmit={sendValues}>
                <h3>{"Header values for " + f.virtual_key.id + " on " + f.mcp_client.name}</h3>
                <p class="hint">
                  {"Expires " + fmtTime(f.expires_at) + (f.has_active_credential ? ". Stored values: " + f.submitted_keys.join(", ") + " (leave a field empty to keep it)." : ".")}
                </p>
                <div class="form-grid">
                  <For each={f.required_header_keys}>
                    {(k) => (
                      <label>
                        {k}
                        <input name={"h:" + k} type="password" autocomplete="off" spellcheck={false} />
                      </label>
                    )}
                  </For>
                  <FormError text={submit.error()} />
                </div>
                <div class="actions">
                  <button type="button" class="ghost" onClick={() => setFlow(undefined)}>
                    Cancel
                  </button>
                  <button type="submit" class="primary" disabled={submit.busy()}>
                    Verify and save
                  </button>
                </div>
              </form>
            )}
          </Show>
        </Guard>
      </div>
    </Card>
  )
}

export function McpAccess() {
  const [tick, setTick] = createSignal(0)
  const bump = () => setTick((n) => n + 1)
  const ctl: Ctl = { tick, bump }
  return (
    <section aria-labelledby="mca-title">
      <Toolbar title="MCP access" id="mca-title">
        <button type="button" id="mca-refresh" class="ghost" onClick={bump}>
          Refresh
        </button>
      </Toolbar>
      <Grants {...ctl} />
      <Sessions {...ctl} />
      <Headers {...ctl} />
    </section>
  )
}

// Virtual MCPs and tool groups. A virtual MCP is a named set of tools picked from the MCP clients,
// served at /mcp/{name}; a tool group is Bifrost's name for the same record (/api/mcp/tool-groups),
// with its tools given as client plus tool names and its keys reached through teams, customers and
// providers as well as directly. Both lists are the same records; the two editors write them.
import { createMemo, createSignal, createStore, For, refresh, Show, snapshot, untrack } from "solid-js"
import { send } from "../api/client"
import { can } from "../perm"
import { DangerButton, FormError, Guard, initChecked, initValue, notify, Pill, Toolbar, tf, useFormRun } from "../ui"

interface VTool {
  source: string
  as?: string
  description?: string
  defaults?: Record<string, unknown>
}

interface VMcp {
  name: string
  description?: string
  tools: VTool[]
  virtual_key_ids: string[]
}

interface Resolved {
  name: string
  tools: string[]
  errors: string[]
}

interface Named {
  id: string
  name?: string
}

interface Opts {
  keys: Named[]
  teams: Named[]
  customers: Named[]
  providers: string[]
  clients: string[]
  sources: string[]
}

const label = (n: Named): string => (n.name ? n.name + " (" + n.id + ")" : n.id)

async function list<T>(path: string, key: string): Promise<T[]> {
  try {
    const r = await send("GET", path)
    const v = (r.data as Record<string, unknown> | undefined)?.[key]
    return Array.isArray(v) ? (v as T[]) : []
  } catch {
    return []
  }
}

async function loadAll(): Promise<{ mcps: VMcp[]; resolved: Record<string, Resolved>; opts: Opts }> {
  const [mcps, resolved, keys, teams, customers, providers, status] = await Promise.all([
    send("GET", "/api/mcp/virtual-mcps").then((r) => (((r.data as { virtual_mcps?: VMcp[] })?.virtual_mcps ?? []) as VMcp[])),
    send("GET", "/api/mcp/virtual").then(
      (r) => (Array.isArray(r.data) ? (r.data as Resolved[]) : []),
      () => [] as Resolved[],
    ),
    list<Named>("/api/governance/virtual-keys", "virtual_keys"),
    list<Named>("/api/governance/teams", "teams"),
    list<Named>("/api/governance/customers", "customers"),
    list<{ name: string }>("/api/providers", "providers"),
    list<{ name: string; tools_list?: { name: string }[] }>("/api/mcp", "clients"),
  ])
  const byName: Record<string, Resolved> = {}
  for (const r of resolved) byName[r.name] = r
  const sources: string[] = []
  for (const c of status) for (const t of c.tools_list ?? []) sources.push(c.name + "-" + t.name)
  return {
    mcps,
    resolved: byName,
    opts: { keys, teams, customers, providers: providers.map((p) => p.name), clients: status.map((c) => c.name), sources },
  }
}

// ---- the virtual MCP editor ----

interface ToolRow {
  source: string
  as: string
  description: string
  defaults: string
}

function McpForm(props: { current: VMcp | undefined; opts: Opts; onClose: () => void; onSaved: () => void }) {
  const { busy, error, run } = useFormRun()
  const cur = untrack(() => props.current)
  const [rows, setRows] = createStore<{ tools: ToolRow[] }>({
    tools: (cur?.tools ?? []).map((t) => ({ source: t.source, as: t.as ?? "", description: t.description ?? "", defaults: t.defaults ? JSON.stringify(t.defaults) : "" })),
  })
  const submit = (ev: SubmitEvent) => {
    ev.preventDefault()
    const form = ev.currentTarget as HTMLFormElement
    const get = (n: string) => (form.elements.namedItem(n) as HTMLInputElement).value
    void run(async () => {
      const tools: VTool[] = []
      for (const r of snapshot(rows).tools) {
        const source = r.source.trim()
        if (!source) continue
        const t: VTool = { source }
        if (r.as.trim()) t.as = r.as.trim()
        if (r.description.trim()) t.description = r.description.trim()
        if (r.defaults.trim()) {
          let d: unknown
          try {
            d = JSON.parse(r.defaults)
          } catch {
            throw new Error("Defaults for " + source + " must be a JSON object, like {\"limit\": 10}")
          }
          if (!d || typeof d !== "object" || Array.isArray(d)) throw new Error("Defaults for " + source + " must be a JSON object, like {\"limit\": 10}")
          t.defaults = d as Record<string, unknown>
        }
        tools.push(t)
      }
      const name = cur ? cur.name : get("name").trim()
      const body = { name, description: get("description").trim(), tools }
      if (cur) await send("PUT", "/api/mcp/virtual-mcps/" + encodeURIComponent(cur.name), { body })
      else await send("POST", "/api/mcp/virtual-mcps", { body })
      notify(cur ? "Virtual MCP saved" : "Virtual MCP created", "ok")
      props.onSaved()
    })
  }
  return (
    <form id="vm-form" class="card" aria-labelledby="vm-form-title" onSubmit={submit}>
      <h2 id="vm-form-title">{cur ? "Edit " + cur.name : "New virtual MCP"}</h2>
      <div class="form-grid">
        <label>
          Name
          <input
            name="name"
            required
            autocomplete="off"
            placeholder="served at /mcp/name"
            readonly={!!cur}
            ref={(el) => {
              initValue(cur?.name ?? "")(el)
              queueMicrotask(() => el.focus())
            }}
          />
        </label>
        <label class="wide">
          Description
          <input name="description" autocomplete="off" ref={initValue(cur?.description ?? "")} />
        </label>
      </div>
      <fieldset style="margin-top:12px">
        <legend>Tools</legend>
        <p class="hint">
          A source is a client and tool name joined with a dash (weather-get_forecast), or the client and * for all of its tools. As renames the tool; defaults are arguments
          filled in when the caller leaves them out.
        </p>
        <datalist id="vm-sources">
          <For each={props.opts.sources}>{(s) => <option value={s} />}</For>
        </datalist>
        <div id="vm-tools">
          <For each={rows.tools}>
            {(row, i) => (
              <div class="rule">
                <input
                  aria-label="Source tool"
                  list="vm-sources"
                  placeholder="client-tool or client-*"
                  autocomplete="off"
                  value={row.source}
                  onInput={(e) => setRows((s) => void (s.tools[i()]!.source = e.currentTarget.value))}
                />
                <input aria-label="Renamed as" placeholder="as (optional)" autocomplete="off" value={row.as} onInput={(e) => setRows((s) => void (s.tools[i()]!.as = e.currentTarget.value))} />
                <input
                  aria-label="Tool description"
                  placeholder="description (optional)"
                  autocomplete="off"
                  value={row.description}
                  onInput={(e) => setRows((s) => void (s.tools[i()]!.description = e.currentTarget.value))}
                />
                <input
                  aria-label="Argument defaults"
                  class="mono"
                  placeholder='defaults, e.g. {"limit": 10}'
                  autocomplete="off"
                  spellcheck={false}
                  value={row.defaults}
                  onInput={(e) => setRows((s) => void (s.tools[i()]!.defaults = e.currentTarget.value))}
                />
                <button type="button" class="ghost" onClick={() => setRows((s) => void s.tools.splice(i(), 1))}>
                  Remove
                </button>
              </div>
            )}
          </For>
        </div>
        <button type="button" id="vm-add-tool" class="ghost" onClick={() => setRows((s) => void s.tools.push({ source: "", as: "", description: "", defaults: "" }))}>
          Add tool
        </button>
      </fieldset>
      <FormError text={error()} />
      <div class="actions">
        <button type="button" id="vm-cancel" class="ghost" onClick={props.onClose}>
          Cancel
        </button>
        <button type="submit" id="vm-save" class="primary" disabled={busy()}>
          {cur ? "Save changes" : "Create virtual MCP"}
        </button>
      </div>
    </form>
  )
}

// ---- the tool group editor ----

interface GroupRow {
  client: string
  tools: string
}

// A stored source "client-tool" back to a client and its tool name. Clients cannot hold a dash.
function groupRows(tools: VTool[], clients: string[]): GroupRow[] {
  const by: Record<string, string[]> = {}
  const order: string[] = []
  for (const t of tools) {
    const dash = t.source.indexOf("-")
    const client = dash > 0 ? t.source.slice(0, dash) : ""
    const tool = dash > 0 ? t.source.slice(dash + 1) : t.source
    if (!clients.includes(client) && client === "") continue
    if (!by[client]) {
      by[client] = []
      order.push(client)
    }
    by[client]!.push(tool)
  }
  return order.map((c) => ({ client: c, tools: by[c]!.join(", ") }))
}

function Checks(props: { legend: string; name: string; items: Named[]; chosen: string[] }) {
  return (
    <fieldset class="wide">
      <legend>{props.legend}</legend>
      <Show when={props.items.length} fallback={<p class="hint">None defined.</p>}>
        <div class="tool-chips">
          <For each={props.items} keyed={(i) => i.id}>
            {(it) => (
              <label class="check">
                <input type="checkbox" name={props.name} value={it().id} ref={initChecked(props.chosen.includes(it().id))} /> {label(it())}
              </label>
            )}
          </For>
        </div>
      </Show>
    </fieldset>
  )
}

function GroupForm(props: { current: VMcp | undefined; opts: Opts; onClose: () => void; onSaved: () => void }) {
  const { busy, error, run } = useFormRun()
  const cur = untrack(() => props.current)
  const [rows, setRows] = createStore<{ tools: GroupRow[] }>({ tools: cur ? groupRows(cur.tools, props.opts.clients) : [] })
  const lossy = () => (cur?.tools ?? []).some((t) => t.as || t.description || t.defaults)
  const submit = (ev: SubmitEvent) => {
    ev.preventDefault()
    const form = ev.currentTarget as HTMLFormElement
    const get = (n: string) => (form.elements.namedItem(n) as HTMLInputElement).value
    const picked = (n: string) => [...form.querySelectorAll<HTMLInputElement>('input[name="' + n + '"]:checked')].map((e) => e.value)
    void run(async () => {
      const tools = snapshot(rows)
        .tools.filter((r) => r.client)
        .map((r) => ({
          mcp_client_name: r.client,
          tool_names: r.tools
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean),
        }))
      const body: Record<string, unknown> = {
        name: cur ? cur.name : get("name").trim(),
        description: get("description").trim(),
        tools,
        virtual_key_ids: picked("g-key"),
        team_ids: picked("g-team"),
        customer_ids: picked("g-customer"),
        provider_names: picked("g-provider"),
      }
      if (cur) await send("PUT", "/api/mcp/tool-groups/" + encodeURIComponent(cur.name), { body })
      else await send("POST", "/api/mcp/tool-groups", { body: { ...body, enabled: true } })
      notify(cur ? "Tool group saved" : "Tool group created", "ok")
      props.onSaved()
    })
  }
  return (
    <form id="tg-form" class="card" aria-labelledby="tg-form-title" onSubmit={submit}>
      <h2 id="tg-form-title">{cur ? "Edit tool group " + cur.name : "New tool group"}</h2>
      <div class="form-grid">
        <label>
          Name
          <input
            name="name"
            required
            autocomplete="off"
            readonly={!!cur}
            ref={(el) => {
              initValue(cur?.name ?? "")(el)
              queueMicrotask(() => el.focus())
            }}
          />
        </label>
        <label class="wide">
          Description
          <input name="description" autocomplete="off" ref={initValue(cur?.description ?? "")} />
        </label>
      </div>
      <fieldset style="margin-top:12px">
        <legend>Tools</legend>
        <p class="hint">Pick a client and list its tools, or * for every tool of the client.</p>
        <Show when={lossy()}>
          <p class="hint" id="tg-lossy">
            Renames, descriptions and defaults set in the virtual MCP editor are not kept when a tool group is saved.
          </p>
        </Show>
        <div id="tg-tools">
          <For each={rows.tools}>
            {(row, i) => (
              <div class="rule">
                <select aria-label="MCP client" onChange={(e) => setRows((s) => void (s.tools[i()]!.client = e.currentTarget.value))}>
                  <option value="" selected={!row.client}>
                    Choose MCP client
                  </option>
                  <For each={untrack(() => (row.client && !props.opts.clients.includes(row.client) ? [...props.opts.clients, row.client] : props.opts.clients))}>
                    {(n) => (
                      <option value={n} selected={n === row.client}>
                        {n}
                      </option>
                    )}
                  </For>
                </select>
                <input
                  aria-label="Tool names"
                  placeholder="* for all, or a comma list"
                  autocomplete="off"
                  value={row.tools}
                  onInput={(e) => setRows((s) => void (s.tools[i()]!.tools = e.currentTarget.value))}
                />
                <button type="button" class="ghost" onClick={() => setRows((s) => void s.tools.splice(i(), 1))}>
                  Remove
                </button>
              </div>
            )}
          </For>
        </div>
        <button type="button" id="tg-add-tool" class="ghost" onClick={() => setRows((s) => void s.tools.push({ client: "", tools: "*" }))}>
          Add client
        </button>
      </fieldset>
      <p class="hint">Who can use the group: the keys you tick, plus every key of the teams, customers and providers you tick. Saving replaces the earlier list.</p>
      <Checks legend="Virtual keys" name="g-key" items={props.opts.keys} chosen={cur?.virtual_key_ids ?? []} />
      <Checks legend="Teams" name="g-team" items={props.opts.teams} chosen={[]} />
      <Checks legend="Customers" name="g-customer" items={props.opts.customers} chosen={[]} />
      <Checks legend="Providers" name="g-provider" items={props.opts.providers.map((p) => ({ id: p }))} chosen={[]} />
      <FormError text={error()} />
      <div class="actions">
        <button type="button" id="tg-cancel" class="ghost" onClick={props.onClose}>
          Cancel
        </button>
        <button type="submit" id="tg-save" class="primary" disabled={busy()}>
          {cur ? "Save changes" : "Create tool group"}
        </button>
      </div>
    </form>
  )
}

// ---- the list ----

function McpCard(props: { m: VMcp; res: Resolved | undefined; keys: Named[]; mode: "mcp" | "group"; onEdit: () => void; onChange: () => void }) {
  const writable = () => can("MCPGateway", "Update")
  const attach = async (ev: Event, vk: string) => {
    const box = ev.currentTarget as HTMLInputElement
    const want = box.checked
    try {
      await send(want ? "POST" : "DELETE", "/api/mcp/virtual-mcps/" + encodeURIComponent(props.m.name) + "/virtual-keys/" + encodeURIComponent(vk))
      notify(want ? "Key attached" : "Key detached", "ok")
      props.onChange()
    } catch (e) {
      box.checked = !want
      notify(e instanceof Error ? e.message : String(e), "error")
    }
  }
  return (
    <article class="card" aria-label={(props.mode === "group" ? "Tool group " : "Virtual MCP ") + props.m.name}>
      <header class="toolbar" style="margin-bottom:8px">
        <h3>{props.m.name}</h3>
        <Pill>{props.m.tools.length + (props.m.tools.length === 1 ? " tool" : " tools")}</Pill>
        <span class="hint mono grow">{"/mcp/" + props.m.name}</span>
        <span class="row-actions">
          <Show when={writable()}>
            <button type="button" class="ghost" onClick={props.onEdit}>
              Edit
            </button>
          </Show>
          <Show when={can("MCPGateway", "Delete")}>
            <DangerButton
              label="Delete"
              action={async () => {
                await send("DELETE", "/api/mcp/virtual-mcps/" + encodeURIComponent(props.m.name))
                notify("Deleted " + props.m.name, "ok")
                props.onChange()
              }}
            />
          </Show>
        </span>
      </header>
      <Show when={props.m.description}>
        <p class="hint">{props.m.description}</p>
      </Show>
      <Show when={props.res && props.res.errors.length}>
        <ul class="error">
          <For each={props.res!.errors}>{(e) => <li>{e}</li>}</For>
        </ul>
      </Show>
      <h4>Tools served</h4>
      <Show when={props.res && props.res.tools.length} fallback={<p class="hint">{props.m.tools.length ? "None of its tools is available yet." : "No tools yet."}</p>}>
        <div class="tool-chips">
          <For each={props.res!.tools}>{(t) => <span class="pill mono">{t}</span>}</For>
        </div>
      </Show>
      <h4>Virtual keys that may use it</h4>
      <Show when={props.keys.length} fallback={<p class="hint">No virtual keys yet.</p>}>
        <div class="tool-chips">
          <For each={props.keys} keyed={(k) => k.id}>
            {(k) => (
              <label class="check">
                <input
                  type="checkbox"
                  aria-label={"Allow key " + k().id}
                  disabled={!can("MCPGateway", "Create") && !can("MCPGateway", "Delete")}
                  ref={initChecked(props.m.virtual_key_ids.includes(k().id))}
                  onChange={(ev) => attach(ev, k().id)}
                />{" "}
                {label(k())}
              </label>
            )}
          </For>
        </div>
      </Show>
    </article>
  )
}

export function VirtualMcp() {
  const data = createMemo(loadAll)
  const reload = () => refresh(data)
  const [mode, setMode] = createSignal<"mcp" | "group">("mcp")
  const [editor, setEditor] = createSignal<{ m: VMcp | undefined } | undefined>(undefined)
  const done = () => {
    setEditor(undefined)
    reload()
  }
  return (
    <section aria-labelledby="vm-title">
      <Toolbar title="Virtual MCPs" id="vm-title">
        <span class="row-actions" role="group" aria-label="Editor">
          <button
            type="button"
            id="vm-mode-mcp"
            class="toggle"
            aria-pressed={tf(mode() === "mcp")}
            onClick={() => {
              setMode("mcp")
              setEditor(undefined)
            }}
          >
            Virtual MCPs
          </button>
          <button
            type="button"
            id="vm-mode-group"
            class="toggle"
            aria-pressed={tf(mode() === "group")}
            onClick={() => {
              setMode("group")
              setEditor(undefined)
            }}
          >
            Tool groups
          </button>
        </span>
        <Show when={can("MCPGateway", "Create")}>
          <button type="button" id="vm-new" class="primary" onClick={() => setEditor({ m: undefined })}>
            {mode() === "mcp" ? "New virtual MCP" : "New tool group"}
          </button>
        </Show>
      </Toolbar>
      <p class="hint">
        {mode() === "mcp"
          ? "A virtual MCP serves a chosen set of tools at /mcp/name. A key that is not attached cannot use it."
          : "Tool groups are the same records in Bifrost's shape: tools by client, and keys reached through teams, customers and providers."}
      </p>
      <Guard>
        <Show when={editor()} keyed>
          {(e) =>
            mode() === "mcp" ? (
              <McpForm current={e.m} opts={data().opts} onClose={() => setEditor(undefined)} onSaved={done} />
            ) : (
              <GroupForm current={e.m} opts={data().opts} onClose={() => setEditor(undefined)} onSaved={done} />
            )
          }
        </Show>
        <div id="vm-list">
          <Show when={data().mcps.length} fallback={<p class="card muted">{mode() === "mcp" ? "No virtual MCPs yet." : "No tool groups yet."}</p>}>
            <For each={data().mcps} keyed={(m) => m.name}>
              {(m) => <McpCard m={m()} res={data().resolved[m().name]} keys={data().opts.keys} mode={mode()} onEdit={() => setEditor({ m: m() })} onChange={reload} />}
            </For>
          </Show>
        </div>
      </Guard>
    </section>
  )
}

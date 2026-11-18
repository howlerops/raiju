// Virtual MCPs and tool groups. A virtual MCP is a named set of tools picked from the MCP clients,
// served at /mcp/{name}; a tool group is the same record at /api/mcp/tool-groups,
// with its tools given as client plus tool names and its keys reached through teams, customers and
// providers as well as directly. Both lists are the same records; the two editors write them.
import { createMemo, createSignal, createStore, For, lazy, Loading, refresh, Show, snapshot, untrack } from "solid-js"
import { getData, listOr, message, send } from "../api/client"
import { loadOptions } from "../api/options"
import { canCall } from "../perm"
import { idLabel, listOf } from "../fmt"
import { ClientToolsRows, type ClientTools, DangerButton, fieldValue, FormError, Guard, initChecked, initValue, notify, Pill, Toolbar, tf, useFormRun } from "../ui"
import { targetURL } from "../gateway"
import { ChoiceSelect } from "../ChoiceSelect"
const JsonEditor = lazy(() => import("../JsonEditor"), { export: "JsonEditor" })
function DefaultsEditor(props: { value: string; onInput: (value: string) => void; onValidityChange: (valid: boolean) => void }) {
  const [open, setOpen] = createSignal(false)
  return (
    <details class="wide" onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>Argument defaults</summary>
      <Show when={open()}>
        <Loading fallback={<div class="skeleton h-32 w-full" aria-label="Loading JSON editor" />}>
          <JsonEditor label="Argument defaults" rows={4} value={props.value} onInput={props.onInput} onValidityChange={props.onValidityChange} />
        </Loading>
      </Show>
    </details>
  )
}

const VMCPS = "/api/mcp/virtual-mcps"
// key boxes drawn at a time in an open card; the filter reaches the rest
const KEY_PAGE = 50

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
  tools: Record<string, string[]>
}

// The records themselves: the only read a key toggle repeats.
const loadMcps = async (): Promise<VMcp[]> => listOf<VMcp>(await getData(VMCPS), "virtual_mcps")

// What the gateway serves for each record, by name; it changes when a record's tools do.
async function loadResolved(): Promise<Record<string, Resolved>> {
  const byName: Record<string, Resolved> = {}
  for (const r of await listOr<Resolved>("/api/mcp/virtual", "")) byName[r.name] = r
  return byName
}

async function loadOpts(): Promise<Opts> {
  const [o, status] = await Promise.all([
    loadOptions("keys", "teams", "customers", "providers"),
    listOr<{ name: string; tools_list?: { name: string }[] }>("/api/mcp", "clients"),
  ])
  const sources: string[] = []
  const tools: Record<string, string[]> = {}
  for (const c of status) {
    tools[c.name] = (c.tools_list ?? []).map((t) => t.name)
    for (const t of c.tools_list ?? []) sources.push(c.name + "-" + t.name)
  }
  return { keys: o.keys, teams: o.teams, customers: o.customers, providers: o.providers.map((p) => p.name), clients: status.map((c) => c.name), sources, tools }
}

// ---- the virtual MCP editor ----

interface ToolRow {
  source: string
  as: string
  description: string
  defaults: string
  valid: boolean
}

function McpForm(props: { current: VMcp | undefined; opts: Opts; onClose: () => void; onSaved: () => void }) {
  const { busy, error, run } = useFormRun()
  const cur = untrack(() => props.current)
  const [rows, setRows] = createStore<{ tools: ToolRow[] }>({
    tools: (cur?.tools ?? []).map((t) => ({ source: t.source, as: t.as ?? "", description: t.description ?? "", defaults: t.defaults ? JSON.stringify(t.defaults) : "", valid: true })),
  })
  const submit = (ev: SubmitEvent) => {
    ev.preventDefault()
    const form = ev.currentTarget as HTMLFormElement
    const get = (n: string) => fieldValue(form, n)
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
      if (cur) await send("PUT", VMCPS + "/" + encodeURIComponent(cur.name), { body })
      else await send("POST", VMCPS, { body })
      notify(cur ? "Virtual MCP saved" : "Virtual MCP created", "ok")
      props.onSaved()
    })
  }
  return (
    <form id="vm-form" class="card panel bg-base-100 border border-base-300" aria-labelledby="vm-form-title" onSubmit={submit}>
      <h2 id="vm-form-title">{cur ? "Edit " + cur.name : "New virtual MCP"}</h2>
      <div class="form-grid">
        <label>
          Name
          <input class="input input-sm"
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
          <input class="input input-sm" name="description" autocomplete="off" ref={initValue(cur?.description ?? "")} />
        </label>
      </div>
      <fieldset style="margin-top:12px">
        <legend>Tools</legend>
        <p class="hint">
          A source is a client and tool name joined with a dash (weather-get_forecast), or the client and * for all of its tools. As renames the tool; defaults are arguments
          filled in when the caller leaves them out.
        </p>
        <div id="vm-tools">
          <For each={rows.tools}>
            {(row, i) => (
              <div class="rule">
                <ChoiceSelect
                  label="Source tool"
                  options={[...props.opts.sources, ...props.opts.clients.map((client) => client + "-*")]}
                  placeholder="Choose a client tool"
                  allowCustom
                  value={row.source}
                  onChange={(value) => setRows((s) => void (s.tools[i()]!.source = value))}
                />
                <label>
                  Renamed as
                  <input class="input input-sm" aria-label="Renamed as" placeholder="Optional alias" autocomplete="off" value={row.as} onInput={(e) => setRows((s) => void (s.tools[i()]!.as = e.currentTarget.value))} />
                </label>
                <label>
                  Tool description
                  <input class="input input-sm" aria-label="Tool description" placeholder="Optional description" autocomplete="off" value={row.description} onInput={(e) => setRows((s) => void (s.tools[i()]!.description = e.currentTarget.value))} />
                </label>
                <div class="field-action">
                  <button type="button" class="btn btn-sm btn-ghost" onClick={() => setRows((s) => void s.tools.splice(i(), 1))}>
                    Remove
                  </button>
                </div>
                <DefaultsEditor
                  value={row.defaults}
                  onInput={(value) => setRows((s) => void (s.tools[i()]!.defaults = value))}
                  onValidityChange={(valid) => setRows((s) => void (s.tools[i()]!.valid = valid))}
                />
              </div>
            )}
          </For>
        </div>
        <button type="button" id="vm-add-tool" class="btn btn-sm btn-ghost" onClick={() => setRows((s) => void s.tools.push({ source: "", as: "", description: "", defaults: "", valid: true }))}>
          Add tool
        </button>
      </fieldset>
      <FormError text={error()} />
      <div class="actions">
        <button type="button" id="vm-cancel" class="btn btn-sm btn-ghost" onClick={props.onClose}>
          Cancel
        </button>
        <button type="submit" id="vm-save" class="btn btn-sm btn-primary" disabled={busy() || rows.tools.some((row) => !row.valid)}>
          {cur ? "Save changes" : "Create virtual MCP"}
        </button>
      </div>
    </form>
  )
}

// ---- the tool group editor ----

type GroupRow = ClientTools

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
                <input class="checkbox checkbox-sm" type="checkbox" name={props.name} value={it().id} ref={initChecked(props.chosen.includes(it().id))} /> {idLabel(it())}
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
    const get = (n: string) => fieldValue(form, n)
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
    <form id="tg-form" class="card panel bg-base-100 border border-base-300" aria-labelledby="tg-form-title" onSubmit={submit}>
      <h2 id="tg-form-title">{cur ? "Edit tool group " + cur.name : "New tool group"}</h2>
      <div class="form-grid">
        <label>
          Name
          <input class="input input-sm"
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
          <input class="input input-sm" name="description" autocomplete="off" ref={initValue(cur?.description ?? "")} />
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
          <ClientToolsRows
            rows={rows.tools}
            clients={props.opts.clients}
            tools={props.opts.tools}
            update={(change) => setRows((s) => change(s.tools))}
            toolsLabel="Tool names"
            toolsPlaceholder="* for all, or a comma list"
          />
        </div>
        <button type="button" id="tg-add-tool" class="btn btn-sm btn-ghost" onClick={() => setRows((s) => void s.tools.push({ client: "", tools: "*" }))}>
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
        <button type="button" id="tg-cancel" class="btn btn-sm btn-ghost" onClick={props.onClose}>
          Cancel
        </button>
        <button type="submit" id="tg-save" class="btn btn-sm btn-primary" disabled={busy()}>
          {cur ? "Save changes" : "Create tool group"}
        </button>
      </div>
    </form>
  )
}

// ---- the list ----

// The keys of one record: a count until the list is opened, then a filter and the first matches,
// so a page of records does not draw a box for every key of every record.
function KeyBoxes(props: { m: VMcp; keys: Named[]; onChange: () => void }) {
  const [open, setOpen] = createSignal(false)
  const [filter, setFilter] = createSignal("")
  const path = () => VMCPS + "/" + encodeURIComponent(props.m.name) + "/virtual-keys"
  const attached = createMemo(() => new Set(props.m.virtual_key_ids))
  // attaching is a POST and detaching a DELETE, so a box follows the permission its next click needs
  const locked = (id: string) => !canCall(attached().has(id) ? "DELETE" : "POST", path())
  const count = createMemo(() => props.keys.reduce((n, k) => n + (attached().has(k.id) ? 1 : 0), 0))
  const matching = createMemo(() => {
    const f = filter().trim().toLowerCase()
    return f ? props.keys.filter((k) => idLabel(k).toLowerCase().includes(f)) : props.keys
  })
  const toggle = async (ev: Event, vk: string) => {
    const box = ev.currentTarget as HTMLInputElement
    const want = box.checked
    try {
      await send(want ? "POST" : "DELETE", path() + "/" + encodeURIComponent(vk))
      notify(want ? "Key attached" : "Key detached", "ok")
      props.onChange()
    } catch (e) {
      box.checked = !want
      notify(message(e), "error")
    }
  }
  return (
    <details class="vm-keys" onToggle={(ev) => setOpen(ev.currentTarget.open)}>
      <summary>{count() + " of " + props.keys.length + (props.keys.length === 1 ? " key" : " keys")}</summary>
      <Show when={open()}>
        <Show when={props.keys.length > KEY_PAGE}>
          <label class="inline-label">
            Filter keys
            <input class="input input-sm" type="search" autocomplete="off" aria-label={"Filter keys of " + props.m.name} onInput={(ev) => setFilter(ev.currentTarget.value)} />
          </label>
        </Show>
        <div class="tool-chips" style="margin-top:6px">
          <For each={matching().slice(0, KEY_PAGE)} keyed={(k) => k.id}>
            {(k) => (
              <label class="check">
                <input class="checkbox checkbox-sm"
                  type="checkbox"
                  aria-label={"Allow key " + k().id}
                  disabled={locked(k().id)}
                  ref={initChecked(attached().has(k().id))}
                  onChange={(ev) => toggle(ev, k().id)}
                />{" "}
                {idLabel(k())}
              </label>
            )}
          </For>
        </div>
        <Show when={matching().length > KEY_PAGE} fallback={<Show when={!matching().length}><p class="hint">No key matches.</p></Show>}>
          <p class="hint" role="status">{"Showing " + KEY_PAGE + " of " + matching().length + " keys. Filter to find the others."}</p>
        </Show>
      </Show>
    </details>
  )
}

function McpCard(props: { m: VMcp; res: Resolved | undefined; keys: Named[]; mode: "mcp" | "group"; onEdit: () => void; onChange: () => void; onKeys: () => void }) {
  const writable = () => canCall("PUT", VMCPS)
  return (
    <article class="card panel bg-base-100 border border-base-300" aria-label={(props.mode === "group" ? "Tool group " : "Virtual MCP ") + props.m.name}>
      <header class="toolbar" style="margin-bottom:8px">
        <h3>{props.m.name}</h3>
        <Pill>{props.m.tools.length + (props.m.tools.length === 1 ? " tool" : " tools")}</Pill>
        <span class="hint mono grow">{targetURL("/mcp/" + encodeURIComponent(props.m.name))}</span>
        <span class="row-actions">
          <Show when={writable()}>
            <button type="button" class="btn btn-sm btn-ghost" onClick={props.onEdit}>
              Edit
            </button>
          </Show>
          <Show when={canCall("DELETE", VMCPS)}>
            <DangerButton
              label="Delete"
              action={async () => {
                await send("DELETE", VMCPS + "/" + encodeURIComponent(props.m.name))
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
          <For each={props.res!.tools}>{(t) => <span class="badge badge-neutral mono">{t}</span>}</For>
        </div>
      </Show>
      <h4>Virtual keys that may use it</h4>
      <Show when={props.keys.length} fallback={<p class="hint">No virtual keys yet.</p>}>
        <KeyBoxes m={props.m} keys={props.keys} onChange={props.onKeys} />
      </Show>
    </article>
  )
}

export function VirtualMcp() {
  // Three reads: a key toggle refetches the records only, an edit the records and what they serve,
  // and the option lists load once and again on Refresh.
  const mcps = createMemo(loadMcps)
  const resolved = createMemo(loadResolved)
  const opts = createMemo(loadOpts)
  const reloadKeys = () => refresh(mcps)
  const reload = () => {
    refresh(mcps)
    refresh(resolved)
  }
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
            class="btn btn-sm tool-toggle"
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
            class="btn btn-sm tool-toggle"
            aria-pressed={tf(mode() === "group")}
            onClick={() => {
              setMode("group")
              setEditor(undefined)
            }}
          >
            Tool groups
          </button>
        </span>
        <button
          type="button"
          id="vm-refresh"
          class="btn btn-sm btn-ghost"
          onClick={() => {
            reload()
            refresh(opts)
          }}
        >
          Refresh
        </button>
        <Show when={canCall("POST", VMCPS)}>
          <button type="button" id="vm-new" class="btn btn-sm btn-primary" onClick={() => setEditor({ m: undefined })}>
            {mode() === "mcp" ? "New virtual MCP" : "New tool group"}
          </button>
        </Show>
      </Toolbar>
      <p class="hint">
        {mode() === "mcp"
          ? "A virtual MCP serves a chosen set of tools at /mcp/name. A key that is not attached cannot use it."
          : "Tool groups are the same records: tools by client, and keys reached through teams, customers and providers."}
      </p>
      <Guard>
        <Show when={editor()} keyed>
          {(e) =>
            mode() === "mcp" ? (
              <McpForm current={e.m} opts={opts()} onClose={() => setEditor(undefined)} onSaved={done} />
            ) : (
              <GroupForm current={e.m} opts={opts()} onClose={() => setEditor(undefined)} onSaved={done} />
            )
          }
        </Show>
        <div id="vm-list">
          <Show when={mcps().length} fallback={<p class="card panel bg-base-100 border border-base-300 muted">{mode() === "mcp" ? "No virtual MCPs yet." : "No tool groups yet."}</p>}>
            <For each={mcps()} keyed={(m) => m.name}>
              {(m) => <McpCard m={m()} res={resolved()[m().name]} keys={opts().keys} mode={mode()} onEdit={() => setEditor({ m: m() })} onChange={reload} onKeys={reloadKeys} />}
            </For>
          </Show>
        </div>
      </Guard>
    </section>
  )
}

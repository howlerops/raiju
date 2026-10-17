import { createMemo, createSignal, Errored, For, Loading, refresh, Show, untrack } from "solid-js"
import { api } from "../api/client"
import type { McpClient, McpStatus } from "../api/types"
import { splitList } from "../fmt"
import { DangerButton, ErrP, FormError, initChecked, initSelected, initValue, notify, Pill, Toolbar, useFormRun, useRun, tf } from "../ui"

type Cfg = Record<string, unknown> & { name?: string; connection_type?: string; connection_string?: string }

function headersOf(text: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const line of text.split("\n")) {
    if (line.trim() === "") continue
    const i = line.indexOf(":")
    const k = i > 0 ? line.slice(0, i).trim() : ""
    if (k === "") throw new Error("Each header line must read Name: value. Check: " + line.trim())
    out[k] = line.slice(i + 1).trim()
  }
  return out
}

// A client's stored config without its id, ready for PUT (masked secrets go back unchanged).
function clientBody(c: Cfg): Cfg {
  const b = { ...c }
  delete b.client_id
  return b
}

async function loadAll(): Promise<{ clients: Cfg[]; status: Record<string, McpStatus> }> {
  const [cfg, st] = await Promise.all([
    api.get("/api/mcp/clients"),
    api.get("/api/mcp").then(
      (s) => s.clients,
      () => [] as McpStatus[],
    ),
  ])
  const status: Record<string, McpStatus> = {}
  for (const s of st) status[s.name] = s
  return { clients: cfg.clients as McpClient[] as Cfg[], status }
}

function McpForm(props: { current: Cfg | undefined; onClose: () => void; onSaved: () => void }) {
  const { busy, error, run } = useFormRun()
  const c = untrack(() => props.current)
  const stdio = (c?.stdio_config ?? {}) as { command?: string; args?: string[] }
  const hdrs = (c?.headers ?? {}) as Record<string, string>
  const submit = (ev: SubmitEvent) => {
    ev.preventDefault()
    const form = ev.currentTarget as HTMLFormElement
    const get = (n: string) => (form.elements.namedItem(n) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement).value
    void run(async () => {
      const type = get("connection_type")
      const prevStdio = (c?.stdio_config ?? {}) as Record<string, unknown>
      const body: Cfg = {
        ...(c ? clientBody(c) : {}),
        name: get("name").trim(),
        connection_type: type,
        connection_string: type === "stdio" ? undefined : get("connection_string").trim() || undefined,
        stdio_config: type === "stdio" ? { ...prevStdio, command: get("command").trim(), args: splitList(get("args")) } : undefined,
        headers: headersOf(get("headers")),
        disabled: (form.elements.namedItem("disabled") as HTMLInputElement).checked,
      }
      if (c) await api.put("/api/mcp/client/{name}", { params: { name: String(c.name) }, body })
      else await api.post("/api/mcp/client", { body })
      notify(c ? "MCP client saved" : "MCP client added", "ok")
      props.onSaved()
    })
  }
  return (
    <form id="mcp-form" class="card" aria-labelledby="mcp-form-title" onSubmit={submit}>
      <h2 id="mcp-form-title">{c ? "Edit " + c.name : "Add MCP client"}</h2>
      <div class="form-grid">
        <label>
          Name
          <input
            name="name"
            required
            autocomplete="off"
            placeholder="letters, digits, underscores"
            readonly={!!c}
            ref={(el) => {
              initValue(c?.name ?? "")(el)
              queueMicrotask(() => el.focus())
            }}
          />
        </label>
        <label>
          Connection
          <select name="connection_type">
            <option value="http" ref={initSelected((c?.connection_type ?? "http") === "http")}>
              HTTP
            </option>
            <option value="sse" ref={initSelected(c?.connection_type === "sse")}>
              SSE
            </option>
            <option value="stdio" ref={initSelected(c?.connection_type === "stdio")}>
              stdio
            </option>
          </select>
        </label>
        <label class="wide">
          URL (HTTP or SSE)
          <input name="connection_string" type="url" autocomplete="off" placeholder="https://..." ref={initValue(c?.connection_string ?? "")} />
        </label>
        <label>
          Command (stdio)
          <input name="command" autocomplete="off" placeholder="npx" ref={initValue(stdio.command ?? "")} />
        </label>
        <label>
          Arguments (stdio, comma separated)
          <input name="args" autocomplete="off" ref={initValue((stdio.args ?? []).join(", "))} />
        </label>
        <label class="wide">
          Headers, one per line as Name: value
          <textarea name="headers" class="mono" rows="3" spellcheck={false} ref={initValue(Object.keys(hdrs).map((k) => k + ": " + hdrs[k]).join("\n"))} />
        </label>
        <label class="check">
          <input type="checkbox" name="disabled" ref={initChecked(!!c?.disabled)} /> Disabled
        </label>
        <FormError text={error()} />
      </div>
      <div class="actions">
        <button type="button" id="mcp-cancel" class="ghost" onClick={props.onClose}>
          Cancel
        </button>
        <button type="submit" id="mcp-save" class="primary" disabled={busy()}>
          {c ? "Save changes" : "Add client"}
        </button>
      </div>
    </form>
  )
}

function ClientCard(props: { c: Cfg; st: McpStatus | undefined; onEdit: () => void; onChange: () => void }) {
  const { busy, run } = useRun()
  const tools = () => props.st?.tools_list ?? []
  const disabled = () => !!props.c.disabled
  const connected = () => !!props.st?.connected
  const status = () => (disabled() ? "disabled" : connected() ? "connected" : "down")
  const where = () => props.c.connection_string || String((props.c.stdio_config as { command?: string } | undefined)?.command ?? "")

  // Turns one tool on or off: the tool goes in or out of tools_to_skip, and of tools_to_execute when
  // that list is set.
  const setAllowed = (tool: string, allow: boolean) =>
    run(async () => {
      const c = props.c
      const body = clientBody(c)
      body.tools_to_skip = ((c.tools_to_skip as string[] | undefined) ?? []).filter((x) => x !== tool).concat(allow ? [] : [tool])
      const exec = (c.tools_to_execute as string[] | undefined) ?? []
      if (exec.length && !exec.includes("*")) body.tools_to_execute = exec.filter((x) => x !== tool).concat(allow ? [tool] : [])
      await api.put("/api/mcp/client/{name}", { params: { name: String(c.name) }, body })
      notify(tool + (allow ? " enabled" : " disabled"), "ok")
      props.onChange()
    })

  return (
    <article class="card" aria-label={"MCP client " + props.c.name}>
      <header class="toolbar" style="margin-bottom:8px">
        <h3>{String(props.c.name)}</h3>
        <Pill>{props.c.connection_type || "http"}</Pill>
        <Pill tone={disabled() ? "" : connected() ? "ok" : "bad"}>{status()}</Pill>
        <span class="hint mono grow">{where()}</span>
        <span class="row-actions">
          <button type="button" class="ghost" onClick={props.onEdit}>
            Edit
          </button>
          <button
            type="button"
            class="ghost"
            disabled={busy()}
            onClick={() =>
              run(async () => {
                await api.post("/api/mcp/client/{name}/reconnect", { params: { name: String(props.c.name) } })
                notify("Reconnecting " + props.c.name, "ok")
                props.onChange()
              })
            }
          >
            Reconnect
          </button>
          <DangerButton
            label="Delete"
            action={async () => {
              await api.del("/api/mcp/client/{name}", { params: { name: String(props.c.name) } })
              notify("MCP client deleted", "ok")
              props.onChange()
            }}
          />
        </span>
      </header>
      <Show when={props.st?.error && !connected() && !disabled()}>
        <p class="error">{props.st?.error}</p>
      </Show>
      <h4>{"Tools" + (tools().length ? " (" + tools().length + ")" : "")}</h4>
      <Show
        when={tools().length}
        fallback={<p class="hint">{disabled() ? "The client is disabled." : "No tools listed yet. Tools appear once the client connects."}</p>}
      >
        <div class="tool-chips">
          <For each={tools()} keyed={(t) => t.name}>
            {(t) => (
              <button
                type="button"
                class="toggle mono"
                aria-pressed={tf(!!t().allowed)}
                title={t().allowed ? "Enabled. Select to disable." : "Disabled. Select to enable."}
                disabled={busy()}
                onClick={() => setAllowed(t().name, !t().allowed)}
              >
                {t().name}
              </button>
            )}
          </For>
        </div>
      </Show>
    </article>
  )
}

export function Mcp() {
  const data = createMemo(loadAll)
  const reload = () => refresh(data)
  const [editor, setEditor] = createSignal<{ c: Cfg | undefined } | undefined>(undefined)
  return (
    <section aria-labelledby="mcp-title">
      <Toolbar title="MCP clients" id="mcp-title">
        <button type="button" id="mcp-refresh" class="ghost" onClick={reload}>
          Refresh
        </button>
        <button type="button" id="mcp-new" class="primary" onClick={() => setEditor({ c: undefined })}>
          Add client
        </button>
      </Toolbar>
      <Show when={editor()} keyed>
        {(e) => (
          <McpForm
            current={e.c}
            onClose={() => setEditor(undefined)}
            onSaved={() => {
              setEditor(undefined)
              reload()
            }}
          />
        )}
      </Show>
      <div id="mcp-list">
        <Errored fallback={(err) => <ErrP error={err()} />}>
          <Loading fallback={<p class="muted">Loading...</p>}>
            <Show when={data().clients.length} fallback={<p class="card muted">No MCP clients yet. Add one above.</p>}>
              <For each={data().clients} keyed={(c) => String(c.name)}>
                {(c) => <ClientCard c={c()} st={data().status[String(c().name)]} onEdit={() => setEditor({ c: c() })} onChange={reload} />}
              </For>
            </Show>
          </Loading>
        </Errored>
      </div>
    </section>
  )
}

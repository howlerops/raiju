import { createMemo, createSignal, createStore, For, refresh, Show, snapshot, untrack } from "solid-js"
import { api } from "../api/client"
import { loadOptions, type Options as AllOptions } from "../api/options"
import { canCall } from "../perm"
import type { VirtualKey, VkProviderConfig } from "../api/types"
import { fmtInt, idLabel, splitList } from "../fmt"
import { CanCall, ClientToolsRows, type ClientTools, copyText, DangerButton, fieldValue, FormError, Guard, initChecked, initSelected, initValue, notify, Table, Toolbar, useFormRun, useRun, tf } from "../ui"

const VK = "/api/governance/virtual-keys"
// rows of the key table shown at a time
const PAGE_SIZE = 50

type Options = Pick<AllOptions, "providers" | "teams" | "customers" | "budgets" | "rate_limits" | "clients">

type McpCfg = NonNullable<VirtualKey["mcp_configs"]>[number]

const loadKeys = async (): Promise<VirtualKey[]> => (await api.get("/api/governance/virtual-keys")).virtual_keys
const loadOpts = (): Promise<Options> => loadOptions("providers", "teams", "customers", "budgets", "rate_limits", "clients")

interface Named {
  id: string
  name?: string
}

// id -> shown name, built once per load so a table row does not scan the list
function nameMap(items: Named[]): Map<string, string> {
  return new Map(items.map((x) => [x.id, x.name || x.id]))
}

function nameOf(names: Map<string, string>, id: string | undefined): string {
  if (!id) return "—"
  return names.get(id) ?? id
}

// What a key may run on MCP: absent means no list (not limited), an empty list means none.
function mcpSummary(list: McpCfg[] | undefined): string {
  if (list === undefined || list === null) return "Not limited"
  if (!list.length) return "None"
  return list
    .map((c) => {
      const t = c.tools_to_execute ?? []
      const what = t.includes("*") ? "all tools" : t.length ? t.join(", ") : "none"
      return c.mcp_client_name + " (" + what + ")"
    })
    .join("; ")
}

// Body for PUT built from a listed key. The masked value is left out, which keeps the stored one.
function recordBody(vk: VirtualKey, patch?: Record<string, unknown>): Record<string, unknown> {
  return {
    id: vk.id,
    name: vk.name || "",
    description: vk.description || "",
    is_active: vk.is_active !== false,
    team_id: vk.team_id || null,
    customer_id: vk.customer_id || null,
    budget_id: vk.budget_id || null,
    rate_limit_id: vk.rate_limit_id || null,
    provider_configs: vk.provider_configs || [],
    key_ids: vk.key_ids,
    expires_at: vk.expires_at,
    disable_content_logging: vk.disable_content_logging,
    mcp_configs: vk.mcp_configs,
    ...(patch ?? {}),
  }
}

function SelectOf(props: { name: string; items: Named[]; selected: string | undefined; label: string }) {
  const missing = () => !!props.selected && !props.items.some((i) => i.id === props.selected)
  return (
    <label>
      {props.label}
      <select class="select select-sm" name={props.name}>
        <option value="" ref={initSelected(!props.selected)}>
          None
        </option>
        <For each={props.items} keyed={(i) => i.id}>
          {(it) => (
            <option value={it().id} ref={initSelected(it().id === props.selected)}>
              {idLabel(it())}
            </option>
          )}
        </For>
        <Show when={missing()}>
          <option value={props.selected} ref={initSelected(true)}>
            {props.selected + " (missing)"}
          </option>
        </Show>
      </select>
    </label>
  )
}

interface RuleRow {
  provider: string
  models: string
}
type McpRow = ClientTools

function VkForm(props: { vk: VirtualKey | undefined; opts: Options; onClose: () => void; onSaved: (secret: string | undefined) => void }) {
  const { busy, error, run } = useFormRun()
  const vk = untrack(() => props.vk)
  const [rows, setRows] = createStore<{ rules: RuleRow[]; mcp: McpRow[] }>({
    rules: (vk?.provider_configs ?? []).map((p) => ({ provider: p.provider, models: (p.allowed_models ?? []).join(", ") })),
    mcp: (vk?.mcp_configs ?? []).map((m) => ({ client: m.mcp_client_name, tools: (m.tools_to_execute ?? []).join(", ") })),
  })
  const providerNames = (extra: string) => {
    const names = props.opts.providers.map((p) => p.name)
    if (extra && !names.includes(extra)) names.push(extra)
    return names
  }
  const clientNames = untrack(() => props.opts.clients.map((c) => String(c.name ?? "")))

  const submit = (ev: SubmitEvent) => {
    ev.preventDefault()
    const form = ev.currentTarget as HTMLFormElement
    const get = (n: string) => fieldValue(form, n)
    const opt = (n: string) => get(n) || null
    void run(async () => {
      const r = snapshot(rows)
      const rules: VkProviderConfig[] = []
      for (const row of r.rules) {
        if (!row.provider) continue
        const prev = (vk?.provider_configs ?? []).find((p) => p.provider === row.provider)
        rules.push({
          weight: prev?.weight,
          budget_id: prev?.budget_id,
          rate_limit_id: prev?.rate_limit_id,
          provider: row.provider,
          allowed_models: splitList(row.models),
        })
      }
      const mcp: McpCfg[] = []
      for (const row of r.mcp) {
        if (!row.client) continue
        mcp.push({ mcp_client_name: row.client, tools_to_execute: splitList(row.tools) })
      }
      const body: Record<string, unknown> = {
        ...(vk ? recordBody(vk) : {}),
        name: get("name").trim(),
        description: get("description").trim(),
        is_active: (form.elements.namedItem("is_active") as HTMLInputElement).checked,
        team_id: opt("team_id"),
        customer_id: opt("customer_id"),
        budget_id: opt("budget_id"),
        rate_limit_id: opt("rate_limit_id"),
        provider_configs: rules,
        mcp_configs: mcp.length ? mcp : undefined,
      }
      const id = vk ? vk.id : get("id").trim()
      if (id) body.id = id
      if (vk) {
        await api.put("/api/governance/virtual-keys/{id}", { params: { id: vk.id }, body })
        notify("Virtual key saved", "ok")
        props.onSaved(undefined)
      } else {
        const created = await api.post("/api/governance/virtual-keys", { body })
        const c = created as { value?: string; virtual_key?: { value?: string } }
        const value = c.value || c.virtual_key?.value
        if (!value) notify("Virtual key created", "ok")
        props.onSaved(value ? String(value) : undefined)
      }
    })
  }

  return (
    <form id="vk-form" class="card panel bg-base-100 border border-base-300" aria-labelledby="vk-form-title" onSubmit={submit}>
      <h2 id="vk-form-title">{vk ? "Edit " + (vk.name || vk.id) : "New virtual key"}</h2>
      <div class="form-grid">
        <label>
          Name
          <input class="input input-sm" name="name" required autocomplete="off" ref={(el) => { initValue(vk?.name ?? "")(el); queueMicrotask(() => el.focus()) }} />
        </label>
        <label>
          ID
          <input name="id" class="input input-sm mono" ref={initValue(vk?.id ?? "")} readonly={!!vk} placeholder="blank = generated" autocomplete="off" />
        </label>
        <label class="wide">
          Description
          <input class="input input-sm" name="description" ref={initValue(vk?.description ?? "")} autocomplete="off" />
        </label>
        <SelectOf name="team_id" label="Team" items={props.opts.teams} selected={vk?.team_id} />
        <SelectOf name="customer_id" label="Customer" items={props.opts.customers} selected={vk?.customer_id} />
        <SelectOf name="budget_id" label="Budget" items={props.opts.budgets} selected={vk?.budget_id} />
        <SelectOf name="rate_limit_id" label="Rate limit" items={props.opts.rate_limits} selected={vk?.rate_limit_id} />
        <label class="check">
          <input class="checkbox checkbox-sm" type="checkbox" name="is_active" ref={initChecked(vk ? vk.is_active !== false : true)} /> Active
        </label>
      </div>

      <fieldset class="wide" style="margin-top:12px">
        <legend>Provider access</legend>
        <p class="hint">Blank models means every model of that provider.</p>
        <div id="vk-rules">
          <For each={rows.rules}>
            {(row, i) => (
              <div class="rule">
                <select class="select select-sm"
                  aria-label="Provider"
                  onChange={(e) => setRows((s) => void (s.rules[i()]!.provider = e.currentTarget.value))}
                >
                  <option value="" selected={!row.provider}>
                    Choose provider
                  </option>
                  <For each={untrack(() => providerNames(row.provider))}>
                    {(n) => (
                      <option value={n} selected={n === row.provider}>
                        {n}
                      </option>
                    )}
                  </For>
                </select>
                <input class="input input-sm"
                  type="text"
                  aria-label="Allowed models"
                  placeholder="all models"
                  autocomplete="off"
                  value={row.models}
                  onInput={(e) => setRows((s) => void (s.rules[i()]!.models = e.currentTarget.value))}
                />
                <button type="button" class="btn btn-sm btn-ghost" onClick={() => setRows((s) => void s.rules.splice(i(), 1))}>
                  Remove
                </button>
              </div>
            )}
          </For>
        </div>
        <button type="button" id="vk-add-rule" class="btn btn-sm btn-ghost" onClick={() => setRows((s) => void s.rules.push({ provider: "", models: "" }))}>
          Add provider
        </button>
      </fieldset>

      <fieldset class="wide" style="margin-top:12px">
        <legend>MCP tools</legend>
        <p class="hint">With no rows the key is not limited to MCP tools. Tools: * for all, blank for none, or a comma list.</p>
        <div id="vk-mcp">
          <ClientToolsRows
            rows={rows.mcp}
            clients={clientNames}
            update={(change) => setRows((s) => change(s.mcp))}
            rowClass="mcp-rule"
            toolsLabel="Allowed MCP tools"
            toolsPlaceholder="* for all, blank for none, or a comma list"
          />
        </div>
        <button type="button" id="vk-add-mcp" class="btn btn-sm btn-ghost" onClick={() => setRows((s) => void s.mcp.push({ client: "", tools: "*" }))}>
          Add MCP client
        </button>
      </fieldset>

      <FormError text={error()} />
      <div class="actions">
        <button type="button" id="vk-cancel" class="btn btn-sm btn-ghost" onClick={props.onClose}>
          Cancel
        </button>
        <button type="submit" id="vk-save" class="btn btn-sm btn-primary" disabled={busy()}>
          {vk ? "Save changes" : "Create key"}
        </button>
      </div>
    </form>
  )
}

function Secret(props: { value: string; onDone: () => void }) {
  const [msg, setMsg] = createSignal("")
  let input: HTMLInputElement | undefined
  return (
    <div id="vk-secret" class="callout" role="status">
      <p>
        <strong>Copy this key now.</strong> The full value is shown only once.
      </p>
      <div class="secret-row">
        <input
          id="vk-secret-value"
          class="input input-sm mono"
          readonly
          aria-label="New virtual key value"
          value={props.value}
          ref={(el) => {
            input = el
            queueMicrotask(() => {
              el.focus()
              el.select()
            })
          }}
        />
        <button
          type="button"
          id="vk-copy"
          class="btn btn-sm btn-primary"
          onClick={async () => {
            const ok = await copyText(props.value, input)
            setMsg(ok ? "Copied to the clipboard." : "Press Ctrl+C (Cmd+C) to copy the selected key.")
          }}
        >
          Copy
        </button>
        <button type="button" id="vk-secret-close" class="btn btn-sm btn-ghost" onClick={props.onDone}>
          Done
        </button>
      </div>
      <p class="hint" id="vk-copy-msg">
        {msg()}
      </p>
    </div>
  )
}

export function Keys() {
  // The keys are their own read: a toggle, a rotation or a save refetches them, not the option lists.
  const keys = createMemo(loadKeys)
  const opts = createMemo(loadOpts)
  const reload = () => refresh(keys)
  const reloadAll = () => {
    refresh(keys)
    refresh(opts)
  }
  const teams = createMemo(() => nameMap(opts().teams))
  const customers = createMemo(() => nameMap(opts().customers))
  const budgets = createMemo(() => nameMap(opts().budgets))
  const rateLimits = createMemo(() => nameMap(opts().rate_limits))
  const [pageNo, setPageNo] = createSignal(0)
  const lastPage = () => Math.max(0, Math.ceil(keys().length / PAGE_SIZE) - 1)
  // a deletion can leave the page past the end
  const start = () => Math.min(pageNo(), lastPage()) * PAGE_SIZE
  const shown = createMemo(() => keys().slice(start(), start() + PAGE_SIZE))
  const [editor, setEditor] = createSignal<{ vk: VirtualKey | undefined } | undefined>(undefined)
  const [secret, setSecret] = createSignal<string | undefined>(undefined)
  const { busy, run } = useRun()

  return (
    <section aria-labelledby="vk-title">
      <Toolbar title="Virtual keys" id="vk-title">
        <button type="button" id="vk-refresh" class="btn btn-sm btn-ghost" onClick={reloadAll}>
          Refresh
        </button>
        <CanCall method="POST" path={VK}>
          <button type="button" id="vk-new" class="btn btn-sm btn-primary" onClick={() => setEditor({ vk: undefined })}>
            New virtual key
          </button>
        </CanCall>
      </Toolbar>

      <Show when={secret()}>{(s) => <Secret value={s()} onDone={() => setSecret(undefined)} />}</Show>

      <Guard variant="table">
        <Show when={editor()} keyed>
          {(e) => (
            <VkForm
              vk={e.vk}
              opts={opts()}
              onClose={() => setEditor(undefined)}
              onSaved={(v) => {
                setEditor(undefined)
                if (v) setSecret(v)
                reload()
              }}
            />
          )}
        </Show>
        <div id="vk-list" class="card panel bg-base-100 border border-base-300">
          <Show when={keys().length} fallback={<p class="muted">No virtual keys yet. Create one to give a client scoped access.</p>}>
            <Table cols={["Name", "Status", "Providers", "MCP tools", "Team", "Customer", "Budget", "Rate limit", ""]}>
              <For each={shown()} keyed={(k) => k.id}>
                {(vk) => {
                  const active = () => vk().is_active !== false
                  const rules = () =>
                    (vk().provider_configs ?? [])
                      .map((p) => p.provider + " (" + (p.allowed_models && p.allowed_models.length ? p.allowed_models.join(", ") : "all models") + ")")
                      .join("; ")
                  return (
                    <tr>
                      <td>
                        <div>
                          <strong>{vk().name || vk().id}</strong>
                          <div class="hint mono">{vk().id}</div>
                        </div>
                      </td>
                      <td>
                        <button
                          type="button"
                          class="btn btn-sm tool-toggle"
                          aria-pressed={tf(active())}
                          disabled={busy() || !canCall("PUT", VK)}
                          onClick={() =>
                            run(async () => {
                              await api.put("/api/governance/virtual-keys/{id}", {
                                params: { id: vk().id },
                                body: recordBody(vk(), { is_active: !active() }),
                              })
                              notify((vk().name || vk().id) + (active() ? " disabled" : " enabled"), "ok")
                              reload()
                            })
                          }
                        >
                          {active() ? "Active" : "Disabled"}
                        </button>
                      </td>
                      <td>{rules() || "none"}</td>
                      <td>{mcpSummary(vk().mcp_configs)}</td>
                      <td>{nameOf(teams(), vk().team_id)}</td>
                      <td>{nameOf(customers(), vk().customer_id)}</td>
                      <td>{nameOf(budgets(), vk().budget_id)}</td>
                      <td>{nameOf(rateLimits(), vk().rate_limit_id)}</td>
                      <td>
                        <span class="row-actions">
                          <CanCall method="PUT" path={VK}>
                            <button type="button" class="btn btn-sm btn-ghost" onClick={() => setEditor({ vk: vk() })}>
                              Edit
                            </button>
                          </CanCall>
                          <CanCall method="POST" path={VK + "/{id}/rotate"}>
                            <button
                              type="button"
                              class="btn btn-sm btn-ghost"
                              disabled={busy()}
                              onClick={() =>
                                run(async () => {
                                  const r = await api.post("/api/governance/virtual-keys/{id}/rotate", { params: { id: vk().id } })
                                  reload()
                                  const value = r.virtual_key?.value
                                  if (value) setSecret(value)
                                  else notify("Virtual key rotated", "ok")
                                })
                              }
                            >
                              Rotate
                            </button>
                          </CanCall>
                          <CanCall method="DELETE" path={VK}>
                            <DangerButton
                              label="Delete"
                              action={async () => {
                                await api.del("/api/governance/virtual-keys/{id}", { params: { id: vk().id } })
                                notify("Virtual key deleted", "ok")
                                reload()
                              }}
                            />
                          </CanCall>
                        </span>
                      </td>
                    </tr>
                  )
                }}
              </For>
            </Table>
            <Show when={keys().length > PAGE_SIZE}>
              <div class="pager">
                <span class="hint" id="vk-range" role="status">
                  {start() + 1 + "–" + (start() + shown().length) + " of " + fmtInt(keys().length)}
                </span>
                <button type="button" id="vk-prev" class="btn btn-sm btn-ghost" disabled={start() === 0} onClick={() => setPageNo(start() / PAGE_SIZE - 1)}>
                  Previous
                </button>
                <button type="button" id="vk-next" class="btn btn-sm btn-ghost" disabled={start() + PAGE_SIZE >= keys().length} onClick={() => setPageNo(start() / PAGE_SIZE + 1)}>
                  Next
                </button>
              </div>
            </Show>
          </Show>
        </div>
      </Guard>
    </section>
  )
}

import { createMemo, createSignal, Errored, For, Loading, refresh, Show, snapshot, untrack } from "solid-js"
import { createStore } from "solid-js"
import { api } from "../api/client"
import { can } from "../perm"
import type { Budget, Customer, McpClient, Provider, RateLimit, Team, VirtualKey, VkProviderConfig } from "../api/types"
import { splitList } from "../fmt"
import { Can, copyText, DangerButton, ErrP, FormError, initChecked, initSelected, initValue, notify, Table, Toolbar, useFormRun, useRun, tf } from "../ui"

interface Options {
  providers: Provider[]
  teams: Team[]
  customers: Customer[]
  budgets: Budget[]
  rate_limits: RateLimit[]
  mcp: McpClient[]
}

type McpCfg = NonNullable<VirtualKey["mcp_configs"]>[number]

async function silently<T>(p: Promise<T>, pick: (t: T) => unknown[]): Promise<unknown[]> {
  try {
    return pick(await p)
  } catch {
    return []
  }
}

async function loadAll(): Promise<{ keys: VirtualKey[]; opts: Options }> {
  const [keys, providers, teams, customers, budgets, rate_limits, mcp] = await Promise.all([
    api.get("/api/governance/virtual-keys"),
    silently(api.get("/api/providers"), (b) => b.providers),
    silently(api.get("/api/governance/teams"), (b) => b.teams),
    silently(api.get("/api/governance/customers"), (b) => b.customers),
    silently(api.get("/api/governance/budgets"), (b) => b.budgets),
    silently(api.get("/api/governance/rate-limits"), (b) => b.rate_limits),
    silently(api.get("/api/mcp/clients"), (b) => b.clients),
  ])
  return {
    keys: keys.virtual_keys,
    opts: {
      providers: providers as Provider[],
      teams: teams as Team[],
      customers: customers as Customer[],
      budgets: budgets as Budget[],
      rate_limits: rate_limits as RateLimit[],
      mcp: mcp as McpClient[],
    },
  }
}

interface Named {
  id: string
  name?: string
}

function nameOf(items: Named[], id: string | undefined): string {
  if (!id) return "—"
  const hit = items.find((x) => x.id === id)
  return hit ? hit.name || hit.id : id
}

function labelOf(it: Named): string {
  return it.name ? it.name + " (" + it.id + ")" : it.id
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
      <select name={props.name}>
        <option value="" ref={initSelected(!props.selected)}>
          None
        </option>
        <For each={props.items} keyed={(i) => i.id}>
          {(it) => (
            <option value={it().id} ref={initSelected(it().id === props.selected)}>
              {labelOf(it())}
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
interface McpRow {
  client: string
  tools: string
}

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
  const clientNames = (extra: string) => {
    const names = props.opts.mcp.map((c) => String(c.name ?? ""))
    if (extra && !names.includes(extra)) names.push(extra)
    return names
  }

  const submit = (ev: SubmitEvent) => {
    ev.preventDefault()
    const form = ev.currentTarget as HTMLFormElement
    const get = (n: string) => (form.elements.namedItem(n) as HTMLInputElement | HTMLSelectElement).value
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
    <form id="vk-form" class="card" aria-labelledby="vk-form-title" onSubmit={submit}>
      <h2 id="vk-form-title">{vk ? "Edit " + (vk.name || vk.id) : "New virtual key"}</h2>
      <div class="form-grid">
        <label>
          Name
          <input name="name" required autocomplete="off" ref={(el) => { initValue(vk?.name ?? "")(el); queueMicrotask(() => el.focus()) }} />
        </label>
        <label>
          ID
          <input name="id" class="mono" ref={initValue(vk?.id ?? "")} readonly={!!vk} placeholder="blank = generated" autocomplete="off" />
        </label>
        <label class="wide">
          Description
          <input name="description" ref={initValue(vk?.description ?? "")} autocomplete="off" />
        </label>
        <SelectOf name="team_id" label="Team" items={props.opts.teams} selected={vk?.team_id} />
        <SelectOf name="customer_id" label="Customer" items={props.opts.customers} selected={vk?.customer_id} />
        <SelectOf name="budget_id" label="Budget" items={props.opts.budgets} selected={vk?.budget_id} />
        <SelectOf name="rate_limit_id" label="Rate limit" items={props.opts.rate_limits} selected={vk?.rate_limit_id} />
        <label class="check">
          <input type="checkbox" name="is_active" ref={initChecked(vk ? vk.is_active !== false : true)} /> Active
        </label>
      </div>

      <fieldset class="wide" style="margin-top:12px">
        <legend>Provider access</legend>
        <p class="hint">Blank models means every model of that provider.</p>
        <div id="vk-rules">
          <For each={rows.rules}>
            {(row, i) => (
              <div class="rule">
                <select
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
                <input
                  type="text"
                  aria-label="Allowed models"
                  placeholder="all models"
                  autocomplete="off"
                  value={row.models}
                  onInput={(e) => setRows((s) => void (s.rules[i()]!.models = e.currentTarget.value))}
                />
                <button type="button" class="ghost" onClick={() => setRows((s) => void s.rules.splice(i(), 1))}>
                  Remove
                </button>
              </div>
            )}
          </For>
        </div>
        <button type="button" id="vk-add-rule" class="ghost" onClick={() => setRows((s) => void s.rules.push({ provider: "", models: "" }))}>
          Add provider
        </button>
      </fieldset>

      <fieldset class="wide" style="margin-top:12px">
        <legend>MCP tools</legend>
        <p class="hint">With no rows the key is not limited to MCP tools. Tools: * for all, blank for none, or a comma list.</p>
        <div id="vk-mcp">
          <For each={rows.mcp}>
            {(row, i) => (
              <div class="rule mcp-rule">
                <select aria-label="MCP client" onChange={(e) => setRows((s) => void (s.mcp[i()]!.client = e.currentTarget.value))}>
                  <option value="" selected={!row.client}>
                    Choose MCP client
                  </option>
                  <For each={untrack(() => clientNames(row.client))}>
                    {(n) => (
                      <option value={n} selected={n === row.client}>
                        {n}
                      </option>
                    )}
                  </For>
                </select>
                <input
                  type="text"
                  aria-label="Allowed MCP tools"
                  placeholder="* for all, blank for none, or a comma list"
                  autocomplete="off"
                  value={row.tools}
                  onInput={(e) => setRows((s) => void (s.mcp[i()]!.tools = e.currentTarget.value))}
                />
                <button type="button" class="ghost" onClick={() => setRows((s) => void s.mcp.splice(i(), 1))}>
                  Remove
                </button>
              </div>
            )}
          </For>
        </div>
        <button type="button" id="vk-add-mcp" class="ghost" onClick={() => setRows((s) => void s.mcp.push({ client: "", tools: "*" }))}>
          Add MCP client
        </button>
      </fieldset>

      <FormError text={error()} />
      <div class="actions">
        <button type="button" id="vk-cancel" class="ghost" onClick={props.onClose}>
          Cancel
        </button>
        <button type="submit" id="vk-save" class="primary" disabled={busy()}>
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
          class="mono"
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
          class="primary"
          onClick={async () => {
            const ok = await copyText(props.value, input)
            setMsg(ok ? "Copied to the clipboard." : "Press Ctrl+C (Cmd+C) to copy the selected key.")
          }}
        >
          Copy
        </button>
        <button type="button" id="vk-secret-close" class="ghost" onClick={props.onDone}>
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
  const data = createMemo(loadAll)
  const reload = () => refresh(data)
  const [editor, setEditor] = createSignal<{ vk: VirtualKey | undefined } | undefined>(undefined)
  const [secret, setSecret] = createSignal<string | undefined>(undefined)
  const { busy, run } = useRun()

  return (
    <section aria-labelledby="vk-title">
      <Toolbar title="Virtual keys" id="vk-title">
        <button type="button" id="vk-refresh" class="ghost" onClick={reload}>
          Refresh
        </button>
        <Can resource="VirtualKeys" op="Create">
          <button type="button" id="vk-new" class="primary" onClick={() => setEditor({ vk: undefined })}>
            New virtual key
          </button>
        </Can>
      </Toolbar>

      <Show when={secret()}>{(s) => <Secret value={s()} onDone={() => setSecret(undefined)} />}</Show>

      <Errored fallback={(err) => <ErrP error={err()} />}>
        <Loading fallback={<p class="muted">Loading...</p>}>
          <Show when={editor()} keyed>
            {(e) => (
              <VkForm
                vk={e.vk}
                opts={data().opts}
                onClose={() => setEditor(undefined)}
                onSaved={(v) => {
                  setEditor(undefined)
                  if (v) setSecret(v)
                  reload()
                }}
              />
            )}
          </Show>
          <div id="vk-list" class="card">
            <Show when={data().keys.length} fallback={<p class="muted">No virtual keys yet. Create one to give a client scoped access.</p>}>
              <Table cols={["Name", "Status", "Providers", "MCP tools", "Team", "Customer", "Budget", "Rate limit", ""]}>
                <For each={data().keys} keyed={(k) => k.id}>
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
                            class="toggle"
                            aria-pressed={tf(active())}
                            disabled={busy() || !can("VirtualKeys", "Update")}
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
                        <td>{nameOf(data().opts.teams, vk().team_id)}</td>
                        <td>{nameOf(data().opts.customers, vk().customer_id)}</td>
                        <td>{nameOf(data().opts.budgets, vk().budget_id)}</td>
                        <td>{nameOf(data().opts.rate_limits, vk().rate_limit_id)}</td>
                        <td>
                          <span class="row-actions">
                            <Can resource="VirtualKeys" op="Update">
                              <button type="button" class="ghost" onClick={() => setEditor({ vk: vk() })}>
                                Edit
                              </button>
                            </Can>
                            <Can resource="VirtualKeys" op="Create">
                              <button
                                type="button"
                                class="ghost"
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
                            </Can>
                            <Can resource="VirtualKeys" op="Delete">
                              <DangerButton
                                label="Delete"
                                action={async () => {
                                  await api.del("/api/governance/virtual-keys/{id}", { params: { id: vk().id } })
                                  notify("Virtual key deleted", "ok")
                                  reload()
                                }}
                              />
                            </Can>
                          </span>
                        </td>
                      </tr>
                    )
                  }}
                </For>
              </Table>
            </Show>
          </div>
        </Loading>
      </Errored>
    </section>
  )
}

import { createMemo, createSignal, Errored, For, Loading, refresh, Show } from "solid-js"
import type { JSX } from "@solidjs/web"
import { api, send } from "../api/client"
import { can } from "../perm"
import { fmtInt, fmtMoney } from "../fmt"
import { Can, DangerButton, ErrP, FormError, Mono, notify, Table, Toolbar, useFormRun } from "../ui"

interface FieldSpec {
  name: string
  label: string
  type?: "number"
  step?: string
  min?: string
  placeholder?: string
  required?: boolean
  key?: boolean
}

interface Column<T> {
  label: string
  get: (row: T) => JSX.Element
}

type Row = Record<string, unknown>

interface Spec<T extends Row> {
  noun: string
  title: string
  path: string
  fields: FieldSpec[]
  load: () => Promise<T[]>
  columns: Column<T>[]
}

// The permission resource of a governance collection (rbac.tov resourceOf)
function resourceOf(path: string): string {
  const coll = path.split("/").pop() ?? ""
  return coll === "teams" ? "Teams" : coll === "customers" ? "Customers" : "Governance"
}

const dash = (v: unknown): string => (v === undefined || v === null || v === "" ? "—" : String(v))

const SPECS: Spec<Row>[] = [
  {
    noun: "Budget",
    title: "Budgets",
    path: "/api/governance/budgets",
    fields: [
      { name: "id", label: "ID", required: true, key: true, placeholder: "e.g. team-ops" },
      { name: "max_limit", label: "Max limit (USD)", type: "number", step: "any", min: "0", required: true },
      { name: "reset_duration", label: "Reset every", placeholder: "1d, 1h, 30m", required: true },
    ],
    load: async () => (await api.get("/api/governance/budgets")).budgets as Row[],
    columns: [
      { label: "ID", get: (b) => <Mono>{dash(b.id)}</Mono> },
      { label: "Max limit", get: (b) => fmtMoney(b.max_limit) },
      { label: "Used", get: (b) => (b.current_usage === undefined ? "—" : fmtMoney(b.current_usage)) },
      { label: "Reset", get: (b) => dash(b.reset_duration) },
    ],
  },
  {
    noun: "Rate limit",
    title: "Rate limits",
    path: "/api/governance/rate-limits",
    fields: [
      { name: "id", label: "ID", required: true, key: true, placeholder: "e.g. standard" },
      { name: "token_max_limit", label: "Max tokens", type: "number", step: "1", min: "0" },
      { name: "token_reset_duration", label: "Token window", placeholder: "1m, 1h" },
      { name: "request_max_limit", label: "Max requests", type: "number", step: "1", min: "0" },
      { name: "request_reset_duration", label: "Request window", placeholder: "1m, 1h" },
    ],
    load: async () => (await api.get("/api/governance/rate-limits")).rate_limits as Row[],
    columns: [
      { label: "ID", get: (r) => <Mono>{dash(r.id)}</Mono> },
      { label: "Tokens", get: (r) => (r.token_max_limit === undefined ? "—" : fmtInt(r.token_max_limit) + " / " + (r.token_reset_duration || "?")) },
      { label: "Requests", get: (r) => (r.request_max_limit === undefined ? "—" : fmtInt(r.request_max_limit) + " / " + (r.request_reset_duration || "?")) },
    ],
  },
  {
    noun: "Team",
    title: "Teams",
    path: "/api/governance/teams",
    fields: [
      { name: "id", label: "ID", required: true, key: true },
      { name: "name", label: "Name", required: true },
      { name: "customer_id", label: "Customer ID" },
      { name: "budget_id", label: "Budget ID" },
    ],
    load: async () => (await api.get("/api/governance/teams")).teams as Row[],
    columns: [
      { label: "ID", get: (t) => <Mono>{dash(t.id)}</Mono> },
      { label: "Name", get: (t) => dash(t.name) },
      { label: "Customer", get: (t) => dash(t.customer_id) },
      { label: "Budget", get: (t) => dash(t.budget_id) },
    ],
  },
  {
    noun: "Customer",
    title: "Customers",
    path: "/api/governance/customers",
    fields: [
      { name: "id", label: "ID", required: true, key: true },
      { name: "name", label: "Name", required: true },
      { name: "budget_id", label: "Budget ID" },
    ],
    load: async () => (await api.get("/api/governance/customers")).customers as Row[],
    columns: [
      { label: "ID", get: (c) => <Mono>{dash(c.id)}</Mono> },
      { label: "Name", get: (c) => dash(c.name) },
      { label: "Budget", get: (c) => dash(c.budget_id) },
    ],
  },
]

function Crud(props: { spec: Spec<Row>; version: () => number }) {
  const spec = props.spec
  const items = createMemo(() => {
    props.version()
    return spec.load()
  })
  const [editing, setEditing] = createSignal<Row | undefined>(undefined)
  const { busy, error, run } = useFormRun()
  let form: HTMLFormElement | undefined

  const reset = () => {
    setEditing(undefined)
    form?.reset()
  }

  const submit = (ev: SubmitEvent) => {
    ev.preventDefault()
    const target = editing()
    void run(async () => {
      const body: Record<string, unknown> = {}
      for (const f of spec.fields) {
        const raw = ((form?.elements.namedItem(f.name) as HTMLInputElement | null)?.value ?? "").trim()
        if (raw === "") {
          body[f.name] = null
          continue
        }
        if (f.type === "number") {
          const n = Number(raw)
          if (!Number.isFinite(n)) throw new Error(f.label + " must be a number.")
          body[f.name] = n
        } else {
          body[f.name] = raw
        }
      }
      if (target) await send("PUT", spec.path + "/" + encodeURIComponent(String(target.id)), { body })
      else await send("POST", spec.path, { body })
      notify(spec.noun + (target ? " saved" : " created"), "ok")
      reset()
      refresh(items)
    })
  }

  const startEdit = (row: Row) => {
    setEditing(row)
    for (const f of spec.fields) {
      const el = form?.elements.namedItem(f.name) as HTMLInputElement | null
      if (!el) continue
      const v = row[f.name]
      el.value = v === undefined || v === null ? "" : String(v)
    }
    const first = form?.querySelector<HTMLInputElement>("input:not([readonly])")
    first?.focus()
  }

  return (
    <section class="card" aria-label={spec.title}>
      <h2>{spec.title}</h2>
      <Show when={!can(resourceOf(spec.path), "Create") && !can(resourceOf(spec.path), "Update")}>
        <p class="hint">Your role can read this list but not change it.</p>
      </Show>
      <form class="form-grid" ref={(el) => (form = el)} onSubmit={submit} hidden={!can(resourceOf(spec.path), "Create") && !can(resourceOf(spec.path), "Update")}>
        <For each={spec.fields}>
          {(f) => (
            <label>
              {f.label}
              <input
                name={f.name}
                type={f.type ?? "text"}
                placeholder={f.placeholder}
                step={f.step}
                min={f.min}
                required={f.required}
                readonly={!!f.key && !!editing()}
                autocomplete="off"
              />
            </label>
          )}
        </For>
        <div class="actions wide">
          <button type="button" class="ghost" hidden={!editing()} onClick={reset}>
            Cancel
          </button>
          <button type="submit" class="primary" disabled={busy()}>
            {editing() ? "Save changes" : "Create"}
          </button>
        </div>
        <FormError text={error()} />
      </form>
      <div>
        <Errored fallback={(err) => <ErrP error={err()} />}>
          <Loading fallback={<p class="muted">Loading...</p>}>
            <Show when={items().length} fallback={<p class="muted">Nothing here yet.</p>}>
              <Table cols={[...spec.columns.map((c) => c.label), ""]}>
                <For each={items()} keyed={(r) => String(r.id)}>
                  {(row) => (
                    <tr>
                      <For each={spec.columns}>{(c) => <td>{c.get(row())}</td>}</For>
                      <td>
                        <span class="row-actions">
                          <Can resource={resourceOf(spec.path)} op="Update">
                            <button type="button" class="ghost" onClick={() => startEdit(row())}>
                              Edit
                            </button>
                          </Can>
                          <Can resource={resourceOf(spec.path)} op="Delete">
                            <DangerButton
                              label="Delete"
                              action={async () => {
                                await send("DELETE", spec.path + "/" + encodeURIComponent(String(row().id)))
                                notify(spec.noun + " deleted", "ok")
                                if (editing() && String(editing()!.id) === String(row().id)) reset()
                                refresh(items)
                              }}
                            />
                          </Can>
                        </span>
                      </td>
                    </tr>
                  )}
                </For>
              </Table>
            </Show>
          </Loading>
        </Errored>
      </div>
    </section>
  )
}

export function Governance() {
  const [version, setVersion] = createSignal(0)
  return (
    <section aria-labelledby="gv-title">
      <Toolbar title="Budgets & limits" id="gv-title">
        <button type="button" id="gv-refresh" class="ghost" onClick={() => setVersion((v) => v + 1)}>
          Refresh
        </button>
      </Toolbar>
      <div id="gov-root">
        <For each={SPECS}>
          {(spec) => (
            <div class="gov-block">
              <Crud spec={spec} version={version} />
            </div>
          )}
        </For>
      </div>
    </section>
  )
}

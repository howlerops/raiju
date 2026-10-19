// Roles and permissions: the built-in roles (read only), the custom roles with an editor for their
// permission pairs (a resource by operation grid), the access profiles attached to each role, and
// the role each admin user holds. Every control follows the caller's own permissions.
import { createMemo, createSignal, Errored, For, Loading, refresh, Show } from "solid-js"
import { message, send } from "../api/client"
import { can } from "../perm"
import { Can, DangerButton, ErrP, FormError, initChecked, initSelected, initValue, Mono, notify, Table, Toolbar, useFormRun, useRun } from "../ui"

interface Pair {
  resource: string
  operation: string
}

interface Role {
  id?: number
  name: string
  description?: string
  dac?: string
  permissions?: Pair[]
  entity_dac?: Record<string, string>
}

interface Profile {
  id: string
  name?: string
  roles?: { role_id: number }[]
}

interface User {
  name: string
  role: string
  disabled?: boolean
}

interface Data {
  roles: Role[]
  resources: string[]
  operations: string[]
  // undefined when the caller may not read them
  profiles: Profile[] | undefined
  users: User[] | undefined
}

// The catalogue a role without Settings / View cannot read; the editor falls back to these.
const RESOURCES = ["Logs", "MCPLogs", "AuditLogs", "ModelProvider", "Observability", "VirtualKeys", "Users", "MCPGateway", "Teams", "Customers", "BusinessUnits", "Projects", "RBAC", "AccessProfiles", "RoutingRules", "Governance", "Settings", "Cluster", "APIKeys"]
const OPERATIONS = ["View", "Create", "Update", "Delete", "Download", "Reveal", "RunInference"]
const DACS: [string, string][] = [
  ["", "Default"],
  ["own-data", "Own data"],
  ["team-data", "Team data"],
  ["business-unit-data", "Business unit data"],
  ["customer-data", "Customer data"],
  ["all-data", "All data"],
]

// What the fixed roles may do (the rules in src/rbac.tov)
const BUILT_IN: [string, string][] = [
  ["admin", "Everything."],
  ["editor", "Reads everything except users, API keys, audit logs and metrics; changes providers and governance records."],
  ["viewer", "Reads everything except users, API keys, audit logs and metrics; changes nothing."],
  ["auditor", "Reads the request logs and the audit logs only."],
]

async function quiet(path: string): Promise<unknown> {
  try {
    return (await send("GET", path, { quiet: true })).data
  } catch {
    return undefined
  }
}

const names = (v: unknown, key: string): string[] | undefined => {
  const list = (v as Record<string, unknown> | undefined)?.[key]
  if (!Array.isArray(list)) return undefined
  return list.map((x) => String((x as { name?: unknown }).name ?? "")).filter((s) => s !== "")
}

async function loadAll(): Promise<Data> {
  const roles = ((await send("GET", "/api/roles")).data as { roles?: Role[] }).roles ?? []
  const [res, ops, profs, users] = await Promise.all([
    quiet("/api/resources"),
    quiet("/api/operations"),
    quiet("/api/governance/access-profiles"),
    quiet("/api/users"),
  ])
  const p = (profs as { profiles?: Profile[] } | undefined)?.profiles
  const u = (users as { users?: User[] } | undefined)?.users
  return { roles, resources: names(res, "resources") ?? RESOURCES, operations: names(ops, "operations") ?? OPERATIONS, profiles: p, users: u }
}

const holders = (d: Data, r: Role): string[] => (d.users ?? []).filter((u) => u.role === r.name).map((u) => u.name)
const attached = (d: Data, r: Role): Profile[] => (d.profiles ?? []).filter((p) => (p.roles ?? []).some((x) => x.role_id === r.id))
const label = (p: Profile): string => (p.name ? p.name + " (" + p.id + ")" : p.id)

function RoleForm(props: { role: Role | undefined; data: Data; onClose: () => void; onSaved: () => void }) {
  const role = props.role
  const { busy, error, run } = useFormRun()
  const held = new Set((role?.permissions ?? []).map((p) => p.resource + "|" + p.operation))
  const wasAttached = new Set(role ? attached(props.data, role).map((p) => p.id) : [])
  const editable = () => (role ? can("RBAC", "Update") : can("RBAC", "Create"))
  const canProfiles = () => editable() && props.data.profiles !== undefined && can("AccessProfiles", "Update")
  let form: HTMLFormElement | undefined

  const rowBoxes = (res: string) => [...(form?.querySelectorAll<HTMLInputElement>('input[name="perm"]') ?? [])].filter((b) => b.value.startsWith(res + "|"))
  const toggleRow = (res: string) => {
    const boxes = rowBoxes(res)
    const all = boxes.every((b) => b.checked)
    for (const b of boxes) b.checked = !all
  }

  const submit = (ev: SubmitEvent) => {
    ev.preventDefault()
    const f = ev.currentTarget as HTMLFormElement
    const get = (n: string) => ((f.elements.namedItem(n) as HTMLInputElement | HTMLSelectElement).value ?? "").trim()
    void run(async () => {
      const permissions: Pair[] = [...f.querySelectorAll<HTMLInputElement>('input[name="perm"]:checked')].map((b) => {
        const [resource, operation] = b.value.split("|")
        return { resource: resource!, operation: operation! }
      })
      const body: Record<string, unknown> = { permissions }
      const description = get("description")
      if (description) body.description = description
      const dac = get("dac")
      if (dac) body.dac = dac
      let id = role?.id
      if (role) {
        // the data access overrides per resource are not edited here; they are sent back as they were
        if (role.entity_dac && Object.keys(role.entity_dac).length) body.entity_dac = role.entity_dac
        await send("PUT", "/api/roles/" + encodeURIComponent(role.name), { body })
      } else {
        body.name = get("name")
        const made = (await send("POST", "/api/roles", { body })).data as Role
        id = made.id
      }
      if (canProfiles() && id !== undefined) {
        const want = new Set([...f.querySelectorAll<HTMLInputElement>('input[name="profile"]:checked')].map((b) => b.value))
        try {
          for (const pid of want) {
            if (!wasAttached.has(pid)) await send("POST", "/api/governance/access-profiles/" + encodeURIComponent(pid) + "/roles", { body: { role_ids: [id] } })
          }
          for (const pid of wasAttached) {
            if (!want.has(pid)) await send("DELETE", "/api/governance/access-profiles/" + encodeURIComponent(pid) + "/roles/" + id)
          }
        } catch (e) {
          // the role itself is saved; say what the profiles did
          notify("Role saved, but its access profiles were not all updated: " + message(e), "error")
          props.onSaved()
          return
        }
      }
      notify(role ? "Role saved" : "Role created", "ok")
      props.onSaved()
    })
  }

  return (
    <form id="role-form" class="card" aria-labelledby="role-form-title" ref={(el) => (form = el)} onSubmit={submit}>
      <h2 id="role-form-title">{role ? "Edit role " + role.name : "New role"}</h2>
      <div class="form-grid">
        <label>
          Name
          <input name="name" required readonly={!!role || !editable()} autocomplete="off" ref={(el) => { initValue(role?.name ?? "")(el); if (!role) queueMicrotask(() => el.focus()) }} />
        </label>
        <label>
          Data access
          <select name="dac" disabled={!editable()}>
            <For each={DACS}>
              {([v, l]) => (
                <option value={v} ref={initSelected((role?.dac ?? "") === v)}>
                  {l}
                </option>
              )}
            </For>
          </select>
        </label>
        <label class="wide">
          Description
          <input name="description" readonly={!editable()} autocomplete="off" ref={initValue(role?.description ?? "")} />
        </label>
      </div>

      <fieldset style="margin-top:12px">
        <legend>Permissions</legend>
        <p class="hint">A request needs the pair of the resource it touches and the operation its method implies. Tick what the role may do.</p>
        <div class="table-wrap">
          <table id="role-grid">
            <thead>
              <tr>
                <th scope="col">Resource</th>
                <For each={props.data.operations}>{(o) => <th scope="col">{o}</th>}</For>
              </tr>
            </thead>
            <tbody>
              <For each={props.data.resources}>
                {(res) => (
                  <tr>
                    <th scope="row">
                      {res}{" "}
                      <button type="button" class="ghost" disabled={!editable()} aria-label={"Toggle every operation on " + res} onClick={() => toggleRow(res)}>
                        All
                      </button>
                    </th>
                    <For each={props.data.operations}>
                      {(op) => (
                        <td>
                          <input type="checkbox" name="perm" value={res + "|" + op} aria-label={res + " " + op} disabled={!editable()} ref={initChecked(held.has(res + "|" + op))} />
                        </td>
                      )}
                    </For>
                  </tr>
                )}
              </For>
            </tbody>
          </table>
        </div>
      </fieldset>

      <Show when={props.data.profiles !== undefined}>
        <fieldset id="role-profiles">
          <legend>Access profiles</legend>
          <p class="hint">Every user holding this role holds the ticked profiles; they limit the models, budget and rate limit of that user's requests.</p>
          <Show when={props.data.profiles!.length} fallback={<p class="muted">There are no access profiles yet.</p>}>
            <For each={props.data.profiles}>
              {(p) => (
                <label class="check">
                  <input type="checkbox" name="profile" value={p.id} disabled={!canProfiles()} ref={initChecked(wasAttached.has(p.id))} />
                  {label(p)}
                </label>
              )}
            </For>
          </Show>
        </fieldset>
      </Show>

      <FormError text={error()} />
      <div class="actions">
        <button type="button" class="ghost" onClick={props.onClose}>
          Cancel
        </button>
        <button type="submit" class="primary" disabled={busy() || !editable()}>
          {role ? "Save role" : "Create role"}
        </button>
      </div>
    </form>
  )
}

function UserRoles(props: { data: Data; onChanged: () => void }) {
  const { busy, run } = useRun()
  const options = () => [...BUILT_IN.map((b) => b[0]), ...props.data.roles.map((r) => r.name)]
  return (
    <section class="card" id="role-users" aria-labelledby="role-users-h">
      <h2 id="role-users-h">Users</h2>
      <p class="hint">The role each admin user holds. A change takes effect on that user's next request.</p>
      <Show when={props.data.users!.length} fallback={<p class="muted">There are no admin users.</p>}>
        <Table cols={["User", "Role"]}>
          <For each={props.data.users} keyed={(u) => u.name}>
            {(u) => (
              <tr>
                <td>
                  <Mono>{u().name}</Mono>
                  <Show when={u().disabled}>
                    <span class="hint"> (disabled)</span>
                  </Show>
                </td>
                <td>
                  <select
                    aria-label={"Role of " + u().name}
                    disabled={busy() || !can("Users", "Update")}
                    onChange={(ev) => {
                      const role = ev.currentTarget.value
                      void run(async () => {
                        try {
                          await send("PUT", "/api/users/" + encodeURIComponent(u().name) + "/role", { body: { role } })
                          notify(u().name + " is now " + role, "ok")
                        } finally {
                          props.onChanged()
                        }
                      })
                    }}
                  >
                    <For each={options()}>
                      {(o) => (
                        <option value={o} ref={initSelected(o === u().role)}>
                          {o}
                        </option>
                      )}
                    </For>
                  </select>
                </td>
              </tr>
            )}
          </For>
        </Table>
      </Show>
    </section>
  )
}

export function Roles() {
  const data = createMemo(() => loadAll())
  const [editor, setEditor] = createSignal<{ role: Role | undefined } | undefined>(undefined)
  const reload = () => refresh(data)

  return (
    <section aria-labelledby="roles-title">
      <Toolbar title="Roles" id="roles-title">
        <button type="button" id="roles-refresh" class="ghost" onClick={reload}>
          Refresh
        </button>
        <Can resource="RBAC" op="Create">
          <button type="button" id="role-new" class="primary" onClick={() => setEditor({ role: undefined })}>
            New role
          </button>
        </Can>
      </Toolbar>

      <section class="card" id="role-builtin" aria-labelledby="role-builtin-h">
        <h2 id="role-builtin-h">Built-in roles</h2>
        <p class="hint">These come with the gateway and cannot be changed.</p>
        <Table cols={["Role", "Access"]}>
          <For each={BUILT_IN}>
            {([n, d]) => (
              <tr>
                <td>
                  <Mono>{n}</Mono>
                </td>
                <td>{d}</td>
              </tr>
            )}
          </For>
        </Table>
      </section>

      <Errored fallback={(err) => <ErrP error={err()} />}>
        <Loading fallback={<p class="muted">Loading...</p>}>
          <Show when={editor()} keyed>
            {(e) => (
              <RoleForm
                role={e.role}
                data={data()}
                onClose={() => setEditor(undefined)}
                onSaved={() => {
                  setEditor(undefined)
                  reload()
                }}
              />
            )}
          </Show>
          <section class="card" id="role-list" aria-labelledby="role-list-h">
            <h2 id="role-list-h">Custom roles</h2>
            <Show when={data().roles.length} fallback={<p class="muted">No custom roles yet. Create one to give a user a limited set of permissions.</p>}>
              <Table cols={["Role", "Data access", "Permissions", "Users", "Access profiles", ""]}>
                <For each={data().roles} keyed={(r) => r.name}>
                  {(r) => (
                    <tr data-role={r().name}>
                      <td>
                        <strong>{r().name}</strong>
                        <Show when={r().description}>
                          <div class="hint">{r().description}</div>
                        </Show>
                      </td>
                      <td>{r().dac || "default"}</td>
                      <td>{(r().permissions ?? []).length}</td>
                      <td>{data().users ? holders(data(), r()).join(", ") || "none" : "—"}</td>
                      <td>{data().profiles ? attached(data(), r()).map(label).join(", ") || "none" : "—"}</td>
                      <td>
                        <span class="row-actions">
                          <button type="button" class="ghost" onClick={() => setEditor({ role: r() })}>
                            {can("RBAC", "Update") ? "Edit" : "View"}
                          </button>
                          <Can resource="RBAC" op="Delete">
                            <DangerButton
                              label="Delete"
                              action={async () => {
                                await send("DELETE", "/api/roles/" + encodeURIComponent(r().name))
                                notify("Role " + r().name + " deleted", "ok")
                                reload()
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
          </section>
          <Show when={data().users !== undefined}>
            <UserRoles data={data()} onChanged={reload} />
          </Show>
        </Loading>
      </Errored>
    </section>
  )
}

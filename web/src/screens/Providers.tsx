import { createMemo, createSignal, Errored, For, Loading, refresh, Show, untrack } from "solid-js"
import { api } from "../api/client"
import type { Key, Provider } from "../api/types"
import { splitList } from "../fmt"
import { Can, DangerButton, ErrP, FormError, initValue, Pill, notify, Table, Toolbar, useFormRun, tf } from "../ui"

// A key is addressed by its id; older records without one fall back to the name.
function keyRef(k: Key): string {
  return k.id || k.name || ""
}

function baseUrlOf(p: Provider): string {
  return p.network_config?.base_url || p.base_url || ""
}

function field(form: HTMLFormElement, name: string): string {
  const el = form.elements.namedItem(name)
  return el instanceof HTMLInputElement || el instanceof HTMLSelectElement ? el.value : ""
}

function KeyEditForm(props: { provider: string; k: Key; onClose: () => void; onSaved: () => void }) {
  const { busy, error, run } = useFormRun()
  // the form edits the key it was opened with
  const key = untrack(() => props.k)
  const submit = (ev: SubmitEvent) => {
    ev.preventDefault()
    const form = ev.currentTarget as HTMLFormElement
    void run(async () => {
      const weight = field(form, "weight")
      const body: Key = {
        name: field(form, "name").trim(),
        models: splitList(field(form, "models")),
        weight: weight === "" ? 1 : Number(weight),
      }
      // a blank value leaves the stored key as it is
      const value = field(form, "value")
      if (value !== "") body.value = value
      await api.put("/api/providers/{provider}/keys/{key_id}", { params: { provider: props.provider, key_id: keyRef(key) }, body })
      notify("Key saved", "ok")
      props.onSaved()
    })
  }
  return (
    <form class="inline-form" aria-label={"Edit key " + (key.name || keyRef(key))} onSubmit={submit}>
      <label>
        Key name
        <input name="name" required autocomplete="off" ref={(el) => { initValue(key.name ?? "")(el); queueMicrotask(() => el.focus()) }} />
      </label>
      <label>
        New API key
        <input name="value" type="password" autocomplete="new-password" spellcheck={false} placeholder="leave blank to keep it" />
      </label>
      <label>
        Models
        <input name="models" ref={initValue((key.models ?? []).join(", "))} placeholder="blank = all models" autocomplete="off" />
      </label>
      <label>
        Weight
        <input name="weight" type="number" min="0" step="0.1" ref={initValue(key.weight === undefined ? "1" : String(key.weight))} />
      </label>
      <div class="actions">
        <button type="button" class="ghost" onClick={props.onClose}>
          Cancel
        </button>
        <button type="submit" class="primary" disabled={busy()}>
          Save key
        </button>
      </div>
      <FormError text={error()} />
    </form>
  )
}

function AddKeyForm(props: { provider: string; onSaved: () => void }) {
  const { busy, error, run } = useFormRun()
  const submit = (ev: SubmitEvent) => {
    ev.preventDefault()
    const form = ev.currentTarget as HTMLFormElement
    void run(async () => {
      const weight = field(form, "weight")
      await api.post("/api/providers/{provider}/keys", {
        params: { provider: props.provider },
        body: {
          name: field(form, "name").trim(),
          value: field(form, "value"),
          models: splitList(field(form, "models")),
          weight: weight === "" ? 1 : Number(weight),
        },
      })
      notify("Key added to " + props.provider, "ok")
      form.reset()
      props.onSaved()
    })
  }
  return (
    <details class="add">
      <summary>Add key</summary>
      <form class="inline-form" onSubmit={submit}>
        <label>
          Key name
          <input name="name" required placeholder="e.g. primary" autocomplete="off" />
        </label>
        <label>
          API key
          <input name="value" type="password" required autocomplete="new-password" spellcheck={false} />
        </label>
        <label>
          Models
          <input name="models" placeholder="blank = all models" autocomplete="off" />
        </label>
        <label>
          Weight
          <input name="weight" type="number" min="0" step="0.1" value="1" />
        </label>
        <div class="actions">
          <button type="submit" class="primary" disabled={busy()}>
            Add key
          </button>
        </div>
        <FormError text={error()} />
      </form>
    </details>
  )
}

function ProviderEditForm(props: { p: Provider; onClose: () => void; onSaved: () => void }) {
  const { busy, error, run } = useFormRun()
  // the form edits the provider it was opened with
  const prov = untrack(() => props.p)
  const custom = () => !!prov.custom_provider_config
  const submit = (ev: SubmitEvent) => {
    ev.preventDefault()
    const form = ev.currentTarget as HTMLFormElement
    void run(async () => {
      const url = field(form, "base_url").trim()
      const baseType = custom() ? field(form, "base_provider_type").trim() : ""
      if (custom() && !baseType) throw new Error("Enter the base provider type for a custom provider.")
      // keys are left out, so the saved keys stay as they are (a PUT without keys keeps them)
      const network: Record<string, unknown> = { ...(prov.network_config ?? {}) }
      if (url) network.base_url = url
      else delete network.base_url
      const p = prov as Record<string, unknown>
      await api.put("/api/providers/{provider}", {
        params: { provider: prov.name },
        body: {
          network_config: Object.keys(network).length ? network : undefined,
          custom_provider_config: custom() ? { ...prov.custom_provider_config, base_provider_type: baseType } : undefined,
          proxy_config: p.proxy_config,
          send_back_raw_response: p.send_back_raw_response,
        },
      })
      notify('Provider "' + prov.name + '" saved', "ok")
      props.onSaved()
    })
  }
  return (
    <form class="form-grid" aria-label={"Edit provider " + prov.name} onSubmit={submit}>
      <label>
        Base URL (optional)
        <input
          name="base_url"
          type="url"
          placeholder="https://..."
          autocomplete="off"
          ref={(el) => {
            initValue(baseUrlOf(prov))(el)
            queueMicrotask(() => el.focus())
          }}
        />
      </label>
      <Show when={custom()}>
        <label>
          Base provider type
          <input name="base_provider_type" ref={initValue(String(prov.custom_provider_config?.base_provider_type ?? ""))} autocomplete="off" />
        </label>
      </Show>
      <div class="actions wide">
        <button type="button" class="ghost" onClick={props.onClose}>
          Cancel
        </button>
        <button type="submit" class="primary" disabled={busy()}>
          Save provider
        </button>
      </div>
      <FormError text={error()} />
    </form>
  )
}

function ProviderCard(props: { p: Provider; onChange: () => void }) {
  const [editing, setEditing] = createSignal(false)
  const [editKey, setEditKey] = createSignal<Key | undefined>(undefined)
  const keys = () => props.p.keys ?? []
  return (
    <article class="card" aria-label={"Provider " + props.p.name}>
      <header class="toolbar" style="margin-bottom:8px">
        <h3>{props.p.name}</h3>
        <Pill>{props.p.kind || "unknown"}</Pill>
        <span class="hint mono grow">{baseUrlOf(props.p) || "default endpoint"}</span>
        <span class="row-actions">
          <Can resource="ModelProvider" op="Update">
            <button type="button" class="ghost" aria-expanded={tf(editing())} onClick={() => setEditing(!editing())}>
              Edit
            </button>
          </Can>
          <Can resource="ModelProvider" op="Delete">
            <DangerButton
              label="Delete"
              action={async () => {
                await api.del("/api/providers/{provider}", { params: { provider: props.p.name } })
                notify("Provider deleted", "ok")
                props.onChange()
              }}
            />
          </Can>
        </span>
      </header>
      <Show when={editing()}>
        <ProviderEditForm
          p={props.p}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false)
            props.onChange()
          }}
        />
      </Show>
      <Show when={keys().length} fallback={<p class="muted">No keys. Requests to this provider fail until one is added.</p>}>
        <Table cols={["Key", "Models", "Weight", ""]}>
          <For each={keys()} keyed={(k) => keyRef(k)}>
            {(k) => (
              <tr>
                <td>
                  <span class="mono">{k().name || "—"}</span>
                </td>
                <td>{k().models && k().models!.length ? k().models!.join(", ") : "all models"}</td>
                <td>{k().weight === undefined ? "—" : String(k().weight)}</td>
                <td>
                  <span class="row-actions">
                    <Can resource="ModelProvider" op="Update">
                      <button type="button" class="ghost" onClick={() => setEditKey(k())}>
                        Edit
                      </button>
                    </Can>
                    <Can resource="ModelProvider" op="Delete">
                      <DangerButton
                        label="Delete"
                        action={async () => {
                          await api.del("/api/providers/{provider}/keys/{key_id}", { params: { provider: props.p.name, key_id: keyRef(k()) } })
                          notify("Key deleted", "ok")
                          props.onChange()
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
      <div>
        <Show when={editKey()} keyed>
          {(k) => (
            <KeyEditForm
              provider={props.p.name}
              k={k}
              onClose={() => setEditKey(undefined)}
              onSaved={() => {
                setEditKey(undefined)
                props.onChange()
              }}
            />
          )}
        </Show>
      </div>
      <Can resource="ModelProvider" op="Create">
        <AddKeyForm provider={props.p.name} onSaved={props.onChange} />
      </Can>
    </article>
  )
}

function AddProvider(props: { names: () => string[]; onSaved: () => void }) {
  const { busy, error, run } = useFormRun()
  const [kind, setKind] = createSignal("openai")
  const submit = (ev: SubmitEvent) => {
    ev.preventDefault()
    const form = ev.currentTarget as HTMLFormElement
    void run(async () => {
      const k = field(form, "kind")
      const name = field(form, "name").trim() || (k !== "custom" ? k : "")
      const base = field(form, "base_url").trim()
      const baseType = field(form, "base_provider_type").trim()
      if (!name) throw new Error("Enter a provider name.")
      if (k === "custom" && !baseType) throw new Error("Enter the base provider type for a custom provider.")
      if (props.names().includes(name)) throw new Error('Provider "' + name + '" already exists. Edit it or add keys below.')
      // keys is left out on purpose: the form only sets the endpoint of a new provider
      await api.put("/api/providers/{provider}", {
        params: { provider: name },
        body: {
          network_config: base ? { base_url: base } : undefined,
          custom_provider_config: k === "custom" ? { base_provider_type: baseType } : undefined,
        },
      })
      notify('Provider "' + name + '" saved', "ok")
      form.reset()
      setKind("openai")
      props.onSaved()
    })
  }
  return (
    <section class="card" aria-labelledby="pv-add-h">
      <h2 id="pv-add-h">Add provider</h2>
      <form id="pv-add" class="form-grid" onSubmit={submit}>
        <label>
          Name
          <input name="name" placeholder="e.g. openai-eu" autocomplete="off" />
        </label>
        <label>
          Kind
          <select name="kind" id="pv-kind" value={kind()} onChange={(e) => setKind(e.currentTarget.value)}>
            <option value="openai">openai</option>
            <option value="anthropic">anthropic</option>
            <option value="gemini">gemini</option>
            <option value="vertex">vertex</option>
            <option value="bedrock">bedrock</option>
            <option value="cohere">cohere</option>
            <option value="custom">custom (base type)</option>
          </select>
        </label>
        <label hidden={kind() !== "custom"}>
          Base provider type
          <input name="base_provider_type" placeholder="openai, anthropic, ..." autocomplete="off" />
        </label>
        <label>
          Base URL (optional)
          <input name="base_url" type="url" placeholder="https://..." autocomplete="off" />
        </label>
        <FormError text={error()} />
        <div class="actions wide">
          <span class="hint grow">Built-in kinds use the kind as the name when the name is blank.</span>
          <button type="submit" class="primary" disabled={busy()}>
            Save provider
          </button>
        </div>
      </form>
    </section>
  )
}

export function Providers() {
  const providers = createMemo(() => api.get("/api/providers"))
  const reload = () => refresh(providers)
  return (
    <section aria-labelledby="pv-title">
      <Toolbar title="Providers" id="pv-title">
        <button type="button" class="ghost" onClick={reload}>
          Refresh
        </button>
      </Toolbar>
      <div id="pv-list">
        <Errored fallback={(err) => <ErrP error={err()} />}>
          <Loading fallback={<p class="muted">Loading...</p>}>
            <Show when={providers().providers.length} fallback={<p class="card muted">No providers configured yet. Add one below.</p>}>
              <For each={providers().providers} keyed={(p) => p.name}>
                {(p) => <ProviderCard p={p()} onChange={reload} />}
              </For>
            </Show>
          </Loading>
        </Errored>
      </div>
      <Can resource="ModelProvider" op="Update">
        <AddProvider names={() => safeNames(providers)} onSaved={reload} />
      </Can>
    </section>
  )
}

function safeNames(m: () => { providers: Provider[] }): string[] {
  try {
    return m().providers.map((p) => p.name)
  } catch {
    return []
  }
}

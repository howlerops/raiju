import { createEffect, createMemo, createSignal, refresh, Show } from "solid-js"
import type { Accessor, Setter } from "solid-js"
import { api } from "../api/client"
import { canCall } from "../perm"
import { pretty } from "../fmt"
import { JsonEditor, parseJson } from "../JsonEditor"
import { FormError, Guard, notify, Toolbar, useFormRun } from "../ui"

type Obj = Record<string, any>

interface ConfigDraft {
  text: Accessor<string>
  setText: Setter<string>
  baseline: Accessor<string>
  setBaseline: Setter<string>
  serverChanged: Accessor<boolean>
  setServerChanged: Setter<boolean>
}

// The settings the editor shows, in the shape PUT /api/config takes.
function editableConfig(full: Obj): Obj {
  const client = full.client ?? {}
  const out: Obj = { client_config: client }
  const ps = full.pricing_sync
  if (ps && (ps.url || ps.interval_seconds)) {
    out.framework_config = { pricing_url: ps.url || "" }
    if (ps.interval_seconds > 0) out.framework_config.pricing_sync_interval = ps.interval_seconds
  }
  const au = full.governance?.auth_config
  if (au && au.username) {
    out.auth_config = {
      admin_username: au.username,
      admin_password: "<redacted>",
      disable_auth_on_inference: client.enforce_auth_on_inference === false,
    }
  }
  return out
}

function Editor(props: { cfg: Obj; onSaved: () => void; draft: ConfigDraft }) {
  const { busy, error, setError, run } = useFormRun()
  const { text, setText, baseline, setBaseline, serverChanged, setServerChanged } = props.draft
  const [valid, setValid] = createSignal(false)
  const dirty = createMemo(() => text() !== baseline())
  createEffect(
    () => props.cfg,
    (cfg) => {
      const next = JSON.stringify(editableConfig(cfg), null, 2)
      if (text() === baseline()) {
        setText(next)
        setServerChanged(false)
      } else if (next !== baseline()) setServerChanged(true)
      setBaseline(next)
    },
  )
  const save = () => {
    if (!valid() || busy() || !canCall("PUT", "/api/config")) return
    return run(async () => {
      const parsed = parseJson(text(), true)
      if (!parsed.valid) throw new Error(parsed.message)
      const body = parsed.value
      if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error("The settings must be a JSON object.")
      const send: Obj = {}
      for (const k of ["client_config", "client", "framework_config", "auth_config"]) {
        if ((body as Obj)[k] !== undefined) send[k] = (body as Obj)[k]
      }
      if (!Object.keys(send).length) throw new Error("Nothing to save: the object needs client_config, framework_config or auth_config.")
      await api.put("/api/config", { body: send })
      setBaseline(text())
      setServerChanged(false)
      notify("Configuration saved", "ok")
      props.onSaved()
    })
  }
  return (
    <section class="card panel bg-base-100 border border-base-300" id="cfg-box" aria-labelledby="cfg-edit-h">
      <h2 id="cfg-edit-h">Settings</h2>
      <p class="hint">
        Saves three sections with PUT /api/config: client_config, framework_config (pricing sync) and auth_config (admin login). Other sections are
        changed on their own pages. A secret shown as &lt;redacted&gt; keeps its stored value.
      </p>
      <JsonEditor
        id="cfg-json"
        label="Settings as JSON"
        value={text()}
        onInput={(value) => { setText(value); setError("") }}
        rows={20}
        required
        disabled={busy() || !canCall("PUT", "/api/config")}
        onValidityChange={setValid}
      />
      <p class="hint" role="status">{dirty() ? "Unsaved changes. Reload keeps your edits; Discard changes uses the latest server settings." : "No unsaved changes."}</p>
      <Show when={serverChanged() && dirty()}>
        <p class="alert alert-warning" role="status">Server settings changed after this draft was started. Your edits were kept. Discard changes to load the latest settings, or save to overwrite their editable sections.</p>
      </Show>
      <FormError text={error()} wide={false} />
      <Show when={!canCall("PUT", "/api/config")}>
        <p class="hint" id="cfg-readonly">
          Your role can read the settings but not change them.
        </p>
      </Show>
      <div class="actions" style="margin-top:10px" hidden={!canCall("PUT", "/api/config")}>
        <button
          type="button"
          id="cfg-discard"
          class="btn btn-sm btn-ghost"
          disabled={busy() || !dirty()}
          onClick={() => {
            setError("")
            setText(baseline())
            setServerChanged(false)
          }}
        >
          Discard changes
        </button>
        <button type="button" id="cfg-save" class="btn btn-sm btn-primary" disabled={busy() || !valid() || !dirty()} onClick={save}>
          Save configuration
        </button>
      </div>
    </section>
  )
}

export function Config() {
  // Keep drafts outside the async boundary, including when a reload fails.
  // This is page-local memory only: never store configuration in browser storage.
  const [text, setText] = createSignal("")
  const [baseline, setBaseline] = createSignal("")
  const [serverChanged, setServerChanged] = createSignal(false)
  const draft: ConfigDraft = { text, setText, baseline, setBaseline, serverChanged, setServerChanged }
  const cfg = createMemo(() => api.get("/api/config") as Promise<Obj>)
  const reload = () => refresh(cfg)
  return (
    <section aria-labelledby="cfg-title">
      <Toolbar title="Configuration" id="cfg-title">
        <button type="button" id="cfg-refresh" class="btn btn-sm btn-ghost" onClick={reload}>
          Reload
        </button>
      </Toolbar>
      <Guard variant="form">
        <Show when={cfg()}>
          {(c) => <Editor cfg={c()} draft={draft} onSaved={reload} />}
        </Show>
        <details class="card panel bg-base-100 border border-base-300" id="cfg-full-box">
          <summary>Full configuration (read only, secrets redacted)</summary>
          <pre class="code" id="cfg-full">
            {pretty(cfg())}
          </pre>
        </details>
      </Guard>
    </section>
  )
}

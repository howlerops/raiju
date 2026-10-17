import { createMemo, createSignal, Errored, Loading, refresh, Show, untrack } from "solid-js"
import { api } from "../api/client"
import { pretty } from "../fmt"
import { ErrP, FormError, notify, Toolbar, useFormRun } from "../ui"

type Obj = Record<string, any>

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

function Editor(props: { cfg: Obj; onSaved: () => void }) {
  const { busy, error, setError, run } = useFormRun()
  const initial = () => JSON.stringify(editableConfig(props.cfg), null, 2)
  const [text, setText] = createSignal(untrack(initial))
  const save = () =>
    run(async () => {
      let body: unknown
      try {
        body = JSON.parse(text())
      } catch (e) {
        throw new Error("The settings are not valid JSON: " + (e as Error).message)
      }
      if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error("The settings must be a JSON object.")
      const send: Obj = {}
      for (const k of ["client_config", "client", "framework_config", "auth_config"]) {
        if ((body as Obj)[k] !== undefined) send[k] = (body as Obj)[k]
      }
      if (!Object.keys(send).length) throw new Error("Nothing to save: the object needs client_config, framework_config or auth_config.")
      await api.put("/api/config", { body: send })
      notify("Configuration saved", "ok")
      props.onSaved()
    })
  return (
    <section class="card" id="cfg-box" aria-labelledby="cfg-edit-h">
      <h2 id="cfg-edit-h">Settings</h2>
      <p class="hint">
        Saves three sections with PUT /api/config: client_config, framework_config (pricing sync) and auth_config (admin login). Other sections are
        changed on their own pages. A secret shown as &lt;redacted&gt; keeps its stored value.
      </p>
      <label class="wide">
        Settings as JSON
        <textarea
          id="cfg-json"
          class="mono"
          rows="16"
          spellcheck={false}
          aria-describedby="cfg-edit-h"
          value={text()}
          onInput={(e) => setText(e.currentTarget.value)}
        />
      </label>
      <FormError text={error()} wide={false} />
      <div class="actions" style="margin-top:10px">
        <button
          type="button"
          id="cfg-discard"
          class="ghost"
          onClick={() => {
            setError("")
            setText(initial())
          }}
        >
          Discard changes
        </button>
        <button type="button" id="cfg-save" class="primary" disabled={busy()} onClick={save}>
          Save configuration
        </button>
      </div>
    </section>
  )
}

export function Config() {
  const cfg = createMemo(() => api.get("/api/config") as Promise<Obj>)
  const reload = () => refresh(cfg)
  return (
    <section aria-labelledby="cfg-title">
      <Toolbar title="Configuration" id="cfg-title">
        <button type="button" id="cfg-refresh" class="ghost" onClick={reload}>
          Reload
        </button>
      </Toolbar>
      <Errored fallback={(err) => <ErrP error={err()} />}>
        <Loading fallback={<p class="muted">Loading...</p>}>
          <Show when={cfg()} keyed>
            {(c) => <Editor cfg={c} onSaved={reload} />}
          </Show>
          <details class="card" id="cfg-full-box">
            <summary>Full configuration (read only, secrets redacted)</summary>
            <pre class="code" id="cfg-full">
              {pretty(cfg())}
            </pre>
          </details>
        </Loading>
      </Errored>
    </section>
  )
}

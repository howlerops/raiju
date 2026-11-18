import { createSignal, onCleanup, Show } from "solid-js"
import { LoadingSkeleton } from "../LoadingSkeleton"
import { ChoiceSelect } from "../ChoiceSelect"
import { message, send } from "../api/client"
import { contentText, fmtInt, listOf, pretty } from "../fmt"
import { fieldValue, notify, Toolbar, useRun } from "../ui"
import { target, targetLabel } from "../gateway"

interface Result {
  ms: number
  text: string
  usage: { prompt_tokens?: number; completion_tokens?: number }
  model: string
  raw: unknown
}

export function Playground() {
  const { busy, run } = useRun()
  const [models, setModels] = createSignal<string[]>([])
  const [modelsMsg, setModelsMsg] = createSignal("")
  const [modelsLoading, setModelsLoading] = createSignal(false)
  const [modelsError, setModelsError] = createSignal("")
  const [model, setModel] = createSignal("")
  const [customModel, setCustomModel] = createSignal(false)
  let modelsRequest = 0
  const [pending, setPending] = createSignal(false)
  const [result, setResult] = createSignal<Result | undefined>(undefined)
  const [failure, setFailure] = createSignal("")
  let form: HTMLFormElement | undefined

  const val = (n: string) => fieldValue(form, n).trim()
  const headers = (): Record<string, string> => {
    const vk = val("vk")
    return vk ? { "x-raiju-vk": vk } : {}
  }

  const loadModels = async () => {
    const request = ++modelsRequest
    setModelsLoading(true)
    setModelsError("")
    setModels([])
    setModelsMsg("Loading the selected gateway's model catalog…")
    try {
      const r = await send("GET", "/v1/models", { auth: false, headers: headers() })
      if (request !== modelsRequest) return
      const ids = [...new Set(listOf<{ id?: string }>(r.data, "data").map((m) => m?.id ?? "").filter(Boolean))].sort()
      setModels(ids)
      if (model() && !ids.includes(model()) && !customModel()) setModel("")
      setModelsMsg(ids.length ? ids.length + " models advertised by this gateway. Virtual-key permissions are checked when sending." : "The gateway returned no models. Check the virtual key or refresh; custom identifiers require explicit opt-in.")
    } catch (e) {
      if (request !== modelsRequest) return
      setModelsError("Could not load models: " + message(e))
      setModelsMsg("Model catalog unavailable. No fallback catalog was used.")
      if (!customModel()) setModel("")
    } finally {
      if (request === modelsRequest) setModelsLoading(false)
    }
  }
  queueMicrotask(() => { if (modelsRequest === 0) void loadModels() })
  onCleanup(() => { ++modelsRequest })

  const submit = (ev: SubmitEvent) => {
    ev.preventDefault()
    const chosen = model().trim()
    const text = val("message")
    if (!chosen || !text) return notify("Choose a model and enter a message.", "error")
    if (!customModel() && (modelsLoading() || !models().includes(chosen))) return notify("Refresh the catalog and choose an available model, or explicitly enable custom identifiers.", "error")
    setPending(true)
    setFailure("")
    setResult(undefined)
    const t0 = performance.now()
    void run(async () => {
      try {
        const r = await send("POST", "/v1/chat/completions", {
          auth: false,
          headers: headers(),
          body: { model: chosen, messages: [{ role: "user", content: text }] },
        })
        const body = (r.data ?? {}) as { choices?: { message?: { content?: unknown }; text?: string }[]; usage?: Result["usage"]; model?: string }
        const choice = body.choices?.[0]
        setResult({
          ms: performance.now() - t0,
          text: contentText(choice?.message?.content) || choice?.text || "",
          usage: body.usage ?? {},
          model: body.model ?? "",
          raw: r.data,
        })
      } catch (e) {
        setFailure(message(e))
      } finally {
        setPending(false)
      }
    })
  }

  return (
    <section aria-labelledby="pg-title">
      <Toolbar title="Playground" id="pg-title" />
      <p class="hint" id="pg-target">Inference target: <strong>{targetLabel()}</strong> · <span class="mono">{target().url}</span>. The virtual key and message go directly to this gateway only; no regional fallback.</p>
      <form id="pg-form" class="card panel bg-base-100 border border-base-300" ref={(el) => (form = el)} onSubmit={submit}>
        <div class="form-grid playground-grid">
          <ChoiceSelect label="Model" name="model" options={models()} value={model()} onChange={setModel}
            required allowCustom={customModel()} loading={modelsLoading()} error={modelsError()} describedBy="pg-models-msg"
            placeholder="Search this gateway's models…" emptyText="No models advertised by this gateway." />
          <label>
            Virtual key (optional)
            <input class="input input-sm" name="vk" type="password" autocomplete="off" spellcheck={false} placeholder="sk-raiju-..."
              onInput={() => {
                ++modelsRequest
                setModels([])
                setModelsLoading(false)
                setModelsError("")
                if (!customModel()) setModel("")
                setModelsMsg("Virtual key changed. Refresh models to load its gateway catalog.")
              }}
              onChange={() => { void loadModels() }} />
          </label>
          <div class="field-support wide">
            <p class="hint" id="pg-models-msg" role="status">{modelsMsg()}</p>
            <button type="button" id="pg-load" class="btn btn-sm btn-ghost" disabled={modelsLoading()} onClick={() => { void loadModels() }}>
              {modelsLoading() ? "Loading models…" : "Refresh models"}
            </button>
          </div>
          <label class="check wide">
            <input type="checkbox" class="checkbox checkbox-sm" checked={customModel()} onChange={(event) => {
              setCustomModel(event.currentTarget.checked)
              if (!event.currentTarget.checked && !models().includes(model())) setModel("")
            }} />
            Allow an unlisted custom model identifier (gateway routing and permissions still apply)
          </label>
          <label class="wide">
            Message
            <textarea class="textarea textarea-sm"
              name="message"
              rows="4"
              required
              placeholder="Say hello"
              onKeyDown={(ev) => {
                if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) {
                  ev.preventDefault()
                  form?.requestSubmit()
                }
              }}
            />
          </label>
          <div class="actions wide">
            <span class="hint grow">Ctrl+Enter sends.</span>
            <button type="submit" class="btn btn-sm btn-primary" disabled={busy()}>
              Send to {targetLabel()}
            </button>
          </div>
        </div>
      </form>
      <div id="pg-result" class="card panel bg-base-100 border border-base-300" aria-live="polite">
        <Show when={pending()}>
          <LoadingSkeleton variant="content" label="Waiting for response" />
        </Show>
        <Show when={failure()}>
          <p class="error" role="alert">
            {failure()}
          </p>
        </Show>
        <Show when={result()}>
          {(r) => (
            <div>
              <div class="chat-meta muted">
                {Math.round(r().ms) +
                  " ms · " +
                  fmtInt(r().usage.prompt_tokens) +
                  " in / " +
                  fmtInt(r().usage.completion_tokens) +
                  " out tokens" +
                  (r().model ? " · " + r().model : "")}
              </div>
              <pre class="reply">{r().text || "(empty reply)"}</pre>
              <details style="margin-top:10px">
                <summary>Raw response</summary>
                <pre class="code">{pretty(r().raw)}</pre>
              </details>
            </div>
          )}
        </Show>
      </div>
    </section>
  )
}

import { createSignal, For, Show } from "solid-js"
import { message, send } from "../api/client"
import { contentText, fmtInt, listOf, pretty } from "../fmt"
import { notify, Toolbar, useRun } from "../ui"

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
  const [pending, setPending] = createSignal(false)
  const [result, setResult] = createSignal<Result | undefined>(undefined)
  const [failure, setFailure] = createSignal("")
  let form: HTMLFormElement | undefined

  const val = (n: string) => ((form?.elements.namedItem(n) as HTMLInputElement | HTMLTextAreaElement | null)?.value ?? "").trim()
  const headers = (): Record<string, string> => {
    const vk = val("vk")
    return vk ? { "x-bf-vk": vk } : {}
  }

  const loadModels = async () => {
    try {
      const r = await send("GET", "/v1/models", { auth: false, headers: headers() })
      const ids = listOf<{ id?: string }>(r.data, "data").map((m) => m?.id ?? "").filter(Boolean)
      setModels(ids)
      setModelsMsg(ids.length ? ids.length + " models available." : "The gateway returned no models.")
    } catch (e) {
      setModelsMsg("Could not load models: " + message(e))
    }
  }

  const submit = (ev: SubmitEvent) => {
    ev.preventDefault()
    const model = val("model")
    const text = val("message")
    if (!model || !text) return notify("Choose a model and enter a message.", "error")
    setPending(true)
    setFailure("")
    setResult(undefined)
    const t0 = performance.now()
    void run(async () => {
      try {
        const r = await send("POST", "/v1/chat/completions", {
          auth: false,
          headers: headers(),
          body: { model, messages: [{ role: "user", content: text }] },
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
      <form id="pg-form" class="card" ref={(el) => (form = el)} onSubmit={submit}>
        <div class="form-grid">
          <label>
            Model
            <input name="model" list="pg-models" required placeholder="openai/gpt-4o-mini" autocomplete="off" />
          </label>
          <datalist id="pg-models">
            <For each={models()}>{(id) => <option value={id} />}</For>
          </datalist>
          <label>
            Virtual key (optional)
            <input name="vk" type="password" autocomplete="off" spellcheck={false} placeholder="sk-bf-..." />
          </label>
          <div class="actions">
            <button type="button" id="pg-load" class="ghost" onClick={loadModels}>
              Load models
            </button>
          </div>
          <p class="hint wide" id="pg-models-msg" role="status">
            {modelsMsg()}
          </p>
          <label class="wide">
            Message
            <textarea
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
            <button type="submit" class="primary" disabled={busy()}>
              Send
            </button>
          </div>
        </div>
      </form>
      <div id="pg-result" class="card" aria-live="polite">
        <Show when={pending()}>
          <p class="muted" role="status">
            Sending...
          </p>
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

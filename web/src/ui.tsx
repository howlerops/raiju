// Small shared pieces: toasts, pills, tables, the two-step delete button,
// busy wrappers and the error line.
import { createSignal, Errored, For, Loading, Show } from "solid-js"
import { LoadingSkeleton } from "./LoadingSkeleton"
import type { JSX } from "@solidjs/web"
import { message } from "./api/client"
import { canCall } from "./perm"
import { targetLabel } from "./gateway"
import { ChoiceSelect } from "./ChoiceSelect"
import { splitList } from "./fmt"

// ---- initial values for uncontrolled fields ----

type Field = HTMLInputElement | HTMLTextAreaElement

// ref={initValue(x)}: set the field once, when it is created
export const initValue = (v: string) => (el: Field) => {
  el.value = v
}

export const initChecked = (b: boolean) => (el: HTMLInputElement) => {
  el.checked = b
}

export const initSelected = (b: boolean) => (el: HTMLOptionElement) => {
  el.selected = b
}

// The value of a named field of a form, "" when the form has no such field.
export function fieldValue(form: HTMLFormElement | undefined, name: string): string {
  const el = form?.elements.namedItem(name)
  return el instanceof HTMLInputElement || el instanceof HTMLSelectElement || el instanceof HTMLTextAreaElement ? el.value : ""
}

// ---- toasts ----

interface Toast {
  id: number
  text: string
  tone: "ok" | "error" | ""
}

const [toasts, setToasts] = createSignal<Toast[]>([])
let toastId = 0

export function notify(text: string, tone: Toast["tone"] = ""): void {
  const id = ++toastId
  setToasts((l) => [...l, { id, text, tone }])
  setTimeout(() => setToasts((l) => l.filter((t) => t.id !== id)), tone === "error" ? 8000 : 4000)
}

export function Toasts() {
  return (
    <div class="toasts" aria-live="polite">
      <For each={toasts()}>
        {(t) => (
          <div class={["notification alert", t.tone === "ok" ? "alert-success" : t.tone === "error" ? "alert-error" : "alert-info"]} role={t.tone === "error" ? "alert" : "status"}>
            {t.text}
          </div>
        )}
      </For>
    </div>
  )
}

// ---- pills, stats, error lines ----

export type Tone = "" | "ok" | "warn" | "bad"

export function Pill(props: { tone?: Tone; children?: JSX.Element }) {
  return <span class={["badge", props.tone ? "badge-soft" : "", props.tone === "ok" ? "badge-success" : props.tone === "warn" ? "badge-warning" : props.tone === "bad" ? "badge-error" : "badge-neutral"]}>{props.children}</span>
}

export function stateTone(s: unknown): Tone {
  if (s === "closed") return "ok"
  if (s === "half_open") return "warn"
  if (s === "open") return "bad"
  return ""
}

export function Stat(props: { label: string; value: string; sub?: string }) {
  return (
    <div class="bg-base-100 border border-base-300 rounded-box stat">
      <div class="stat-title">{props.label}</div>
      <div class="stat-value">{props.value}</div>
      <Show when={props.sub}>
        <div class="stat-desc">{props.sub}</div>
      </Show>
    </div>
  )
}

export function ErrP(props: { error: unknown }) {
  return (
    <p class="error" role="alert">
      {message(props.error)}
    </p>
  )
}

// ---- tables ----

export function Table(props: { cols: string[]; children?: JSX.Element }) {
  return (
    <div class="table-wrap">
      <table class="table table-sm">
        <thead>
          <tr>
            <For each={props.cols}>{(c) => <th scope="col">{c}</th>}</For>
          </tr>
        </thead>
        <tbody>{props.children}</tbody>
      </table>
    </div>
  )
}

// A loading skeleton and an error line around async content.
export function Guard(props: { variant?: "content" | "table" | "form"; children?: JSX.Element }) {
  return (
    <Errored fallback={(err) => <ErrP error={err()} />}>
      <Loading fallback={<LoadingSkeleton variant={props.variant ?? "content"} />}>{props.children}</Loading>
    </Errored>
  )
}

export function Mono(props: { children?: JSX.Element }) {
  return <span class="mono">{props.children}</span>
}

// ---- busy wrappers ----

// Runs fn while busy() is true, reporting a failure as a toast.
export function useRun() {
  const [busy, setBusy] = createSignal(false)
  const run = async (fn: () => Promise<void>): Promise<void> => {
    setBusy(true)
    try {
      await fn()
    } catch (e) {
      notify(message(e), "error")
    } finally {
      setBusy(false)
    }
  }
  return { busy, run }
}

// Like useRun, but a failure goes to error() so the form can show it next to its fields.
export function useFormRun() {
  const [busy, setBusy] = createSignal(false)
  const [error, setError] = createSignal("")
  const run = async (fn: () => Promise<void>): Promise<void> => {
    setError("")
    setBusy(true)
    try {
      await fn()
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, setError, run }
}

export function FormError(props: { text: string; wide?: boolean }) {
  return (
    <p class={["error", { wide: props.wide !== false }]} role="alert" hidden={props.text === ""}>
      {props.text}
    </p>
  )
}

// A delete button that asks for an in-page confirmation (no confirm() dialogs).
export function DangerButton(props: { label: string; action: () => Promise<void>; disabled?: boolean }) {
  const [confirming, setConfirming] = createSignal(false)
  const { busy, run } = useRun()
  const go = async () => {
    await run(() => props.action())
    setConfirming(false)
  }
  return (
    <span class="confirm">
      <Show
        when={confirming()}
        fallback={
          <button type="button" class="btn btn-sm btn-outline btn-error" disabled={props.disabled} onClick={() => setConfirming(true)}>
            {props.label}
          </button>
        }
      >
        <span class="muted">Confirm on {targetLabel()}?</span>
        <button type="button" class="btn btn-sm btn-error" disabled={busy()} onClick={go}>
          {"Confirm " + props.label.toLowerCase()}
        </button>
        <button type="button" class="btn btn-sm btn-ghost" disabled={busy()} onClick={() => setConfirming(false)}>
          Cancel
        </button>
      </Show>
    </span>
  )
}

// ---- client and tools rows ----

export interface ClientTools {
  client: string
  tools: string
}

// The rows of a "which tools of which MCP client" editor: a client select, a tools field and Remove.
// rows is the form's store; update runs a change on it.
export function ClientToolsRows(props: {
  rows: ClientTools[]
  clients: string[]
  tools?: Readonly<Record<string, readonly string[]>>
  update: (change: (rows: ClientTools[]) => void) => void
  toolsLabel: string
  toolsPlaceholder: string
  rowClass?: string
}) {
  // a stored client that is no longer configured stays selectable
  const names = (extra: string) => (extra && !props.clients.includes(extra) ? [...props.clients, extra] : props.clients)
  return (
    <For each={props.rows}>
      {(row, i) => (
        <div class={["rule", props.rowClass]}>
          <ChoiceSelect label="MCP client" options={names(row.client)} value={row.client} placeholder="Choose MCP client"
            onChange={(value) => props.update((r) => void (r[i()]!.client = value))} />
          <ChoiceSelect label={props.toolsLabel} multiple allowCustom
            options={["*", ...(props.tools?.[row.client] ?? [])]} value={splitList(row.tools)}
            placeholder={props.toolsPlaceholder}
            onChange={(values) => props.update((r) => void (r[i()]!.tools = values.join(", ")))} />
          <div class="field-action">
            <button type="button" class="btn btn-sm btn-ghost" onClick={() => props.update((r) => void r.splice(i(), 1))}>
              Remove
            </button>
          </div>
        </div>
      )}
    </For>
  )
}

// A section with a heading, used by the overview and the governance lists.
export function Card(props: { title: string; id: string; children?: JSX.Element }) {
  return (
    <section class="card panel bg-base-100 border border-base-300" aria-labelledby={props.id}>
      <h2 id={props.id}>{props.title}</h2>
      {props.children}
    </section>
  )
}

export function Toolbar(props: { title: string; id: string; children?: JSX.Element }) {
  return (
    <div class="toolbar">
      <h1 id={props.id}>{props.title}</h1>
      <span class="grow"></span>
      {props.children}
    </div>
  )
}

// Copies text. Falls back to selecting the text in the given field.
export async function copyText(text: string, field?: HTMLInputElement): Promise<boolean> {
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // fall through to the selection fallback
  }
  if (field) {
    field.focus()
    field.select()
    try {
      return document.execCommand("copy")
    } catch {
      return false
    }
  }
  return false
}

// aria-pressed and aria-expanded take the strings "true" and "false"
export function tf(b: boolean): "true" | "false" {
  return b ? "true" : "false"
}

// Shows its children only when the signed-in role may make the call (the server still decides).
// The permission pair comes from the call itself, so a control cannot name the wrong one.
export function CanCall(props: { method: string; path: string; children?: JSX.Element }) {
  return <Show when={canCall(props.method, props.path)}>{props.children}</Show>
}

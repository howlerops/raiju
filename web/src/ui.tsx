// Small shared pieces: toasts, pills, tables, the two-step delete button,
// busy wrappers and the error line.
import { createSignal, Errored, For, Loading, Show } from "solid-js"
import type { JSX } from "@solidjs/web"
import { message } from "./api/client"
import { can, type Op } from "./perm"

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
          <div class={["toast", t.tone]} role={t.tone === "error" ? "alert" : "status"}>
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
  return <span class={["pill", props.tone ?? ""]}>{props.children}</span>
}

export function stateTone(s: unknown): Tone {
  if (s === "closed") return "ok"
  if (s === "half_open") return "warn"
  if (s === "open") return "bad"
  return ""
}

export function Stat(props: { label: string; value: string; sub?: string }) {
  return (
    <div class="stat">
      <div class="label">{props.label}</div>
      <div class="value">{props.value}</div>
      <Show when={props.sub}>
        <div class="sub">{props.sub}</div>
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
      <table>
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

// Loading text and an error line around async content.
export function Guard(props: { children?: JSX.Element }) {
  return (
    <Errored fallback={(err) => <ErrP error={err()} />}>
      <Loading fallback={<p class="muted">Loading...</p>}>{props.children}</Loading>
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
  const [busy, setBusy] = createSignal(false)
  const go = async () => {
    setBusy(true)
    try {
      await props.action()
    } catch (e) {
      notify(message(e), "error")
    } finally {
      setBusy(false)
      setConfirming(false)
    }
  }
  return (
    <span class="confirm">
      <Show
        when={confirming()}
        fallback={
          <button type="button" class="danger-outline" disabled={props.disabled} onClick={() => setConfirming(true)}>
            {props.label}
          </button>
        }
      >
        <span class="muted">Are you sure?</span>
        <button type="button" class="danger" disabled={busy()} onClick={go}>
          {"Confirm " + props.label.toLowerCase()}
        </button>
        <button type="button" class="ghost" disabled={busy()} onClick={() => setConfirming(false)}>
          Cancel
        </button>
      </Show>
    </span>
  )
}

// A section with a heading, used by the overview and the governance lists.
export function Card(props: { title: string; id: string; children?: JSX.Element }) {
  return (
    <section class="card" aria-labelledby={props.id}>
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

// Shows its children only when the signed-in role holds the permission (the server still decides).
export function Can(props: { resource: string; op?: Op; children?: JSX.Element }) {
  return <Show when={can(props.resource, props.op ?? "View")}>{props.children}</Show>
}

import { createEffect, createMemo, createSignal, For, onCleanup, Show, untrack } from "solid-js"

export interface ChoiceOption {
  value: string
  label?: string
}

interface ChoiceBase {
  label: string
  options: readonly (string | ChoiceOption)[]
  name?: string
  placeholder?: string
  class?: string
  disabled?: boolean
  required?: boolean
  allowCustom?: boolean
  loading?: boolean
  error?: string
  emptyText?: string
  describedBy?: string
}

type ChoiceProps = ChoiceBase & (
  | { multiple?: false; value?: string; defaultValue?: string; onChange?: (value: string) => void }
  | { multiple: true; value?: string[]; defaultValue?: string[]; onChange?: (value: string[]) => void }
)

let nextChoiceId = 0

// Search is only a draft. Form values change only when an option (or explicit custom entry) is chosen.
// Multi-value form fields serialize as comma-separated identifiers, matching splitList/fieldValue.
export function ChoiceSelect(props: ChoiceProps) {
  const id = "choice-" + ++nextChoiceId
  const initial = untrack(() => props.defaultValue ?? props.value ?? (props.multiple ? [] : ""))
  const [local, setLocal] = createSignal<string | string[]>(initial)
  const [open, setOpen] = createSignal(false)
  const [query, setQuery] = createSignal("")
  const [active, setActive] = createSignal(0)
  let root: HTMLDivElement | undefined
  let input: HTMLInputElement | undefined
  let disposed = false
  const selected = (): string[] => {
    const value = props.value ?? local()
    return Array.isArray(value) ? value : value ? [value] : []
  }
  const options = createMemo(() => {
    const seen = new Set<string>()
    return props.options.map((o) => typeof o === "string" ? { value: o, label: o } : o)
      .filter((o) => {
        if (!o.value || seen.has(o.value)) return false
        seen.add(o.value)
        return true
      })
  })
  const labelOf = (value: string) => options().find((o) => o.value === value)?.label || value
  const filtered = createMemo(() => {
    const q = query().trim().toLowerCase()
    return options().filter((o) => !q || (o.label || o.value).toLowerCase().includes(q) || o.value.toLowerCase().includes(q))
  })
  const custom = () => props.allowCustom && query().trim() && !options().some((o) => o.value === query().trim()) ? query().trim() : ""
  const count = () => filtered().length + (custom() ? 1 : 0)
  const activeIndex = () => Math.min(active(), count() - 1)
  const change = (values: string[]) => {
    if (props.multiple) {
      setLocal(values)
      props.onChange?.(values)
    } else {
      const value = values[0] ?? ""
      setLocal(value)
      props.onChange?.(value)
    }
  }
  const close = () => { setOpen(false); setQuery(""); setActive(0) }
  const choose = (value: string) => {
    if (props.disabled) return
    if (props.multiple) {
      change(selected().includes(value) ? selected().filter((v) => v !== value) : [...selected(), value])
      setQuery("")
      setActive(0)
    } else {
      change([value])
      close()
    }
    input?.focus()
  }
  const reveal = () => {
    if (props.disabled || open()) return
    setQuery("")
    setActive(0)
    setOpen(true)
  }
  const reset = () => {
    if (props.multiple) change(Array.isArray(initial) ? [...initial] : [])
    else change(typeof initial === "string" && initial ? [initial] : [])
    close()
  }
  createEffect(() => !!props.required && selected().length === 0, (missing) => {
    input?.setCustomValidity(missing ? "Choose " + props.label.toLowerCase() + "." : "")
  })
  createEffect(() => open() ? activeIndex() : -1, (index) => {
    if (index >= 0) document.getElementById(id + "-option-" + index)?.scrollIntoView({ block: "nearest" })
  })
  const outside = (event: PointerEvent) => {
    if (event.target instanceof Node && !root?.contains(event.target)) close()
  }
  document.addEventListener("pointerdown", outside)
  let form: HTMLFormElement | null = null
  queueMicrotask(() => {
    if (disposed) return
    form = input?.form ?? null
    form?.addEventListener("reset", reset)
  })
  onCleanup(() => {
    disposed = true
    document.removeEventListener("pointerdown", outside)
    form?.removeEventListener("reset", reset)
  })
  return (
    <div class={["dropdown", "choice-field", { "dropdown-open": open() }, props.class]} ref={(el) => (root = el)}
      onFocusOut={(event) => {
        if (!(event.relatedTarget instanceof Node) || !root?.contains(event.relatedTarget)) close()
      }}>
      <label for={id}>{props.label}</label>
      <input type="hidden" name={props.name} value={selected().join(",")} disabled={props.disabled} />
      <div class="choice-control">
        <input id={id} ref={(el) => (input = el)} class="input input-sm choice-input" type="text"
          role="combobox" aria-autocomplete="list" aria-expanded={open() ? "true" : "false"} aria-controls={id + "-list"}
          aria-activedescendant={open() && activeIndex() >= 0 ? id + "-option-" + activeIndex() : undefined}
          aria-required={props.required ? "true" : undefined} aria-describedby={[props.describedBy, id + "-status"].filter(Boolean).join(" ")}
          autocomplete="off" spellcheck={false} disabled={props.disabled}
          placeholder={props.placeholder ?? (props.multiple ? "Search and add…" : "Search choices…")}
          value={open() ? query() : props.multiple ? "" : selected().map(labelOf).join("")}
          onFocus={reveal} onClick={reveal}
          onInput={(event) => { setQuery(event.currentTarget.value); setActive(0); setOpen(true) }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault()
              if (!open()) { reveal(); if (event.key === "ArrowUp") setActive(Math.max(0, count() - 1)) }
              else setActive((n) => count() ? (n + (event.key === "ArrowDown" ? 1 : -1) + count()) % count() : 0)
            } else if (event.key === "Enter" && open()) {
              event.preventDefault()
              const index = activeIndex()
              const option = filtered()[index]
              if (option) choose(option.value)
              else if (index === filtered().length && custom()) choose(custom())
            } else if (event.key === "Escape" && open()) {
              event.preventDefault(); event.stopPropagation(); close()
            } else if (event.key === "Tab") close()
          }} />
        <span aria-hidden="true" class="choice-indicator">▾</span>
      <Show when={open()}>
        <ul id={id + "-list"} class="dropdown-content menu bg-base-100 rounded-box border border-base-300 shadow-lg choice-options"
          role="listbox" aria-label={props.label} aria-multiselectable={props.multiple ? "true" : undefined}>
          <For each={filtered()}>{(option, index) => <li role="presentation"><button type="button" role="option" tabindex="-1"
            id={id + "-option-" + index()} aria-selected={selected().includes(option.value) ? "true" : "false"}
            class={{ "menu-active": activeIndex() === index() }} style="overflow-wrap:anywhere;white-space:normal"
            onPointerDown={(event) => event.preventDefault()} onPointerMove={() => setActive(index())} onClick={() => choose(option.value)}>
            <Show when={props.multiple}><span aria-hidden="true">{selected().includes(option.value) ? "✓" : "○"}</span></Show>{option.label || option.value}
          </button></li>}</For>
          <Show when={custom()}><li role="presentation"><button type="button" role="option" tabindex="-1" id={id + "-option-" + filtered().length}
            aria-selected="false" class={{ "menu-active": activeIndex() === filtered().length }}
            onPointerDown={(event) => event.preventDefault()} onPointerMove={() => setActive(filtered().length)} onClick={() => choose(custom())}>Use custom identifier: {custom()}</button></li></Show>
          <Show when={!count()}><li role="presentation"><span>{props.loading ? "Loading choices…" : props.error ? "Choices unavailable." : query() ? "No matching choices." : props.emptyText ?? "No choices available."}</span></li></Show>
        </ul>
      </Show>
      </div>
      <div class="choice-feedback">
      <Show when={props.multiple && selected().length}>
        <div class="flex flex-wrap gap-1" aria-label={props.label + " selected"}>
          <For each={selected()}>{(value) => <button type="button" class="badge badge-soft gap-1" disabled={props.disabled}
            aria-label={"Remove " + labelOf(value)} onClick={() => change(selected().filter((v) => v !== value))}>{labelOf(value)} <span aria-hidden="true">×</span></button>}</For>
        </div>
      </Show>
      <Show when={!props.multiple && selected().length}>
        <button type="button" class="btn btn-xs btn-ghost self-start" disabled={props.disabled} onClick={() => { change([]); close() }}>Clear {props.label.toLowerCase()}</button>
      </Show>
      <span id={id + "-status"} class={props.error ? "error" : "hint"} role="status">
        {props.loading ? "Loading choices…" : props.error || (props.allowCustom ? "Search choices or explicitly add a custom identifier." : "")}
      </span>
      </div>
    </div>
  )
}

import { createEffect, createSignal, createUniqueId, onSettled, Show, untrack } from "solid-js"
import { Compartment, EditorState, Transaction } from "@codemirror/state"
import { drawSelection, EditorView, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers } from "@codemirror/view"
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands"
import { bracketMatching, HighlightStyle, indentOnInput, indentUnit, syntaxHighlighting } from "@codemirror/language"
import { json, jsonLanguage } from "@codemirror/lang-json"
import { tags } from "@lezer/highlight"

export interface JsonEditorProps {
  value: string
  onInput: (text: string) => void
  label: string
  id?: string
  name?: string
  rows?: number
  disabled?: boolean
  required?: boolean
  onValidityChange?: (valid: boolean) => void
}

type JsonResult = { valid: true; value: unknown } | { valid: false; message: string; offset: number; line: number; column: number }

// Do not surface JSON.parse's message: some browsers include document contents in it.
// The JSON grammar supplies a location without leaking credentials into error text.
export function parseJson(text: string, required = false): JsonResult {
  if (!text.trim() && !required) return { valid: true, value: undefined }
  try {
    return { valid: true, value: JSON.parse(text) }
  } catch {
    let offset = text.length
    const cursor = jsonLanguage.parser.parse(text).cursor()
    do {
      if (cursor.type.isError) {
        offset = cursor.from
        break
      }
    } while (cursor.next())
    let line = 1
    let column = 1
    for (let i = 0; i < offset; i++) {
      if (text[i] === "\n" || (text[i] === "\r" && text[i + 1] !== "\n")) {
        line++
        column = 1
      } else column++
    }
    const message = !text.trim()
      ? "JSON is required."
      : `Invalid JSON at line ${line}, column ${column}. Check quotes, commas, and matching brackets.`
    return { valid: false, message, offset, line, column }
  }
}

// Preserve number literals and duplicate keys. JSON.stringify(JSON.parse(text))
// would silently round large integers and drop duplicate properties.
function formatJson(text: string, compact: boolean): string {
  if (compact) return text.replace(/"(?:\\.|[^"\\])*"|\s+/g, (token) => token.startsWith('"') ? token : "")
  let output = ""
  let depth = 0
  let previous = ""
  for (const match of text.matchAll(/"(?:\\.|[^"\\])*"|true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|[{}\[\],:]/g)) {
    const token = match[0]
    const closing = token === "}" || token === "]"
    const opened = previous === "{" || previous === "["
    if (closing) {
      depth--
      if (!opened) output += "\n" + "  ".repeat(depth)
    } else if (opened) output += "\n" + "  ".repeat(depth)
    if (token === ",") output += ",\n" + "  ".repeat(depth)
    else if (token === ":") output += ": "
    else output += token
    if (token === "{" || token === "[") depth++
    previous = token
  }
  return output
}

const colors = syntaxHighlighting(HighlightStyle.define([
  { tag: tags.propertyName, color: "var(--color-base-content)", fontWeight: "600" },
  { tag: tags.string, color: "var(--color-primary)" },
  { tag: [tags.number, tags.bool, tags.null], color: "var(--color-secondary)" },
  { tag: tags.punctuation, color: "var(--muted)" },
  { tag: tags.invalid, color: "var(--color-error)", textDecoration: "underline wavy" },
]))

const theme = EditorView.theme({
  "&": { backgroundColor: "var(--color-base-100)", color: "var(--color-base-content)", fontSize: "13px" },
  "&.cm-focused": { outline: "2px solid var(--color-primary)", outlineOffset: "2px" },
  ".cm-scroller": { fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", lineHeight: "1.6", overflow: "auto" },
  ".cm-content": { padding: "10px 0", caretColor: "var(--color-base-content)" },
  ".cm-line": { padding: "0 12px" },
  ".cm-gutters": { backgroundColor: "var(--color-base-200)", color: "var(--muted)", borderRight: "1px solid var(--color-base-300)" },
  ".cm-activeLine, .cm-activeLineGutter": { backgroundColor: "color-mix(in oklab, var(--color-primary) 7%, var(--color-base-100))" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": { backgroundColor: "color-mix(in oklab, var(--color-primary) 24%, var(--color-base-100))" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--color-base-content)" },
  ".cm-matchingBracket": { backgroundColor: "color-mix(in oklab, var(--color-primary) 18%, var(--color-base-100))", outline: "1px solid var(--color-primary)" },
})

export function JsonEditor(props: JsonEditorProps) {
  const generatedId = "json-" + createUniqueId()
  const id = () => props.id ?? generatedId
  let source = untrack(() => props.value)
  const [result, setResult] = createSignal<JsonResult>(untrack(() => parseJson(source, props.required)))
  const [checking, setChecking] = createSignal(false)
  const [position, setPosition] = createSignal({ line: 1, column: 1 })
  let host!: HTMLDivElement
  let field!: HTMLTextAreaElement
  let view: EditorView | undefined
  let timer: number | undefined
  let lastValidity: boolean | undefined
  const options = new Compartment()
  const attributes = new Compartment()
  const size = new Compartment()
  const status = () => {
    if (checking()) return "Checking JSON…"
    const parsed = result()
    if (!parsed.valid) return parsed.message
    return source.trim() ? "Valid JSON syntax. Server validation still applies." : "Empty (optional)."
  }
  const validate = () => {
    clearTimeout(timer)
    const parsed = parseJson(source, props.required)
    setResult(parsed)
    setChecking(false)
    // Signals settle asynchronously in Solid 2, so use the result directly here.
    field?.setCustomValidity(parsed.valid ? "" : parsed.message)
    if (lastValidity !== parsed.valid) {
      lastValidity = parsed.valid
      props.onValidityChange?.(parsed.valid)
    }
    return parsed
  }
  const contentAttributes = () => EditorView.contentAttributes.of({
    id: id(),
    role: "textbox",
    "aria-label": props.label,
    "aria-multiline": "true",
    "aria-required": String(!!props.required),
    "aria-readonly": String(!!props.disabled),
    "aria-describedby": `${id()}-help ${id()}-status`,
    "aria-invalid": String(!checking() && !result().valid),
    spellcheck: "false",
    autocapitalize: "off",
    autocorrect: "off",
    tabindex: "0",
  })
  const dimensions = () => EditorView.theme({ ".cm-scroller": { height: `${Math.max(4, props.rows ?? 16) * 1.6 + 2}em` } })
  const editable = () => [EditorState.readOnly.of(!!props.disabled), EditorView.editable.of(!props.disabled)]

  createEffect(
    () => ({ value: props.value, disabled: props.disabled, required: props.required, rows: props.rows, id: id(), label: props.label }),
    (next, previous) => {
      if (next.value !== source) {
        source = next.value
        view?.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: source }, annotations: Transaction.addToHistory.of(false) })
        validate()
      } else if (previous && next.required !== previous.required) validate()
      if (next.disabled !== previous?.disabled) view?.dispatch({ effects: options.reconfigure(editable()) })
      if (next.rows !== previous?.rows) view?.dispatch({ effects: size.reconfigure(dimensions()) })
    },
  )
  createEffect(
    () => ({ invalid: !checking() && !result().valid, id: id(), label: props.label, required: props.required, disabled: props.disabled }),
    () => view?.dispatch({ effects: attributes.reconfigure(contentAttributes()) }),
  )

  onSettled(() => {
    view = new EditorView({
      parent: host,
      state: EditorState.create({
        doc: source,
        extensions: [
          json(), colors, theme, history(), lineNumbers(), highlightActiveLine(), highlightActiveLineGutter(),
          drawSelection(), bracketMatching(), indentOnInput(), indentUnit.of("  "), EditorState.tabSize.of(2),
          keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
          options.of(editable()), attributes.of(contentAttributes()), size.of(dimensions()),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) {
              const next = update.state.doc.toString()
              if (next !== source) {
                source = next
                field.value = next
                setChecking(true)
                field.setCustomValidity("Wait for JSON validation.")
                if (lastValidity !== false) {
                  lastValidity = false
                  props.onValidityChange?.(false)
                }
                clearTimeout(timer)
                timer = window.setTimeout(validate, 250)
                props.onInput(next)
              }
            }
            if (update.selectionSet || update.docChanged) {
              const head = update.state.selection.main.head
              const line = update.state.doc.lineAt(head)
              setPosition({ line: line.number, column: head - line.from + 1 })
            }
          }),
        ],
      }),
    })
    const parsed = result()
    field.setCustomValidity(parsed.valid ? "" : parsed.message)
    lastValidity = parsed.valid
    props.onValidityChange?.(parsed.valid)
    return () => {
      clearTimeout(timer)
      view?.destroy()
      view = undefined
    }
  })

  const format = (compact: boolean) => {
    if (!view || props.disabled || !validate().valid || !source.trim()) return
    const next = formatJson(source, compact)
    if (next !== source) view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: next } })
    view.focus()
  }
  const goToError = () => {
    const parsed = validate()
    if (!view || parsed.valid) return
    const line = view.state.doc.line(Math.min(parsed.line, view.state.doc.lines))
    const at = Math.min(line.from + parsed.column - 1, line.to)
    view.dispatch({ selection: { anchor: at }, effects: EditorView.scrollIntoView(at, { y: "center" }) })
    view.focus()
  }

  return (
    <div class="wide min-w-0 space-y-2">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <label class="font-medium text-base-content" for={id()} onClick={() => view?.focus()}>{props.label}</label>
        <div class="flex gap-2" role="group" aria-label={`${props.label} formatting`}>
          <button type="button" class="btn btn-xs btn-ghost" disabled={props.disabled || checking() || !result().valid} onClick={() => format(false)}>Format</button>
          <button type="button" class="btn btn-xs btn-ghost" disabled={props.disabled || checking() || !result().valid} onClick={() => format(true)}>Minify</button>
        </div>
      </div>
      <div ref={host} class="overflow-hidden rounded-field border border-base-300" />
      <textarea
        ref={field}
        class="sr-only"
        tabindex={-1}
        aria-hidden="true"
        name={props.name}
        value={props.value}
        disabled={props.disabled}
        required={props.required}
        autocomplete="off"
        spellcheck={false}
        onInvalid={(event) => { event.preventDefault(); goToError() }}
      />
      <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
        <p id={`${id()}-status`} role="status" aria-live="polite" class={!checking() && !result().valid ? "text-error" : "text-base-content/70"}>
          {status()}
        </p>
        <span class="text-base-content/70" aria-label="Cursor position">Ln {position().line}, Col {position().column}</span>
        <Show when={!checking() && !result().valid}>
          <button type="button" class="btn btn-xs btn-ghost" onClick={goToError}>Go to error</button>
        </Show>
      </div>
      <p id={`${id()}-help`} class="hint">JSON only; comments and trailing commas are not allowed. Tab indents; Shift+Tab unindents. Press Escape, then Tab to leave the editor. Changes stay in this page until saved.</p>
    </div>
  )
}

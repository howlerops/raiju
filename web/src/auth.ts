// Admin sign-in state: the bearer token (kept for this tab only) and the
// sign-in dialog, which the HTTP client opens when a call returns 401.
import { createSignal } from "solid-js"

const TOKEN_KEY = "raiju.adminToken"

function readToken(): string {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? ""
  } catch {
    return ""
  }
}

function writeToken(t: string): void {
  try {
    if (t) sessionStorage.setItem(TOKEN_KEY, t)
    else sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    // storage blocked: the token lasts for this page only
  }
}

let current = readToken()
const [tokenSet, setTokenSet] = createSignal(current !== "")
const [dialog, setDialog] = createSignal<{ message: string } | undefined>(undefined)

export { tokenSet, dialog }

export function adminToken(): string {
  return current
}

let tokenListener: (() => void) | undefined

// Called after the token changes (sign-in, sign-out); the app reloads what the caller may do.
export function onTokenChange(fn: () => void): void {
  tokenListener = fn
}

export function setToken(t: string): void {
  const changed = t !== current
  current = t
  writeToken(t)
  setTokenSet(t !== "")
  if (changed && tokenListener) tokenListener()
}

let pending: Promise<string> | undefined
let resolvePending: ((t: string) => void) | undefined
let declined = false

// Opens the dialog and resolves to the entered token ("" when the person declines).
// Concurrent callers share one dialog.
export function askToken(message: string): Promise<string> {
  if (declined) return Promise.resolve("")
  if (!pending) {
    pending = new Promise<string>((resolve) => {
      resolvePending = resolve
    })
    setDialog({ message })
  }
  return pending
}

// A person-initiated open (the header button) clears an earlier decline.
export function openSignIn(message: string): void {
  declined = false
  void askToken(message)
}

export function closeSignIn(token: string | undefined): void {
  declined = token === undefined
  if (token !== undefined) setToken(token)
  setDialog(undefined)
  const r = resolvePending
  pending = undefined
  resolvePending = undefined
  if (r) r(token ?? "")
}

export function clearSignIn(): void {
  setToken("")
  declined = true
  setDialog(undefined)
  const r = resolvePending
  pending = undefined
  resolvePending = undefined
  if (r) r("")
}

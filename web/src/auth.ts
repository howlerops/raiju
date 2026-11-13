// Admin sign-in state: the bearer token (kept for this tab only) and the
// sign-in dialog, which the HTTP client opens when a call returns 401.
import { createSignal } from "solid-js"
import { consoleConfig, isActive, reloadTarget, target } from "./gateway"

function tokenKey(): string { return "raiju.adminToken:" + target().url }

function readToken(): string {
  try {
    const saved = sessionStorage.getItem(tokenKey())
    if (saved !== null) return saved
    // Only the embedded gateway can inherit its pre-console token.
    if (!consoleConfig() && target().url === location.origin) {
      const legacy = sessionStorage.getItem("raiju.adminToken") ?? ""
      if (legacy) sessionStorage.setItem(tokenKey(), legacy)
      sessionStorage.removeItem("raiju.adminToken")
      return legacy
    }
    return ""
  } catch {
    return ""
  }
}

function writeToken(t: string): void {
  try {
    if (t) sessionStorage.setItem(tokenKey(), t)
    else sessionStorage.removeItem(tokenKey())
  } catch {
    throw new Error("Tab session storage is required to change credentials safely. Allow session storage and try again.")
  }
}

let current = ""
const [tokenSet, setTokenSet] = createSignal(current !== "")
const [dialog, setDialog] = createSignal<{ message: string } | undefined>(undefined)

export { tokenSet, dialog }

export function initializeAuth(): void {
  current = readToken()
  setTokenSet(current !== "")
}

export function adminToken(): string {
  return current
}


export function setToken(t: string): void {
  if (!isActive()) return
  const changed = t !== current
  writeToken(t)
  current = t
  setTokenSet(t !== "")
  // Changing identity clears every page's cached data and permissions as well.
  if (changed) reloadTarget()
}

let pending: Promise<string> | undefined
let resolvePending: ((t: string) => void) | undefined
let declined = false

// Opens the dialog and resolves to the entered token ("" when the person declines).
// Concurrent callers share one dialog.
export function askToken(message: string): Promise<string> {
  if (!isActive()) return new Promise<string>(() => {})
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
  if (!isActive()) return
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

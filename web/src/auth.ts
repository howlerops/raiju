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

const [verified, setVerified] = createSignal(false)
export { tokenSet, dialog, verified, setVerified }

export function revokeSession(): void {
  setVerified(false)
  setDialog(undefined)
  window.dispatchEvent(new Event("raiju-session-expired"))
}


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

export function openSignIn(message: string): void {
  if (isActive()) setDialog({ message })
}
export function dismissSignIn(): void { setDialog(undefined) }

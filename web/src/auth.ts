// Admin identity for this tab: native bearer credentials or explicitly configured loginless mode.
// The HTTP client revokes verified access on management 401s; loginless never offers credential dialogs.
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

export type AdministrationMode = "native" | "loginless"
const [administrationMode, setAdministrationMode] = createSignal<AdministrationMode>("native")

const [verified, setVerified] = createSignal(false)
export { tokenSet, dialog, verified, setVerified, administrationMode }

export function revokeSession(): void {
  setVerified(false)
  setDialog(undefined)
  window.dispatchEvent(new Event("raiju-session-expired"))
}


export function initializeAuth(): void {
  current = readToken()
  setTokenSet(current !== "")
}

// This mode comes only from the public session status, never from a failed login.
// Keep other regions' tab credentials intact, but never expose a native bearer in loginless mode.
export function configureAdministrationMode(mode: AdministrationMode): void {
  setVerified(false)
  setDialog(undefined)
  setAdministrationMode(mode)
  if (mode === "loginless") {
    writeToken("")
    current = ""
    setTokenSet(false)
  }
}

export function adminToken(): string {
  return administrationMode() === "native" ? current : ""
}


export function setToken(t: string): void {
  if (!isActive() || administrationMode() !== "native") return
  const changed = t !== current
  writeToken(t)
  current = t
  setTokenSet(t !== "")
  // Changing identity clears every page's cached data and permissions as well.
  if (changed) reloadTarget()
}

export function openSignIn(message: string): void {
  if (isActive() && administrationMode() === "native") setDialog({ message })
}
export function dismissSignIn(): void { setDialog(undefined) }

// Frontend permissions mirror the native server's expanded permission pairs.
import { createSignal } from "solid-js"
import { send, ApiError } from "./api/client"
import { adminToken, verified, revokeSession } from "./auth"

export type Op = "View" | "Create" | "Update" | "Delete"
export interface Me {
  user: string
  role: string
  builtIn: boolean
  pairs: { resource: string; operation: string }[]
}
const [me, setMe] = createSignal<Me | undefined>(undefined)
export { me }

export function allows(m: Me | undefined, resource: string, op: Op): boolean {
  // Metrics is a scrape endpoint, not a native management permission resource.
  if (resource === "Metrics") return !!m && m.builtIn && m.role === "admin" && op === "View"
  return !!m && m.pairs.some((p) => p.resource === resource && p.operation === op)
}
export function can(resource: string, op: Op = "View"): boolean {
  return verified() && allows(me(), resource, op)
}
export async function verifyToken(token: string): Promise<Me> {
  const r = await send("GET", "/api/users/me/permissions", {
    auth: false, quiet: true, headers: token ? { authorization: "Bearer " + token } : {},
  })
  const d = r.data as { user?: unknown; role?: unknown; built_in?: unknown; permissions?: unknown } | undefined
  if (r.status !== 200 || !d || typeof d.user !== "string" || !d.user || typeof d.role !== "string" || !d.role || typeof d.built_in !== "boolean" || !Array.isArray(d.permissions) || !d.permissions.every((p) => p && typeof p.resource === "string" && p.resource && typeof p.operation === "string" && p.operation)) {
    throw new Error("The gateway returned invalid permissions. Access remains locked.")
  }
  return { user: d.user, role: d.role, builtIn: d.built_in, pairs: d.permissions }
}
export async function refreshMe(): Promise<void> {
  setMe(undefined)
  try { setMe(await verifyToken(adminToken())) }
  catch (e) {
    if (e instanceof ApiError && e.status === 401) revokeSession()
    throw e
  }
}
export function roleLabel(m: Me | undefined): string {
  return m ? (m.user ? m.user + " · " : "") + m.role.replace("_", " ") : ""
}

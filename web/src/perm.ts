// Frontend permissions mirror the native server's expanded permission pairs.
import { createSignal } from "solid-js"
import { send, ApiError } from "./api/client"
import { adminToken, administrationMode, verified, revokeSession } from "./auth"

export type Op = "View" | "Create" | "Update" | "Delete"
// Shared with the role editor: built-in admin expands to every catalogue pair.
export const RESOURCES = ["Logs", "MCPLogs", "AuditLogs", "ModelProvider", "Observability", "VirtualKeys", "Users", "MCPGateway", "Teams", "Customers", "BusinessUnits", "Projects", "RBAC", "AccessProfiles", "RoutingRules", "Governance", "Settings", "Cluster", "APIKeys", "Crews"]
export const OPERATIONS = ["View", "Create", "Update", "Delete", "Download", "Reveal", "RunInference"]
export interface Me {
  user: string
  role: string
  builtIn: boolean
  pairs: { resource: string; operation: string }[]
}
const [me, setMe] = createSignal<Me | undefined>(undefined)
export { me }

export function allows(m: Me | undefined, resource: string, op: string): boolean {
  // Metrics is a scrape endpoint, not a native management permission resource.
  if (resource === "Metrics") return !!m && m.builtIn && m.role === "admin" && op === "View"
  return !!m && m.pairs.some((p) => p.resource === resource && p.operation === op)
}
export function can(resource: string, op: Op = "View"): boolean {
  return verified() && allows(me(), resource, op)
}

// The pair the server checks for a management call: resourceOf in src/rbac.tov, kept in step with it.
const SECRET_SEGMENTS = ["secrets", "reveal"]
const AREAS: Record<string, string> = {
  users: "Users", scim: "Users", "audit-logs": "AuditLogs", logs: "Logs", "mcp-logs": "MCPLogs",
  providers: "ModelProvider", keys: "ModelProvider", models: "ModelProvider", mcp: "MCPGateway", oauth2: "MCPGateway",
  cluster: "Cluster", alerting: "Observability", alerts: "Observability", roles: "RBAC", "api-keys": "APIKeys",
  crews: "Crews", "access-profiles": "AccessProfiles",
}
const GOVERNANCE: Record<string, string> = {
  "virtual-keys": "VirtualKeys", users: "Users", teams: "Teams", customers: "Customers", "business-units": "BusinessUnits",
  projects: "Projects", "access-profiles": "AccessProfiles", "routing-rules": "RoutingRules", "audit-logs": "AuditLogs", rbac: "RBAC",
}
export function need(method: string, path: string): { resource: string; op: string } {
  const q = path.indexOf("?")
  const segs = (q < 0 ? path : path.slice(0, q)).split("/").filter((s) => s !== "")
  const m = method.toUpperCase()
  let op = m === "POST" ? "Create" : m === "PUT" || m === "PATCH" ? "Update" : m === "DELETE" ? "Delete" : "View"
  if (segs.some((s) => SECRET_SEGMENTS.includes(s))) op = "Reveal"
  const area = segs[1] ?? ""
  const pick = (table: Record<string, string>, key: string) => (Object.hasOwn(table, key) ? table[key] : undefined)
  const resource = area === "governance" ? (pick(GOVERNANCE, segs[2] ?? "") ?? "Governance") : (pick(AREAS, area) ?? "Settings")
  return { resource, op }
}
// Whether the signed-in role may make this call (the server still decides).
export function canCall(method: string, path: string): boolean {
  const n = need(method, path)
  return verified() && allows(me(), n.resource, n.op)
}
export async function verifyToken(token: string): Promise<Me> {
  const r = await send("GET", "/api/users/me/permissions", {
    auth: false, quiet: true, headers: administrationMode() === "native" && token ? { authorization: "Bearer " + token } : {},
  })
  const d = r.data as { user?: unknown; role?: unknown; built_in?: unknown; permissions?: unknown } | undefined
  if (r.status !== 200 || !d || typeof d.user !== "string" || !d.user || typeof d.role !== "string" || !d.role || typeof d.built_in !== "boolean" || !Array.isArray(d.permissions) || !d.permissions.every((p) => p && typeof p.resource === "string" && p.resource && typeof p.operation === "string" && p.operation)) {
    throw new Error("The gateway returned invalid permissions. Access remains locked.")
  }
  if (administrationMode() === "loginless") {
    const pairs = new Set(d.permissions.map((p) => p.resource + ":" + p.operation))
    if (d.user !== "loginless" || d.role !== "admin" || d.built_in !== true || !RESOURCES.every((resource) => OPERATIONS.every((operation) => pairs.has(resource + ":" + operation)))) {
      throw new Error("The gateway did not return the loginless administrator permissions. Access remains locked.")
    }
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

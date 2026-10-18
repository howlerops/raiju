// What the signed-in caller may do, so the pages hide or disable actions the role cannot take.
// The gateway still checks every request; this only keeps buttons honest. The source is
// GET /api/users/me/permissions: a custom role or a management API key lists (resource, operation)
// pairs; a built-in role (admin, editor, viewer, auditor) is reported by name and mirrors the fixed
// rules in src/rbac.tov.
import { createSignal } from "solid-js"
import { send } from "./api/client"

export type Op = "View" | "Create" | "Update" | "Delete"

export interface Me {
  user: string
  role: string
  builtIn: boolean
  pairs: { resource: string; operation: string }[]
}

// undefined until the first answer; can() allows everything then, and the server decides
const [me, setMe] = createSignal<Me | undefined>(undefined)
export { me }

// the resources an editor writes (rbac.tov editorWrites: providers and governance records)
const EDITOR_WRITES = ["ModelProvider", "VirtualKeys", "Governance", "Teams", "Customers", "AccessProfiles"]
// the resources only an admin reads
const ADMIN_ONLY = ["Users", "APIKeys", "AuditLogs", "Metrics"]

export function allows(m: Me | undefined, resource: string, op: Op): boolean {
  if (!m) return true
  if (m.builtIn) {
    if (m.role === "admin") return true
    if (m.role === "auditor") return op === "View" && (resource === "Logs" || resource === "AuditLogs")
    if (op === "View") return !ADMIN_ONLY.includes(resource)
    return m.role === "editor" && EDITOR_WRITES.includes(resource)
  }
  return m.pairs.some((p) => p.resource === resource && p.operation === op)
}

export function can(resource: string, op: Op = "View"): boolean {
  return allows(me(), resource, op)
}

export async function refreshMe(): Promise<void> {
  try {
    const r = await send("GET", "/api/users/me/permissions", { quiet: true })
    const d = (r.data ?? {}) as { user?: string; role?: string; built_in?: boolean; permissions?: { resource?: string; operation?: string }[] }
    setMe({
      user: d.user ?? "",
      role: d.role ?? "admin",
      builtIn: d.built_in !== false,
      pairs: (d.permissions ?? []).map((p) => ({ resource: p.resource ?? "", operation: p.operation ?? "" })),
    })
  } catch {
    // not signed in, or a gateway without the route: keep the last answer, the server still decides
  }
}

export function roleLabel(m: Me | undefined): string {
  if (!m) return ""
  return (m.user ? m.user + " · " : "") + m.role.replace("_", " ")
}

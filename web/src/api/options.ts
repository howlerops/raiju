// The lists the forms offer as choices (keys, teams, providers, ...). They change rarely, so a screen
// loads them once and again on Refresh, apart from the list it edits.
import { listOr } from "./client"
import type { Budget, Customer, McpClient, Provider, RateLimit, Team, VirtualKey } from "./types"

export interface Options {
  keys: VirtualKey[]
  providers: Provider[]
  teams: Team[]
  customers: Customer[]
  budgets: Budget[]
  rate_limits: RateLimit[]
  clients: McpClient[]
}

const SOURCES: { [K in keyof Options]: [path: string, key: string] } = {
  keys: ["/api/governance/virtual-keys", "virtual_keys"],
  providers: ["/api/providers", "providers"],
  teams: ["/api/governance/teams", "teams"],
  customers: ["/api/governance/customers", "customers"],
  budgets: ["/api/governance/budgets", "budgets"],
  rate_limits: ["/api/governance/rate-limits", "rate_limits"],
  clients: ["/api/mcp/clients", "clients"],
}

// The named lists, each empty when the caller may not read it.
export async function loadOptions<K extends keyof Options>(...want: K[]): Promise<Pick<Options, K>> {
  const lists = await Promise.all(want.map((k) => listOr<unknown>(SOURCES[k][0], SOURCES[k][1])))
  const out: Partial<Record<keyof Options, unknown[]>> = {}
  want.forEach((k, i) => (out[k] = lists[i]))
  return out as Pick<Options, K>
}

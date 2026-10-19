// Named shapes from the generated schema (schema.d.ts).
import type { components } from "./schema"

type S = components["schemas"]

export type Provider = S["ProviderResponse"]
export type Key = S["Key"]
export type VirtualKey = S["VirtualKey"]
export type VkProviderConfig = S["VirtualKeyProviderConfig"]
export type Budget = S["Budget"]
export type RateLimit = S["RateLimit"]
export type Team = S["Team"]
export type Customer = S["Customer"]
export type LogEntry = S["LogEntry"]
export type McpClient = S["MCPClient"]
export type McpClientConfig = S["MCPClientConfig"]
export type McpStatus = S["MCPClientStatus"]

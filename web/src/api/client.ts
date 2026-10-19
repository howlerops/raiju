// A small typed fetch client over the generated schema (schema.d.ts, from
// docs/openapi/management.yaml). The path and method pick the parameter,
// body and response types.
import type { paths } from "./schema"
import { adminToken, askToken } from "../auth"

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

type Method = "get" | "post" | "put" | "delete"
type Json<T> = T extends { content: { "application/json": infer J } } ? J : never
type OkOf<R> = Json<R[Extract<keyof R, 200 | 201 | 202>]>
type OpOf<P extends keyof paths, M extends Method> = paths[P] extends Record<M, infer O> ? O : never
type ResOf<O> = O extends { responses: infer R } ? OkOf<R> : unknown
type BodyOf<O> = O extends { requestBody: { content: { "application/json": infer B } } } ? B : never
type ParamsOf<O> = O extends { parameters: { path: infer PP } } ? PP : never
type QueryOf<O> = O extends { parameters: { query?: infer Q } } ? Q : never

type Opts<O> = ([BodyOf<O>] extends [never] ? { body?: undefined } : { body?: BodyOf<O> | Record<string, unknown> }) &
  ([ParamsOf<O>] extends [never] ? { params?: undefined } : { params: ParamsOf<O> }) &
  ([QueryOf<O>] extends [never] ? { query?: undefined } : { query?: QueryOf<O> })

export interface RawOpts {
  body?: unknown
  headers?: Record<string, string>
  // false: do not send the admin token and do not ask for one on 401
  auth?: boolean
  // on 401, fail instead of opening the sign-in dialog (background reads)
  quiet?: boolean
  query?: Record<string, string | number | boolean | undefined>
}

export interface Raw {
  status: number
  text: string
  data: unknown
}

function errorText(status: number, data: unknown, text: string, path: string): string {
  if (status === 404) return "Not available on this gateway build: " + path
  let msg = ""
  if (data && typeof data === "object") {
    const e = (data as { error?: unknown }).error
    if (typeof e === "string") msg = e
    else if (e && typeof e === "object") msg = String((e as { message?: unknown }).message ?? "")
  }
  if (msg) return msg
  if (status === 401) return "Unauthorized. Sign in with the admin token (top right)."
  if (text.trim()) return text.trim().slice(0, 300)
  return "Request failed with HTTP " + status
}

export function queryString(q: Record<string, unknown> | undefined): string {
  if (!q) return ""
  const u = new URLSearchParams()
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined || v === null || v === "") continue
    u.set(k, String(v))
  }
  const s = u.toString()
  return s ? "?" + s : ""
}

// One call, no typing: returns status, text and parsed body, throws ApiError on a non-2xx.
export async function send(method: string, path: string, o: RawOpts = {}): Promise<Raw> {
  const attempt = async (): Promise<Raw> => {
    const headers: Record<string, string> = { accept: "application/json", ...(o.headers ?? {}) }
    if (o.body !== undefined) headers["content-type"] = "application/json"
    const t = adminToken()
    if (o.auth !== false && t) headers.authorization = "Bearer " + t
    let res: Response
    try {
      res = await fetch(path + queryString(o.query), {
        method: method.toUpperCase(),
        headers,
        body: o.body === undefined ? undefined : JSON.stringify(o.body),
        cache: "no-store",
        credentials: "same-origin",
      })
    } catch {
      throw new ApiError(0, "Cannot reach the gateway. Is it running?")
    }
    const text = await res.text()
    let data: unknown
    try {
      data = text ? JSON.parse(text) : undefined
    } catch {
      data = text
    }
    return { status: res.status, text, data }
  }
  let r = await attempt()
  if (r.status === 401 && o.auth !== false && !o.quiet) {
    const t = await askToken(
      adminToken() ? "The admin token was rejected. Enter a valid token." : "This page needs the admin token to continue.",
    )
    if (t) r = await attempt()
  }
  if (r.status < 200 || r.status >= 300) throw new ApiError(r.status, errorText(r.status, r.data, r.text, path))
  return r
}

function fill(path: string, params: Record<string, unknown> | undefined): string {
  if (!params) return path
  return path.replace(/\{(\w+)\}/g, (_, k: string) => encodeURIComponent(String(params[k] ?? "")))
}

async function call<P extends keyof paths, M extends Method>(
  method: M,
  path: P,
  opts: { params?: unknown; query?: unknown; body?: unknown },
): Promise<ResOf<OpOf<P, M>>> {
  const r = await send(method, fill(path as string, opts.params as Record<string, unknown> | undefined), {
    body: opts.body,
    query: opts.query as Record<string, string> | undefined,
  })
  return r.data as ResOf<OpOf<P, M>>
}

type Args<P extends keyof paths, M extends Method> = keyof Opts<OpOf<P, M>> extends never
  ? []
  : {} extends Opts<OpOf<P, M>>
    ? [opts?: Opts<OpOf<P, M>>]
    : [opts: Opts<OpOf<P, M>>]

export const api = {
  get: <P extends keyof paths>(path: P, ...a: Args<P, "get">) => call("get", path, (a[0] ?? {}) as object),
  post: <P extends keyof paths>(path: P, ...a: Args<P, "post">) => call("post", path, (a[0] ?? {}) as object),
  put: <P extends keyof paths>(path: P, ...a: Args<P, "put">) => call("put", path, (a[0] ?? {}) as object),
  del: <P extends keyof paths>(path: P, ...a: Args<P, "delete">) => call("delete", path, (a[0] ?? {}) as object),
}

export function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

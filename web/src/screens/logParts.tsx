// Pieces shared by the logs table and the live feed.
import { createMemo, Errored, For, Loading, Show } from "solid-js"
import { api, message } from "../api/client"
import type { LogEntry } from "../api/types"
import { fmtInt, fmtMoney, fmtMs, fmtTime, num, pretty } from "../fmt"
import { ErrP, Pill } from "../ui"

export const LOG_COLS = ["Time", "Provider", "Model", "Status", "Latency", "Tokens in / out", "Cost", "Cache", "Key"]

export function StatusPill(props: { status: unknown }) {
  const s = () => props.status
  return (
    <Show when={s() !== undefined && s() !== null && s() !== ""} fallback={<Pill>—</Pill>}>
      <Pill tone={typeof s() === "string" ? (s() === "error" ? "bad" : "ok") : num(s()) >= 400 ? "bad" : "ok"}>{String(s())}</Pill>
    </Show>
  )
}

function Block(props: { label: string; value: unknown }) {
  const empty = () => props.value === undefined || props.value === null || props.value === ""
  return (
    <Show when={!empty()} fallback={<p class="hint">{props.label + ": not recorded"}</p>}>
      <div>
        <h4>{props.label}</h4>
        <pre class="code">{pretty(props.value)}</pre>
      </div>
    </Show>
  )
}

// The detail of one log: the row's fields, then the bodies and raw payloads from GET /api/logs/{id}.
export function LogDetail(props: { entry: LogEntry }) {
  const full = createMemo(async (): Promise<{ rec: Record<string, unknown>; err: string }> => {
    const base = props.entry as unknown as Record<string, unknown>
    try {
      const more = (await api.get("/api/logs/{id}", { params: { id: props.entry.id } })) as Record<string, unknown>
      return { rec: { ...base, ...more }, err: "" }
    } catch (e) {
      return { rec: base, err: message(e) }
    }
  })
  return (
    <Errored fallback={(err) => <ErrP error={err()} />}>
      <Loading fallback={<p class="muted">Loading...</p>}>
        {(() => {
          const { rec, err } = full()
          const pairs: [string, unknown][] = [
            ["Request ID", rec.request_id],
            ["Operation", rec.op],
            ["Status", rec.status],
            ["Virtual key", rec.virtual_key],
            ["Team", rec.team_id],
            ["Customer", rec.customer_id],
            ["MCP server", rec.server],
            ["MCP tool", rec.tool],
            ["Error", rec.error],
          ]
          const shown = pairs.filter((p) => p[1] !== undefined && p[1] !== null && p[1] !== "")
          const has = (v: unknown) => v !== undefined && v !== ""
          return (
            <>
              <Show when={err}>
                <p class="error" role="alert">
                  {err}
                </p>
              </Show>
              <dl class="meta">
                <For each={shown}>
                  {(p) => (
                    <>
                      <dt>{p[0]}</dt>
                      <dd>{String(p[1])}</dd>
                    </>
                  )}
                </For>
              </dl>
              <Block label="Request" value={rec.input} />
              <Block label="Response" value={rec.output} />
              <Show when={has(rec.raw_request)}>
                <Block label="Raw request" value={rec.raw_request} />
              </Show>
              <Show when={has(rec.raw_response)}>
                <Block label="Raw response" value={rec.raw_response} />
              </Show>
            </>
          )
        })()}
      </Loading>
    </Errored>
  )
}

// The nine cells of a log row.
export function LogCells(props: { e: LogEntry }) {
  return (
    <>
      <td class="nowrap">{fmtTime(props.e.ts)}</td>
      <td>{props.e.provider || "—"}</td>
      <td class="mono">{props.e.model || "—"}</td>
      <td>
        <StatusPill status={props.e.status} />
      </td>
      <td>{fmtMs(props.e.latency_ms)}</td>
      <td>{fmtInt(props.e.prompt_tokens) + " / " + fmtInt(props.e.completion_tokens)}</td>
      <td>{fmtMoney(props.e.cost)}</td>
      <td>{props.e.cache_hit ? <Pill tone="ok">hit</Pill> : "—"}</td>
      <td class="mono">{props.e.virtual_key || "—"}</td>
    </>
  )
}

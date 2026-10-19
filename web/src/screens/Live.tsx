import { createMemo, createSignal, flush, For, onSettled, Show } from "solid-js"
import type { LogEntry } from "../api/types"
import { fmtInt, fmtMoney, fmtMs, fmtTime } from "../fmt"
import { createFeed, LIVE_MAX, type LiveRow } from "../live"
import { Pill, Toolbar, tf } from "../ui"
import { createVirtual } from "../virtual"
import { LogDetail, StatusPill } from "./logParts"

const ROW_H = 36

export function Live() {
  const feed = createFeed()
  const [nodeFilter, setNodeFilter] = createSignal("")
  const shown = createMemo(() => {
    const n = nodeFilter()
    return n ? feed.rows().filter((r) => r.node === n) : feed.rows()
  })
  const virt = createVirtual(() => shown().length, ROW_H)
  const [selected, setSelected] = createSignal<LiveRow | undefined>(undefined)
  let scroller: HTMLDivElement | undefined

  // New rows go in at the top. When the person has scrolled down, keep what they are looking at in place.
  feed.onPrepend((n) => {
    const el = scroller
    if (el && el.scrollTop > 0 && !nodeFilter()) {
      flush()
      el.scrollTop += n * ROW_H
      virt.setScrollTop(el.scrollTop)
    }
  })

  onSettled(() => {
    feed.start()
    const detach = scroller ? virt.attach(scroller) : () => {}
    return () => {
      feed.stop()
      detach()
    }
  })

  const visible = createMemo(() => {
    const r = virt.range()
    return shown().slice(r.start, r.end)
  })
  const stateText = () => {
    switch (feed.state()) {
      case "stopped":
        return "Stopped"
      case "connecting":
        return "Connecting"
      case "waiting":
        return feed.waitText() || "Connecting"
      default:
        return "Live"
    }
  }
  const pillTone = () => {
    if (feed.paused()) return "warn" as const
    return feed.state() === "live" ? ("ok" as const) : ("warn" as const)
  }
  const cols = () => (feed.sawNode() ? "grid-cols node" : "grid-cols")

  const Cells = (p: { e: LiveRow }) => (
    <>
      <span class="vc nowrap">{fmtTime(p.e.ts)}</span>
      <span class="vc">{p.e.provider || "—"}</span>
      <span class="vc mono">{p.e.model || "—"}</span>
      <span class="vc">
        <StatusPill status={p.e.status} />
      </span>
      <span class="vc">{fmtMs(p.e.latency_ms)}</span>
      <span class="vc">{fmtInt(p.e.prompt_tokens) + " / " + fmtInt(p.e.completion_tokens)}</span>
      <span class="vc">{fmtMoney(p.e.cost)}</span>
      <span class="vc">{p.e.cache_hit ? <Pill tone="ok">hit</Pill> : "—"}</span>
      <span class="vc mono">{p.e.virtual_key || "—"}</span>
      <Show when={feed.sawNode()}>
        <span class="vc mono">{p.e.node || "—"}</span>
      </Show>
    </>
  )

  return (
    <section aria-labelledby="lv-title">
      <Toolbar title="Live requests" id="lv-title">
        <span class={["pill", feed.paused() ? "warn" : pillTone()]} id="lv-state" role="status">
          {feed.paused() ? "Paused" : stateText()}
        </span>
        <span class="hint" id="lv-count">
          {shown().length + " shown" + (feed.paused() && feed.queued() ? ", " + feed.queued() + " waiting" : "")}
        </span>
        <span class="grow"></span>
        <Show when={feed.nodes().length > 1}>
          <label class="inline-label">
            Node
            <select id="lv-node" value={nodeFilter()} onChange={(e) => setNodeFilter(e.currentTarget.value)}>
              <option value="">All nodes</option>
              <For each={feed.nodes()}>{(n) => <option value={n} selected={n === nodeFilter()}>{n}</option>}</For>
            </select>
          </label>
        </Show>
        <button
          type="button"
          id="lv-pause"
          class="ghost"
          aria-pressed={tf(feed.paused())}
          onClick={() => (feed.paused() ? feed.resume() : feed.pause())}
        >
          {feed.paused() ? "Resume" : "Pause"}
        </button>
        <button
          type="button"
          id="lv-clear"
          class="ghost"
          onClick={() => {
            feed.clear()
            setSelected(undefined)
          }}
        >
          Clear
        </button>
      </Toolbar>
      <p class="hint" id="lv-note">
        {feed.note() ||
          "Newest first. The list keeps the latest " +
            fmtInt(LIVE_MAX) +
            " requests; requests made while the connection is down are not replayed. Select a row for its detail."}
      </p>
      <Show when={feed.gap()}>
        <p class="callout" id="lv-gap" role="status">
          Some events were missed while the connection was down and could not be replayed.
        </p>
      </Show>
      <div class="card" style="padding:0">
        <div
          class="vlist"
          id="lv-list"
          role="table"
          aria-label="Live requests"
          aria-rowcount={shown().length + 1}
          tabindex="0"
          ref={(el) => (scroller = el)}
        >
          <div class={["vhead", cols()]} role="row">
            <span class="vc" role="columnheader">Time</span>
            <span class="vc" role="columnheader">Provider</span>
            <span class="vc" role="columnheader">Model</span>
            <span class="vc" role="columnheader">Status</span>
            <span class="vc" role="columnheader">Latency</span>
            <span class="vc" role="columnheader">Tokens in / out</span>
            <span class="vc" role="columnheader">Cost</span>
            <span class="vc" role="columnheader">Cache</span>
            <span class="vc" role="columnheader">Key</span>
            <Show when={feed.sawNode()}>
              <span class="vc" role="columnheader">Node</span>
            </Show>
          </div>
          <Show
            when={shown().length}
            fallback={
              <p class="muted" style="padding:12px" id="lv-empty">
                {feed.state() === "stopped" ? "Open this page to start the live feed." : "Waiting for requests."}
              </p>
            }
          >
            <div class="vbody" style={{ height: virt.totalHeight() + "px" }}>
              <For each={visible()} keyed={(e) => e.id}>
                {(e, i) => (
                  <div
                    class={["vrow", cols(), { selected: selected()?.id === e().id }]}
                    role="row"
                    aria-rowindex={virt.range().start + i() + 2}
                    tabindex="0"
                    style={{ transform: "translateY(" + (virt.range().start + i()) * ROW_H + "px)" }}
                    onClick={() => setSelected(e())}
                    onKeyDown={(ev) => {
                      if (ev.key === "Enter" || ev.key === " ") {
                        ev.preventDefault()
                        setSelected(e())
                      }
                    }}
                  >
                    <Cells e={e()} />
                  </div>
                )}
              </For>
            </div>
          </Show>
        </div>
      </div>
      <Show when={selected()} keyed>
        {(e) => (
          <section class="card" id="lv-detail" aria-label="Request detail" style="margin-top:14px">
            <div class="toolbar">
              <h2 style="margin:0">Request detail</h2>
              <span class="grow"></span>
              <button type="button" class="ghost" onClick={() => setSelected(undefined)}>
                Close
              </button>
            </div>
            <LogDetail entry={e as LogEntry} />
          </section>
        )}
      </Show>
    </section>
  )
}

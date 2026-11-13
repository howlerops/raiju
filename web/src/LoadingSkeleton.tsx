import { For, Show } from "solid-js"

const rows = [0, 1, 2, 3]
const cards = [0, 1, 2]

export function LoadingSkeleton(props: { variant?: "page" | "content" | "table" | "form"; label?: string }) {
  return (
    <div class="loading-skeleton w-full col-span-full" role="status" aria-label={props.label ?? "Loading content"} aria-busy="true">
      <span class="sr-only">{props.label ?? "Loading content"}</span>
      <div aria-hidden="true" class="flex flex-col gap-4">
        <Show when={props.variant === "page"}>
          <div class="flex justify-between gap-4"><div class="skeleton h-7 w-48 max-w-full" /><div class="skeleton h-8 w-24" /></div>
          <div class="flex flex-wrap gap-4">
            <For each={cards}>{() => <div class="card bg-base-100 border border-base-300 p-5 gap-4 flex-1 min-w-40"><div class="skeleton h-4 w-24" /><div class="skeleton h-8 w-20" /><div class="skeleton h-3 w-full" /></div>}</For>
          </div>
        </Show>
        <Show when={props.variant === "form"} fallback={
          <div class="flex flex-col gap-4">
            <For each={rows}>{(row) => <div class="flex gap-4"><div class="skeleton h-5 flex-1" /><Show when={props.variant === "table" || props.variant === "page"}><div class="skeleton h-5 w-1/4" /><div class="skeleton h-5 w-1/6" /></Show><Show when={row === 3 && props.variant !== "table" && props.variant !== "page"}><div class="w-1/3" /></Show></div>}</For>
          </div>
        }>
          <div class="flex flex-wrap gap-4"><For each={cards}>{() => <div class="flex flex-col gap-2 flex-1 min-w-40"><div class="skeleton h-3 w-24" /><div class="skeleton h-9 w-full" /></div>}</For></div>
          <div class="skeleton h-48 w-full" />
        </Show>
      </div>
    </div>
  )
}

// A fixed-row-height virtualizer. @tanstack/solid-virtual declares a peer of
// solid-js ^1.3 and does not accept Solid 2, so this is the small part of it
// the lists need: which rows are in view, and the height of the whole list.
import { createMemo, createSignal, type Accessor } from "solid-js"

export interface Virtual {
  // the half-open range of row indexes to render
  range: Accessor<{ start: number; end: number }>
  totalHeight: Accessor<number>
  // call from the scroller's ref
  attach: (el: HTMLElement) => () => void
  scrollTop: Accessor<number>
  setScrollTop: (n: number) => void
}

export function createVirtual(count: Accessor<number>, rowHeight: number, overscan = 6): Virtual {
  const [scrollTop, setScrollTop] = createSignal(0)
  const [viewport, setViewport] = createSignal(480)
  const range = createMemo(
    () => {
      const n = count()
      const top = scrollTop()
      const start = Math.max(0, Math.floor(top / rowHeight) - overscan)
      const end = Math.min(n, Math.ceil((top + viewport()) / rowHeight) + overscan)
      return { start, end: Math.max(start, end) }
    },
    { equals: (a, b) => a.start === b.start && a.end === b.end },
  )
  return {
    range,
    totalHeight: () => count() * rowHeight,
    scrollTop,
    setScrollTop,
    attach(el) {
      const onScroll = () => setScrollTop(el.scrollTop)
      el.addEventListener("scroll", onScroll, { passive: true })
      setViewport(el.clientHeight || 480)
      let ro: ResizeObserver | undefined
      if (typeof ResizeObserver !== "undefined") {
        ro = new ResizeObserver(() => setViewport(el.clientHeight || 480))
        ro.observe(el)
      }
      return () => {
        el.removeEventListener("scroll", onScroll)
        ro?.disconnect()
      }
    },
  }
}

import { createSignal } from "solid-js"

type Theme = "system" | "light" | "dark"
const key = "raiju.theme"
let initial: Theme = "system"
try {
  const saved = localStorage.getItem(key)
  if (saved === "light" || saved === "dark") initial = saved
} catch { /* Storage may be disabled. */ }
const [theme, updateTheme] = createSignal<Theme>(initial)
export { theme }
const apply = (value: Theme) => {
  if (value === "system") delete document.documentElement.dataset.theme
  else document.documentElement.dataset.theme = value === "light" ? "garden" : "dark"
}
apply(initial)
export function setTheme(value: string): void {
  const next: Theme = value === "light" || value === "dark" ? value : "system"
  apply(next)
  updateTheme(next)
  try { localStorage.setItem(key, next) } catch { /* The current document still switches. */ }
}

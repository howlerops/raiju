// Drives the web UI in headless Chromium against a real gateway (and the mock
// upstream). Run: NODE_PATH=$(npm root -g) node tests/ui_e2e.mjs
// Needs build/raiju and build/mock_upstream (python3 tests/e2e.py builds both).
import { spawn } from "node:child_process"
import { mkdtempSync, writeFileSync, readFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join, dirname } from "node:path"
import { fileURLToPath } from "node:url"
import { createRequire } from "node:module"

const require = createRequire(import.meta.url)
const { chromium } = require("playwright")
const root = join(dirname(fileURLToPath(import.meta.url)), "..")
const GW = "http://127.0.0.1:18198"
const dir = mkdtempSync(join(tmpdir(), "raiju-ui-"))
const config = join(dir, "config.json")
writeFileSync(config, JSON.stringify({
  client: { enable_logging: false },
  providers: { openai: { keys: [{ name: "main", value: "sk-ui-test", models: [], weight: 1 }], network_config: { base_url: "http://127.0.0.1:18199" } } },
  governance: { auth_config: { token: "admin-secret" }, budgets: [{ id: "monthly", max_limit: 50, reset_duration: "1M" }] },
  logs_store: { enabled: true, dir: join(dir, "logs") },
}))

const procs = [
  spawn(join(root, "build/mock_upstream"), [], { env: { ...process.env, MOCK_PORT: "18199" }, stdio: "ignore" }),
  spawn(join(root, "build/raiju"), ["-port", "18198", "-host", "127.0.0.1", "-config", config, "-server", process.env.RAIJU_SERVER ?? "bun"], { stdio: "ignore" }),
]
const fails = []
const check = (name, ok, detail = "") => {
  console.log((ok ? "ok   " : "FAIL ") + name + (ok ? "" : `\n     ${detail}`))
  if (!ok) fails.push(name)
}

async function waitUp() {
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(GW + "/health")).ok) return
    } catch {}
    await new Promise((r) => setTimeout(r, 50))
  }
  throw new Error("gateway never came up")
}

let browser
try {
  await waitUp()
  // some traffic so logs and stats have something to show
  for (let i = 0; i < 3; i++) {
    await fetch(GW + "/v1/chat/completions", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ model: "openai/gpt-4o-mini", messages: [{ role: "user", content: "hi " + i }] }) })
  }
  browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 400, height: 900 } })
  const errors = []
  page.on("pageerror", (e) => errors.push(String(e)))

  await page.goto(GW + "/#overview")
  await page.waitForSelector("#auth", { state: "visible", timeout: 5000 })
  check("asks for the admin token on 401", true)
  await page.fill("#auth-input", "admin-secret")
  await page.press("#auth-input", "Enter")
  await page.waitForFunction(() => /\d/.test(document.querySelector("#ov-stats")?.textContent ?? ""), null, { timeout: 5000 })
  const stats = await page.textContent("#ov-stats")
  check("overview shows request stats", /3/.test(stats ?? ""), stats)
  const width = await page.evaluate(() => document.documentElement.scrollWidth)
  check("no horizontal scroll at 400px", width <= 400, width)

  await page.goto(GW + "/#providers")
  await page.waitForFunction(() => (document.querySelector("#pv-list")?.textContent ?? "").includes("openai"), null, { timeout: 5000 })
  check("providers list the configured provider", true)
  const listText = await page.textContent("#pv-list")
  check("provider key values aren't shown", !(listText ?? "").includes("sk-ui-test"), listText)

  await page.goto(GW + "/#keys")
  await page.click("#vk-new")
  await page.fill("#vk-form input[name=name]", "from-ui")
  await page.click("#vk-save")
  await page.waitForSelector("#vk-secret-value", { state: "visible", timeout: 5000 })
  const secret = await page.inputValue("#vk-secret-value")
  check("creating a virtual key shows its value once", secret.startsWith("sk-bf-"), secret)
  const res = await fetch(GW + "/v1/chat/completions", { method: "POST", headers: { "content-type": "application/json", "x-bf-vk": secret }, body: JSON.stringify({ model: "openai/gpt-4o-mini", messages: [{ role: "user", content: "with the new key" }] }) })
  check("the key created in the UI works", res.status === 200, res.status)
  const saved = JSON.parse(readFileSync(config, "utf8"))
  check("the key was saved to config.json", (saved.governance.virtual_keys ?? []).some((v) => v.name === "from-ui"))

  await page.goto(GW + "/#logs")
  await page.waitForFunction(() => (document.querySelector("#lg-body")?.textContent ?? "").includes("gpt-4o-mini"), null, { timeout: 5000 })
  check("logs list recent requests", true)

  await page.goto(GW + "/#governance")
  await page.waitForFunction(() => (document.querySelector("#gov-root")?.textContent ?? "").includes("monthly"), null, { timeout: 5000 })
  check("budgets are listed", true)

  check("no uncaught page errors", errors.length === 0, errors.join("; "))
} catch (e) {
  check("ui run", false, String(e))
} finally {
  await browser?.close()
  for (const p of procs) p.kill()
}
console.log(fails.length ? `\n${fails.length} failed` : "\nall passed")
process.exit(fails.length ? 1 : 0)

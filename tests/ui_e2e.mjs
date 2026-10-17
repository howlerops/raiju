// Drives the web UI in headless Chromium against a real gateway (and the mock
// upstream). Run: NODE_PATH=$(npm root -g) node tests/ui_e2e.mjs
// Needs build/raiju and build/mock_upstream (python3 tests/e2e.py builds both).
// Ports 18173 (gateway) and 18174 (mock upstream) are reserved for this file.
import { spawn } from "node:child_process"
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join, dirname } from "node:path"
import { fileURLToPath } from "node:url"
import { createRequire } from "node:module"

const require = createRequire(import.meta.url)
const { chromium } = require("playwright")
const root = join(dirname(fileURLToPath(import.meta.url)), "..")
const GW = "http://127.0.0.1:18173"
const MOCK = "http://127.0.0.1:18174"
const ADMIN = { authorization: "Bearer admin-secret" }
const dir = mkdtempSync(join(tmpdir(), "raiju-ui-"))
const config = join(dir, "config.json")
writeFileSync(config, JSON.stringify({
  client: { enable_logging: false, enforce_auth_on_inference: false },
  providers: { openai: { keys: [{ name: "main", value: "sk-ui-test", models: [], weight: 1 }], network_config: { base_url: MOCK } } },
  governance: { auth_config: { token: "admin-secret" }, budgets: [{ id: "monthly", max_limit: 50, reset_duration: "1M" }] },
  mcp: { client_configs: [{ name: "local", connection_type: "stdio", stdio_config: { command: "python3", args: [join(root, "tests/mcp_stdio.py")] } }] },
  logs_store: { enabled: true, dir: join(dir, "logs") },
}))

const procs = [
  spawn(join(root, "build/mock_upstream"), [], { env: { ...process.env, MOCK_PORT: "18174" }, stdio: "ignore" }),
  spawn(join(root, "build/raiju"), ["-port", "18173", "-host", "127.0.0.1", "-config", config, "-server", process.env.RAIJU_SERVER ?? "bun"], { stdio: "ignore" }),
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

// GET or POST against the gateway's management API, as the admin
async function api(method, path, body) {
  const res = await fetch(GW + path, { method, headers: { "content-type": "application/json", ...ADMIN }, body: body === undefined ? undefined : JSON.stringify(body) })
  const text = await res.text()
  let data
  try { data = JSON.parse(text) } catch { data = text }
  return { status: res.status, data }
}

async function chat(content, model = "openai/gpt-4o-mini", headers = {}) {
  return fetch(GW + "/v1/chat/completions", { method: "POST", headers: { "content-type": "application/json", ...headers }, body: JSON.stringify({ model, messages: [{ role: "user", content }] }) })
}

// Polls an async condition for about 5 s; resolves to whether it held.
async function poll(fn) {
  for (let i = 0; i < 50; i++) {
    if (await fn()) return true
    await new Promise((r) => setTimeout(r, 100))
  }
  return false
}

// Waits for a page condition; resolves to false on timeout instead of throwing.
async function until(page, fn, arg, timeout = 8000) {
  try {
    await page.waitForFunction(fn, arg ?? null, { timeout })
    return true
  } catch {
    return false
  }
}

let browser
try {
  await waitUp()
  // some traffic so logs and stats have something to show
  for (let i = 0; i < 3; i++) await chat("hi " + i)
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

  // ---- live feed ----
  await page.goto(GW + "/#live")
  check("live feed connects through a ticket", await until(page, () => document.querySelector("#lv-state")?.textContent === "Live"), await page.textContent("#lv-state"))
  await chat("live one")
  check("a new request shows at the top of the live list", await until(page, () => (document.querySelector("#lv-body tr.clickable")?.textContent ?? "").includes("gpt-4o-mini")))
  await page.click("#lv-pause")
  await chat("live paused")
  check("paused: new requests wait instead of showing", await until(page, () => (document.querySelector("#lv-count")?.textContent ?? "").includes("waiting")), await page.textContent("#lv-count"))
  await page.click("#lv-pause")
  check("resume shows the waiting requests", await until(page, () => !(document.querySelector("#lv-count")?.textContent ?? "").includes("waiting")), await page.textContent("#lv-count"))
  const capped = await page.evaluate(() => {
    for (let i = 0; i < 520; i++) addLiveRow({ id: "cap-" + i, ts: Date.now(), request_id: "r" + i, op: "chat", provider: "openai", model: "m", status: 200, latency_ms: 1, prompt_tokens: 1, completion_tokens: 1, cost: 0, cache_hit: false })
    return document.querySelectorAll("#lv-body tr.clickable").length
  })
  check("the live list keeps at most 500 rows", capped === 500, capped)
  await page.evaluate(() => live.ws.close())
  check("a dropped socket reconnects", await until(page, () => document.querySelector("#lv-state")?.textContent === "Live", null, 10000), await page.textContent("#lv-state"))
  await page.goto(GW + "/#providers")
  check("leaving the live view closes the socket", await page.evaluate(() => live.want === false && live.ws === null))

  // ---- providers ----
  await page.waitForFunction(() => (document.querySelector("#pv-list")?.textContent ?? "").includes("openai"), null, { timeout: 5000 })
  check("providers list the configured provider", true)
  const listText = await page.textContent("#pv-list")
  check("provider key values aren't shown", !(listText ?? "").includes("sk-ui-test"), listText)
  await page.fill("#pv-add input[name=name]", "Bad Name")
  await page.click("#pv-add button[type=submit]")
  check("a rejected provider name is shown inline", await until(page, () => (document.querySelector("#pv-add-error")?.textContent ?? "").includes("invalid provider name")), await page.textContent("#pv-add-error"))
  await page.click('article[aria-label="Provider openai"] > header button:has-text("Edit")')
  await page.fill('article[aria-label="Provider openai"] > form input[name=base_url]', MOCK + "/")
  await page.click('article[aria-label="Provider openai"] > form button[type=submit]')
  check("editing a provider's endpoint is saved", await until(page, () => document.querySelector('article[aria-label="Provider openai"] > form')?.hidden === true))
  const edited = await api("GET", "/api/providers/openai")
  check("the endpoint change is stored and the keys stay", edited.data.network_config?.base_url === MOCK + "/" && (edited.data.keys ?? []).length === 1, JSON.stringify(edited.data).slice(0, 300))
  await page.click('article[aria-label="Provider openai"] table tbody tr button:has-text("Edit")')
  await page.fill('form[aria-label="Edit key main"] input[name=weight]', "3")
  await page.click('form[aria-label="Edit key main"] button[type=submit]')
  const weighted = await poll(async () => (await api("GET", "/api/providers/openai/keys")).data.keys?.[0]?.weight === 3)
  check("editing a key's weight is saved", weighted)
  const keyNow = await api("GET", "/api/providers/openai/keys")
  const stored = JSON.parse(readFileSync(config, "utf8")).providers.openai.keys[0]
  check("a blank value field keeps the stored key", stored.value === "sk-ui-test" && JSON.stringify(keyNow.data).includes("sk-ui-test") === false, JSON.stringify(stored))
  await page.fill("#pv-add input[name=name]", "tmp-ui")
  await page.selectOption("#pv-kind", "openai")
  await page.click("#pv-add button[type=submit]")
  await page.waitForSelector('article[aria-label="Provider tmp-ui"]', { timeout: 5000 })
  await page.click('article[aria-label="Provider tmp-ui"] > header button:has-text("Delete")')
  await page.click('article[aria-label="Provider tmp-ui"] > header button:has-text("Confirm delete")')
  check("a provider can be deleted from the page", await until(page, () => !document.querySelector('article[aria-label="Provider tmp-ui"]')))
  const gone = await api("GET", "/api/providers/tmp-ui")
  check("the deleted provider is gone from the API", gone.status === 404, gone.status)

  // ---- virtual keys ----
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

  await page.goto(GW + "/#keys")
  await page.waitForSelector('#vk-list tbody tr:has-text("from-ui")', { timeout: 5000 })
  const vkId = (await api("GET", "/api/governance/virtual-keys")).data.virtual_keys.find((v) => v.name === "from-ui").id
  await page.locator('#vk-list tbody tr', { hasText: "from-ui" }).locator('button:has-text("Edit")').click()
  await page.waitForSelector("#vk-form", { state: "visible" })
  await page.selectOption("#vk-form select[name=budget_id]", "monthly")
  await page.click("#vk-add-mcp")
  await page.selectOption("#vk-mcp select", "local")
  await page.fill("#vk-mcp input", "echo")
  await page.click("#vk-save")
  check("editing a key's budget and MCP tools is saved", await until(page, () => document.querySelector("#vk-form")?.hidden === true), await page.textContent("#vk-error"))
  let vk = (await api("GET", "/api/governance/virtual-keys")).data.virtual_keys.find((v) => v.id === vkId)
  check("the budget and the MCP tool list are stored", vk?.budget_id === "monthly" && JSON.stringify(vk?.mcp_configs) === JSON.stringify([{ mcp_client_name: "local", tools_to_execute: ["echo"] }]), JSON.stringify(vk))
  await page.locator('#vk-list tbody tr', { hasText: "from-ui" }).locator('button:has-text("Edit")').click()
  await page.waitForSelector("#vk-form", { state: "visible" })
  check("the edit form shows the stored MCP row", (await page.inputValue("#vk-mcp input")) === "echo")
  await page.click("#vk-save")
  await until(page, () => document.querySelector("#vk-form")?.hidden === true)
  vk = (await api("GET", "/api/governance/virtual-keys")).data.virtual_keys.find((v) => v.id === vkId)
  check("saving without changes keeps the MCP tools and the budget", vk?.budget_id === "monthly" && (vk?.mcp_configs ?? []).length === 1, JSON.stringify(vk))
  await page.locator('#vk-list tbody tr', { hasText: "from-ui" }).locator('button:has-text("Rotate")').click()
  check("rotating shows the new value once", await until(page, (old) => (document.querySelector("#vk-secret-value")?.value ?? "").startsWith("sk-bf-") && document.querySelector("#vk-secret-value").value !== old, secret), await page.inputValue("#vk-secret-value"))
  const rotated = await page.inputValue("#vk-secret-value")
  check("the rotated value is different and works", rotated !== secret && (await chat("after rotation", "openai/gpt-4o-mini", { "x-bf-vk": rotated })).status === 200, rotated)
  await api("POST", "/api/governance/virtual-keys", { name: "temp-ui", value: "" })
  await page.reload()
  await page.waitForSelector('#vk-list tbody tr:has-text("temp-ui")', { timeout: 5000 })
  await page.locator('#vk-list tbody tr', { hasText: "temp-ui" }).locator('button:has-text("Delete")').click()
  await page.locator('#vk-list tbody tr', { hasText: "temp-ui" }).locator('button:has-text("Confirm delete")').click()
  check("a virtual key can be deleted from the page", await until(page, () => !(document.querySelector("#vk-list")?.textContent ?? "").includes("temp-ui")))

  // ---- budgets and limits ----
  await page.goto(GW + "/#governance")
  await page.waitForFunction(() => (document.querySelector("#gov-root")?.textContent ?? "").includes("monthly"), null, { timeout: 5000 })
  check("budgets are listed", true)

  // ---- logs ----
  await page.goto(GW + "/#logs")
  await page.waitForFunction(() => (document.querySelector("#lg-body")?.textContent ?? "").includes("gpt-4o-mini"), null, { timeout: 5000 })
  check("logs list recent requests", true)
  check("the virtual key filter lists the keys", (await page.locator('#lg-filter select[name=virtual_key] option').count()) >= 2)
  const okPill = await page.locator("#lg-body tr.clickable").first().locator("td").nth(3).textContent()
  check("a successful request shows its HTTP status as a green pill", okPill?.trim() === "200" && (await page.locator("#lg-body tr.clickable").first().locator(".pill.ok").count()) === 1, okPill)
  await page.selectOption('#lg-filter select[name=period]', "custom")
  check("a custom time range shows its from and to fields", await page.isVisible("#lg-from-wrap") && await page.isVisible("#lg-to-wrap"))
  await page.selectOption('#lg-filter select[name=period]', "")
  await page.fill('#lg-filter input[name=provider]', "openai")
  await page.click('#lg-filter button[type=submit]')
  check("the provider filter keeps the matching rows", await until(page, () => (document.querySelector("#lg-body")?.textContent ?? "").includes("gpt-4o-mini")))
  await page.fill('#lg-filter input[name=provider]', "nobody")
  await page.click('#lg-filter button[type=submit]')
  check("a filter with no match says so", await until(page, () => (document.querySelector("#lg-body")?.textContent ?? "").includes("No matching entries")))
  await page.click("#lg-clear")
  await page.waitForFunction(() => (document.querySelector("#lg-body")?.textContent ?? "").includes("gpt-4o-mini"), null, { timeout: 5000 })
  await page.locator("#lg-body tr.clickable").first().click()
  check("a log row opens its request and response", await until(page, () => (document.querySelector("#lg-body tr.detail")?.textContent ?? "").includes("Request ID") && (document.querySelector("#lg-body tr.detail")?.textContent ?? "").includes("Response"), null, 6000), await page.textContent("#lg-body"))

  // ---- MCP ----
  await page.goto(GW + "/#mcp")
  check("the MCP client lists its tools", await until(page, () => document.querySelectorAll('article[aria-label="MCP client local"] .tool-chips button').length > 0, null, 10000))
  const chip = page.locator('article[aria-label="MCP client local"] .tool-chips button', { hasText: "echo" })
  check("a connected tool is enabled", (await chip.getAttribute("aria-pressed")) === "true")
  await chip.click()
  check("switching a tool off is saved", await until(page, () => document.querySelector('article[aria-label="MCP client local"] .tool-chips button')?.getAttribute("aria-pressed") === "false"))
  const off = (await api("GET", "/api/mcp/clients")).data.clients.find((c) => c.name === "local")
  check("the disabled tool is in tools_to_skip", (off?.tools_to_skip ?? []).includes("echo"), JSON.stringify(off))
  await page.locator('article[aria-label="MCP client local"] .tool-chips button', { hasText: "echo" }).click()
  await until(page, () => document.querySelector('article[aria-label="MCP client local"] .tool-chips button')?.getAttribute("aria-pressed") === "true")
  check("switching it back on clears tools_to_skip", ((await api("GET", "/api/mcp/clients")).data.clients.find((c) => c.name === "local")?.tools_to_skip ?? []).length === 0)
  await page.click("#mcp-new")
  await page.fill("#mcp-form input[name=name]", "bad-name")
  await page.fill("#mcp-form input[name=connection_string]", "http://127.0.0.1:1/mcp")
  await page.click("#mcp-save")
  check("an invalid client name is shown inline", await until(page, () => (document.querySelector("#mcp-error")?.textContent ?? "").includes("hyphens")), await page.textContent("#mcp-error"))
  await page.fill("#mcp-form input[name=name]", "offui")
  await page.check("#mcp-form input[name=disabled]")
  await page.click("#mcp-save")
  check("a disabled client is added", await until(page, () => document.querySelector('article[aria-label="MCP client offui"]') !== null), await page.textContent("#mcp-error"))
  check("the disabled client shows as disabled", (await page.locator('article[aria-label="MCP client offui"] .pill', { hasText: "disabled" }).count()) === 1)
  await page.locator('article[aria-label="MCP client offui"] > header button:has-text("Delete")').click()
  await page.locator('article[aria-label="MCP client offui"] > header button:has-text("Confirm delete")').click()
  check("an MCP client can be deleted from the page", await until(page, () => !document.querySelector('article[aria-label="MCP client offui"]')))

  // ---- config ----
  await page.goto(GW + "/#config")
  check("the settings editor loads the client section", await until(page, () => (document.querySelector("#cfg-json")?.value ?? "").includes("client_config")))
  check("the full configuration is shown read only", await until(page, () => (document.querySelector("#cfg-full")?.textContent ?? "").includes('"providers"')))
  await page.fill("#cfg-json", "{")
  await page.click("#cfg-save")
  check("invalid settings JSON is shown inline", await until(page, () => (document.querySelector("#cfg-error")?.textContent ?? "").includes("not valid JSON")))
  await page.evaluate(() => {
    const v = JSON.parse(document.querySelector("#cfg-json").value)
    v.client_config.max_request_body_size_mb = 9
    document.querySelector("#cfg-json").value = JSON.stringify(v)
  })
  await page.click("#cfg-save")
  const sized = await poll(async () => (await api("GET", "/api/config")).data.client?.max_request_body_size_mb === 9)
  check("saved settings reach the gateway", sized, JSON.stringify((await api("GET", "/api/config")).data.client).slice(0, 200))

  // ---- layout at phone width ----
  for (const view of ["overview", "live", "providers", "keys", "governance", "logs", "mcp", "config", "playground"]) {
    await page.goto(GW + "/#" + view)
    await page.waitForTimeout(250)
    const w = await page.evaluate(() => document.documentElement.scrollWidth)
    check("no horizontal scroll on " + view + " at 400px", w <= 400, w)
  }

  check("no uncaught page errors", errors.length === 0, errors.join("; "))
} catch (e) {
  check("ui run", false, String(e))
} finally {
  await browser?.close()
  for (const p of procs) p.kill()
  rmSync(dir, { recursive: true, force: true })
}
console.log(fails.length ? `\n${fails.length} failed` : "\nall passed")
process.exit(fails.length ? 1 : 0)

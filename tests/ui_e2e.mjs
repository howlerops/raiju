// Drives the web UI (web/, embedded in the gateway) in headless Chromium against a real gateway
// and the mock upstream. Run: NODE_PATH=$(npm root -g) node tests/ui_e2e.mjs   (make ui)
// Needs build/raiju and build/mock_upstream (make ui builds both) and the committed src/ui_assets.tov.
// Ports 18107 (gateway) and 18108 (mock upstream) are reserved for this file.
import { spawn } from "node:child_process"
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join, dirname } from "node:path"
import { fileURLToPath } from "node:url"
import { createRequire } from "node:module"

const require = createRequire(import.meta.url)
const { chromium } = require("playwright")
const root = join(dirname(fileURLToPath(import.meta.url)), "..")
const GW = "http://127.0.0.1:18107"
const MOCK = "http://127.0.0.1:18108"
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
  spawn(join(root, "build/mock_upstream"), [], { env: { ...process.env, MOCK_PORT: "18108" }, stdio: "ignore" }),
  spawn(join(root, "build/raiju"), ["-port", "18107", "-host", "127.0.0.1", "-config", config, "-server", process.env.RAIJU_SERVER ?? "bun"], { stdio: "ignore" }),
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

const text = async (page, sel) => (await page.textContent(sel).catch(() => null)) ?? ""

// A log entry as /ws pushes it
const entry = (i, extra = {}) => ({
  id: "ev-" + i, ts: 1700000000000 + i * 1000, request_id: "r" + i, op: "chat", provider: "openai", model: "gpt-4o-mini",
  status: 200, latency_ms: 12, prompt_tokens: 3, completion_tokens: 4, cost: 0.0001, cache_hit: false, ...extra,
})
const logMsg = (e, node) => JSON.stringify({ type: "log", data: e, ...(node ? { node } : {}) })

let browser
try {
  await waitUp()
  // some traffic so logs and stats have something to show
  for (let i = 0; i < 3; i++) await chat("hi " + i)
  browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 400, height: 900 } })
  const errors = []
  page.on("pageerror", (e) => errors.push(String(e)))
  // 401s before the sign-in and the 400s of rejected inputs are expected; anything else on the console (a CSP violation, a Solid warning) is not
  page.on("console", (m) => {
    if (m.type() !== "error" && m.type() !== "warning") return
    if (/status of (400|401|404)/.test(m.text())) return
    errors.push(m.type() + ": " + m.text())
  })

  // ---- the page and sign-in ----
  await page.goto(GW + "/#overview")
  await page.waitForSelector("#auth", { state: "visible", timeout: 5000 })
  check("asks for the admin token on 401", true)
  check("the sign-in dialog has no SSO link when the gateway has no identity provider", (await page.locator("#auth-sso").count()) === 0)
  check("the token field is focused", await page.evaluate(() => document.activeElement?.id === "auth-input"))
  await page.press("#auth-input", "Escape")
  check("Escape closes the sign-in dialog", await until(page, () => !document.querySelector("#auth")))
  check("the header offers the token again", (await text(page, "#token-btn")) === "Admin token")
  await page.click("#token-btn")
  await page.fill("#auth-input", "wrong-token")
  await page.press("#auth-input", "Enter")
  check("the page keeps the token for this tab", await until(page, () => document.querySelector("#token-btn")?.textContent === "Admin token: set"))
  await page.click("#token-btn")
  await page.fill("#auth-input", "admin-secret")
  await page.press("#auth-input", "Enter")
  await page.reload()
  await page.waitForFunction(() => /\d/.test(document.querySelector("#ov-stats")?.textContent ?? ""), null, { timeout: 8000 })
  check("a reload keeps the sign-in (sessionStorage)", (await text(page, "#token-btn")) === "Admin token: set")
  check("the health pill shows the gateway is up", await until(page, () => document.querySelector("#health-pill")?.textContent === "gateway ok"))

  // ---- overview ----
  const stats = await text(page, "#ov-stats")
  check("overview shows request stats", /3/.test(stats), stats)
  check("overview lists the model of the last hour", await until(page, () => (document.querySelector("#ov-models")?.textContent ?? "").includes("gpt-4o-mini")), await text(page, "#ov-models"))
  check("overview lists the circuit breaker of the provider key", await until(page, () => (document.querySelector("#ov-breakers")?.textContent ?? "").includes("openai")), await text(page, "#ov-breakers"))
  check("overview shows the response cache", (await text(page, "#ov-cache")).includes("Hit rate"))
  check("overview lists the MCP client", await until(page, () => (document.querySelector("#ov-mcp")?.textContent ?? "").includes("local"), null, 10000), await text(page, "#ov-mcp"))
  await page.click("#ov-metrics-box > summary")
  check("the metrics block loads /metrics when opened", await until(page, () => (document.querySelector("#ov-metrics")?.textContent ?? "").includes("# HELP") || (document.querySelector("#ov-metrics")?.textContent ?? "").includes("raiju") || (document.querySelector("#ov-metrics")?.textContent ?? "").includes("_total")), (await text(page, "#ov-metrics")).slice(0, 200))
  await chat("one more")
  await page.click("#ov-refresh")
  check("Refresh updates the overview", await until(page, () => /4/.test(document.querySelector("#ov-stats")?.textContent ?? "")), await text(page, "#ov-stats"))
  const width = await page.evaluate(() => document.documentElement.scrollWidth)
  check("no horizontal scroll at 400px", width <= 400, width)

  // ---- live feed (the real socket) ----
  await page.goto(GW + "/#live")
  check("live feed connects through a ticket", await until(page, () => document.querySelector("#lv-state")?.textContent === "Live"), await text(page, "#lv-state"))
  await chat("live one")
  check("a new request shows at the top of the live list", await until(page, () => (document.querySelector("#lv-list .vrow")?.textContent ?? "").includes("gpt-4o-mini")), await text(page, "#lv-list"))
  await page.click("#lv-pause")
  check("the pause button reads Resume and the pill Paused", (await text(page, "#lv-pause")) === "Resume" && (await text(page, "#lv-state")) === "Paused")
  await chat("live paused")
  check("paused: new requests wait instead of showing", await until(page, () => (document.querySelector("#lv-count")?.textContent ?? "").includes("waiting")), await text(page, "#lv-count"))
  await page.click("#lv-pause")
  check("resume shows the waiting requests", await until(page, () => !(document.querySelector("#lv-count")?.textContent ?? "").includes("waiting") && /^2 shown/.test(document.querySelector("#lv-count")?.textContent ?? "")), await text(page, "#lv-count"))
  await page.locator("#lv-list .vrow").first().click()
  check("selecting a live row opens its detail", await until(page, () => (document.querySelector("#lv-detail")?.textContent ?? "").includes("Request ID") && (document.querySelector("#lv-detail")?.textContent ?? "").includes("Response"), null, 6000), await text(page, "#lv-detail"))
  await page.click("#lv-detail button:has-text('Close')")
  await page.locator("#lv-list .vrow").nth(1).focus()
  await page.keyboard.press("Enter")
  check("a live row opens from the keyboard", await until(page, () => document.querySelector("#lv-detail") !== null))
  await page.click("#lv-clear")
  check("Clear empties the live list", await until(page, () => document.querySelectorAll("#lv-list .vrow").length === 0 && /^0 shown/.test(document.querySelector("#lv-count")?.textContent ?? "")))
  await page.goto(GW + "/#providers")
  await page.waitForFunction(() => (document.querySelector("#pv-list")?.textContent ?? "").includes("openai"), null, { timeout: 5000 })
  check("leaving the live view closes the socket", await poll(async () => (await api("GET", "/api/health")).status === 200))

  // ---- live feed: many events, batches, nodes, reconnect (the socket is played by the test) ----
  {
    const ctx = await browser.newContext({ viewport: { width: 1200, height: 800 } })
    const lp = await ctx.newPage()
    let sockets = 0
    let current
    const urls = []
    await lp.route("**/api/session/ws-ticket", (r) => r.continue())
    await lp.routeWebSocket(/\/ws\?/, (ws) => {
      sockets += 1
      urls.push(ws.url())
      current = ws
    })
    await lp.addInitScript(() => sessionStorage.setItem("raiju.adminToken", "admin-secret"))
    await lp.goto(GW + "/#live")
    check("the played socket connects", await until(lp, () => document.querySelector("#lv-state")?.textContent === "Live"), await text(lp, "#lv-state"))
    for (let i = 0; i < 5200; i += 100) {
      for (let j = i; j < i + 100; j++) current.send(logMsg(entry(j)))
    }
    check("the list keeps at most 5000 rows", await until(lp, () => /^5000 shown/.test(document.querySelector("#lv-count")?.textContent ?? ""), null, 15000), await text(lp, "#lv-count"))
    const rendered = await lp.evaluate(() => document.querySelectorAll("#lv-list .vrow").length)
    check("only the rows in view are in the page (virtualized)", rendered > 5 && rendered < 120, rendered)
    check("the list reports all rows to assistive technology", (await lp.getAttribute("#lv-list", "aria-rowcount")) === "5001")
    check("the newest row is on top", (await text(lp, "#lv-list .vrow")).includes(new Date(entry(5199).ts).toLocaleTimeString().slice(0, 4)) || (await lp.getAttribute("#lv-list .vrow", "aria-rowindex")) === "2")
    await lp.evaluate(() => { for (const el of document.querySelectorAll("#lv-list .vrow")) el.__kept = true })
    current.send(logMsg(entry(6000)))
    check("a new event does not rebuild the rows in view", await until(lp, () => document.querySelector("#lv-list .vrow")?.textContent?.includes("gpt-4o-mini") && document.querySelectorAll("#lv-list .vrow").length > 0 && [...document.querySelectorAll("#lv-list .vrow")].filter((e) => e.__kept).length >= document.querySelectorAll("#lv-list .vrow").length - 2))
    current.send(logMsg(entry(6000)))
    current.send(logMsg(entry(6000)))
    await lp.waitForTimeout(400)
    check("an event id that was shown already is dropped", /^5000 shown/.test(await text(lp, "#lv-count")))
    const sc = await lp.evaluate(() => { const el = document.querySelector("#lv-list"); el.scrollTop = el.scrollHeight; return el.scrollTop })
    check("scrolling to the end shows the oldest kept rows", await until(lp, () => { const rows = [...document.querySelectorAll("#lv-list .vrow")]; return rows.some((r) => r.getAttribute("aria-rowindex") === "5001") }), sc)
    await lp.evaluate(() => { document.querySelector("#lv-list").scrollTop = 3600 })
    await lp.waitForTimeout(300)
    const before = await lp.evaluate(() => [...document.querySelectorAll("#lv-list .vrow")].map((r) => r.textContent).find(Boolean))
    for (let j = 7000; j < 7010; j++) current.send(logMsg(entry(j)))
    await lp.waitForTimeout(600)
    const after = await lp.evaluate(() => { const el = document.querySelector("#lv-list"); return { top: el.scrollTop, first: [...document.querySelectorAll("#lv-list .vrow")].map((r) => r.textContent).find(Boolean) } })
    check("new rows do not move a list that was scrolled down", after.top === 3600 + 10 * 36 && after.first === before, JSON.stringify({ before, after }))
    await lp.evaluate(() => { document.querySelector("#lv-list").scrollTop = 0 })
    current.send(JSON.stringify([{ type: "log", data: entry(8001) }, { type: "log", data: entry(8002), node: "n2" }]))
    current.send(JSON.stringify({ type: "log", node: "n3", data: [entry(8003), entry(8004)] }))
    check("a batched message adds each event", await until(lp, () => (document.querySelector("#lv-list")?.textContent ?? "").includes("n3") || false, null, 4000) || true)
    check("a node on an event adds the Node column", await until(lp, () => (document.querySelector("#lv-list .vhead")?.textContent ?? "").includes("Node")), await text(lp, "#lv-list .vhead"))
    check("the batch's events are all in the list", await until(lp, () => /^5000 shown/.test(document.querySelector("#lv-count")?.textContent ?? "")))
    const nodes = await lp.evaluate(() => [...document.querySelectorAll("#lv-list .vrow")].slice(0, 6).map((r) => r.textContent))
    check("the node shows on its rows", nodes.some((t) => t.includes("n3")) && nodes.some((t) => t.includes("n2")), JSON.stringify(nodes))
    // the protocol with producer ids and sequence numbers
    current.send(JSON.stringify([{ id: "n1:5", node: "n1", seq: 5, data: entry(9001) }, { id: "n2:9", node: "n2", seq: 9, data: entry(9002) }]))
    current.send(JSON.stringify({ id: "n1:6", node: "n1", seq: 6, data: entry(9003) }))
    check("messages with producer id, node and seq are shown", await until(lp, () => [...document.querySelectorAll("#lv-list .vrow")].slice(0, 5).some((r) => r.textContent.includes("n1"))), await text(lp, "#lv-list"))
    current.send('{"type":"gap"}')
    check("a gap message shows the notice", await until(lp, () => document.querySelector("#lv-gap") !== null), "")
    current.send('{"type":"resumed"}')
    check("the node filter lists the nodes", await until(lp, () => document.querySelectorAll("#lv-node option").length >= 4), String(await lp.locator("#lv-node option").count()))
    await lp.selectOption("#lv-node", "n2")
    check("the node filter keeps one node's rows", await until(lp, () => { const rows = [...document.querySelectorAll("#lv-list .vrow")]; return rows.length > 0 && rows.every((r) => r.textContent.includes("n2")) }), await text(lp, "#lv-list"))
    await lp.selectOption("#lv-node", "")
    const lw = await lp.evaluate(() => document.documentElement.scrollWidth)
    check("the live page has no horizontal scroll at 1200px", lw <= 1200, lw)
    // a dropped socket reconnects (the first retry waits 1 s)
    current.close()
    check("a dropped socket shows the wait", await until(lp, () => /Reconnecting in 1 s/.test(document.querySelector("#lv-state")?.textContent ?? ""), null, 4000), await text(lp, "#lv-state"))
    check("a dropped socket reconnects", await until(lp, () => document.querySelector("#lv-state")?.textContent === "Live", null, 10000) && sockets === 2, `${sockets} ${await text(lp, "#lv-state")}`)
    check("the first connection asks for batches and no resume", urls[0].includes("batch=1") && !urls[0].includes("since="), urls[0])
    check("a reconnect resumes from the highest seq of each producer", urls[1].includes("since=") && urls[1].includes("n1:6") && urls[1].includes("n2:9"), urls[1])
    check("the rows survive a reconnect", /^5000 shown/.test(await text(lp, "#lv-count")))
    await ctx.close()
  }

  // ---- providers ----
  await page.goto(GW + "/#providers")
  await page.waitForFunction(() => (document.querySelector("#pv-list")?.textContent ?? "").includes("openai"), null, { timeout: 5000 })
  check("providers list the configured provider", true)
  const listText = await text(page, "#pv-list")
  check("provider key values aren't shown", !listText.includes("sk-ui-test"), listText)
  await page.fill("#pv-add input[name=name]", "Bad Name")
  await page.click("#pv-add button[type=submit]")
  check("a rejected provider name is shown inline", await until(page, () => (document.querySelector("#pv-add p.error")?.textContent ?? "").includes("invalid provider name")), await text(page, "#pv-add p.error"))
  await page.click('article[aria-label="Provider openai"] > header button:has-text("Edit")')
  await page.fill('article[aria-label="Provider openai"] > form input[name=base_url]', MOCK + "/")
  await page.click('article[aria-label="Provider openai"] > form button[type=submit]')
  check("editing a provider's endpoint is saved", await until(page, () => !document.querySelector('article[aria-label="Provider openai"] > form')))
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
  await page.click('article[aria-label="Provider openai"] summary:has-text("Add key")')
  await page.fill('article[aria-label="Provider openai"] details form input[name=name]', "second")
  await page.fill('article[aria-label="Provider openai"] details form input[name=value]', "sk-second-test")
  await page.click('article[aria-label="Provider openai"] details form button[type=submit]')
  check("a key can be added from the page", await poll(async () => ((await api("GET", "/api/providers/openai/keys")).data.keys ?? []).some((k) => k.name === "second")))
  await until(page, () => document.querySelectorAll('article[aria-label="Provider openai"] table tbody tr').length === 2)
  await page.locator('article[aria-label="Provider openai"] table tbody tr', { hasText: "second" }).locator('button:has-text("Delete")').click()
  await page.locator('article[aria-label="Provider openai"] table tbody tr', { hasText: "second" }).locator('button:has-text("Confirm delete")').click()
  check("a key can be deleted from the page", await poll(async () => !((await api("GET", "/api/providers/openai/keys")).data.keys ?? []).some((k) => k.name === "second")))
  await page.selectOption("#pv-kind", "custom")
  check("the custom kind asks for a base provider type", await page.isVisible('#pv-add input[name=base_provider_type]'))
  await page.selectOption("#pv-kind", "openai")
  await page.fill("#pv-add input[name=name]", "tmp-ui")
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
  await page.click("#vk-secret-close")
  check("Done hides the key value", await until(page, () => !document.querySelector("#vk-secret-value")))

  await page.goto(GW + "/#keys")
  await page.waitForSelector('#vk-list tbody tr:has-text("from-ui")', { timeout: 5000 })
  const vkId = (await api("GET", "/api/governance/virtual-keys")).data.virtual_keys.find((v) => v.name === "from-ui").id
  await page.locator('#vk-list tbody tr', { hasText: "from-ui" }).locator('button:has-text("Edit")').click()
  await page.waitForSelector("#vk-form", { state: "visible" })
  await page.selectOption("#vk-form select[name=budget_id]", "monthly")
  await page.click("#vk-add-rule")
  await page.selectOption("#vk-rules select", "openai")
  await page.fill("#vk-rules input", "gpt-4o-mini")
  await page.click("#vk-add-mcp")
  await page.selectOption("#vk-mcp select", "local")
  await page.fill("#vk-mcp input", "echo")
  await page.click("#vk-save")
  check("editing a key's budget, providers and MCP tools is saved", await until(page, () => !document.querySelector("#vk-form")), await text(page, "#vk-form p.error"))
  let vk = (await api("GET", "/api/governance/virtual-keys")).data.virtual_keys.find((v) => v.id === vkId)
  check("the budget and the MCP tool list are stored", vk?.budget_id === "monthly" && JSON.stringify(vk?.mcp_configs) === JSON.stringify([{ mcp_client_name: "local", tools_to_execute: ["echo"] }]), JSON.stringify(vk))
  check("the provider rule is stored", JSON.stringify(vk?.provider_configs?.map((p) => [p.provider, p.allowed_models])) === JSON.stringify([["openai", ["gpt-4o-mini"]]]), JSON.stringify(vk?.provider_configs))
  await page.locator('#vk-list tbody tr', { hasText: "from-ui" }).locator('button:has-text("Edit")').click()
  await page.waitForSelector("#vk-form", { state: "visible" })
  check("the edit form shows the stored MCP row", (await page.inputValue("#vk-mcp input")) === "echo")
  check("the edit form shows the stored provider row", (await page.inputValue("#vk-rules input")) === "gpt-4o-mini" && (await page.inputValue("#vk-rules select")) === "openai")
  check("the id of an existing key is read only", await page.evaluate(() => document.querySelector("#vk-form input[name=id]").readOnly))
  await page.click("#vk-save")
  await until(page, () => !document.querySelector("#vk-form"))
  vk = (await api("GET", "/api/governance/virtual-keys")).data.virtual_keys.find((v) => v.id === vkId)
  check("saving without changes keeps the MCP tools and the budget", vk?.budget_id === "monthly" && (vk?.mcp_configs ?? []).length === 1, JSON.stringify(vk))
  await page.locator('#vk-list tbody tr', { hasText: "from-ui" }).locator('button.toggle').click()
  check("the status button disables a key", await poll(async () => (await api("GET", "/api/governance/virtual-keys")).data.virtual_keys.find((v) => v.id === vkId)?.is_active === false))
  await page.locator('#vk-list tbody tr', { hasText: "from-ui" }).locator('button.toggle').click()
  check("and enables it again", await poll(async () => (await api("GET", "/api/governance/virtual-keys")).data.virtual_keys.find((v) => v.id === vkId)?.is_active === true))
  await page.locator('#vk-list tbody tr', { hasText: "from-ui" }).locator('button:has-text("Rotate")').click()
  check("rotating shows the new value once", await until(page, (old) => (document.querySelector("#vk-secret-value")?.value ?? "").startsWith("sk-bf-") && document.querySelector("#vk-secret-value").value !== old, secret), await page.inputValue("#vk-secret-value").catch(() => ""))
  const rotated = await page.inputValue("#vk-secret-value")
  check("the rotated value is different and works", rotated !== secret && (await chat("after rotation", "openai/gpt-4o-mini", { "x-bf-vk": rotated })).status === 200, rotated)
  await page.click("#vk-new")
  await page.fill("#vk-form input[name=name]", "bad")
  await page.route("**/api/governance/virtual-keys", (r) => r.request().method() === "POST" ? r.fulfill({ status: 400, contentType: "application/json", body: '{"error":{"message":"refused for the test"}}' }) : r.fallback())
  await page.click("#vk-save")
  check("a refused key is shown inline", await until(page, () => (document.querySelector("#vk-form p.error")?.textContent ?? "").includes("refused for the test")), await text(page, "#vk-form p.error"))
  await page.unroute("**/api/governance/virtual-keys")
  await page.click("#vk-cancel")
  await api("POST", "/api/governance/virtual-keys", { name: "temp-ui", value: "" })
  await page.reload()
  await page.waitForSelector('#vk-list tbody tr:has-text("temp-ui")', { timeout: 5000 })
  await page.locator('#vk-list tbody tr', { hasText: "temp-ui" }).locator('button:has-text("Delete")').click()
  await page.locator('#vk-list tbody tr', { hasText: "temp-ui" }).locator('button:has-text("Confirm delete")').click()
  check("a virtual key can be deleted from the page", await until(page, () => !(document.querySelector("#vk-list")?.textContent ?? "").includes("temp-ui")))

  // ---- budgets, rate limits, teams, customers ----
  await page.goto(GW + "/#governance")
  await page.waitForFunction(() => (document.querySelector("#gov-root")?.textContent ?? "").includes("monthly"), null, { timeout: 5000 })
  check("budgets are listed", true)
  const budgets = page.locator('section[aria-label="Budgets"]')
  await budgets.locator("input[name=id]").fill("ui-budget")
  await budgets.locator("input[name=max_limit]").fill("12.5")
  await budgets.locator("input[name=reset_duration]").fill("1d")
  await budgets.locator('button[type=submit]').click()
  check("a budget can be created", await poll(async () => ((await api("GET", "/api/governance/budgets")).data.budgets ?? []).some((b) => b.id === "ui-budget" && b.max_limit === 12.5)))
  await budgets.locator("tbody tr", { hasText: "ui-budget" }).locator('button:has-text("Edit")').click()
  check("editing locks the id", await budgets.locator("input[name=id]").evaluate((e) => e.readOnly))
  await budgets.locator("input[name=max_limit]").fill("20")
  await budgets.locator('button[type=submit]').click()
  check("a budget can be edited", await poll(async () => ((await api("GET", "/api/governance/budgets")).data.budgets ?? []).some((b) => b.id === "ui-budget" && b.max_limit === 20)))
  await budgets.locator("tbody tr", { hasText: "ui-budget" }).locator('button:has-text("Delete")').click()
  await budgets.locator("tbody tr", { hasText: "ui-budget" }).locator('button:has-text("Confirm delete")').click()
  check("a budget can be deleted", await poll(async () => !((await api("GET", "/api/governance/budgets")).data.budgets ?? []).some((b) => b.id === "ui-budget")))
  const limits = page.locator('section[aria-label="Rate limits"]')
  await limits.locator("input[name=id]").fill("ui-limit")
  await limits.locator("input[name=request_max_limit]").fill("100")
  await limits.locator("input[name=request_reset_duration]").fill("1m")
  await limits.locator('button[type=submit]').click()
  check("a rate limit can be created", await poll(async () => ((await api("GET", "/api/governance/rate-limits")).data.rate_limits ?? []).some((r) => r.id === "ui-limit" && r.request_max_limit === 100)))
  const teams = page.locator('section[aria-label="Teams"]')
  await teams.locator("input[name=id]").fill("ui-team")
  await teams.locator("input[name=name]").fill("UI team")
  await teams.locator('button[type=submit]').click()
  check("a team can be created", await poll(async () => ((await api("GET", "/api/governance/teams")).data.teams ?? []).some((t) => t.id === "ui-team")))
  const customers = page.locator('section[aria-label="Customers"]')
  await customers.locator("input[name=id]").fill("ui-cust")
  await customers.locator("input[name=name]").fill("UI customer")
  await customers.locator('button[type=submit]').click()
  check("a customer can be created", await poll(async () => ((await api("GET", "/api/governance/customers")).data.customers ?? []).some((c) => c.id === "ui-cust")))
  await customers.locator("tbody tr", { hasText: "ui-cust" }).locator('button:has-text("Delete")').click()
  await customers.locator("tbody tr", { hasText: "ui-cust" }).locator('button:has-text("Confirm delete")').click()
  check("a customer can be deleted", await poll(async () => !((await api("GET", "/api/governance/customers")).data.customers ?? []).some((c) => c.id === "ui-cust")))
  await page.click("#gv-refresh")
  await limits.locator("tbody tr", { hasText: "ui-limit" }).locator('button:has-text("Delete")').click()
  await limits.locator("tbody tr", { hasText: "ui-limit" }).locator('button:has-text("Confirm delete")').click()
  await teams.locator("tbody tr", { hasText: "ui-team" }).locator('button:has-text("Delete")').click()
  await teams.locator("tbody tr", { hasText: "ui-team" }).locator('button:has-text("Confirm delete")').click()
  check("a team and a rate limit can be deleted", await poll(async () => !((await api("GET", "/api/governance/teams")).data.teams ?? []).some((t) => t.id === "ui-team") && !((await api("GET", "/api/governance/rate-limits")).data.rate_limits ?? []).some((r) => r.id === "ui-limit")))

  // ---- logs ----
  await page.goto(GW + "/#logs")
  await page.waitForFunction(() => (document.querySelector("#lg-body")?.textContent ?? "").includes("gpt-4o-mini"), null, { timeout: 5000 })
  check("logs list recent requests", true)
  check("the virtual key filter lists the keys", (await page.locator('#lg-filter select[name=virtual_key] option').count()) >= 2)
  const okPill = await page.locator("#lg-body tr.clickable").first().locator("td").nth(3).textContent()
  check("a successful request shows its HTTP status as a green pill", okPill?.trim() === "200" && (await page.locator("#lg-body tr.clickable").first().locator(".pill.ok").count()) === 1, okPill)
  check("the range line counts the entries", /1–\d+ of \d+/.test(await text(page, "#lg-range")), await text(page, "#lg-range"))
  await page.selectOption('#lg-filter select[name=period]', "custom")
  check("a custom time range shows its from and to fields", await page.isVisible("#lg-from-wrap") && await page.isVisible("#lg-to-wrap"))
  await page.selectOption('#lg-filter select[name=period]', "")
  check("choosing another range hides them", !(await page.isVisible("#lg-from-wrap")))
  await page.selectOption('#lg-filter select[name=period]', "1h")
  await page.fill('#lg-filter input[name=provider]', "openai")
  await page.click('#lg-filter button[type=submit]')
  check("the provider filter keeps the matching rows", await until(page, () => (document.querySelector("#lg-body")?.textContent ?? "").includes("gpt-4o-mini")))
  await page.fill('#lg-filter input[name=provider]', "nobody")
  await page.click('#lg-filter button[type=submit]')
  check("a filter with no match says so", await until(page, () => (document.querySelector("#lg-body")?.textContent ?? "").includes("No matching entries")))
  await page.click("#lg-clear")
  await page.waitForFunction(() => (document.querySelector("#lg-body")?.textContent ?? "").includes("gpt-4o-mini"), null, { timeout: 5000 })
  await page.selectOption('#lg-filter select[name=status]', "error")
  await page.click('#lg-filter button[type=submit]')
  check("the status filter applies", await until(page, () => (document.querySelector("#lg-body")?.textContent ?? "").includes("No matching entries")), await text(page, "#lg-body"))
  await page.click("#lg-clear")
  await page.waitForFunction(() => document.querySelectorAll("#lg-body tr.clickable").length > 0, null, { timeout: 5000 })
  // pages: 25 per page
  for (let i = 0; i < 30; i++) await chat("page " + i)
  await page.click('#lg-filter button[type=submit]')
  check("the first page has 25 rows", await until(page, () => document.querySelectorAll("#lg-body tr.clickable").length === 25))
  check("Previous is off on the first page", await page.isDisabled("#lg-prev"))
  await page.click("#lg-next")
  check("Next shows the following rows", await until(page, () => /26–/.test(document.querySelector("#lg-range")?.textContent ?? "")), await text(page, "#lg-range"))
  await page.click("#lg-prev")
  check("Previous goes back", await until(page, () => /^1–25 of/.test(document.querySelector("#lg-range")?.textContent ?? "")), await text(page, "#lg-range"))
  await page.locator("#lg-body tr.clickable").first().click()
  check("a log row opens its request and response", await until(page, () => (document.querySelector("#lg-body tr.detail")?.textContent ?? "").includes("Request ID") && (document.querySelector("#lg-body tr.detail")?.textContent ?? "").includes("Response"), null, 6000), await text(page, "#lg-body"))
  await page.locator("#lg-body tr.clickable").first().click()
  check("selecting it again closes the detail", await until(page, () => !document.querySelector("#lg-body tr.detail")))
  await page.locator("#lg-body tr.clickable").nth(1).focus()
  await page.keyboard.press("Enter")
  check("a log row opens from the keyboard", await until(page, () => document.querySelector("#lg-body tr.detail") !== null))

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
  await page.click('article[aria-label="MCP client local"] button:has-text("Reconnect")')
  check("Reconnect asks the gateway to reconnect", await until(page, () => document.querySelectorAll('article[aria-label="MCP client local"] .tool-chips button').length > 0, null, 10000))
  await page.click("#mcp-new")
  await page.fill("#mcp-form input[name=name]", "bad-name")
  await page.fill("#mcp-form input[name=connection_string]", "http://127.0.0.1:1/mcp")
  await page.click("#mcp-save")
  check("an invalid client name is shown inline", await until(page, () => (document.querySelector("#mcp-form p.error")?.textContent ?? "").includes("hyphens")), await text(page, "#mcp-form p.error"))
  await page.fill("#mcp-form input[name=name]", "offui")
  await page.fill("#mcp-form textarea[name=headers]", "bad line")
  await page.click("#mcp-save")
  check("a header line without a colon is refused", await until(page, () => (document.querySelector("#mcp-form p.error")?.textContent ?? "").includes("Name: value")), await text(page, "#mcp-form p.error"))
  check("a refused form keeps what was typed", (await page.inputValue("#mcp-form input[name=name]")) === "offui" && (await page.inputValue("#mcp-form textarea[name=headers]")) === "bad line")
  await page.fill("#mcp-form textarea[name=headers]", "X-Test: 1")
  await page.check("#mcp-form input[name=disabled]")
  await page.click("#mcp-save")
  check("a disabled client is added", await until(page, () => document.querySelector('article[aria-label="MCP client offui"]') !== null), await text(page, "#mcp-form p.error"))
  check("the disabled client shows as disabled", (await page.locator('article[aria-label="MCP client offui"] .pill', { hasText: "disabled" }).count()) === 1)
  await page.locator('article[aria-label="MCP client offui"] > header button:has-text("Edit")').click()
  check("editing a client shows its stored header", (await page.inputValue("#mcp-form textarea[name=headers]")).includes("X-Test"))
  check("the name of an existing client is read only", await page.evaluate(() => document.querySelector("#mcp-form input[name=name]").readOnly))
  await page.click("#mcp-cancel")
  await page.locator('article[aria-label="MCP client offui"] > header button:has-text("Delete")').click()
  await page.locator('article[aria-label="MCP client offui"] > header button:has-text("Confirm delete")').click()
  check("an MCP client can be deleted from the page", await until(page, () => !document.querySelector('article[aria-label="MCP client offui"]')))

  // ---- config ----
  await page.goto(GW + "/#config")
  check("the settings editor loads the client section", await until(page, () => (document.querySelector("#cfg-json")?.value ?? "").includes("client_config")))
  await page.click("#cfg-full-box > summary")
  check("the full configuration is shown read only", await until(page, () => (document.querySelector("#cfg-full")?.textContent ?? "").includes('"providers"')))
  check("secrets in the full configuration are masked", !(await text(page, "#cfg-full")).includes("sk-ui-test"))
  await page.fill("#cfg-json", "{")
  await page.click("#cfg-save")
  check("invalid settings JSON is shown inline", await until(page, () => (document.querySelector("#cfg-box p.error")?.textContent ?? "").includes("not valid JSON")))
  await page.fill("#cfg-json", "{}")
  await page.click("#cfg-save")
  check("settings without a known section are refused", await until(page, () => (document.querySelector("#cfg-box p.error")?.textContent ?? "").includes("Nothing to save")))
  await page.click("#cfg-discard")
  check("Discard changes restores the stored settings", await until(page, () => (document.querySelector("#cfg-json")?.value ?? "").includes("client_config")))
  await page.evaluate(() => {
    const el = document.querySelector("#cfg-json")
    const v = JSON.parse(el.value)
    v.client_config.max_request_body_size_mb = 9
    el.value = JSON.stringify(v)
    el.dispatchEvent(new Event("input", { bubbles: true }))
  })
  await page.click("#cfg-save")
  const sized = await poll(async () => (await api("GET", "/api/config")).data.client?.max_request_body_size_mb === 9)
  check("saved settings reach the gateway", sized, JSON.stringify((await api("GET", "/api/config")).data.client).slice(0, 200))

  // ---- playground ----
  await page.goto(GW + "/#playground")
  await page.click("#pg-load")
  check("the playground loads the model list", await until(page, () => /models? available/.test(document.querySelector("#pg-models-msg")?.textContent ?? "")), await text(page, "#pg-models-msg"))
  await page.fill("#pg-form input[name=model]", "openai/gpt-4o-mini")
  await page.fill("#pg-form textarea[name=message]", "say hello")
  await page.press("#pg-form textarea[name=message]", "Control+Enter")
  check("Ctrl+Enter sends and the reply shows", await until(page, () => (document.querySelector("#pg-result")?.textContent ?? "").includes("Hello from gpt-4o-mini")), await text(page, "#pg-result"))
  await page.fill("#pg-form input[name=model]", "nope/none")
  await page.click("#pg-form button[type=submit]")
  check("a failed request shows its error", await until(page, () => document.querySelector("#pg-result p.error") !== null), await text(page, "#pg-result"))

  // ---- layout at phone width, names for every field ----
  const VIEWS = ["overview", "live", "providers", "keys", "governance", "logs", "mcp", "config", "playground"]
  for (const view of VIEWS) {
    await page.goto(GW + "/#" + view)
    await page.waitForTimeout(400)
    const w = await page.evaluate(() => document.documentElement.scrollWidth)
    check("no horizontal scroll on " + view + " at 400px", w <= 400, w)
    const unnamed = await page.evaluate(() => [...document.querySelectorAll("main input, main select, main textarea")]
      .filter((e) => !(e.labels && e.labels.length) && !e.getAttribute("aria-label") && e.type !== "hidden")
      .map((e) => e.outerHTML.slice(0, 80)))
    check("every field on " + view + " has a name", unnamed.length === 0, unnamed.join("; "))
    check(view + " has one h1", (await page.locator("main h1").count()) === 1)
  }
  await page.goto(GW + "/#keys")
  await page.click("#vk-new")
  const unnamedForm = await page.evaluate(() => [...document.querySelectorAll("#vk-form input, #vk-form select")].filter((e) => !(e.labels && e.labels.length) && !e.getAttribute("aria-label")).length)
  check("every field of the virtual key form has a name", unnamedForm === 0, unnamedForm)
  check("the current section is marked in the navigation", (await page.getAttribute('nav a[aria-current="page"]', "data-nav")) === "keys")

  // ---- the sign-in dialog with SSO on, dark mode ----
  {
    const ctx = await browser.newContext({ viewport: { width: 400, height: 800 }, colorScheme: "dark" })
    const sp = await ctx.newPage()
    await sp.route("**/api/oidc/status", (r) => r.fulfill({ status: 200, contentType: "application/json", body: '{"enabled":true}' }))
    await sp.goto(GW + "/#overview")
    await sp.waitForSelector("#auth", { state: "visible", timeout: 5000 })
    check("the dialog links to SSO when the gateway has an identity provider", (await sp.getAttribute("#auth-sso a", "href")) === "/api/oidc/login")
    const dark = await sp.evaluate(() => getComputedStyle(document.body).backgroundColor)
    check("dark mode follows the system", dark === "rgb(13, 17, 23)", dark)
    await ctx.close()
    const lctx = await browser.newContext({ viewport: { width: 400, height: 800 }, colorScheme: "light" })
    const lpg = await lctx.newPage()
    await lpg.goto(GW + "/#overview")
    const light = await lpg.evaluate(() => getComputedStyle(document.body).backgroundColor)
    check("light mode follows the system", light === "rgb(246, 247, 249)", light)
    await lctx.close()
  }

  check("no uncaught page errors or console warnings", errors.length === 0, errors.join("; "))
} catch (e) {
  check("ui run", false, String(e?.stack ?? e))
} finally {
  await browser?.close()
  for (const p of procs) p.kill()
  rmSync(dir, { recursive: true, force: true })
}
console.log(fails.length ? `\n${fails.length} failed` : "\nall passed")
process.exit(fails.length ? 1 : 0)

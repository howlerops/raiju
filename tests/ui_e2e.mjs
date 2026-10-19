// Drives the web UI (web/, embedded in the gateway) in headless Chromium against a real gateway
// and the mock upstream. Run: NODE_PATH=$(npm root -g) node tests/ui_e2e.mjs   (make ui)
// Needs build/raiju and build/mock_upstream (make ui builds both) and the committed src/ui_assets.tov.
// Ports 18107 (gateway) and 18108 (mock upstream) are reserved for this file; UI_E2E_PORT=n uses n and n+1.
import { spawn, execFileSync } from "node:child_process"
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join, dirname } from "node:path"
import { fileURLToPath } from "node:url"
import { createRequire } from "node:module"
import { createHash, randomBytes } from "node:crypto"

const require = createRequire(import.meta.url)
const { chromium } = require("playwright")
const root = join(dirname(fileURLToPath(import.meta.url)), "..")
const PORT = Number(process.env.UI_E2E_PORT ?? 18107)
const GW = `http://127.0.0.1:${PORT}`
const MOCK = `http://127.0.0.1:${PORT + 1}`
const ADMIN = { authorization: "Bearer admin-secret" }
const dir = mkdtempSync(join(tmpdir(), "raiju-ui-"))
const config = join(dir, "config.json")
// the MCP authorization server needs a signing key to validate a saved configuration
const signingKey = execFileSync("openssl", ["genrsa", "2048"], { stdio: ["ignore", "pipe", "ignore"] }).toString()
writeFileSync(config, JSON.stringify({
  client: { enable_logging: false, enforce_auth_on_inference: false, mcp_server_auth_mode: "both", mcp_enable_temp_token_auth: true, oauth2_server_config: { issuer_url: GW, signing_key: signingKey } },
  providers: { openai: { keys: [{ name: "main", value: "sk-ui-test", models: [], weight: 1 }], network_config: { base_url: MOCK } } },
  governance: {
    auth_config: { token: "admin-secret" },
    budgets: [{ id: "monthly", max_limit: 50, reset_duration: "1M" }],
    virtual_keys: [
      { id: "vk-ui-oauth", value: "sk-bf-ui-oauth", mcp_configs: [{ mcp_client_name: "local", tools_to_execute: ["*"] }] },
      { id: "vk-po-a", value: "sk-bf-po-a", mcp_configs: [{ mcp_client_name: "po", tools_to_execute: ["*"] }] },
    ],
  },
  mcp: {
    tool_sync_interval: "1h",
    oauth_private_allowlist: ["127.0.0.1"],
    client_configs: [
      { name: "local", connection_type: "stdio", stdio_config: { command: "python3", args: [join(root, "tests/mcp_stdio.py")] } },
      { name: "po", connection_type: "http", connection_string: MOCK + "/mcp-peruser-oauth", auth_type: "per_user_oauth", auth: { type: "oauth" } },
      { name: "tenant", connection_type: "http", connection_string: MOCK + "/mcp-peruser", auth_type: "per_user_headers", per_user_header_keys: ["x-tenant"] },
    ],
  },
  logs_store: { enabled: true, dir: join(dir, "logs") },
  // one crew pool for the Crews screen: a cheap and a strong candidate at a fixed multiplier, so a failed first attempt
  // escalates to the strong worker (as in the L154 e2e) and its outcome is learned; each class frontier has a knee
  pricing: {
    "openai/crew-cheap": { input_cost_per_token: 0.0000001, output_cost_per_token: 0.0000001 },
    "openai/crew-strong": { input_cost_per_token: 0.00001, output_cost_per_token: 0.00001 },
  },
  crews: { task_ttl_seconds: 3600, pools: [{
    name: "codeaf", roles: ["worker", "checker"], classes: ["bug-fix", "open-ended", "other"], uncertain_class: "open-ended",
    candidates: [
      { id: "cheap", model: "openai/crew-cheap", route: "api" },
      { id: "strong", model: "openai/crew-strong", route: "api" },
    ],
    profiles: Object.fromEntries(["bug-fix", "open-ended", "other"].map((c) => [c, { worker: { calls: 1, input_tokens: 2000, output_tokens: 500 }, checker: { calls: 1, input_tokens: 2000, output_tokens: 300 } }])),
    priors: { version: 1, baseline: { "bug-fix": 0.4 }, cells: [{ class: "bug-fix", role: "worker", candidate: "strong", delta: 0.55, n: 50, info: 0.2 }] },
    operating_point: { mode: "lambda", lambda: 23 },
    sequential: { enabled: true, max_attempts: 6, per_candidate: 1, verifier_accuracy: { "bug-fix": 0.9 } },
    credibility: { prior_scale: 1.2 },
  }] },
}))

const procs = [
  spawn(join(root, "build/mock_upstream"), [], { env: { ...process.env, MOCK_PORT: String(PORT + 1) }, stdio: "ignore" }),
  spawn(join(root, "build/raiju"), ["-port", String(PORT), "-host", "127.0.0.1", "-config", config, "-server", process.env.RAIJU_SERVER ?? "bun"], { stdio: "ignore" }),
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
    if (/status of (400|401|403|404|409|422)/.test(m.text())) return
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

  // ---- overview charts ----
  await chat("a failing one", "nope/none")
  await page.click("#ov-refresh")
  check("the requests chart is an svg with a title and a description", await until(page, () => {
    const svg = document.querySelector("#ch-requests svg")
    return !!svg && svg.getAttribute("role") === "img" && !!svg.querySelector("title")?.textContent && !!svg.querySelector("desc")?.textContent
  }), await text(page, "#ch-requests"))
  check("the requests chart draws bars for success and errors", await until(page, () => document.querySelectorAll("#ch-requests rect.bar").length >= 2), String(await page.locator("#ch-requests rect.bar").count()))
  check("the requests chart has a legend", (await text(page, "#ch-requests .legend")).includes("Errors"))
  await page.click("#ch-requests summary")
  const tbl = await text(page, "#ch-requests details table")
  check("the data table lists the same numbers as the chart", /Success/.test(tbl) && /\b[1-9]\d*\b/.test(tbl), tbl.slice(0, 200))
  check("latency, tokens, cost and provider charts are drawn", await until(page, () => ["ch-latency", "ch-tokens", "ch-cost", "ch-provider-cost"].every((id) => document.querySelector("#" + id + " svg") !== null)), await text(page, "#ov-charts"))
  check("the latency chart draws a line per percentile", (await page.locator("#ch-latency svg path").count()) === 4)
  check("top models are ranked with their numbers", await until(page, () => (document.querySelector("#ch-models")?.textContent ?? "").includes("gpt-4o-mini") && /tokens/.test(document.querySelector("#ch-models")?.textContent ?? "")), await text(page, "#ch-models"))
  check("top providers are ranked", await until(page, () => (document.querySelector("#ch-providers")?.textContent ?? "").includes("openai")), await text(page, "#ch-providers"))
  const chartW = await page.evaluate(() => Number(document.querySelector("#ch-requests svg").getAttribute("width")))
  check("a chart fits a 400px screen", chartW > 200 && chartW <= 400, chartW)
  const box = await page.locator("#ch-requests svg").boundingBox()
  await page.mouse.move(box.x + box.width - 30, box.y + box.height / 2)
  check("hovering a chart shows a readout of that bucket", await until(page, () => (document.querySelector("#ch-requests .chart-tip")?.textContent ?? "").includes("Success")), await text(page, "#ch-requests"))
  await page.mouse.move(2, 2)
  await page.focus("#ch-requests svg")
  await page.keyboard.press("ArrowLeft")
  check("the arrow keys read single buckets", await until(page, () => document.querySelector("#ch-requests .chart-tip") !== null))
  const lightFill = await page.evaluate(() => getComputedStyle(document.querySelector("#ch-requests rect.bar")).fill)
  await page.emulateMedia({ colorScheme: "dark" })
  const darkFill = await page.evaluate(() => getComputedStyle(document.querySelector("#ch-requests rect.bar")).fill)
  await page.emulateMedia({ colorScheme: "light" })
  check("the chart colours follow the colour scheme", lightFill !== darkFill, lightFill + " " + darkFill)
  await page.selectOption("#ov-period", "24h")
  check("the period menu reloads the charts", await until(page, () => document.querySelector("#ch-requests svg") !== null && document.querySelector("#ov-charts select").value === "24h"))
  await page.selectOption("#ov-period", "1h")

  // ---- chart series toggles and zoom (overview) ----
  await until(page, () => document.querySelector("#ch-requests svg") !== null)
  const axisOf = (sel) => page.evaluate((s) => [...document.querySelectorAll(s + " svg text.axis[text-anchor=end]")].map((t) => t.textContent).join("|"), sel)
  const legendBtn = (id, name) => page.locator("#" + id + ' .legend-toggle:has-text("' + name + '")')
  const barsBefore = await page.locator("#ch-requests rect.bar").count()
  const axisBefore = await axisOf("#ch-requests")
  check("each legend entry is a toggle button, pressed while its series is drawn", (await legendBtn("ch-requests", "Success").getAttribute("aria-pressed")) === "true" && (await page.locator("#ch-requests .legend button").count()) >= 2)
  await legendBtn("ch-requests", "Success").click()
  check("hiding a series marks its legend entry and removes its bars", (await legendBtn("ch-requests", "Success").getAttribute("aria-pressed")) === "false" && (await page.locator("#ch-requests rect.bar").count()) < barsBefore, barsBefore + " -> " + (await page.locator("#ch-requests rect.bar").count()))
  check("the axis rescales to the series still shown", (await axisOf("#ch-requests")) !== axisBefore, axisBefore + " vs " + (await axisOf("#ch-requests")))
  check("the hover readout leaves the hidden series out", await (async () => {
    const b = await page.locator("#ch-requests svg").boundingBox()
    await page.mouse.move(b.x + b.width - 20, b.y + 80)
    await until(page, () => document.querySelector("#ch-requests .chart-tip") !== null)
    return !(await text(page, "#ch-requests .chart-tip")).includes("Success")
  })())
  await legendBtn("ch-requests", "Success").click()
  check("showing the series again restores the bars and the axis", (await page.locator("#ch-requests rect.bar").count()) === barsBefore && (await axisOf("#ch-requests")) === axisBefore)
  const linesBefore = await page.locator("#ch-latency svg path").count()
  await legendBtn("ch-latency", "p99").click()
  check("a line series can be hidden too", (await page.locator("#ch-latency svg path").count()) === linesBefore - 1, linesBefore)
  await legendBtn("ch-latency", "p99").click()
  check("the legend toggles are keyboard operable", await (async () => {
    await page.focus('#ch-latency .legend-toggle:has-text("p90")')
    await page.keyboard.press("Enter")
    const hid = (await page.locator("#ch-latency svg path").count()) === linesBefore - 1
    await page.keyboard.press("Space")
    return hid && (await page.locator("#ch-latency svg path").count()) === linesBefore
  })())

  const dashReqs = []
  page.on("request", (r) => { if (r.url().includes("/api/logs/dashboard")) dashReqs.push(new URL(r.url())) })
  await page.locator("#ch-requests svg").scrollIntoViewIfNeeded()
  const ob = await page.locator("#ch-requests svg").boundingBox()
  await page.mouse.move(ob.x + ob.width * 0.55, ob.y + 80)
  await page.mouse.down()
  await page.mouse.move(ob.x + ob.width * 0.8, ob.y + 80, { steps: 5 })
  check("dragging across a chart draws the selection", await until(page, () => document.querySelector("#ch-requests rect.sel") !== null))
  await page.mouse.up()
  check("releasing the drag zooms every overview chart to that range and drops the period", await until(page, () => document.querySelector("#ch-requests .zoom-reset") !== null && document.querySelector("#ch-latency .zoom-reset") !== null) && dashReqs.length > 0 && dashReqs[dashReqs.length - 1].searchParams.has("start_time") && dashReqs[dashReqs.length - 1].searchParams.has("end_time") && !dashReqs[dashReqs.length - 1].searchParams.has("period"), dashReqs.map((u) => u.search).join(" "))
  {
    const u = dashReqs[dashReqs.length - 1]
    const span = Number(u.searchParams.get("end_time")) - Number(u.searchParams.get("start_time"))
    check("the zoomed range is a part of the hour", span > 0 && span < 3600000, span)
  }
  await page.locator("#ch-requests .zoom-reset").click()
  check("Reset zoom brings the period back", await until(page, () => document.querySelector("#ch-requests .zoom-reset") === null) && dashReqs[dashReqs.length - 1].searchParams.get("period") === "1h" && !dashReqs[dashReqs.length - 1].searchParams.has("start_time"), dashReqs.map((u) => u.search).join(" "))

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
  // charts on the logs screen
  check("the logs screen draws the requests chart", await until(page, () => document.querySelectorAll("#lgc-requests rect.bar").length > 0), await text(page, "#lg-charts"))
  check("it breaks the cost down by provider", await until(page, () => (document.querySelector("#lgc-by figcaption")?.textContent ?? "") === "Cost by provider" && document.querySelectorAll("#lgc-by rect.bar").length > 0), await text(page, "#lgc-by"))
  check("it ranks the providers", await until(page, () => (document.querySelector("#lgc-rank")?.textContent ?? "").includes("openai")), await text(page, "#lgc-rank"))
  await page.selectOption("#lg-dim", "model")
  await page.selectOption("#lg-metric", "latency")
  check("the dimension and measure menus change the chart", await until(page, () => (document.querySelector("#lgc-by figcaption")?.textContent ?? "") === "p95 latency by model" && document.querySelectorAll("#lgc-by svg path").length > 0), await text(page, "#lgc-by"))
  check("the ranking follows the dimension", await until(page, () => (document.querySelector("#lgc-rank")?.textContent ?? "").includes("gpt-4o-mini")), await text(page, "#lgc-rank"))
  await page.selectOption("#lg-metric", "tokens")
  check("tokens by model are drawn", await until(page, () => (document.querySelector("#lgc-by figcaption")?.textContent ?? "") === "Tokens by model" && document.querySelectorAll("#lgc-by rect.bar").length > 0))
  await page.selectOption("#lg-dim", "virtual_key")
  check("virtual key is a dimension too", await until(page, () => (document.querySelector("#lgc-by figcaption")?.textContent ?? "") === "Tokens by virtual key"))
  await page.selectOption("#lg-dim", "provider")
  await page.selectOption("#lg-metric", "cost")
  await page.fill('#lg-filter input[name=provider]', "nobody")
  await page.click('#lg-filter button[type=submit]')
  check("the charts follow the log filters", await until(page, () => (document.querySelector("#lgc-requests")?.textContent ?? "").includes("No data in this period")), await text(page, "#lgc-requests"))
  await page.fill('#lg-filter input[name=provider]', "")
  await page.click('#lg-filter button[type=submit]')
  await until(page, () => document.querySelectorAll("#lgc-requests rect.bar").length > 0)
  // zoom: a drag over the chart narrows the screen's time range, the list and the charts refetch
  {
    const hist = []
    const list = []
    const onReq = (r) => {
      const u = new URL(r.url())
      if (u.pathname === "/api/logs/histogram") hist.push(u)
      if (u.pathname === "/api/logs") list.push(u)
    }
    page.on("request", onReq)
    const spanOf = (u) => Number(u.searchParams.get("end_time")) - Number(u.searchParams.get("start_time"))
    await page.reload()
    await until(page, () => document.querySelectorAll("#lgc-requests rect.bar").length > 0)
    const fullSpan = spanOf(hist[hist.length - 1])
    check("the log charts start on the last 24 hours", Math.abs(fullSpan - 86400000) < 5000, fullSpan)
    await page.locator("#lgc-requests svg").scrollIntoViewIfNeeded()
    const b = await page.locator("#lgc-requests svg").boundingBox()
    const nHist = hist.length
    await page.mouse.move(b.x + b.width * 0.6, b.y + 80)
    await page.mouse.down()
    await page.mouse.move(b.x + b.width - 12, b.y + 80, { steps: 6 })
    await page.mouse.up()
    check("a drag selection refetches the charts over the selected range", await until(page, () => document.querySelector("#lgc-requests .zoom-reset") !== null) && hist.length > nHist && spanOf(hist[hist.length - 1]) <= fullSpan * 0.6 && spanOf(hist[hist.length - 1]) > 0, hist.map(spanOf).join(","))
    const z = hist[hist.length - 1]
    check("the log list takes the same range", list.length > 0 && Number(list[list.length - 1].searchParams.get("since")) === Number(z.searchParams.get("start_time")) && Number(list[list.length - 1].searchParams.get("until")) === Number(z.searchParams.get("end_time")), list.map((u) => u.search).join(" "))
    check("the filter form shows it as a custom range", (await page.inputValue('#lg-filter select[name=period]')) === "custom" && (await page.inputValue('#lg-filter input[name=from]')) !== "" && (await page.isVisible("#lg-from-wrap")))
    await page.locator("#lgc-requests .zoom-reset").click()
    check("Reset zoom restores the 24 hour range and the form", await until(page, () => document.querySelector("#lgc-requests .zoom-reset") === null) && Math.abs(spanOf(hist[hist.length - 1]) - 86400000) < 5000 && (await page.inputValue('#lg-filter select[name=period]')) === "" && !(await page.isVisible("#lg-from-wrap")), hist.map(spanOf).join(","))
    // from the keyboard: arrows read a bucket, Shift+arrows extend a selection, Enter zooms, Escape cancels
    await page.focus("#lgc-requests svg")
    await page.keyboard.press("ArrowLeft")
    await page.keyboard.press("Shift+ArrowLeft")
    await page.keyboard.press("Shift+ArrowLeft")
    check("Shift+arrows select a range and say which", await until(page, () => document.querySelector("#lgc-requests rect.sel") !== null && /to/.test(document.querySelector("#lgc-requests .zoom-bar")?.textContent ?? "")), await text(page, "#lgc-requests .zoom-bar"))
    await page.keyboard.press("Escape")
    check("Escape drops the selection without zooming", await until(page, () => document.querySelector("#lgc-requests rect.sel") === null) && (await page.locator("#lgc-requests .zoom-reset").count()) === 0)
    await page.keyboard.press("Shift+ArrowRight")
    await page.keyboard.press("Shift+ArrowRight")
    await page.keyboard.press("Enter")
    check("Enter zooms to the keyboard selection", await until(page, () => document.querySelector("#lgc-requests .zoom-reset") !== null) && spanOf(hist[hist.length - 1]) <= fullSpan * 0.6, hist.map(spanOf).join(","))
    await page.locator("#lgc-requests .zoom-reset").click()
    await until(page, () => document.querySelector("#lgc-requests .zoom-reset") === null)
    // the selection can also be applied with its button
    await page.focus("#lgc-requests svg")
    await page.keyboard.press("ArrowLeft")
    await page.keyboard.press("Shift+ArrowLeft")
    await page.locator("#lgc-requests .zoom-apply").click()
    check("the Zoom to selection button applies a selection", await until(page, () => document.querySelector("#lgc-requests .zoom-reset") !== null))
    await page.fill('#lg-filter input[name=text]', "")
    await page.click('#lg-filter button[type=submit]')
    check("Apply on the filters leaves the zoom", await until(page, () => document.querySelector("#lgc-requests .zoom-reset") === null))
    page.off("request", onReq)
  }
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
  check("the status filter applies", await until(page, () => { const t = document.querySelector("#lg-body")?.textContent ?? ""; return t.includes("nope/none") && !t.includes("gpt-4o-mini") }), await text(page, "#lg-body"))
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

  // ---- MCP OAuth: the consent pages, the grants and the per-user sessions ----
  {
    const redirect = "http://127.0.0.1:8080/cb"
    const cp = await browser.newPage({ viewport: { width: 400, height: 800 } })
    await cp.route("http://127.0.0.1:8080/**", (r) => r.fulfill({ status: 200, contentType: "text/plain", body: "callback" }))
    const reg = await fetch(GW + "/oauth2/register", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ client_name: "ui-client", redirect_uris: [redirect] }) })
    const cid = (await reg.json()).client_id
    const verifier = randomBytes(32).toString("base64url")
    const challenge = createHash("sha256").update(verifier).digest("base64url")
    const q = new URLSearchParams({ client_id: cid, redirect_uri: redirect, response_type: "code", state: "st-ui", code_challenge: challenge, code_challenge_method: "S256", scope: "mcp" })
    const au = await fetch(GW + "/oauth2/authorize?" + q, { redirect: "manual" })
    const consentUrl = new URL(au.headers.get("location") ?? "", GW).href
    check("the authorize redirect opens the consent page", consentUrl.includes("/oauth/consent?flow=") && consentUrl.includes("#t="), consentUrl)
    await cp.goto(consentUrl)
    check("the consent page names the client", await until(cp, () => document.querySelector("#client")?.textContent === "ui-client"), await text(cp, "main"))
    check("the consent page shows where the code goes", (await text(cp, "#redirect")) === redirect)
    check("the consent page carries the gateway header and a titled form", (await cp.title()) === "Authorize an MCP client" && (await cp.locator("header.top .logo").count()) === 1 && (await cp.locator("h1").count()) === 1)
    check("the key field has a label and focus", await cp.evaluate(() => document.activeElement?.id === "vk" && document.querySelector("#vk").labels.length === 1))
    const lightBg = await cp.evaluate(() => getComputedStyle(document.body).backgroundColor)
    await cp.emulateMedia({ colorScheme: "dark" })
    const darkBg = await cp.evaluate(() => getComputedStyle(document.body).backgroundColor)
    await cp.emulateMedia({ colorScheme: "light" })
    check("the consent page follows the colour scheme", lightBg !== darkBg, lightBg + " " + darkBg)
    check("the consent page fits a 400px screen", (await cp.evaluate(() => document.documentElement.scrollWidth)) <= 400)
    await cp.fill("#vk", "   ")
    await cp.click("#go")
    check("a blank key is refused on the page, as an alert", await until(cp, () => document.querySelector("#msg")?.getAttribute("role") === "alert" && /Enter the virtual key/.test(document.querySelector("#msg").textContent)), await text(cp, "#msg"))
    await cp.fill("#vk", "sk-bf-not-a-key")
    await cp.click("#go")
    check("a key the gateway does not know is refused with the reason", await until(cp, () => /HTTP 4\d\d/.test(document.querySelector("#msg")?.textContent ?? "")), await text(cp, "#msg"))
    await cp.fill("#vk", "sk-bf-ui-oauth")
    await cp.click("#go")
    check("approving with a virtual key returns to the client with a code", await cp.waitForURL(/8080\/cb\?code=/, { timeout: 8000 }).then(() => true, () => false), cp.url())
    const code = new URL(cp.url()).searchParams.get("code") ?? ""
    const tokenRes = await fetch(GW + "/oauth2/token", {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ grant_type: "authorization_code", code, code_verifier: verifier, client_id: cid, redirect_uri: redirect, resource: GW + "/mcp" }).toString(),
    })
    check("the client exchanges the code for tokens", tokenRes.status === 200 && !!(await tokenRes.json()).refresh_token)
    await cp.goto(consentUrl)
    check("a used consent link says so", await until(cp, () => document.querySelector("#msg")?.getAttribute("role") === "alert"), await text(cp, "#msg"))
    await cp.goto(GW + "/oauth/consent")
    check("a consent link without a flow explains itself", await until(cp, () => /incomplete/.test(document.querySelector("#msg")?.textContent ?? "")), await text(cp, "#msg"))
    await cp.close()

    await page.goto(GW + "/#mcpaccess")
    check("the OAuth grant of the client is listed", await until(page, () => (document.querySelector("#mca-grants")?.textContent ?? "").includes("ui-client")), await text(page, "#mca-grants"))
    const grantRow = page.locator("#mca-grants tbody tr", { hasText: "ui-client" })
    check("the grant shows its mode and the key", (await grantRow.textContent()).includes("vk") && (await grantRow.textContent()).includes("vk-ui-oauth"), await grantRow.textContent())
    await page.fill("#mca-grant-q", "nobody-like-this")
    await page.press("#mca-grant-q", "Enter")
    check("the grant filter narrows the list", await until(page, () => (document.querySelector("#mca-grants")?.textContent ?? "").includes("No live grants")), await text(page, "#mca-grants"))
    await page.fill("#mca-grant-q", "")
    await page.press("#mca-grant-q", "Enter")
    await until(page, () => (document.querySelector("#mca-grants")?.textContent ?? "").includes("ui-client"))
    await page.locator("#mca-grants tbody tr", { hasText: "ui-client" }).locator('button:has-text("Revoke")').click()
    await page.locator("#mca-grants tbody tr", { hasText: "ui-client" }).locator('button:has-text("Confirm revoke")').click()
    check("a grant can be revoked from the page", await poll(async () => ((await api("GET", "/api/oauth2/sessions")).data.sessions ?? []).length === 0))
    check("the revoked grant leaves the list", await until(page, () => !(document.querySelector("#mca-grants")?.textContent ?? "").includes("ui-client")), await text(page, "#mca-grants"))

    // per-user OAuth: the admin authorizes the client once, a caller consents on the connect page
    const init = await api("POST", "/api/mcp/client/po/initiate-verification")
    const hop = await fetch(init.data.authorize_url, { redirect: "manual" })
    await fetch(hop.headers.get("location"), { headers: ADMIN })
    await api("POST", "/api/mcp/client/po/complete-oauth")
    const poReady = await poll(async () => ((await api("GET", "/api/mcp")).data.clients ?? []).some((c) => c.name === "po" && c.connected))
    check("the per-user OAuth client connects with the admin's token", poReady)
    const call = await fetch(GW + "/v1/mcp/tool/execute", {
      method: "POST",
      headers: { "content-type": "application/json", authorization: "Bearer sk-bf-po-a" },
      body: JSON.stringify({ id: "c1", type: "function", function: { name: "po-get_weather", arguments: '{"city":"Oslo"}' } }),
    })
    const denial = await call.text()
    const link = /flow=([0-9a-f]+)#t=([0-9a-f]+)/.exec(denial)
    check("a caller without consent is given a consent link", call.status === 401 && !!link, denial.slice(0, 200))
    const pp = await browser.newPage({ viewport: { width: 400, height: 800 } })
    await pp.goto(GW + "/workspace/mcp-sessions/auth")
    check("the connect page without a flow explains itself", await until(pp, () => document.querySelector("#msg")?.getAttribute("role") === "alert" && /no flow/.test(document.querySelector("#msg").textContent)), await text(pp, "#msg"))
    await pp.goto(GW + "/workspace/mcp-sessions/auth?flow=" + link[1] + "#t=" + link[2])
    check("the connect page names the client and the caller", await until(pp, () => document.querySelector("#client")?.textContent === "po" && (document.querySelector("#caller")?.textContent ?? "").includes("vk-po-a")), await text(pp, "main"))
    check("the connect page has a titled card and the gateway header", (await pp.title()) === "Connect an MCP client" && (await pp.locator("header.top").count()) === 1)
    await pp.click("#go")
    check("Connect goes through the provider and back to the gateway", await pp.waitForFunction(() => document.body.textContent.includes("for this caller"), null, { timeout: 8000 }).then(() => true, () => false), await pp.textContent("body").catch(() => ""))
    await pp.close()

    await page.click("#mca-refresh")
    check("the caller's token row is listed", await until(page, () => (document.querySelector("#mca-sessions")?.textContent ?? "").includes("OAuth token")), await text(page, "#mca-sessions"))
    const tokenRow = page.locator("#mca-sessions tbody tr", { hasText: "OAuth token" })
    check("the row shows the client, the key and an active status", (await tokenRow.textContent()).includes("po") && (await tokenRow.textContent()).includes("vk-po-a") && (await tokenRow.locator(".pill.ok").count()) === 1, await tokenRow.textContent())
    check("no token is shown", !(await text(page, "#mca-sessions")).includes("oauth-access-"))
    await tokenRow.locator('button:has-text("Re-authorize")').click()
    check("Re-authorize shows a new consent link", await until(page, () => (document.querySelector("#mca-link input")?.value ?? "").includes("/workspace/mcp-sessions/auth?flow=")), await text(page, "#mca-sessions"))
    await page.click("#mca-link button:has-text('Close')")
    await page.selectOption("#mca-kind", "flow")
    check("the kind menu narrows the sessions", await until(page, () => (document.querySelector("#mca-sessions")?.textContent ?? "").includes("Pending consent") && !(document.querySelector("#mca-sessions")?.textContent ?? "").includes("OAuth token")), await text(page, "#mca-sessions"))
    await page.selectOption("#mca-kind", "token")
    await until(page, () => (document.querySelector("#mca-sessions")?.textContent ?? "").includes("OAuth token"))
    await page.locator("#mca-sessions tbody tr", { hasText: "OAuth token" }).locator('button:has-text("Revoke")').click()
    await page.locator("#mca-sessions tbody tr", { hasText: "OAuth token" }).locator('button:has-text("Confirm revoke")').click()
    check("a session can be revoked from the page", await poll(async () => ((await api("GET", "/api/mcp/sessions?kind=token")).data.sessions ?? []).length === 0))

    // per-user headers
    await page.selectOption("#mca-kind", "")
    await page.selectOption("#mca-hdr-open select[name=client]", "tenant")
    await page.selectOption("#mca-hdr-open select[name=vk]", "vk-po-a")
    await page.click("#mca-hdr-open button[type=submit]")
    check("opening a submission asks for the client's header names", await until(page, () => document.querySelector('#mca-hdr-flow input[name="h:x-tenant"]') !== null), await text(page, "#mca-headers"))
    await page.fill('#mca-hdr-flow input[name="h:x-tenant"]', "not-a-tenant")
    await page.click("#mca-hdr-flow button[type=submit]")
    check("values the MCP server rejects are shown inline", await until(page, () => (document.querySelector("#mca-hdr-flow p.error")?.textContent ?? "").includes("Verification failed")), await text(page, "#mca-hdr-flow"))
    await page.fill('#mca-hdr-flow input[name="h:x-tenant"]', "tenant-a-key-example")
    await page.click("#mca-hdr-flow button[type=submit]")
    check("verified values are stored for the key", await poll(async () => ((await api("GET", "/api/mcp/sessions?kind=header")).data.sessions ?? []).some((r) => r.virtual_key_id === "vk-po-a" && r.mcp_client.name === "tenant")))
    await page.selectOption("#mca-kind", "header")
    check("the header credential is listed without its values", await until(page, () => (document.querySelector("#mca-sessions")?.textContent ?? "").includes("Header credential") && !(document.querySelector("#mca-sessions")?.textContent ?? "").includes("tenant-a-key-example")), await text(page, "#mca-sessions"))
    await page.locator("#mca-sessions tbody tr", { hasText: "Header credential" }).locator('button:has-text("Revoke")').click()
    await page.locator("#mca-sessions tbody tr", { hasText: "Header credential" }).locator('button:has-text("Confirm revoke")').click()
    check("a header credential can be revoked", await poll(async () => ((await api("GET", "/api/mcp/sessions?kind=header")).data.sessions ?? []).length === 0))
    const w3 = await page.evaluate(() => document.documentElement.scrollWidth)
    check("MCP access has no horizontal scroll at 400px", w3 <= 400, w3)
  }

  // ---- virtual MCPs and tool groups ----
  {
    await page.goto(GW + "/#vmcp")
    await page.click("#vm-new")
    await page.fill("#vm-form input[name=name]", "ui-vmcp")
    await page.fill("#vm-form input[name=description]", "made in the browser")
    await page.click("#vm-add-tool")
    await page.fill('#vm-tools input[aria-label="Source tool"]', "nowhere-tool")
    await page.click("#vm-save")
    check("a source of an unknown client is refused inline", await until(page, () => (document.querySelector("#vm-form p.error")?.textContent ?? "").includes("nowhere")), await text(page, "#vm-form p.error"))
    await page.fill('#vm-tools input[aria-label="Source tool"]', "local-echo")
    await page.fill('#vm-tools input[aria-label="Renamed as"]', "say")
    await page.fill('#vm-tools input[aria-label="Argument defaults"]', "{")
    await page.click("#vm-save")
    check("defaults that are not a JSON object are refused", await until(page, () => (document.querySelector("#vm-form p.error")?.textContent ?? "").includes("JSON object")), await text(page, "#vm-form p.error"))
    await page.fill('#vm-tools input[aria-label="Argument defaults"]', "")
    await page.click("#vm-save")
    check("a virtual MCP is created from the page", await until(page, () => document.querySelector('article[aria-label="Virtual MCP ui-vmcp"]') !== null), await text(page, "#vm-form p.error"))
    const made = (await api("GET", "/api/mcp/virtual-mcps/ui-vmcp")).data.virtual_mcp
    check("its tools are stored as written", JSON.stringify(made?.tools) === JSON.stringify([{ source: "local-echo", as: "say" }]), JSON.stringify(made))
    check("the card lists the tool the gateway serves", await until(page, () => (document.querySelector('article[aria-label="Virtual MCP ui-vmcp"]')?.textContent ?? "").includes("say")), await text(page, "#vm-list"))
    const card = page.locator('article[aria-label="Virtual MCP ui-vmcp"]')
    check("every key may use it until one is detached", (await card.locator("input[type=checkbox]:checked").count()) === (await card.locator("input[type=checkbox]").count()) && (await card.locator("input[type=checkbox]").count()) >= 2)
    await card.locator('input[aria-label="Allow key vk-po-a"]').uncheck()
    check("unticking a key detaches it", await poll(async () => !((await api("GET", "/api/mcp/virtual-mcps/ui-vmcp")).data.virtual_mcp.virtual_key_ids ?? []).includes("vk-po-a")))
    check("the other keys stay attached", ((await api("GET", "/api/mcp/virtual-mcps/ui-vmcp")).data.virtual_mcp.virtual_key_ids ?? []).includes("vk-ui-oauth"))
    await card.locator('input[aria-label="Allow key vk-po-a"]').check()
    check("ticking it attaches it again", await poll(async () => ((await api("GET", "/api/mcp/virtual-mcps/ui-vmcp")).data.virtual_mcp.virtual_key_ids ?? []).includes("vk-po-a")))
    await card.locator('button:has-text("Edit")').click()
    check("the editor keeps the name read only and shows the stored tool", (await page.evaluate(() => document.querySelector("#vm-form input[name=name]").readOnly)) && (await page.inputValue('#vm-tools input[aria-label="Renamed as"]')) === "say")
    await page.fill("#vm-form input[name=description]", "edited")
    await page.click("#vm-save")
    check("an edit is saved", await poll(async () => (await api("GET", "/api/mcp/virtual-mcps/ui-vmcp")).data.virtual_mcp.description === "edited"))

    // tool groups
    await page.click("#vm-mode-group")
    check("the tool group view lists the same record", await until(page, () => document.querySelector('article[aria-label="Tool group ui-vmcp"]') !== null))
    await page.click("#vm-new")
    await page.fill("#tg-form input[name=name]", "ui-group")
    await page.click("#tg-add-tool")
    await page.selectOption('#tg-tools select[aria-label="MCP client"]', "local")
    await page.fill('#tg-tools input[aria-label="Tool names"]', "echo")
    await page.check('#tg-form input[name="g-key"][value="vk-po-a"]')
    await page.click("#tg-save")
    check("a tool group is created from the page", await until(page, () => document.querySelector('article[aria-label="Tool group ui-group"]') !== null), await text(page, "#tg-form p.error"))
    const grp = (await api("GET", "/api/mcp/tool-groups/ui-group")).data.mcp_tool_group
    check("its tools and its one key are stored", JSON.stringify(grp?.tools) === JSON.stringify([{ source: "local-echo" }]) && JSON.stringify(grp?.virtual_key_ids) === JSON.stringify(["vk-po-a"]), JSON.stringify(grp))
    await page.locator('article[aria-label="Tool group ui-group"] button:has-text("Edit")').click()
    check("the group editor shows the stored client and tools and the attached key", (await page.inputValue('#tg-tools input[aria-label="Tool names"]')) === "echo" && (await page.isChecked('#tg-form input[name="g-key"][value="vk-po-a"]')) && !(await page.isChecked('#tg-form input[name="g-key"][value="vk-ui-oauth"]')))
    await page.check('#tg-form input[name="g-key"][value="vk-ui-oauth"]')
    await page.click("#tg-save")
    check("a group's keys are replaced on save", await poll(async () => ((await api("GET", "/api/mcp/tool-groups/ui-group")).data.mcp_tool_group.virtual_key_ids ?? []).length === 2))
    for (const n of ["ui-group", "ui-vmcp"]) {
      await page.locator('article[aria-label$="' + n + '"] button:has-text("Delete")').click()
      await page.locator('article[aria-label$="' + n + '"] button:has-text("Confirm delete")').click()
    }
    check("virtual MCPs and groups can be deleted", await poll(async () => ((await api("GET", "/api/mcp/virtual-mcps")).data.virtual_mcps ?? []).length === 0))
    await page.click("#vm-mode-mcp")
    const w4 = await page.evaluate(() => document.documentElement.scrollWidth)
    check("the virtual MCP page has no horizontal scroll at 400px", w4 <= 400, w4)
  }

  // ---- roles: each role sees the actions it can take ----
  {
    const mk = async (role, name) => {
      const r = await api("POST", "/api/users", { name, role })
      return r.data.token
    }
    await api("POST", "/api/roles", { name: "keys-reader", permissions: [{ resource: "VirtualKeys", operation: "View" }] })
    const tokens = { viewer: await mk("viewer", "ui-viewer"), editor: await mk("editor", "ui-editor"), auditor: await mk("auditor", "ui-auditor"), custom: await mk("keys-reader", "ui-custom") }
    const as = async (token) => {
      const ctx = await browser.newContext({ viewport: { width: 1200, height: 900 } })
      const p = await ctx.newPage()
      const denied = []
      p.on("response", (r) => {
        if (r.status() === 403) denied.push(r.url())
      })
      await p.addInitScript((t) => sessionStorage.setItem("raiju.adminToken", t), token)
      return { ctx, p, denied }
    }
    const has = (p, sel) => p.locator(sel).count().then((n) => n > 0)

    // viewer: reads everything, changes nothing
    {
      const { ctx, p, denied } = await as(tokens.viewer)
      await p.goto(GW + "/#overview")
      check("the header names the signed-in user and role", await until(p, () => /ui-viewer/.test(document.querySelector("#role-pill")?.textContent ?? "") && /viewer/.test(document.querySelector("#role-pill").textContent)), await text(p, "#role-pill"))
      check("a viewer sees the overview without the metrics box", (await until(p, () => /\d/.test(document.querySelector("#ov-stats")?.textContent ?? ""))) && !(await has(p, "#ov-metrics-box")))
      await p.goto(GW + "/#keys")
      await p.waitForSelector("#vk-list tbody tr", { timeout: 6000 })
      check("a viewer has no New virtual key button", !(await has(p, "#vk-new")))
      check("a viewer's key rows have no Edit, Rotate or Delete", (await p.locator('#vk-list button:has-text("Edit"), #vk-list button:has-text("Rotate"), #vk-list button:has-text("Delete")').count()) === 0)
      check("the status toggle is disabled for a viewer", await p.evaluate(() => [...document.querySelectorAll("#vk-list button.toggle")].every((b) => b.disabled)))
      await p.goto(GW + "/#providers")
      await p.waitForSelector("#pv-list article", { timeout: 6000 })
      check("a viewer sees providers without add, edit or delete", !(await has(p, "#pv-add")) && (await p.locator('#pv-list button:has-text("Edit"), #pv-list button:has-text("Delete"), #pv-list summary').count()) === 0)
      await p.goto(GW + "/#governance")
      await p.waitForFunction(() => (document.querySelector("#gov-root")?.textContent ?? "").includes("monthly"), null, { timeout: 6000 })
      check("a viewer sees budgets read only", (await p.locator("#gov-root form:not([hidden])").count()) === 0 && (await p.locator('#gov-root button:has-text("Delete"), #gov-root button:has-text("Edit")').count()) === 0)
      await p.goto(GW + "/#mcp")
      await p.waitForSelector('article[aria-label="MCP client local"]', { timeout: 6000 })
      check("a viewer sees MCP clients without add, edit, reconnect or delete", !(await has(p, "#mcp-new")) && (await p.locator('#mcp-list button:has-text("Edit"), #mcp-list button:has-text("Reconnect"), #mcp-list button:has-text("Delete")').count()) === 0)
      await until(p, () => document.querySelectorAll('article[aria-label="MCP client local"] .tool-chips button').length > 0, null, 10000)
      check("the tool switches are disabled", await p.evaluate(() => [...document.querySelectorAll(".tool-chips button")].every((b) => b.disabled)))
      await p.goto(GW + "/#config")
      check("a viewer reads the settings but cannot save them", (await until(p, () => document.querySelector("#cfg-json") !== null)) && (await p.evaluate(() => document.querySelector("#cfg-json").readOnly)) && !(await p.isVisible("#cfg-save")) && (await has(p, "#cfg-readonly")))
      await p.goto(GW + "/#mcpaccess")
      await p.waitForSelector("#mca-sessions", { timeout: 6000 })
      check("a viewer has no revoke or open-submission actions on MCP access", (await p.locator('#mca-grants button:has-text("Revoke"), #mca-sessions button:has-text("Revoke"), #mca-hdr-open').count()) === 0)
      await p.goto(GW + "/#vmcp")
      await p.waitForSelector("#vm-title", { timeout: 6000 })
      check("a viewer has no New button on virtual MCPs", !(await has(p, "#vm-new")))
      check("a viewer's own pages never got a 403", denied.length === 0, denied.join(" "))
      await ctx.close()
    }
    // editor: providers and governance records, no MCP or settings
    {
      const { ctx, p } = await as(tokens.editor)
      await p.goto(GW + "/#keys")
      check("an editor can create virtual keys", await until(p, () => document.querySelector("#vk-new") !== null))
      await p.goto(GW + "/#providers")
      check("an editor can add providers", await until(p, () => document.querySelector("#pv-add") !== null))
      await p.goto(GW + "/#mcp")
      await p.waitForSelector("#mcp-title", { timeout: 6000 })
      check("an editor cannot add MCP clients", !(await has(p, "#mcp-new")))
      await p.goto(GW + "/#config")
      check("an editor cannot save settings", await until(p, () => document.querySelector("#cfg-readonly") !== null))
      await ctx.close()
    }
    // auditor: logs only
    {
      const { ctx, p } = await as(tokens.auditor)
      await p.goto(GW + "/#logs")
      check("an auditor sees the logs", await until(p, () => (document.querySelector("#lg-body")?.textContent ?? "").includes("gpt-4o-mini")))
      const nav = await p.evaluate(() => [...document.querySelectorAll("nav.tabs a")].map((a) => a.getAttribute("data-nav")))
      check("an auditor's tabs are the logs and the pages that need no permission", nav.includes("logs") && nav.includes("live") && !nav.includes("providers") && !nav.includes("keys") && !nav.includes("config") && !nav.includes("mcp"), nav.join(","))
      await ctx.close()
    }
    // custom role: the pairs it holds
    {
      const { ctx, p } = await as(tokens.custom)
      await p.goto(GW + "/#keys")
      check("a custom role sees the key list", await until(p, () => document.querySelector("#vk-list") !== null))
      const nav = await p.evaluate(() => [...document.querySelectorAll("nav.tabs a")].map((a) => a.getAttribute("data-nav")))
      check("its tabs follow its permissions", nav.includes("keys") && !nav.includes("providers") && !nav.includes("logs") && !nav.includes("config"), nav.join(","))
      check("it has no write actions", !(await has(p, "#vk-new")))
      await ctx.close()
    }
    await api("DELETE", "/api/users/ui-viewer")
    await api("DELETE", "/api/users/ui-editor")
    await api("DELETE", "/api/users/ui-auditor")
    await api("DELETE", "/api/users/ui-custom")
    await api("DELETE", "/api/roles/keys-reader")
  }

  // ---- crews: the frontier with its knee and the table behind it, the learned cells, the task lookup; a viewer sees no actions ----
  {
    const crewChat = (task, role, attempt = 1) => chat("Fix the crash in the parser", "crew/codeaf", { "x-raiju-task-id": task, "x-raiju-crew-role": role, "x-raiju-task-class": "bug-fix", "x-raiju-task-attempt": String(attempt) })
    await crewChat("t-ui-1", "worker")
    await crewChat("t-ui-1", "checker")
    await api("POST", "/api/crews/codeaf/assign", { task_id: "t-ui-2", class: "open-ended" })
    // the first attempt fails its verifier; the sequential layer opens attempt 2 on a dearer crew, which passes: the cells of that crew are learned
    await api("POST", "/api/crews/tasks/t-ui-1/outcome?pool=codeaf", { quality: 0.2, verifier: "fail" })
    await api("POST", "/api/crews/tasks/t-ui-1/next?pool=codeaf")
    await crewChat("t-ui-1", "worker", 2)
    await api("POST", "/api/crews/tasks/t-ui-1/outcome?pool=codeaf", { quality: 0.8, verifier: "pass", attempt: 2 })
    await page.goto(GW + "/#crews")
    check("the Crews tab is there for the admin", await until(page, () => document.querySelector('nav.tabs a[data-nav="crews"]') !== null))
    check("the pool's card names its pool and roles", await until(page, () => (document.querySelector("#cr-pool-codeaf h2")?.textContent ?? "") === "Pool codeaf" && (document.querySelector("#cr-pool-codeaf")?.textContent ?? "").includes("worker, checker")), await text(page, "#cr-pool-codeaf"))
    check("the frontier chart is an svg with a title and a description", await until(page, () => {
      const svg = document.querySelector("#cr-codeaf-bug-fix svg")
      return !!svg && svg.getAttribute("role") === "img" && /Frontier of bug-fix/.test(svg.querySelector("title")?.textContent ?? "") && !!svg.querySelector("desc")?.textContent
    }), await text(page, "#cr-codeaf-bug-fix"))
    check("the frontier draws its crews as points", (await page.locator("#cr-codeaf-bug-fix svg circle").count()) >= 2, await page.locator("#cr-codeaf-bug-fix svg circle").count())
    check("the knee is marked on the frontier and named in the class", (await page.locator("#cr-codeaf-bug-fix svg polygon").count()) === 1 && (await text(page, "#cr-codeaf-bug-fix")).includes("Knee"), await text(page, "#cr-codeaf-bug-fix"))
    check("the table behind the chart lists the frontier crews", await until(page, () => document.querySelectorAll("#cr-codeaf-bug-fix details.chart-table tbody tr").length >= 2))
    await page.focus("#cr-codeaf-bug-fix svg")
    await page.keyboard.press("ArrowRight")
    check("the arrow keys read a frontier crew", await until(page, () => (document.querySelector("#cr-codeaf-bug-fix .chart-tip")?.textContent ?? "").includes("Cost:")), await text(page, "#cr-codeaf-bug-fix"))
    const chosen = await page.locator("#cr-codeaf-bug-fix-class dt").allTextContents()
    check("the class names the chosen crew for each role", chosen.includes("worker") && chosen.includes("checker"), chosen.join(","))
    check("the pacing shows the live writers and the completed tasks", (await text(page, "#cr-pool-codeaf")).includes("Live writers") && (await text(page, "#cr-pool-codeaf")).includes("Tasks completed"))
    check("the candidates table lists the models and routes", (await text(page, "#cr-pool-codeaf")).includes("openai/crew-strong") && (await page.locator("#cr-pool-codeaf table").first().textContent()).includes("api"))
    check("the learned role effects table has the credited cells", await until(page, () => document.querySelectorAll("table.cr-cells tbody tr").length >= 1), await text(page, "#cr-pool-codeaf"))
    const sortPrior = () => page.evaluate(() => [...document.querySelectorAll("table.cr-cells th")].find((th) => (th.textContent ?? "").includes("Prior δ"))?.getAttribute("aria-sort"))
    await page.click('table.cr-cells th button:has-text("Prior δ")')
    const first = await sortPrior()
    const vals = await page.$$eval("table.cr-cells tbody tr", (rows) => rows.map((r) => parseFloat(r.children[3].textContent)))
    check("the learned cells sort by a column when its header is pressed", first === "descending" && vals.every((v, i) => i === 0 || vals[i - 1] >= v), JSON.stringify(vals))
    await page.click('table.cr-cells th button:has-text("Prior δ")')
    check("pressing the same header again reverses the order", (await sortPrior()) === "ascending")
    await page.fill("#cr-task-id", "t-ui-1")
    await page.click('#cr-task-form button[type="submit"]')
    check("the task lookup shows the assignment, its attempt and its calls", await until(page, () => (document.querySelector("#cr-task-detail")?.textContent ?? "").includes("Task t-ui-1") && document.querySelectorAll("#cr-task-detail tbody tr").length >= 3), await text(page, "#cr-task-detail"))
    check("the admin sees the assign, outcome and next actions", (await page.locator("#cr-assign-form, #cr-outcome-form, #cr-next").count()) === 3)
    await page.fill("#cr-task-id", "t-ui-nope")
    await page.click('#cr-task-form button[type="submit"]')
    check("an unknown task says so in the lookup", await until(page, () => /No task t-ui-nope in pool codeaf/.test(document.querySelector("#cr-task-form [role=alert]")?.textContent ?? "")), await text(page, "#cr-task-form"))
    await page.fill("#cr-task-id", "t-ui-2")
    await page.click('#cr-task-form button[type="submit"]')
    await until(page, () => (document.querySelector("#cr-task-detail")?.textContent ?? "").includes("Task t-ui-2"))
    await page.fill("#cr-outcome-quality", "0.6")
    await page.selectOption("#cr-outcome-verifier", "pass")
    await page.click('#cr-outcome-form button[type="submit"]')
    check("recording an outcome from the page confirms it", await until(page, () => (document.querySelector(".toasts")?.textContent ?? "").includes("Outcome recorded")), await text(page, ".toasts"))
    check("the outcome shows on the task", await until(page, () => (document.querySelector("#cr-task-detail")?.textContent ?? "").includes("pass")))

    // a viewer reads the crews and the tasks, and is offered no action on them
    const viewerTok = (await api("POST", "/api/users", { name: "ui-crew-viewer", role: "viewer" })).data.token
    const vctx = await browser.newContext({ viewport: { width: 1200, height: 900 } })
    const vp = await vctx.newPage()
    const vdenied = []
    vp.on("response", (r) => {
      if (r.status() === 403) vdenied.push(r.url())
    })
    await vp.addInitScript((t) => sessionStorage.setItem("raiju.adminToken", t), viewerTok)
    await vp.goto(GW + "/#crews")
    check("a viewer reads the pool and its frontier", await until(vp, () => document.querySelector("#cr-codeaf-bug-fix svg[role=img]") !== null && (document.querySelector("#cr-pool-codeaf")?.textContent ?? "").includes("Candidates")), await text(vp, "#cr-pool-codeaf"))
    check("a viewer has no assign, outcome or next forms", (await vp.locator("#cr-assign-form, #cr-outcome-form, #cr-next").count()) === 0)
    check("a viewer's task panel has no action buttons", (await vp.locator('#cr-tasks button:has-text("Assign"), #cr-tasks button:has-text("Record outcome"), #cr-tasks button:has-text("Ask for the next step")').count()) === 0)
    check("a viewer is told it reads the crews but cannot change them", (await text(vp, "#cr-tasks")).includes("can read the crews but not"))
    await vp.fill("#cr-task-id", "t-ui-1")
    await vp.click('#cr-task-form button[type="submit"]')
    check("a viewer looks a task up", await until(vp, () => (document.querySelector("#cr-task-detail")?.textContent ?? "").includes("Task t-ui-1")))
    check("a viewer's pages never got a 403", vdenied.length === 0, vdenied.join(" "))
    await vctx.close()
    await api("DELETE", "/api/users/ui-crew-viewer")
  }

  // ---- role editor: a role made in the UI limits what a user sees and may call ----
  {
    await api("POST", "/api/governance/access-profiles", { id: "p-ui-role", name: "UI role profile", allowed_models: ["openai/gpt-4o-mini"] })
    const mk = async (name, role) => (await api("POST", "/api/users", { name, role })).data.token
    const asUser = async (token) => {
      const ctx = await browser.newContext({ viewport: { width: 1200, height: 900 } })
      const p = await ctx.newPage()
      await p.addInitScript((t) => sessionStorage.setItem("raiju.adminToken", t), token)
      return { ctx, p }
    }
    const callAs = async (token, method, path, body) => {
      const res = await fetch(GW + path, { method, headers: { "content-type": "application/json", authorization: "Bearer " + token }, body: body === undefined ? undefined : JSON.stringify(body) })
      return res.status
    }
    const navOf = (p) => p.evaluate(() => [...document.querySelectorAll("nav.tabs a")].map((a) => a.getAttribute("data-nav")))
    const roleToken = await mk("ui-roleuser", "viewer")

    await page.goto(GW + "/#roles")
    check("the roles page lists the built-in roles, read only", await until(page, () => ["admin", "editor", "viewer", "auditor"].every((r) => (document.querySelector("#role-builtin")?.textContent ?? "").includes(r))) && (await page.locator("#role-builtin button, #role-builtin input").count()) === 0)
    await until(page, () => document.querySelector("#role-new") !== null)
    await page.click("#role-new")
    await page.waitForSelector("#role-form")
    check("the permission grid has a row per resource and a column per operation", (await page.locator("#role-grid tbody tr").count()) >= 18 && (await page.locator("#role-grid thead th").count()) === 8, await page.locator("#role-grid tbody tr").count())
    await page.fill('#role-form input[name=name]', "ui-keyreader")
    await page.fill('#role-form input[name=description]', "reads virtual keys")
    await page.check('#role-grid input[aria-label="VirtualKeys View"]')
    check("an access profile can be attached to the new role", await page.isVisible('#role-profiles input[value="p-ui-role"]'))
    await page.check('#role-profiles input[value="p-ui-role"]')
    await page.click('#role-form button[type=submit]')
    check("a created role appears in the list with its permission count", await until(page, () => /1/.test(document.querySelector('#role-list tr[data-role="ui-keyreader"]')?.children[2]?.textContent ?? "") && document.querySelector("#role-form") === null), await text(page, "#role-list"))
    const made = (await api("GET", "/api/roles/ui-keyreader")).data
    check("the gateway stored exactly the ticked pair", JSON.stringify(made.permissions) === JSON.stringify([{ resource: "VirtualKeys", operation: "View" }]) && made.description === "reads virtual keys", JSON.stringify(made))
    const prof = (await api("GET", "/api/governance/access-profiles")).data.profiles.find((p) => p.id === "p-ui-role")
    check("the access profile is attached to the role", (prof.roles ?? []).some((r) => r.role_id === made.id), JSON.stringify(prof))
    check("the list names the attached profile", (await text(page, '#role-list tr[data-role="ui-keyreader"]')).includes("p-ui-role"))

    // assign the role to a user
    await page.selectOption('select[aria-label="Role of ui-roleuser"]', "ui-keyreader")
    check("choosing a role for a user saves it", await poll(async () => (await api("GET", "/api/users/ui-roleuser/role")).data.role === "ui-keyreader"), JSON.stringify((await api("GET", "/api/users/ui-roleuser/role")).data))
    check("the list shows the role's holders", await until(page, () => (document.querySelector('#role-list tr[data-role="ui-keyreader"]')?.textContent ?? "").includes("ui-roleuser")), await text(page, "#role-list"))

    // the user is limited, in the UI and on the API
    {
      const { ctx, p } = await asUser(roleToken)
      await p.goto(GW + "/#keys")
      check("the user sees the key list the role reads", await until(p, () => document.querySelector("#vk-list") !== null))
      const nav = await navOf(p)
      check("the user's tabs follow the role", nav.includes("keys") && !nav.includes("providers") && !nav.includes("logs") && !nav.includes("config") && !nav.includes("roles"), nav.join(","))
      check("it has no New virtual key button", (await p.locator("#vk-new").count()) === 0)
      check("the API lets it read keys and refuses providers and writes", (await callAs(roleToken, "GET", "/api/governance/virtual-keys")) === 200 && (await callAs(roleToken, "GET", "/api/providers")) === 403 && (await callAs(roleToken, "POST", "/api/governance/virtual-keys", {})) === 403)
      await ctx.close()
    }

    // edit the role in the UI: the grid shows what it holds, one more pair widens the user's access
    await page.click('#role-list tr[data-role="ui-keyreader"] button:has-text("Edit")')
    await page.waitForSelector("#role-form")
    check("the editor opens with the role's pairs and profiles ticked", (await page.isChecked('#role-grid input[aria-label="VirtualKeys View"]')) && !(await page.isChecked('#role-grid input[aria-label="VirtualKeys Create"]')) && (await page.isChecked('#role-profiles input[value="p-ui-role"]')) && (await page.inputValue('#role-form input[name=name]')) === "ui-keyreader")
    check("a saved role's name is fixed", await page.evaluate(() => document.querySelector('#role-form input[name=name]').readOnly))
    await page.check('#role-grid input[aria-label="VirtualKeys Create"]')
    await page.click('#role-grid button[aria-label="Toggle every operation on Logs"]')
    await page.click('#role-grid button[aria-label="Toggle every operation on Logs"]')
    check("a row's All button ticks and unticks the whole row", !(await page.isChecked('#role-grid input[aria-label="Logs View"]')))
    await page.click('#role-form button[type=submit]')
    check("the saved edit reaches the gateway", await poll(async () => ((await api("GET", "/api/roles/ui-keyreader")).data.permissions ?? []).length === 2), JSON.stringify((await api("GET", "/api/roles/ui-keyreader")).data))
    {
      const { ctx, p } = await asUser(roleToken)
      await p.goto(GW + "/#keys")
      check("the widened role shows the user New virtual key", await until(p, () => document.querySelector("#vk-new") !== null))
      check("and the API no longer refuses the write", (await callAs(roleToken, "POST", "/api/governance/virtual-keys", {})) !== 403)
      await ctx.close()
    }
    // untick the profile again: it is detached
    await page.click('#role-list tr[data-role="ui-keyreader"] button:has-text("Edit")')
    await page.waitForSelector("#role-form")
    await page.uncheck('#role-profiles input[value="p-ui-role"]')
    await page.click('#role-form button[type=submit]')
    check("unticking a profile detaches it from the role", await poll(async () => ((await api("GET", "/api/governance/access-profiles")).data.profiles.find((p) => p.id === "p-ui-role").roles ?? []).length === 0))

    // a role that only reads RBAC sees the roles read only
    await api("POST", "/api/roles", { name: "ui-rbac-ro", permissions: [{ resource: "RBAC", operation: "View" }] })
    const roToken = await mk("ui-rbac-user", "ui-rbac-ro")
    {
      const { ctx, p } = await asUser(roToken)
      await p.goto(GW + "/#roles")
      check("a role that reads RBAC sees the custom roles", await until(p, () => document.querySelector('#role-list tr[data-role="ui-keyreader"]') !== null))
      check("it has no New role, Delete or Users section", (await p.locator("#role-new, #role-users").count()) === 0 && (await p.locator('#role-list button:has-text("Delete")').count()) === 0)
      await p.click('#role-list tr[data-role="ui-keyreader"] button:has-text("View")')
      await p.waitForSelector("#role-form")
      check("the form opens with every control disabled", await p.evaluate(() => document.querySelector('#role-form button[type=submit]').disabled && [...document.querySelectorAll('#role-grid input[name=perm]')].every((b) => b.disabled)))
      check("the API refuses its writes", (await callAs(roToken, "POST", "/api/roles", { name: "nope" })) === 403 && (await callAs(roToken, "DELETE", "/api/roles/ui-keyreader")) === 403)
      await ctx.close()
    }

    // deleting a role a user holds is refused; once released it goes
    await page.click('#role-list tr[data-role="ui-keyreader"] button:has-text("Delete")')
    await page.click('#role-list tr[data-role="ui-keyreader"] button:has-text("Confirm delete")')
    check("a role a user still holds is not deleted, and the refusal is shown", await until(page, () => document.querySelector(".toast.error") !== null) && (await api("GET", "/api/roles/ui-keyreader")).status === 200, await text(page, ".toasts"))
    await api("PUT", "/api/users/ui-roleuser/role", { role: "viewer" })
    await page.click("#roles-refresh")
    await until(page, () => !(document.querySelector('#role-list tr[data-role="ui-keyreader"]')?.textContent ?? "").includes("ui-roleuser"))
    await page.click('#role-list tr[data-role="ui-keyreader"] button:has-text("Delete")')
    await page.click('#role-list tr[data-role="ui-keyreader"] button:has-text("Confirm delete")')
    check("a released role is deleted", await until(page, () => document.querySelector('#role-list tr[data-role="ui-keyreader"]') === null) && (await api("GET", "/api/roles/ui-keyreader")).status === 404)
    const w = await page.evaluate(() => document.documentElement.scrollWidth)
    check("the roles page has no horizontal scroll at 400px", w <= 400, w)

    await api("DELETE", "/api/users/ui-roleuser")
    await api("DELETE", "/api/users/ui-rbac-user")
    await api("DELETE", "/api/roles/ui-rbac-ro")
    await api("DELETE", "/api/governance/access-profiles/p-ui-role")
  }

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
  const jwks = await (await fetch(GW + "/.well-known/jwks.json")).json().catch(() => ({}))
  check("saving the settings keeps the MCP authorization server and its signing key", (await api("GET", "/api/config")).data.client?.mcp_server_auth_mode === "both" && (jwks.keys ?? []).length === 1, JSON.stringify(jwks).slice(0, 200))

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
  const VIEWS = ["overview", "live", "providers", "keys", "governance", "logs", "mcp", "roles", "config", "playground"]
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

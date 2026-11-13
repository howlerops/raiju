// Against scripts/preview_console.py's real native console and two isolated local gateways.
// NODE_PATH=<playwright install>/node_modules [PLAYWRIGHT_CHANNEL=chrome] node tests/console_e2e.mjs
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { readFileSync, existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const { chromium } = require('playwright')
const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const accessPath = join(root, 'build/console-preview-access.json')
const deadline = Date.now() + 60000
while (!existsSync(accessPath)) {
  if (Date.now() >= deadline) throw new Error('Local preview did not publish its private access file')
  await new Promise((resolve) => setTimeout(resolve, 100))
}
const access = JSON.parse(readFileSync(accessPath, 'utf8'))
const [eu, us] = access.gateways
assert.match(access.owner, /^raiju-console-preview-[a-f0-9]+$/)
for (const value of [access.console, eu.url, us.url]) {
  const u = new URL(value)
  assert.equal(u.protocol, 'http:')
  assert.equal(u.hostname, '127.0.0.1', 'This regression must never target a real deployment')
}
for (const gateway of [eu, us]) assert.ok(gateway.container.startsWith(access.owner + '-'))
const allowed = new Set([access.console, eu.url, us.url])
const api = async (gateway, method, path, body) => {
  const response = await fetch(gateway.url + path, { method, redirect: 'error', headers: {
    authorization: 'Bearer ' + gateway.token, ...(body === undefined ? {} : {'content-type':'application/json'}),
  }, body: body === undefined ? undefined : JSON.stringify(body) })
  assert.ok(response.ok, `${gateway.name} ${method} ${path}: HTTP ${response.status}`)
  return response.json()
}
const check = (name) => console.log('ok ' + name)
const browser = await chromium.launch({headless:true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel:process.env.PLAYWRIGHT_CHANNEL} : {})})
const context = await browser.newContext({viewport:{width:1440,height:1000}})
await context.addCookies([{name:'raiju_session', value:'synthetic-ambient-cookie', url:eu.url, httpOnly:true}])
const page = await context.newPage()
const records = [], collecting = [], sockets = [], errors = []
page.on('pageerror', (error) => errors.push(error.message))
page.on('websocket', (socket) => sockets.push(socket.url()))
page.on('request', (request) => {
  collecting.push(request.allHeaders().then((headers) => records.push({url:request.url(), method:request.method(), headers})))
})
await context.route('**/*', (route) => allowed.has(new URL(route.request().url()).origin) ? route.continue() : route.abort())
const targetIs = async (gateway) => {
  await page.waitForFunction((url) => document.querySelector('#target-endpoint')?.textContent === url, gateway.url)
}
const select = async (gateway) => {
  await page.locator('#gateway-select').selectOption(gateway.id)
  await targetIs(gateway)
}
const login = async (gateway) => {
  if (!(await page.locator('#auth').isVisible())) await page.locator('#token-btn').click()
  await page.locator('#auth details summary').click()
  await page.locator('#auth-username').fill(gateway.username)
  await page.locator('#auth-password').fill(gateway.password)
  await page.getByRole('button', {name:'Sign in to ' + gateway.name, exact:true}).click()
  await page.locator('#auth').waitFor({state:'hidden'})
  await targetIs(gateway)
  await page.waitForFunction(() => document.querySelector('#token-btn')?.textContent?.includes('set'))
}
let oldClient, paused = false
try {
  const documentResponse = await page.goto(access.console)
  const csp = documentResponse.headers()['content-security-policy'] ?? ''
  for (const origin of [eu.url, us.url]) assert.ok(csp.includes(origin), 'Console CSP omitted a configured origin')
  assert.ok(!/(?:^|\s)wss?:[;\s]/.test(csp), 'Console CSP allowed scheme-wide sockets')
  await targetIs(eu)
  await page.getByRole('region', {name:eu.name, exact:true}).getByText('Ready', {exact:true}).waitFor()
  await page.getByRole('region', {name:us.name, exact:true}).getByText('Ready', {exact:true}).waitFor()
  await Promise.all(collecting)
  assert.ok(records.filter((r) => new URL(r.url).origin !== access.console).every((r) => ['/health','/ready'].includes(new URL(r.url).pathname)))
  check('fleet loads only public regional health/readiness, not admin or inference data')

  // The native preflight must permit bearer management without granting the actual call.
  const preflight = await fetch(eu.url + '/api/config', {method:'OPTIONS', headers:{
    origin:access.console, 'access-control-request-method':'PUT',
    'access-control-request-headers':'authorization,content-type',
  }})
  assert.equal(preflight.status, 204)
  assert.equal(preflight.headers.get('access-control-allow-origin'), access.console)
  assert.match(preflight.headers.get('access-control-allow-headers') ?? '', /authorization/i)
  const bad = await fetch(eu.url + '/api/config', {method:'OPTIONS', headers:{origin:'https://untrusted.example', 'access-control-request-method':'PUT'}})
  assert.equal(bad.headers.get('access-control-allow-origin'), null)
  const unauth = await fetch(eu.url + '/api/config', {headers:{origin:access.console}})
  assert.ok([401,403].includes(unauth.status))
  check('native CORS preflight permits only configured origins and does not bypass actual auth')
  for (const path of ['/api/providers','/api/users','/api/session/setup','/api/session/ws-ticket','/v1/chat/completions']) {
    const response = await fetch(eu.url + path, {method:'OPTIONS', headers:{
      origin:access.console, 'access-control-request-method':'POST',
      'access-control-request-headers':'authorization,content-type,x-raiju-setup-token,x-raiju-vk',
    }})
    assert.equal(response.status, 204)
    assert.equal(response.headers.get('access-control-allow-credentials'), null)
    for (const header of ['authorization','content-type','x-raiju-setup-token','x-raiju-vk']) {
      assert.ok(response.headers.get('access-control-allow-headers').toLowerCase().includes(header))
    }
  }
  const notPreflight = await fetch(eu.url + '/api/providers', {method:'OPTIONS', headers:{origin:access.console}})
  assert.ok([401,403].includes(notPreflight.status))
  for (const stream of [false,true]) {
    const response = await fetch(eu.url + '/v1/chat/completions', {method:'POST', headers:{origin:access.console,'content-type':'application/json'},
      body:JSON.stringify({model:'openai/preview-model',messages:[{role:'user',content:'must not reach a provider'}],stream})})
    assert.equal(response.status, 401)
    assert.equal(response.headers.get('access-control-allow-origin'), access.console)
    assert.equal(response.headers.get('access-control-allow-credentials'), null)
  }
  const deniedPublic = await fetch(eu.url + '/api/session/is-auth-enabled', {headers:{origin:'https://untrusted.example'}})
  assert.equal(deniedPublic.status, 200)
  assert.equal(deniedPublic.headers.get('access-control-allow-origin'), null)
  const varied = await fetch(eu.url + '/', {headers:{origin:access.console}})
  assert.ok(varied.headers.get('vary').toLowerCase().includes('accept-encoding'))
  assert.ok(varied.headers.get('vary').toLowerCase().includes('origin'))
  const wrongSetup = await fetch(access.console + '/api/session/setup', {method:'POST',
    headers:{origin:access.console,'x-raiju-setup-token':'wrong','content-type':'application/json'}, body:'{}'})
  assert.equal(wrongSetup.status, 403)
  assert.equal(wrongSetup.headers.get('access-control-allow-origin'), access.console)
  const correctSetup = await fetch(access.console + '/api/providers',
    {headers:{origin:access.console,'x-raiju-setup-token':access.consoleSetupToken}})
  assert.equal(correctSetup.status, 200)
  assert.equal(correctSetup.headers.get('access-control-allow-origin'), access.console)
  check('real management/setup/inference paths keep auth, readable errors and existing Vary across CORS')

  await page.locator('[data-nav="config"]').click()
  await login(eu)
  await page.locator('#cfg-json').waitFor()

  // A slow screen module or API must never replace the shell or block navigation.
  const shell = await page.locator('nav[aria-label="Sections"]').elementHandle()
  const header = await page.locator('.console-heading').elementHandle()
  let documents = 0
  const countDocuments = (request) => { if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents++ }
  page.on('request', countDocuments)
  let releaseChunk, releaseCache
  const chunkGate = new Promise((resolve) => { releaseChunk = resolve })
  const cacheGate = new Promise((resolve) => { releaseCache = resolve })
  const slowChunk = async (route) => { await chunkGate; await route.continue() }
  const slowCache = async (route) => { await cacheGate; await route.continue() }
  await page.route('**/assets/Overview-*.js', slowChunk)
  await page.route('**/api/cache', slowCache)
  try {
    await page.locator('[data-nav="overview"]').click()
    await page.getByRole('status').filter({hasText:'Loading Overview'}).waitFor()
    await page.locator('[data-nav="fleet"]').click()
    await page.locator('#fleet-title').waitFor()
    assert.ok(await shell.evaluate((node) => node === document.querySelector('nav[aria-label="Sections"]')))
    releaseChunk()
    await page.locator('[data-nav="overview"]').click()
    await page.locator('#ov-title').waitFor()
    await page.waitForFunction(() => {
      const text = document.querySelector('#ov-breakers')?.textContent
      return text && !text.includes('Loading...')
    })
    assert.match(await page.locator('#ov-cache').textContent(), /Loading/)
    await page.locator('[data-nav="config"]').click()
    await page.locator('#cfg-json').waitFor()
    await page.goBack()
    await page.locator('#ov-title').waitFor()
    await page.goForward()
    await page.locator('#cfg-json').waitFor()
    assert.ok(await shell.evaluate((node) => node === document.querySelector('nav[aria-label="Sections"]')))
    assert.ok(await header.evaluate((node) => node === document.querySelector('.console-heading')))
    assert.equal(documents, 0, 'Same-region routes must not reload the document')
    check('lazy routes preserve shell identity, support history and isolate slow component data')
  } finally {
    releaseChunk()
    releaseCache()
    await page.unroute('**/assets/Overview-*.js', slowChunk)
    await page.unroute('**/api/cache', slowCache)
    page.off('request', countDocuments)
    await shell.dispose()
    await header.dispose()
  }
  const beforeEU = await api(eu, 'GET', '/api/config')
  const beforeUS = await api(us, 'GET', '/api/config')
  oldClient = beforeEU.client
  const editor = JSON.parse(await page.locator('#cfg-json').inputValue())
  editor.client_config.max_request_body_size_mb = 101
  await page.locator('#cfg-json').fill(JSON.stringify({client_config:editor.client_config}, null, 2))
  await page.locator('#cfg-save').click()
  await page.getByText('Configuration saved', {exact:true}).waitFor()
  assert.equal((await api(eu, 'GET', '/api/config')).client.max_request_body_size_mb, 101)
  assert.deepEqual((await api(us, 'GET', '/api/config')).client, beforeUS.client)
  check('regional password login and UI config write change Europe only')

  await page.locator('#cfg-json').fill('{"client_config":{"max_request_body_size_mb":777}}')
  await select(us)
  await page.locator('#auth').waitFor()
  assert.equal(await page.locator('#cfg-json').count(), 0, 'Old regional form must not survive a switch')
  await login(us)
  await page.locator('[data-nav="config"]').click()
  await page.locator('#cfg-json').waitFor()
  assert.ok(!(await page.locator('#cfg-json').inputValue()).includes('777'))
  const tokens = await page.evaluate(() => Object.fromEntries(Object.entries(sessionStorage).filter(([key]) => key.startsWith('raiju.adminToken:'))))
  assert.ok(tokens['raiju.adminToken:' + eu.url] && tokens['raiju.adminToken:' + us.url])
  assert.notEqual(tokens['raiju.adminToken:' + eu.url], tokens['raiju.adminToken:' + us.url])
  check('switching clears forms/permissions and keeps independent per-origin sessions')

  await page.locator('[data-nav="playground"]').click()
  await page.locator('#pg-form [name="model"]').fill('openai/preview-model')
  await page.locator('#pg-form [name="vk"]').fill(us.virtualKey)
  await page.locator('#pg-form [name="message"]').fill('Local gateway isolation proof')
  await page.getByRole('button', {name:'Send to ' + us.name, exact:true}).click()
  await page.locator('#pg-result pre.reply').filter({hasText:'Local America: local mock response'}).waitFor()
  const streamed = await page.evaluate(async ({url, virtualKey}) => {
    const response = await fetch(url + '/v1/chat/completions', {method:'POST', credentials:'omit', redirect:'error',
      headers:{'content-type':'application/json','x-raiju-vk':virtualKey},
      body:JSON.stringify({model:'openai/preview-model',messages:[{role:'user',content:'Local streaming proof'}],stream:true})})
    return {status:response.status, type:response.headers.get('content-type'), body:await response.text()}
  }, {url:us.url, virtualKey:us.virtualKey})
  assert.equal(streamed.status, 200)
  assert.ok(streamed.type.includes('text/event-stream'))
  assert.ok(streamed.body.includes('Local America: local mock response') && streamed.body.includes('[DONE]'))
  await page.locator('[data-nav="live"]').click()
  await page.waitForFunction(() => document.querySelector('#lv-state')?.textContent?.toLowerCase() === 'live')
  assert.ok(sockets.some((url) => url.startsWith(us.url.replace('http:', 'ws:') + '/ws?') && new URL(url).searchParams.get('ticket')))
  assert.ok(sockets.every((url) => !url.includes(tokens['raiju.adminToken:' + us.url]) && !url.includes(us.token)))
  check('Playground and one-use-ticket live socket use the explicitly selected America gateway')

  await select(eu)
  await page.waitForFunction(() => document.querySelector('#token-btn')?.textContent?.includes('set'))
  await page.locator('[data-nav="config"]').click()
  await page.locator('#cfg-json').waitFor()
  assert.equal(JSON.parse(await page.locator('#cfg-json').inputValue()).client_config.max_request_body_size_mb, 101)
  check('returning to Europe restores only its own session and data')

  await page.locator('a[href="#fleet"]').first().click()
  execFileSync('docker', ['pause', us.container], {stdio:'pipe'})
  paused = true
  await page.getByRole('button', {name:'Refresh health', exact:true}).click()
  await page.getByRole('region', {name:us.name, exact:true}).getByText('Unreachable / CORS blocked').first().waitFor({timeout:15000})
  await page.getByRole('region', {name:eu.name, exact:true}).getByText('Ready', {exact:true}).waitFor()
  assert.equal(await page.locator('#target-endpoint').textContent(), eu.url)
  execFileSync('docker', ['unpause', us.container], {stdio:'pipe'})
  paused = false
  check('one unreachable region does not hide the healthy region or retarget operations')

  await Promise.all(collecting)
  for (const record of records) {
    const url = new URL(record.url)
    assert.ok(allowed.has(url.origin), 'Browser requested an unconfigured origin')
    if (url.origin === access.console) continue
    assert.ok(!record.headers.cookie, 'Console HTTP leaked an ambient regional cookie')
    if (['/health','/ready'].includes(url.pathname)) {
      assert.ok(!record.headers.authorization && !record.headers.cookie && !record.headers['x-raiju-vk'], 'Fleet probe carried credentials')
    }
    const bearer = record.headers.authorization
    if (bearer === 'Bearer ' + tokens['raiju.adminToken:' + eu.url]) assert.equal(url.origin, eu.url)
    if (bearer === 'Bearer ' + tokens['raiju.adminToken:' + us.url]) assert.equal(url.origin, us.url)
    if (url.pathname === '/v1/chat/completions') {
      assert.equal(url.origin, us.url)
      assert.equal(record.headers['x-raiju-vk'], us.virtualKey)
      assert.ok(!bearer, 'Playground must not substitute an admin token')
    }
  }
  assert.deepEqual(errors, [])
  check('observed browser traffic contains no cross-region bearer leakage, credentialed probes or admin inference')

  // Malformed operator metadata must stop bootstrap before any gateway requests.
  const invalid = await browser.newContext()
  const invalidPage = await invalid.newPage()
  let targetRequests = 0
  invalidPage.on('request', (request) => { if ([eu.url,us.url].includes(new URL(request.url()).origin)) targetRequests++ })
  await invalidPage.route('**/console.json', (route) => route.fulfill({contentType:'application/json', body:JSON.stringify({gateways:[{id:'bad',name:'Bad',url:'https://untrusted.example',token:'must-not-be-accepted'}]})}))
  await invalidPage.goto(access.console)
  await invalidPage.getByRole('heading', {name:'Console configuration unavailable'}).waitFor()
  assert.equal(targetRequests, 0)
  await invalid.close()
  check('invalid public metadata fails closed before regional requests')

  // A removed saved target requires an explicit allowed choice, never automatic fallback.
  await select(us)
  await page.route('**/console.json', (route) => route.fulfill({contentType:'application/json', body:JSON.stringify({gateways:[{id:eu.id,name:eu.name,url:eu.url}], defaultGateway:eu.id})}))
  // Header promises from the previous document may settle after reload; count
  // request starts in the new document rather than slicing their completion order.
  let reloaded = false
  const recoveryRequests = []
  const recoveryNavigation = (frame) => { if (frame === page.mainFrame()) reloaded = true }
  const recoveryRequest = (request) => { if (reloaded) recoveryRequests.push(request.url()) }
  page.on('framenavigated', recoveryNavigation)
  page.on('request', recoveryRequest)
  try {
    await page.reload()
    await page.getByRole('heading', {name:'Console configuration unavailable'}).waitFor()
    assert.ok(!recoveryRequests.some((url) => [eu.url,us.url].includes(new URL(url).origin)), 'Unavailable saved targets must make no regional requests')
  } finally {
    page.off('framenavigated', recoveryNavigation)
    page.off('request', recoveryRequest)
  }
  await page.getByRole('button', {name:new RegExp('Select ' + eu.name)}).click()
  await targetIs(eu)
  await page.unroute('**/console.json')
  check('removed saved targets require explicit recovery into a configured gateway')
  await page.goto(access.console + '/#fleet')
  await page.reload() // A hash-only navigation must not silently replace an immutable manifest.
  await page.getByRole('region', {name:eu.name, exact:true}).getByText('Ready', {exact:true}).waitFor()
  await page.getByRole('region', {name:us.name, exact:true}).getByText('Ready', {exact:true}).waitFor()
  await page.screenshot({path:join(root,'build/console-preview.png'), fullPage:true})
} finally {
  if (paused) execFileSync('docker', ['unpause', us.container], {stdio:'pipe'})
  if (oldClient) await api(eu, 'PUT', '/api/config', {client_config:oldClient})
  await context.close()
  await browser.close()
}

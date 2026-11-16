# Value-semantics audit: the functions where today's runtime copied on write (branch mig-cow)

Source of the list: `cow/fns.tsv` (unit suite + part of e2e), plus the functions that only show in
`cow/e2e-bun-sites.tsv` and in the later `cow/e2e.log` (re-resolved here, see "About the evidence").
Line numbers are those of this branch. Verdicts: DIVERGES fixed / SAME / UNSURE copied / NOT FIXED HERE.

The instrumented runtime logs arrays and maps only. Records (`let n = u; n.x = ...`) are not in this evidence;
where one sits inside a listed function it is named under "Record aliases seen" and left to the static lists.

## About the evidence

- `cow/e2e-sites.tsv` mixes two runs made with two different builds of `build/raiju` (cache `832a…` and `b1bf…`,
  different instrumented runtimes) but was resolved against one. Rows of the older run resolve to a neighbouring
  function, so these names in `fns.tsv` are not real sites: `sort13268`, `crcTable` (gzip, sink_kafka),
  `noticeJson`, `planProfile`, `Engine.withMcpResponses`, `storeOff` in largeconv.tov, and the "tv_map_delete"
  rows of `Engine.attempt_resume` / `Engine.serveInner_resume`. Their real functions are in
  `cow/e2e-bun-sites.tsv` (resolved at the time with the right build) and are reviewed below.
- I re-resolved `cow/e2e.log` with `addr2line -i` against both builds (script: scratchpad `cowwork/resym.py`,
  outputs `cowwork/e2e-re2.tsv`, `cowwork/unit-re.tsv`); every row resolved against `b1bf…`. That gave the
  functions marked (e2e, later) below, which `fns.tsv` does not have.
- The older run's runtime did not yet make `.slice()` a real copy, so its crypto rows are explicit slices.

## Sites

### src/gateway.tov
- 990 `errorResponse` — DIVERGES fixed: `let h = extra; h.set("content-type")` wrote into the caller's map; now `copyHdrs(extra)` (new helper in src/schemas.tov; `new Map(m)` is refused by the pinned compiler, U0017).
- 3895 `Engine.serveInner` (`let h = h0`, then `h.delete(NO_CHARGE_HEADER)` and `route(&h)` setting x-raiju-api-key / x-raiju-routing-rule) — DIVERGES fixed: `h0` is serve's map and, from chatOnce, the caller's `ph`, both alive after the call; now `copyHdrs(h0)`.
- 4132 `Engine.serveInner` (`ctx.outHeaders = out`, then `out.set(...)` for the rest of the function, while `attempt` does `ctx.outHeaders.set(...)` when it opens a stream, 2720-2727) — DIVERGES fixed: today the two are separate from this line on; now `ctx.outHeaders = copyHdrs(out)`. This is the 66-hit serveInner site and the `Engine.attempt_resume` site.
- 3750 `Engine.route` (`act.headers: h`, then `h.set(...)` inside the chain loop, then `rules.match(act)` again) — DIVERGES fixed: a chained step would match on the key and rule name the step before set; now `headers: copyHdrs(h)`. `decided`/`out` are built in the function: SAME.
- 2971 `Engine.withInjected` (`let fs = body; setField(&fs, "tools")`) — DIVERGES fixed: `body` is the shaped body the build closure of chatOnce makes for every attempt (it can be chatOnce's own `body`); now `body.slice()` (setField replaces elements, it does not change them in place).
- 4811 `Engine.chat`, 4879 `Engine.responsesAgent` (`const out = last.h; out.set(...)`) — SAME: `last` is a local holder, never read again.
- 5274 `Engine.chatOnce` (`body = given.body` / `mc.body`, then `setField(&body, ...)`) — SAME: `given` comes only from `chat`, which returns at once; `mc` is a local result.
- 2446 `Engine.attempt` — the logged site is `ctx.outHeaders.set` (fixed at 4132). `let tl = ctx.labels … ctx.labels = tl` is written back: SAME.
- 5197 `Engine.passThrough` (e2e, later; `const hs = out; hs.set(...)`) — SAME: `out` is serveInner's local, returned at once (and no longer shared with ctx.outHeaders).
- 3035 `Engine.withMcpResponses` — SAME: `fs` is parsed in the function (the row is a mis-resolved one).
- Engine.serveInner calls of `cacheHeaders(&out)`, `routedHeaders(&out)`, `compatHeaders(&out)` — SAME: `out` is the local.

### src/providers/openai.tov
- 115 `storeOff` (`let fs = body; setField(&fs, "store", "false")`) — DIVERGES fixed: same body reused across attempts; now `body.slice()`.

### src/front.tov
- 68 `toRequest` (`let h = req.headers; h.delete/set` of the client-watch and client-ip headers) — SAME, no edit: after the call `req.headers` is read only for content-length (front.tov:141) and by http1.tov for connection / upgrade / websocket headers; nothing reads the two headers changed here from it. (119 hits: today this copies the map per request.)

### src/claimsync.tov
- 227 `resolveGrants` (`let teams = d.teams; teams.push(t)`, same for `bus`) — DIVERGES fixed: the caller's directory would gain the teams that are also returned in `newTeams` (applyInto then pushes them again); now `.slice()` on both.
- 336 `applyClaims` (`let teams = next.teams ?? []; addOnce(&teams, t)`) — DIVERGES fixed: without team rules `appliedUser` hands back the stored user's own `teams` array; now `.slice()`.

### src/provision.tov
- 133 `applyInto` (e2e, later; `d.teams.push(t)`, `d.businessUnits.push(b)` through `inout d`) — DIVERGES fixed at the callers: `planDirectory`, `planReconcile`, `scimResync` did `let d = d0`, so the pushes would reach the caller's directory (built from the stored config); now `ownDirectory(d0)` (new helper, same shape as the one in the wt-sb worktree). `users` is already `users0.slice()`.
- 207 `withRemovals` (`let plan = p; plan.changes.push(...)`) — SAME, no edit: all three callers (ops.tov 5906, 6133, the test at provision.tov 427) drop `p` or assign the result over it.

### src/ops.tov
- 5613 `Ops.syncSignIn` (e2e, later; `let users = g.users ?? []; users[at] = after / users.push(after)` before `store.setClaimSync`) — DIVERGES fixed: a refused save would leave the stored list changed; now `.slice()`.
- 4796 `Ops.a2aSendHttp`, 4860 `Ops.a2aSendGrpc`, `Ops.a2aHeaders` (e2e, later; `let hm = hd.headers; hm.set(...)`, `let mine = managed.headers`) — SAME: the maps are built by `a2aHeaders` / `upstreamHeaders` for this call.

### src/main.tov, src/config.tov
- config.tov 1388 `resolveConfig(inout c)` — the function itself is SAME (it changes its argument by contract, every part read and written back). Its callers DIVERGE, fixed: main.tov 128 (`let resolved = c`, c is the store's config) and main.tov 282 (`let first = raw`, raw is what `new ConfigStore(args.config, raw)` holds "as written"). resolveConfig changes nested records in place (provider records inside the map, exporters' elements, auth_proxy, log_exports, …), so under sharing the resolved env values would land in the stored config and be saved. A field-by-field copy of the top record is not enough. New `detachedConfig(c)` in config.tov: a copy through `JSON.stringify` / `JSON.parse … as Config` with `plugins` carried over, the way `ops.tov withSecrets` already rebuilds a config. Checked with a temporary test (not committed) on tests/e2e.config.json, deploy/config.example.json and the three bench configs: the copy stringifies identically, resolves to the same config as a separately parsed one, and leaves the source unchanged. NOT covered by a committed test and not run end to end — see "Left open".
- parseConfig, loadConfig and the tests call it on a config they just made: SAME.

### src/mcpapi.tov
- 1220 `submitFlow` (`let creds = cfg.mcp?.user_credentials ?? []; creds[ui] = row / creds.push(row)` before `persistAfter`) — DIVERGES fixed: `.slice()`.
- 1555 `createVirtual` (`let next = virtualsOf(store.cfg); next.push(v)` before `persist`) — DIVERGES fixed: `.slice()`.
- 1591 `updateVirtual`, 1642 `setAttached`, 1801 `setVirtualKeys`, 1892 `oauthConfigRoute`, 569 `createClient`, 660 `updateClient` (`let next = list; next[at] = … / next.push(c)`, `list` being the stored array) — DIVERGES fixed: `list.slice()` in each. `persist` keeps `prev = store.cfg` to restore after a failed save, which only works if the stored list was not changed.
- 1654 `setAttached` (`let keys = v.allowed_keys ?? …; keys.push(vkId)`) — DIVERGES fixed: `.slice()` (the stored virtual MCP's own list).
- 876 `inlineSpecUrl` (e2e, later; `let out = fs; setField(&out, …)`) — SAME: `fs` is parsed in the function and not read again.

### src/media_cloud.tov, src/media_native.tov
- media_cloud 619 `chatOf`, media_native 152 `chatOf` (`let fs = l.body; setField(&fs, "model")`) — DIVERGES fixed: the callers pass `l.body` / `bl.body` again as the raw body right after (`messagesBody(chatOf(l, m), l.body, …)`, `generateBody(chatOf(bl, model), bl.body)`); now `.slice()`.
- media_native 929 `geminiTranscriptionStream` (`let h = mr.headers; h.set(...); mr.headers = h`) — SAME: `mr` is built by `geminiTranscription` for this call and the map is written back.

### src/scim.tov
- 365 `patchAttrs`, 311 `putAttr` (`inout m`, `m.set` / `m.delete`) — the functions are SAME; the alias is in `patchUser` (now 484): `attrs: old.scim_attributes ?? new Map()` — DIVERGES fixed: the stored user's map would change before the checks that can still refuse the patch; now a new map filled from it (values are replaced whole by putAttr, never changed in place).
- `pushedAttrs` (`let m = into`) — SAME: both callers pass `new Map()` or assign the result back.

### src/rtsession.tov
- 262 `withGaModel` (`let s = session`), 292 `bareNestedModels` (`let fs = session`) — SAME, no edit: every caller (rtsession.tov 389/393/397/438, realtimecalls.tov 34/45) passes a temporary or assigns the result over the argument.

### src/directory.tov
- 296 `set1` / `user` (`let c = claims; set1(&c, …)`) — SAME: the five callers pass a map they just built and return.
- 700 `withClaim`, 607 `keycloakDetail` (e2e, later; `let c = u.claims; c.set(...)`) — SAME: callers replace the user with the result (`users = users.map(...)`, `out.push(await keycloakDetail(...))`).
- 503 `addTo` (e2e, later) — SAME: get, push, set back.

### Others — SAME, no edit
- src/a2a.tov 300 `restCall` — `fs = inner; setField(&fs, …)`: `inner` is parsed in the function.
- src/agenthistory.tov 323 `selectedCalls`, src/logstore.tov 1587 `groupBy`, 1847 `groupByPair`, src/clusterstate.tov 129 `ClusterState.onChange`, src/store.tov 230 `dupLines`, src/pricing.tov 147 `buildCatalog`, src/governance.tov 328 `Governance.constructor` (`mine`), src/awsprofile.tov 55 `parseIni` — get, change, set back into the same map.
- src/config_compat.tov 1705 `mapWebhooks` — `let hf = orig` then a loop over `orig` that replaces the element just read in `hf`; `orig` is not used after the loop. 2146 `warnings` — `let out = n.notes`: `n` is normalize's fresh result.
- src/openapi.tov 1163 `flattenQuerystring` — `let js = schema`: `schema` is local and not read after.
- src/plughttp.tov 81 `applyHttpReq` (`inout r`, `r.headers.set`) — the request record is the caller's by contract; in pluginroute.tov `hr.headers = hs` and `hs` is not read after the pre hooks.
- src/pluginroute.tov 478 `hookedRun` (`let hh = hs; hh.set(ATTEMPT_HEADER, id)`) — `hs` is llmHooked's local, not read after the call.
- src/rbac.tov 1273 `withIp` — a test helper; every call passes `basic(...)`, a new map.
- src/webhooks.tov 126 `DeliveryLog.refresh` — `let merged = this.rows` is written back whenever it was changed.
- src/agents.tov 346 `fetchCard`, src/agentauth.tov 182 `withAcceptedCredential` (e2e, later) — maps built by `upstreamHeaders` for the call.
- src/notify.tov 63 `NoticeList.page`, src/crypto.tov 112 `Sha256.digest`, src/aesgcm.tov 112 `gmul`, 152 `inc32`, src/ws.tov 66 `sha1`, src/passhash.tov `Eks` / 269 `bcryptWithSalt`, src/jobs.tov 598 `rerankJson` (older e2e run only) — each mutates an explicit `.slice()`.
- src/notify.tov 93 `noticeJson`, src/gzip.tov 16 / src/sink_kafka.tov 26 `crcTable`, src/awsprofile.tov 122 `planProfile`, src/largeconv.tov 210 `storeOff` — no shared value is changed in them; mis-resolved names (see above).

### Inline tests
- `test_13390_body` = src/store.tov:5858 ("business-unit members carry their source…") — `us[0] = first; g.users = us; s.cfg = n`: written back, SAME.
- `test_137228_body` = src/sink_maxim.tov:660 — `ids.set(...)` then `e.maxim = ids` again: SAME.
- `test_36647_body` = src/ops.tov:8356 — `ops.rbac.users[0]!.disabled = true` changes the list in place and expects the change: SAME.

## Record aliases seen in the listed functions — NOT FIXED HERE (records are not in this evidence; both static lists have these lines)
- gateway.tov 4181 `let sl = ctx.labels; sl.provider = …`, 4190 `let ul = ctx.labels; ul.provider = …` (serveInner): would change ctx.labels, which `record` reads afterwards.
- claimsync.tov 315 `appliedUser`: `let n = u; n.role = …` — `u` is the stored user; applyClaims and its callers compare old and new.
- mcpapi.tov 685 `updateClient`: `let c = cur` (cur = `list[at]`), then `list[at]!.auth_type !== c.auth_type` and the token_exchange comparison — under sharing these compare a record with itself, and a refused update leaves the stored client changed. Same shape: 1604 `updateVirtual` (`let v = list[at]!`), 1653 `setAttached`, 1807 `setVirtualKeys` (`let v = next[at]!; v.allowed_keys = keys`), 1925 `oauthConfigRoute` (`let na = a`), and the helpers `withClients` / `withVirtuals` / `withHeaderState` / `withAuth` (`let n = c; n.x = …; return n`), which `persist`'s rollback depends on.
- provision.tov 207 `withRemovals`: `let plan = p` (harmless for today's callers, see above).
- config.tov resolveConfig: `let np = p; np.keys = rk` and the like are why the callers need a full copy.

## Not in my list, same problem
- provision.tov `planDirectory` / `planReconcile` / `scimResync` `let d = d0` — fixed (above).
- main.tov `applyChange` and `main` — fixed with `detachedConfig` (above).
- Not fixed: nothing else found; I did not look beyond the listed functions and their callers.

## The merged list (cow/fns-all.tsv, 60 functions)
Its 11 additions over fns.tsv are all reviewed above, where they are marked "(e2e, later)": Ops.a2aSendGrpc,
Ops.a2aSendHttp, withAcceptedCredential, fetchCard, addTo, keycloakDetail, withClaim, Engine.passThrough,
inlineSpecUrl (all SAME), Ops.syncSignIn and applyInto (DIVERGES fixed).

## Left open
- `detachedConfig` (main.tov 128, 282) is verified by the unit suite and a temporary comparison on five config
  files only. It has not been run end to end, and it assumes a Config survives JSON.stringify / JSON.parse unchanged
  (plugins excepted), which is what saving and reloading a config already assumes.
- The record aliases listed above are not fixed on this branch.
- `withRemovals`, `withGaModel`, `bareNestedModels`, `withClaim`, `keycloakDetail`, `pushedAttrs`, `withIp`,
  `toRequest` still change their argument under sharing; they are SAME only because no current caller reads the
  argument afterwards.

## Tests
`tov test src/main.tov` at 020d0ff (all source edits): 2639 passed, 0 failed. An earlier run, started before the
provision/ops edits and alongside other jobs, had 2638 passed, 1 failed: rbac.tov:1325, a wall-clock comparison of
bcrypt timings in a file this branch does not touch; it passed in the final run.

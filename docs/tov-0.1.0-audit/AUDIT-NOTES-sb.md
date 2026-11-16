# Value-semantics audit, static list B (src/otel_metrics.tov … end of src/, and src/providers/)

439 sites reviewed against the brief (copies made explicit where today's code relies on an implicit copy, so the
code behaves the same once arrays, maps, sets and records are shared as in JavaScript).

| verdict | sites |
|---|---|
| SAME (left alone) | 295 |
| DIVERGES fixed | 138 |
| UNSURE copied | 6 |

Line numbers are those of the list (commit 5d1461a), not of the files after the fixes.

## How the fixes are made

Records are copied by `copyX(r)` functions that build a new literal field by field (the pinned Tov has no spread).
They sit next to their types: 26 in `src/config.tov` ("copies of records", after `Config`), `copyMcpConfig`,
`copyMcpClientConfig` and `copyMcpUserCredential` in `src/mcp.tov`, `copyMcpAuthConfig` in `src/mcpauth.tov`,
`copyMcpUserToken` in `src/mcpuser.tov`, `copyTarget` in `src/providers/types.tov`. Each copies the record only; the
arrays, maps and records in its fields are shared, and are copied separately where they are changed in place.
`scripts/copy_lint.py` (run by `scripts/check.py`, tested by `tests/test_copy_lint.py`) fails the check when a
`copyX` does not list exactly the fields of `X`, so a field added to a type cannot be dropped by its copy unnoticed.

Three fixes cover many sites at once:

- `store.tov` `gov(c)` returns a copy of the governance section (42 sites: the 28 `gov(this.cfg)` callers and the 14
  `this.cfg.governance ?? {}` ones, now `gov(this.cfg)`), and `withGov` / `withProviders` copy the config they are
  given. `ConfigStore.commit` keeps `prev = this.cfg` to put back after a failed save, `group` keeps `before`, and
  `saveLocked` keeps `baseCfg`: each needs the next config to be another record than the current one.
- `router.tov` `aliasOverrides` always returns its own key record, so `Target.key` from `router.target` is never the
  stored config's key (callers write minted tokens into `t.key.value`).
- `provision.tov` `ownDirectory(d0)` gives each plan its own team and business-unit lists.

## Sites

`file:line | function | local | verdict | why`

src/otel_metrics.tov:424 | exportMetricsRequest | `fams` | SAME | parseExposition builds a new map
src/otel_metrics.tov:437 | exportMetricsRequest | `headers` | SAME | mergeHeaders builds a new map
src/passhash.tov:270 | bcryptWithSalt | `key` | SAME | encode() result is new
src/plughttp.tov:311 | test "a request round trips through its JSON form and …" | `r` | SAME | emptyReq returns a new literal
src/plughttp.tov:328 | test "a request round trips through its JSON form and …" | `same` | SAME | emptyReq returns a new literal
src/pluginroute.tov:86 | transportStart | `hs` | SAME | snapshot() builds a new map
src/pluginroute.tov:105 | transportStart | `hr` | SAME | emptyReq returns a new literal
src/pluginroute.tov:316 | chunkWhole | `blocks` | SAME | SseBuffer.push returns a new array each call
src/pluginroute.tov:413 | llmHooked | `hs` | SAME | snapshot() builds a new map
src/pluginroute.tov:493 | hookedRun | `hh` | SAME | hs is llmHooked's own snapshot; neither function reads it after hh.set
src/pluginroute.tov:559 | postProcess | `hs` | SAME | snapshotRecord builds a new map
src/pluginroute.tov:709 | storageHooked | `refs` | SAME | objectRefs returns an array it built
src/plugins.tov:711 | latencyText | `fs` | SAME | fields()/elements() parse into a new array
src/plugins.tov:727 | mockerConfigText | `fs` | SAME | fields()/elements() parse into a new array
src/plugins.tov:738 | mockerConfigText | `rf` | SAME | fields()/elements() parse into a new array
src/plugins.tov:1178 | stripFencesIn | `fs` | SAME | fields()/elements() parse into a new array
src/plugins.tov:1185 | stripFencesIn | `cf` | SAME | fields()/elements() parse into a new array
src/plugins.tov:1191 | stripFencesIn | `mf` | SAME | fields()/elements() parse into a new array
src/plugins.tov:1235 | JsonParserPlugin.postChunk | `fs` | SAME | fields() parses into a new array
src/plugins.tov:1484 | withContent | `fs` | SAME | fields()/elements() parse into a new array
src/plugins.tov:1490 | withContent | `cf` | SAME | fields()/elements() parse into a new array
src/plugins.tov:1491 | withContent | `df` | SAME | fields()/elements() parse into a new array
src/plugins.tov:1637 | MaxTokensPlugin.preRequest | `fs` | SAME | fields()/elements() parse into a new array
src/plugins.tov:1915 | test "chain runs pre hooks in order and threads the bo…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:1924 | test "short-circuit stops later pre hooks; post hooks …" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:1940 | test "post hooks run in reverse over all plugins when …" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:1949 | test "a throwing plugin is skipped in both directions…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:1960 | test "a throwing post hook is skipped and the rest sti…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:1970 | test "header plugin sets lower-cased request headers",…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:1981 | test "mocker matches model exactly or by wildcard, and…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:1989 | test "mocker matches model exactly or by wildcard, and…" | `other` | SAME | test helper returns a new literal
src/plugins.tov:1991 | test "mocker matches model exactly or by wildcard, and…" | `wild` | SAME | test helper returns a new literal
src/plugins.tov:1994 | test "mocker matches model exactly or by wildcard, and…" | `miss` | SAME | test helper returns a new literal
src/plugins.tov:2000 | test "mocker generates a chat.completion and reports l…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2019 | test "jsonparser strips json fences with and without a…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2029 | test "jsonparser leaves unfenced content and other bod…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2039 | test "blocklist rejects any case of a listed word", ()…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2054 | test "maxtokens sets a missing max_tokens and lowers o…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2157 | test "a chunk a post hook skips is dropped, and the pl…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2174 | test "the post hooks split at the cache: post_builtin …" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2181 | test "the post hooks split at the cache: post_builtin …" | `hit` | SAME | test helper returns a new literal
src/plugins.tov:2187 | test "the post hooks split at the cache: post_builtin …" | `p` | SAME | test helper returns a new literal
src/plugins.tov:2200 | test "jsonparser completes a Responses stream's text d…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2208 | test "jsonparser completes a Responses stream's text d…" | `bad` | SAME | test helper returns a new literal
src/plugins.tov:2214 | test "jsonparser completes a Responses stream's text d…" | `chat` | SAME | test helper returns a new literal
src/plugins.tov:2270 | test "mocker priority picks the highest rule first, an…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2283 | test "mocker conditions match provider, model and mess…" | `a` | SAME | test helper returns a new literal
src/plugins.tov:2286 | test "mocker conditions match provider, model and mess…" | `g` | SAME | test helper returns a new literal
src/plugins.tov:2289 | test "mocker conditions match provider, model and mess…" | `miss` | SAME | test helper returns a new literal
src/plugins.tov:2300 | test "mocker answers Responses requests in Responses' …" | `c` | SAME | test helper returns a new literal
src/plugins.tov:2311 | test "mocker answers Responses requests in Responses' …" | `s` | SAME | test helper returns a new literal
src/plugins.tov:2320 | test "mocker answers Responses requests in Responses' …" | `e` | SAME | test helper returns a new literal
src/plugins.tov:2324 | test "mocker answers Responses requests in Responses' …" | `m` | SAME | test helper returns a new literal
src/plugins.tov:2334 | test "mocker error responses carry status_code, and de…" | `hit` | SAME | test helper returns a new literal
src/plugins.tov:2340 | test "mocker error responses carry status_code, and de…" | `other` | SAME | test helper returns a new literal
src/plugins.tov:2344 | test "mocker error responses carry status_code, and de…" | `s` | SAME | test helper returns a new literal
src/plugins.tov:2355 | test "mocker weights pick a response, and global laten…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2384 | test "mocker latencies read integer nanoseconds as Rai…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2396 | test "mocker: the resolved provider stands for a bare …" | `bare` | SAME | test helper returns a new literal
src/plugins.tov:2401 | test "mocker: the resolved provider stands for a bare …" | `unknown` | SAME | test helper returns a new literal
src/plugins.tov:2403 | test "mocker: the resolved provider stands for a bare …" | `f` | SAME | test helper returns a new literal
src/plugins.tov:2406 | test "mocker: the resolved provider stands for a bare …" | `s` | SAME | test helper returns a new literal
src/plugins.tov:2430 | test "a path ending in .wasm loads as a plugin, rewrit…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2441 | test "a wasm plugin can short-circuit, and one that fa…" | `c1` | SAME | test helper returns a new literal
src/plugins.tov:2450 | test "a wasm plugin can short-circuit, and one that fa…" | `c2` | SAME | test helper returns a new literal
src/plugins.tov:2554 | test "the HTTP pre hooks run in order on the request, …" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2555 | test "the HTTP pre hooks run in order on the request, …" | `req` | SAME | emptyReq returns a new literal
src/plugins.tov:2569 | test "an HTTP pre hook may answer, and then the later …" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2570 | test "an HTTP pre hook may answer, and then the later …" | `req` | SAME | emptyReq returns a new literal
src/plugins.tov:2582 | test "a failing HTTP hook is skipped in every directio…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2583 | test "a failing HTTP hook is skipped in every directio…" | `req` | SAME | emptyReq returns a new literal
src/plugins.tov:2596 | test "an HTTP post hook that returns a message stops t…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2607 | test "the chunk hooks run in reverse, may rewrite, dro…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2614 | test "the chunk hooks run in reverse, may rewrite, dro…" | `ctx2` | SAME | test helper returns a new literal
src/plugins.tov:2625 | test "post hooks get an error as one, may turn a respo…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2635 | test "post hooks get an error as one, may turn a respo…" | `ctx2` | SAME | test helper returns a new literal
src/plugins.tov:2694 | test "a built-in plugin takes part in a provider-forma…" | `mctx` | SAME | test helper returns a new literal
src/plugins.tov:2720 | test "the plugins that handle a request type are the o…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2729 | test "an error event in a stream reaches the chunk pos…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2739 | test "the post hooks of a stream run per chunk for the…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2751 | test "the post hooks of a stream run per chunk for the…" | `c2` | SAME | test helper returns a new literal
src/plugins.tov:2764 | test "the header plugin sets response headers in its H…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2788 | test "a wasm plugin's context travels from http_pre_ho…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2790 | test "a wasm plugin's context travels from http_pre_ho…" | `req` | SAME | emptyReq returns a new literal
src/plugins.tov:2810 | test "a wasm plugin turns a response into an error and…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2816 | test "a wasm plugin turns a response into an error and…" | `c2` | SAME | test helper returns a new literal
src/plugins.tov:2824 | test "a wasm plugin that answers or refuses in http_pr…" | `ctx` | SAME | test helper returns a new literal
src/plugins.tov:2825 | test "a wasm plugin that answers or refuses in http_pr…" | `req` | SAME | emptyReq returns a new literal
src/pricing.tov:170 | buildCatalog | `have` | SAME | written straight back with byModel.set; nothing reads the map in between
src/pricing.tov:223 | catalogProviders | `out` | SAME | already an explicit slice()
src/profiles.tov:132 | applyProfiles | `out` | DIVERGES fixed | out was the caller's virtual key (governance.tov passes the stored key); now copyVirtualKeyConfig(vk)
src/profiles.tov:482 | snapshotOf | `c` | SAME | only withVersion calls it, on a record its callers built (toProfile/copyOf) and it overwrites versions right after
src/profiles.tov:494 | withVersion | `out` | SAME | every caller passes a record it just built (toProfile, copyOf) and uses only the result
src/profiles.tov:519 | updateProfile | `made` | SAME | toProfile returns a new literal
src/profiles.tov:570 | profileAction | `p` | UNSURE copied | copyOf is a JSON round trip (new), but its catch returned p itself; the catch now returns copyAccessProfile(p)
src/profiles.tov:584 | profileAction | `c` | UNSURE copied | copyOf is a JSON round trip (new), but its catch returned p itself; the catch now returns copyAccessProfile(p)
src/prompts.tov:568 | injectVersion | `fs` | SAME | fields()/elements() parse into a new array
src/providers/anthropic.tov:193 | messagesBody | `blocks` | SAME | contentBlocks returns a new array
src/providers/anthropic.tov:258 | upstreamHeaders | `o` | SAME | headers() builds a new map
src/providers/anthropic.tov:263 | upstreamHeaders | `h` | SAME | headers() builds a new map
src/providers/anthropic.tov:303 | markContent | `blocks` | SAME | fields()/elements() parse into a new array
src/providers/anthropic.tov:327 | injectMessagesCache | `roles` | SAME | both arms are new array literals
src/providers/anthropic.tov:328 | injectMessagesCache | `contents` | SAME | both arms are new array literals
src/providers/anthropic_route.tov:104 | anthropicRoute | `n` | DIVERGES fixed | t is the caller's target (gateway.tov keeps using it; the test reads it again); now copyTarget(t)
src/providers/anthropic_route.tov:107 | anthropicRoute | `cfg` | DIVERGES fixed | n.cfg is the stored provider config; now copyProviderConfig
src/providers/anthropic_route.tov:108 | anthropicRoute | `nc` | DIVERGES fixed | cfg.network_config is the stored network config; now copyNetworkConfig
src/providers/anthropic_route.tov:149 | test "Claude on Azure goes to the resource's Anthropic…" | `gt` | SAME | test: t is not read after gt changes
src/providers/bedrock.tov:58 | signHashed | `out` | SAME | headers() builds a new map
src/providers/bedrock.tov:354 | withBody | `hs` | SAME | signRequest/signHashed return the map headers() built
src/providers/bedrock.tov:447 | openAIChatRequest | `fs` | SAME | without() is a filter: a new array, and setField replaces elements
src/providers/bedrock.tov:745 | test "use_openai_endpoints sends OpenAI families to be…" | `bearer` | SAME | test helper returns a new literal
src/providers/bedrock_mantle.tov:64 | withModel | `fs` | SAME | without() is a filter: a new array, and setField replaces elements
src/providers/bedrock_mantle.tov:181 | postAt | `h` | SAME | headers() builds a new map
src/providers/bedrock_mantle.tov:198 | postAt | `h` | SAME | signV4 returns a map it built
src/providers/bedrock_mantle.tov:239 | countRequestAt | `fs` | SAME | without() is a filter: a new array, and setField replaces elements
src/providers/bedrock_mantle.tov:375 | test "project_id scopes calls and the listing: OpenAI-…" | `t` | SAME | test helper returns a new literal
src/providers/bedrock_mantle.tov:384 | test "project_id scopes calls and the listing: OpenAI-…" | `sg` | SAME | test helper returns a new literal
src/providers/bedrock_mantle.tov:412 | test "Claude on Mantle applies the provider's cache_co…" | `t` | SAME | test helper returns a new literal
src/providers/bedrock_mantle.tov:444 | test "Mantle Qwen streams preserve the endpoint, beare…" | `t` | SAME | test helper returns a new literal
src/providers/bedrock_mantle.tov:473 | test "Mantle Claude streams keep native Messages and c…" | `t` | SAME | test helper returns a new literal
src/providers/cloudflare.tov:26 | authHeaders | `h` | SAME | headers() builds a new map
src/providers/cloudflare.tov:34 | withModel | `fs` | SAME | without() is a filter: a new array, and setField replaces elements
src/providers/cohere.tov:14 | upstreamHeaders | `h` | SAME | headers() builds a new map
src/providers/cohere.tov:163 | streamRequest | `fs` | SAME | fields()/elements() parse into a new array
src/providers/cohere.tov:266 | modelRetrieveRequest | `h` | SAME | upstreamHeaders builds a new map
src/providers/databricks.tov:75 | authHeaders | `h` | SAME | headers() builds a new map
src/providers/databricks.tov:86 | withModel | `fs` | SAME | without() is a filter: a new array, and setField replaces elements
src/providers/decision_native.tov:68 | sortedJson | `fs` | SAME | fields()/elements() parse into a new array
src/providers/decision_native.tov:162 | readsImages | `dt` | DIVERGES fixed | perplexityBody reads d.refusal after readsImages(d) cleared it on the same record; readsImages now returns a new literal
src/providers/decision_native.tov:204 | withFields | `fs` | SAME | fields()/elements() parse into a new array
src/providers/decision_native.tov:214 | cloudflareBody | `dt` | SAME | readsImages returns a new record (after the fix at :162)
src/providers/decision_native.tov:249 | perplexityBody | `dt` | SAME | readsImages returns a new record (after the fix at :162)
src/providers/decision_native.tov:270 | bearerIfSet | `h` | SAME | headers() builds a new map
src/providers/decision_native.tov:380 | databricksAnswers | `af` | SAME | fields()/elements() parse into a new array
src/providers/gemini.tov:80 | generateBody | `parts` | SAME | partsOf returns a new array
src/providers/gemini.tov:153 | upstreamHeaders | `h` | SAME | headers() builds a new map
src/providers/githubcopilot.tov:153 | chatRequest | `h` | SAME | headers() builds a new map
src/providers/githubcopilot.tov:167 | chatRequest | `fs` | SAME | without() is a filter: a new array, and setField replaces elements
src/providers/githubcopilot.tov:179 | modelsRequest | `h` | SAME | headers() builds a new map
src/providers/huggingface.tov:198 | jsonHeaders | `h` | SAME | headers() builds a new map
src/providers/huggingface.tov:250 | embeddingsBody | `fs` | SAME | out is this function's own array and is not read after
src/providers/huggingface.tov:275 | embeddingsResponse | `fs` | SAME | fields()/elements() parse into a new array
src/providers/index.tov:54 | embeddingsUpstream | `first` | SAME | ups is a new array from bedrockRequests and is not read after first.extra is set
src/providers/openai.tov:60 | authHeaders | `h` | SAME | headers() builds a new map
src/providers/openai.tov:78 | modelFields | `fs` | SAME | without() is a filter: a new array, and setField replaces elements
src/providers/openai.tov:117 | storeOff | `fs` | SAME | both callers pass modelFields(...), a new array
src/providers/openai.tov:148 | azureHeaders | `h` | SAME | both arms call headers(), a new map
src/providers/openai.tov:157 | azureModelsRequest | `h` | SAME | azureHeaders returns a map it built
src/providers/openai.tov:233 | messagesCountRequest | `h` | SAME | headers() builds a new map
src/providers/openai.tov:240 | messagesCountRequest | `fs` | SAME | without() is a filter: a new array, and setField replaces elements
src/providers/openai.tov:251 | chatResponse | `fs` | SAME | fields()/elements() parse into a new array
src/providers/openai.tov:282 | streamResponse | `fs` | SAME | fields() parses into a new array
src/providers/openai.tov:303 | embeddingsResponse | `fs` | SAME | fields()/elements() parse into a new array
src/providers/openai.tov:442 | test "Hugging Face chat names the inference provider a…" | `one` | SAME | test: t is not read after one changes
src/providers/openrouter.tov:22 | decisionUpstream | `fs` | SAME | fields()/elements() parse into a new array
src/providers/replicate.tov:112 | chatBody | `merged` | SAME | merged is reassigned to merged.filter(...) before every push, so input is never changed
src/providers/replicate.tov:131 | chatRequest | `h` | SAME | headers() builds a new map
src/providers/replicate.tov:144 | largeRequest | `h` | SAME | headers() builds a new map
src/providers/replicate.tov:295 | predictionRequest | `h` | SAME | headers() builds a new map
src/providers/replicate.tov:388 | deploymentsRequest | `h` | SAME | headers() builds a new map
src/providers/replicate.tov:403 | pollHeaders | `h` | SAME | headers() builds a new map
src/providers/replicate.tov:457 | fileHeaders | `h` | SAME | headers() builds a new map
src/providers/typesafe.tov:40 | authHeaders | `h` | SAME | headers() builds a new map
src/providers/typesafe.tov:104 | nativeUpstream | `fs` | SAME | fields()/elements() parse into a new array
src/providers/vertex.tov:159 | countRequest | `h` | SAME | headers() builds a new map
src/providers/vertex.tov:162 | countRequest | `fs` | SAME | without() is a filter: a new array, and setField replaces elements
src/providers/vertex.tov:174 | chatRequest | `h` | SAME | headers() builds a new map
src/providers/vertex.tov:180 | chatRequest | `fs` | SAME | without() is a filter: a new array, and setField replaces elements
src/providers/vertex.tov:191 | streamRequest | `h` | SAME | headers() builds a new map
src/providers/vertex.tov:195 | streamRequest | `fs` | SAME | without() is a filter: a new array, and setField replaces elements
src/providers/vertex.tov:206 | largeRequest | `h` | SAME | headers() builds a new map
src/providers/vertex.tov:349 | test "a tuned model (an endpoint id) is called under t…" | `t` | SAME | test helper returns a new literal
src/providers/vertex.tov:367 | test "Claude on Vertex applies the provider's cache_co…" | `t` | SAME | test helper returns a new literal
src/providers/vertex.tov:391 | test "the multi-region locations use their rep hosts, …" | `forced` | SAME | test helper returns a new literal
src/providers/watsonx.tov:65 | modelsRequest | `h` | SAME | headers() builds a new map
src/provision.tov:92 | guardAdmins | `users` | SAME | every caller hands in a plan whose users list is its own (a slice/filter result) and returns only guardAdmins' result
src/provision.tov:145 | applyInto | `ch` | SAME | changeOf returns a new record
src/provision.tov:164 | planDirectory | `d` | DIVERGES fixed | d0 is ops.dirNow(): its teams and business-unit lists are the stored config's, and ops passes one dir to planDirectory then withRemovals; applyInto pushed onto them. Now ownDirectory(d0) slices both lists
src/provision.tov:202 | withRemovals | `plan` | SAME | callers pass a literal (ops removeUsersNow), or a plan they replace with the result (ops runSync) or do not read again (test)
src/provision.tov:229 | planReconcile | `d` | DIVERGES fixed | d0 is ops.dirNow(): its teams and business-unit lists are the stored config's, and ops passes one dir to planDirectory then withRemovals; applyInto pushed onto them. Now ownDirectory(d0) slices both lists
src/provision.tov:257 | roleless | `n` | DIVERGES fixed | u is an element of after0 that scimResync then compares with the result in changeOf(u, after); now copyAdminUserConfig(u)
src/provision.tov:268 | scimResync | `d` | DIVERGES fixed | d0 is ops.dirNow(): its teams and business-unit lists are the stored config's, and ops passes one dir to planDirectory then withRemovals; applyInto pushed onto them. Now ownDirectory(d0) slices both lists
src/provision.tov:301 | stripped | `n` | DIVERGES fixed | u is an element of the caller's after list (server.tov passes plan.users); now copyAdminUserConfig(u)
src/provision.tov:312 | restored | `n` | DIVERGES fixed | same as stripped: u is an element of the caller's list; now copyAdminUserConfig(u)
src/provision.tov:313 | restored | `teams` | DIVERGES fixed | u.teams is the caller's user's list; now (u.teams ?? []).slice()
src/provjobs.tov:37 | interruptedBody | `fs` | SAME | fields()/elements() parse into a new array
src/rbac.tov:1274 | withIp | `m` | SAME | test helper: every call passes basic(...), a new map
src/realtime.tov:283 | sessionUpstream | `k` | DIVERGES fixed | t.key is the target's key, the stored config's when no alias override applies; the provider token went into it. Now copyKeyConfig(t.key)
src/realtimecalls.tov:32 | providerSession | `fs` | SAME | fields()/elements() parse into a new array
src/realtimecalls.tov:35 | providerSession | `audio` | SAME | fields()/elements() parse into a new array
src/realtimecalls.tov:36 | providerSession | `input` | SAME | fields()/elements() parse into a new array
src/realtimecalls.tov:37 | providerSession | `tr` | SAME | fields()/elements() parse into a new array
src/regex.tov:745 | ReParser.flagGroup | `f` | DIVERGES fixed | group() holds saved = this.flags and restores it after the group; f changed that same record, so (?i:..) would leak. Now a new Flags literal
src/regex.tov:1273 | charsOf | `cs` | SAME | emptyCset returns a new literal
src/respconv.tov:117 | RespConv.finish | `tail` | SAME | without() is a filter: a new array, and setField replaces elements
src/respconv.tov:643 | canonJson | `fs` | SAME | fields()/elements() parse into a new array
src/router.tov:454 | aliasOverrides | `n` | DIVERGES fixed | k is keys[i] of the stored provider config; now copyKeyConfig(k)
src/router.tov:456 | aliasOverrides | `az` | DIVERGES fixed | the per-provider block is the stored key's; now copied (copyAzureKeyConfig / copyVertexKeyConfig / copyBedrockKeyConfig / copyReplicateKeyConfig)
src/router.tov:469 | aliasOverrides | `vk` | DIVERGES fixed | the per-provider block is the stored key's; now copied (copyAzureKeyConfig / copyVertexKeyConfig / copyBedrockKeyConfig / copyReplicateKeyConfig)
src/router.tov:485 | aliasOverrides | `bk` | DIVERGES fixed | the per-provider block is the stored key's; now copied (copyAzureKeyConfig / copyVertexKeyConfig / copyBedrockKeyConfig / copyReplicateKeyConfig)
src/router.tov:496 | aliasOverrides | `rk` | DIVERGES fixed | the per-provider block is the stored key's; now copied (copyAzureKeyConfig / copyVertexKeyConfig / copyBedrockKeyConfig / copyReplicateKeyConfig)
src/rtsession.tov:109 | withSecret | `root` | SAME | fields()/elements() parse into a new array
src/rtsession.tov:114 | withSecret | `cs` | SAME | fields()/elements() parse into a new array
src/rtsession.tov:263 | withGaModel | `s` | SAME | callers pass without(...) (new) or assign the result back to the local they passed
src/rtsession.tov:264 | withGaModel | `audio` | SAME | objAt parses into a new array; the other arm is a literal
src/rtsession.tov:265 | withGaModel | `input` | SAME | objAt parses into a new array; the other arm is a literal
src/rtsession.tov:266 | withGaModel | `tr` | SAME | objAt parses into a new array; the other arm is a literal
src/rtsession.tov:278 | bareModelIn | `fs` | SAME | fields() parses into a new array
src/rtsession.tov:293 | bareNestedModels | `fs` | SAME | callers pass a new array or use only the result (build(...) / assigned back)
src/rtsession.tov:298 | bareNestedModels | `af` | SAME | audio and input come from objAt, new arrays
src/rtsession.tov:301 | bareNestedModels | `inf` | SAME | audio and input come from objAt, new arrays
src/rtsession.tov:359 | mintBody | `root` | SAME | fields()/elements() parse into a new array
src/rtsession.tov:382 | mintBody | `tr` | SAME | objAt parses into a new array; the other arm is a literal
src/rtsession.tov:434 | pinTranscriptionModel | `fs` | SAME | fields() parses into a new array
src/rtsession.tov:436 | pinTranscriptionModel | `session` | SAME | objAt parses into a new array; the other arm is a literal
src/rtsession.tov:440 | pinTranscriptionModel | `tr` | SAME | objAt parses into a new array; the other arm is a literal
src/scim.tov:267 | withTeam | `n` | SAME | userWith returns a new record (after the fix at :275)
src/scim.tov:275 | userWith | `n` | DIVERGES fixed | saveUser compares old with userWith(old, ...) in losesLastAdmin, and old is an element of st.users; now copyAdminUserConfig(u)
src/scim.tov:332 | pushedAttrs | `m` | SAME | callers pass new Map() or assign the result back to the map they passed (patchAttrs)
src/scim.tov:463 | saveUser | `next` | SAME | userWith returns a new record (after the fix at :275)
src/scim.tov:486 | patchUser | `attrs` | DIVERGES fixed | w.attrs was old.scim_attributes, the stored user's map, changed before validation and before the old/new comparisons; patchUser now starts from a copy of the map
src/semcache.tov:595 | test "promptText rules", () => {" | `ex` | SAME | returns a new literal
src/semcache.tov:644 | test "TTL, threshold override, partitions and eviction…" | `tiny` | SAME | returns a new literal
src/semcache.tov:678 | test "scopeKey respects config", () => {" | `noModel` | SAME | returns a new literal
src/semcache.tov:749 | test "identity scope: per virtual key by default, shar…" | `shared` | SAME | returns a new literal
src/server.tov:202 | bedrockPages | `t` | DIVERGES fixed | t0.key is the stored key (router.target); now a copied target and key take the chain credentials
src/server.tov:228 | ownListingIds | `lt` | DIVERGES fixed | t.key is the stored key; the minted Copilot/Entra token went into it. Now copyTarget + copyKeyConfig
src/server.tov:234 | ownListingIds | `nc` | DIVERGES fixed | lt.cfg.network_config is the stored one; now copyNetworkConfig
src/server.tov:236 | ownListingIds | `pc` | DIVERGES fixed | lt.cfg is the stored provider config; now copyProviderConfig
src/server.tov:253 | ownListingIds | `nb` | DIVERGES fixed | bk is the stored bedrock block; now copyBedrockKeyConfig
src/server.tov:1036 | withWebhooks | `n` | DIVERGES fixed | commitRebased(base, withX(base, ...)) needs base unchanged; now copyConfig(c)
src/server.tov:1042 | withAgents | `n` | DIVERGES fixed | commitRebased(base, withX(base, ...)) needs base unchanged; now copyConfig(c)
src/server.tov:1126 | cors | `h` | SAME | snapshot() builds a new map
src/server.tov:2136 | chatStreamed | `hs` | SAME | snapshot() builds a new map
src/server.tov:2313 | withClientIp | `hs` | SAME | snapshot() builds a new map
src/server.tov:2332 | withWatch | `hs` | SAME | snapshot() builds a new map
src/server.tov:2618 | test "a peer route's body is read only when a node sig…" | `h` | SAME | peerHeaders builds a new map
src/server.tov:2638 | test "a peer route's body is read only when a node sig…" | `other` | SAME | peerHeaders builds a new map
src/signinguard.tov:223 | SignInGuard.fail | `ts` | SAME | times() returns a filter result (new), and it is stored back with mem.set
src/sink_gcp.tov:208 | test "bigquery: content columns are absent when the en…" | `e` | SAME | test helper returns a new literal
src/sink_maxim.tov:593 | test "maxim: a chat row is the plugin's trace, in maxi…" | `e` | SAME | test helper returns a new literal
src/sink_maxim.tov:606 | test "maxim: a chat row is the plugin's trace, in maxi…" | `pref` | SAME | test helper returns a new literal
src/sink_maxim.tov:625 | test "maxim: without the bodies the trace has no messa…" | `e` | SAME | test helper returns a new literal
src/sink_maxim.tov:635 | test "maxim: x-raiju-maxim attributes name the trace, …" | `e` | SAME | test helper returns a new literal
src/sink_maxim.tov:661 | test "maxim: a generation named by the caller gets onl…" | `e` | SAME | test helper returns a new literal
src/sink_maxim.tov:672 | test "maxim: a generation named by the caller gets onl…" | `rt` | SAME | test helper returns a new literal
src/sink_maxim.tov:675 | test "maxim: a generation named by the caller gets onl…" | `mcp` | SAME | test helper returns a new literal
src/sink_maxim.tov:693 | test "maxim: chat image, file and audio parts are the …" | `e` | SAME | test helper returns a new literal
src/sink_maxim.tov:720 | test "maxim: chat image, file and audio parts are the …" | `named` | SAME | test: e is not read after named changes
src/sink_maxim.tov:729 | test "maxim: Responses parts and image-generation inpu…" | `r` | SAME | test helper returns a new literal
src/sink_maxim.tov:738 | test "maxim: Responses parts and image-generation inpu…" | `g` | SAME | test helper returns a new literal
src/sink_parquet.tov:82 | levels | `out` | SAME | uvarintOf returns a new array
src/sink_parquet.tov:269 | parquetFileWith | `body` | SAME | encode() result is new
src/starlark.tov:486 | Parser.smallStmt | `r` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:500 | Parser.smallStmt | `a` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:510 | Parser.smallStmt | `a` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:516 | Parser.smallStmt | `x` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:536 | Parser.ifStmt | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:557 | Parser.whileStmt | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:572 | Parser.forStmt | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:582 | Parser.defStmt | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:611 | Parser.lambdaExpr | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:629 | Parser.lambdaExpr | `r` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:637 | Parser.suite | `blk` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:659 | Parser.testList | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:681 | Parser.targetList | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:700 | Parser.test | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:714 | Parser.orTest | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:727 | Parser.andTest | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:740 | Parser.notTest | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:767 | Parser.comparison | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:782 | Parser.arith | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:797 | Parser.term | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:812 | Parser.factor | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:831 | Parser.postfix | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:843 | Parser.callArgs | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:875 | Parser.subscript | `ix` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:886 | Parser.subscript | `sl` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:897 | Parser.atom | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:908 | Parser.atom | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:915 | Parser.atom | `c` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:921 | Parser.atom | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:946 | Parser.parenthesized | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:968 | Parser.listDisplay | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:975 | Parser.listDisplay | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:999 | Parser.dictDisplay | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:1007 | Parser.dictDisplay | `n` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:1035 | Parser.clauses | `c` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:1043 | Parser.clauses | `c` | SAME | nd() returns a new node; it is filled, then returned or pushed, and not changed after
src/starlark.tov:2589 | test "while loops run until their condition fails, wit…" | `small` | SAME | returns a new literal
src/starlark.tov:2604 | test "limits: steps, output size, memory and recursion…" | `small` | SAME | returns a new literal
src/starlark.tov:2610 | test "limits: steps, output size, memory and recursion…" | `lo` | SAME | returns a new literal
src/starlark.tov:2667 | errOf | `small` | SAME | returns a new literal
src/startup.tov:124 | test "changedDefaults lists only what the config relie…" | `quiet` | SAME | test: busy is not read after quiet changes
src/store.tov:184 | withGov | `n` | DIVERGES fixed | withGov(this.cfg, g): commit keeps prev = this.cfg to restore on a failed save; now copyConfig(c)
src/store.tov:199 | withProviders | `n` | DIVERGES fixed | withProviders(this.cfg, ps): same as withGov; now copyConfig(c)
src/store.tov:205 | withKeys | `n` | DIVERGES fixed | p is the stored provider config; now copyProviderConfig(p)
src/store.tov:241 | dupLines | `next` | SAME | written straight back with ids.set
src/store.tov:304 | prepKey | `n` | SAME | kept is keyWithSecrets' new record (after the fix at :346)
src/store.tov:346 | keyWithSecrets | `n` | DIVERGES fixed | k is a stored key on the masking path (redactKey, restore false): masking would overwrite the stored secrets; now copyKeyConfig(k)
src/store.tov:349 | keyWithSecrets | `a` | DIVERGES fixed | the block is the stored key's; now its copyX (azure, vertex, workload identity, watsonx, databricks, github copilot, oauth)
src/store.tov:356 | keyWithSecrets | `v` | DIVERGES fixed | the block is the stored key's; now its copyX (azure, vertex, workload identity, watsonx, databricks, github copilot, oauth)
src/store.tov:360 | keyWithSecrets | `w` | DIVERGES fixed | the block is the stored key's; now its copyX (azure, vertex, workload identity, watsonx, databricks, github copilot, oauth)
src/store.tov:369 | keyWithSecrets | `w` | DIVERGES fixed | the block is the stored key's; now its copyX (azure, vertex, workload identity, watsonx, databricks, github copilot, oauth)
src/store.tov:374 | keyWithSecrets | `d` | DIVERGES fixed | the block is the stored key's; now its copyX (azure, vertex, workload identity, watsonx, databricks, github copilot, oauth)
src/store.tov:379 | keyWithSecrets | `g` | DIVERGES fixed | the block is the stored key's; now its copyX (azure, vertex, workload identity, watsonx, databricks, github copilot, oauth)
src/store.tov:384 | keyWithSecrets | `o` | DIVERGES fixed | the block is the stored key's; now its copyX (azure, vertex, workload identity, watsonx, databricks, github copilot, oauth)
src/store.tov:396 | bedrockSecrets | `n` | DIVERGES fixed | b is the stored bedrock block; now copyBedrockKeyConfig(b)
src/store.tov:787 | redactKey | `out` | SAME | keyWithSecrets returns a new record (after the fix at :346)
src/store.tov:796 | redactProvider | `px` | DIVERGES fixed | p.proxy_config is the stored block whose password was masked in place; now copyProxyConfig
src/store.tov:797 | redactProvider | `n` | DIVERGES fixed | p is the stored provider; now copyProviderConfig(p)
src/store.tov:870 | redactConfig | `n` | DIVERGES fixed | c is the stored config (GET /api/config); now copyConfig(c)
src/store.tov:875 | redactConfig | `g` | DIVERGES fixed | g0 is the stored governance section; now copyGovernanceConfig(g0)
src/store.tov:893 | redactConfig | `ms` | DIVERGES fixed | sc is the stored scim_config; now copyScimConfig(sc)
src/store.tov:894 | redactConfig | `mc` | DIVERGES fixed | sc.config is the stored provider settings whose secrets were masked in place; now copyScimProviderConfig
src/store.tov:1070 | sealAdminRow | `x` | SAME | a JSON round trip: new record
src/store.tov:1161 | transformSecrets | `out` | DIVERGES fixed | "The input is not changed": c is the live config being sealed for the file; now copyConfig(c)
src/store.tov:1165 | transformSecrets | `p` | DIVERGES fixed | ps.get(name) is the stored provider; now copyProviderConfig
src/store.tov:1170 | transformSecrets | `kk` | DIVERGES fixed | k is the stored key whose value was sealed in place; now copyKeyConfig(k)
src/store.tov:1185 | transformSecrets | `x` | DIVERGES fixed | stored webhook endpoint; now copyWebhookEndpoint(w)
src/store.tov:1202 | transformSecrets | `x` | DIVERGES fixed | stored agent; now copyAgentConfig(a)
src/store.tov:1210 | transformSecrets | `g` | DIVERGES fixed | stored governance section; now copyGovernanceConfig(gov)
src/store.tov:1213 | transformSecrets | `a` | DIVERGES fixed | stored auth_config; now copyAdminAuthConfig(au)
src/store.tov:1224 | transformSecrets | `x` | DIVERGES fixed | stored virtual key; now copyVirtualKeyConfig(vk)
src/store.tov:1234 | transformSecrets | `nm` | DIVERGES fixed | stored mcp section; now copyMcpConfig(mcp)
src/store.tov:1237 | transformSecrets | `x` | DIVERGES fixed | stored MCP client; now copyMcpClientConfig(cc)
src/store.tov:1240 | transformSecrets | `a` | DIVERGES fixed | stored MCP client auth; now copyMcpAuthConfig(au)
src/store.tov:1261 | transformSecrets | `x` | DIVERGES fixed | stored token row; now copyMcpUserToken
src/store.tov:1266 | transformSecrets | `mt` | DIVERGES fixed | out.mcp is still c.mcp when the config has no client_configs; now copyMcpConfig(out.mcp)
src/store.tov:1274 | transformSecrets | `x` | DIVERGES fixed | stored token row; now copyMcpUserToken
src/store.tov:1279 | transformSecrets | `ma` | DIVERGES fixed | out.mcp is still c.mcp when the config has no client_configs; now copyMcpConfig(out.mcp)
src/store.tov:1287 | transformSecrets | `x` | DIVERGES fixed | stored credential row; now copyMcpUserCredential(uc)
src/store.tov:1293 | transformSecrets | `mo` | DIVERGES fixed | out.mcp is still c.mcp when the config has no client_configs; now copyMcpConfig(out.mcp)
src/store.tov:1347 | withOwnCluster | `fs` | SAME | without() is a filter: a new array, and setField replaces elements
src/store.tov:1740 | ConfigStore.keepNewerAdmin | `c` | UNSURE copied | written back to this.cfg, but group's `before`, commit's prev and baseCfg can be that same record and are restored/compared after a failed save; now copyConfig(this.cfg)
src/store.tov:1741 | ConfigStore.keepNewerAdmin | `m` | UNSURE copied | c.mcp is shared with those held configs; now copyMcpConfig
src/store.tov:1792 | ConfigStore.setPromptRepo | `n` | DIVERGES fixed | commit(n) keeps prev = this.cfg to restore after a failed save (and group keeps `before`, saveLocked baseCfg); n was that same record. Now copyConfig(this.cfg)
src/store.tov:1799 | ConfigStore.setAgents | `n` | DIVERGES fixed | commit(n) keeps prev = this.cfg to restore after a failed save (and group keeps `before`, saveLocked baseCfg); n was that same record. Now copyConfig(this.cfg)
src/store.tov:1806 | ConfigStore.setWebhooks | `n` | DIVERGES fixed | commit(n) keeps prev = this.cfg to restore after a failed save (and group keeps `before`, saveLocked baseCfg); n was that same record. Now copyConfig(this.cfg)
src/store.tov:1813 | ConfigStore.setFeatureFlags | `n` | DIVERGES fixed | commit(n) keeps prev = this.cfg to restore after a failed save (and group keeps `before`, saveLocked baseCfg); n was that same record. Now copyConfig(this.cfg)
src/store.tov:1820 | ConfigStore.setUserAgentMappings | `n` | DIVERGES fixed | commit(n) keeps prev = this.cfg to restore after a failed save (and group keeps `before`, saveLocked baseCfg); n was that same record. Now copyConfig(this.cfg)
src/store.tov:1827 | ConfigStore.setPlugins | `n` | DIVERGES fixed | commit(n) keeps prev = this.cfg to restore after a failed save (and group keeps `before`, saveLocked baseCfg); n was that same record. Now copyConfig(this.cfg)
src/store.tov:1834 | ConfigStore.setAlerts | `n` | DIVERGES fixed | commit(n) keeps prev = this.cfg to restore after a failed save (and group keeps `before`, saveLocked baseCfg); n was that same record. Now copyConfig(this.cfg)
src/store.tov:1841 | ConfigStore.setProfiles | `g` | DIVERGES fixed | g was the stored governance record, changed before commit (and on early-return error paths); now gov(this.cfg), which returns a copy
src/store.tov:1848 | ConfigStore.setApiKeys | `g` | DIVERGES fixed | g was the stored governance record, changed before commit (and on early-return error paths); now gov(this.cfg), which returns a copy
src/store.tov:1855 | ConfigStore.setUsers | `g` | DIVERGES fixed | g was the stored governance record, changed before commit (and on early-return error paths); now gov(this.cfg), which returns a copy
src/store.tov:1866 | ConfigStore.upgradePasswords | `next` | DIVERGES fixed | u is a stored user; now copyAdminUserConfig(u)
src/store.tov:1883 | ConfigStore.setClaimSync | `g` | DIVERGES fixed | g was the stored governance record, changed before commit (and on early-return error paths); now gov(this.cfg), which returns a copy
src/store.tov:1892 | ConfigStore.setScimToken | `sc` | DIVERGES fixed | stored scim_config; now copyScimConfig
src/store.tov:1893 | ConfigStore.setScimToken | `c` | DIVERGES fixed | stored scim provider settings; now copyScimProviderConfig
src/store.tov:1896 | ConfigStore.setScimToken | `n` | DIVERGES fixed | commit(n) keeps prev = this.cfg to restore after a failed save (and group keeps `before`, saveLocked baseCfg); n was that same record. Now copyConfig(this.cfg)
src/store.tov:1904 | ConfigStore.setProvisioned | `g` | DIVERGES fixed | g was the stored governance record, changed before commit (and on early-return error paths); now gov(this.cfg), which returns a copy
src/store.tov:1915 | ConfigStore.setProvisioned | `n` | DIVERGES fixed | p is a stored project; now copyProjectConfig(p)
src/store.tov:1927 | ConfigStore.setScim | `g` | DIVERGES fixed | g was the stored governance record, changed before commit (and on early-return error paths); now gov(this.cfg), which returns a copy
src/store.tov:1935 | ConfigStore.setUserProfile | `g` | DIVERGES fixed | g was the stored governance record, changed before commit (and on early-return error paths); now gov(this.cfg), which returns a copy
src/store.tov:1945 | ConfigStore.setUserProfile | `nu` | DIVERGES fixed | u is a stored user; now copyAdminUserConfig(u)
src/store.tov:1959 | ConfigStore.setUserBudgetOverride | `g` | DIVERGES fixed | g was the stored governance record, changed before commit (and on early-return error paths); now gov(this.cfg), which returns a copy
src/store.tov:1971 | ConfigStore.setUserBudgetOverride | `nu` | DIVERGES fixed | u is a stored user; now copyAdminUserConfig(u)
src/store.tov:1983 | ConfigStore.setVkProfile | `g` | DIVERGES fixed | g was the stored governance record, changed before commit (and on early-return error paths); now gov(this.cfg), which returns a copy
src/store.tov:1987 | ConfigStore.setVkProfile | `nvk` | DIVERGES fixed | vk is a stored virtual key; now copyVirtualKeyConfig(vk)
src/store.tov:1997 | ConfigStore.replaceVirtualKeys | `g` | DIVERGES fixed | g was the stored governance record, changed before commit (and on early-return error paths); now gov(this.cfg), which returns a copy
src/store.tov:2004 | ConfigStore.setProxy | `n` | DIVERGES fixed | commit(n) keeps prev = this.cfg to restore after a failed save (and group keeps `before`, saveLocked baseCfg); n was that same record. Now copyConfig(this.cfg)
src/store.tov:2011 | ConfigStore.setCircuitPolicies | `n` | DIVERGES fixed | commit(n) keeps prev = this.cfg to restore after a failed save (and group keeps `before`, saveLocked baseCfg); n was that same record. Now copyConfig(this.cfg)
src/store.tov:2018 | ConfigStore.setMetadata | `n` | DIVERGES fixed | commit(n) keeps prev = this.cfg to restore after a failed save (and group keeps `before`, saveLocked baseCfg); n was that same record. Now copyConfig(this.cfg)
src/store.tov:2025 | ConfigStore.setClient | `n` | DIVERGES fixed | commit(n) keeps prev = this.cfg to restore after a failed save (and group keeps `before`, saveLocked baseCfg); n was that same record. Now copyConfig(this.cfg)
src/store.tov:2032 | ConfigStore.setPricingSync | `n` | DIVERGES fixed | commit(n) keeps prev = this.cfg to restore after a failed save (and group keeps `before`, saveLocked baseCfg); n was that same record. Now copyConfig(this.cfg)
src/store.tov:2039 | ConfigStore.setAdminAuth | `g` | DIVERGES fixed | g was the stored governance record, changed before commit (and on early-return error paths); now gov(this.cfg), which returns a copy
src/store.tov:2046 | ConfigStore.setBudgetOverride | `g` | DIVERGES fixed | g was the stored governance record, changed before commit (and on early-return error paths); now gov(this.cfg), which returns a copy
src/store.tov:2064 | ConfigStore.upsertRoutingRule | `g` | DIVERGES fixed | g was the stored governance record, changed before commit (and on early-return error paths); now gov(this.cfg), which returns a copy
src/store.tov:2070 | ConfigStore.deleteRoutingRule | `g` | DIVERGES fixed | g was the stored governance record, changed before commit (and on early-return error paths); now gov(this.cfg), which returns a copy
src/store.tov:2079 | ConfigStore.setComplexity | `n` | DIVERGES fixed | commit(n) keeps prev = this.cfg to restore after a failed save (and group keeps `before`, saveLocked baseCfg); n was that same record. Now copyConfig(this.cfg)
src/store.tov:2110 | ConfigStore.putProvider | `ps` | SAME | copyProviders builds a new map
src/store.tov:2141 | ConfigStore.deleteProvider | `ps` | SAME | copyProviders builds a new map
src/store.tov:2199 | ConfigStore.upsertVirtualKey | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2246 | ConfigStore.rotateVirtualKey | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2279 | ConfigStore.deleteVirtualKey | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2289 | ConfigStore.upsertBudget | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2302 | ConfigStore.deleteBudget | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2314 | ConfigStore.upsertRateLimit | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2327 | ConfigStore.deleteRateLimit | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2338 | ConfigStore.upsertTeam | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2356 | ConfigStore.deleteTeam | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2367 | ConfigStore.upsertCustomer | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2380 | ConfigStore.deleteCustomer | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2407 | ConfigStore.upsertProject | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2422 | ConfigStore.deleteProject | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2430 | ConfigStore.addProjectMembers | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2449 | ConfigStore.addProjectMembers | `np` | DIVERGES fixed | pj is a stored project; now copyProjectConfig(pj)
src/store.tov:2457 | ConfigStore.removeProjectMember | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2465 | ConfigStore.removeProjectMember | `np` | DIVERGES fixed | pj is a stored project; now copyProjectConfig(pj)
src/store.tov:2474 | ConfigStore.setMemberShares | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2497 | ConfigStore.setMemberShares | `np` | DIVERGES fixed | pj is a stored project; now copyProjectConfig(pj)
src/store.tov:2508 | ConfigStore.upsertBusinessUnit | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2524 | ConfigStore.deleteBusinessUnit | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2561 | ConfigStore.saveRole | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2584 | ConfigStore.deleteRole | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2598 | ConfigStore.deleteRole | `np` | DIVERGES fixed | p is a stored access profile; now copyAccessProfile(p)
src/store.tov:2612 | ConfigStore.attachProfileRoles | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2619 | ConfigStore.attachProfileRoles | `np` | DIVERGES fixed | p is a stored access profile; now copyAccessProfile(p)
src/store.tov:2644 | ConfigStore.detachProfileRole | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2650 | ConfigStore.detachProfileRole | `np` | DIVERGES fixed | p is a stored access profile; now copyAccessProfile(p)
src/store.tov:2669 | ConfigStore.upsertModelConfig | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2694 | ConfigStore.deleteModelConfig | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2706 | ConfigStore.upsertProviderGov | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2726 | ConfigStore.deleteProviderGov | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2740 | ConfigStore.savePricingOverride | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:2758 | ConfigStore.deletePricingOverride | `g` | DIVERGES fixed | gov() returned the stored governance record, changed before commit and on error returns; fixed once in gov(), which now returns copyGovernanceConfig (fields are only reassigned here, never changed in place)
src/store.tov:3770 | businessUnitUsers | `u` | DIVERGES fixed | next[i] is a stored user, changed before setUsers saves; now copyAdminUserConfig
src/store.tov:3771 | businessUnitUsers | `held` | DIVERGES fixed | u.business_units is the stored user's list; now sliced
src/store.tov:3785 | businessUnitUsers | `u` | DIVERGES fixed | next[i] is a stored user, changed before setUsers saves; now copyAdminUserConfig
src/store.tov:4189 | providerRoute | `k` | SAME | parseKey is JSON.parse: new record
src/store.tov:4307 | frameworkPlan | `ps` | DIVERGES fixed | cur is store.cfg.pricing_sync; now copyPricingSyncConfig
src/store.tov:4403 | putConfig | `cl` | DIVERGES fixed | store.cfg.client is the stored section (c is this request's parsed body); now copyClientConfig on that arm
src/store.tov:5844 | test "team members: the users whose teams name the tea…" | `g` | SAME | test: gov() now returns a copy
src/store.tov:5846 | test "team members: the users whose teams name the tea…" | `n` | SAME | test: written straight back with s.cfg = n
src/store.tov:5865 | test "business-unit members carry their source; admins…" | `g` | SAME | test: gov() now returns a copy
src/store.tov:5866 | test "business-unit members carry their source; admins…" | `us` | SAME | test: changed and stored back (us[0] = first; g.users = us; s.cfg = n) with no read of s.cfg in between
src/store.tov:5867 | test "business-unit members carry their source; admins…" | `first` | SAME | test: changed and stored back (us[0] = first; g.users = us; s.cfg = n) with no read of s.cfg in between
src/store.tov:5872 | test "business-unit members carry their source; admins…" | `n` | SAME | test: written straight back with s.cfg = n
src/store.tov:6253 | agentsSet | `n` | DIVERGES fixed | test helper: commitRebased(b2, agentsSet(b2, [])) needs b2 unchanged; now copyConfig(c)
src/store.tov:6367 | test "group commit: a save made inside a group waits f…" | `n` | SAME | test: written straight back with s.cfg = n
src/streamconv.tov:1275 | test "a held thing over holdMax is refused", () => {" | `o` | SAME | test helper returns a new literal
src/streams.tov:221 | OpenAIPassthrough.rewrite | `fs` | SAME | fields()/elements() parse into a new array
src/textconv.tov:363 | canon | `fs` | SAME | fields()/elements() parse into a new array
src/tokenexchange.tov:335 | renewedRow | `n` | UNSURE copied | row is the caller's stored credential (renewAdmin's callers are in mcp/ops and keep the old row to compare); now copyMcpUserToken(row)
src/tokenexchange.tov:347 | reverifyRow | `n` | UNSURE copied | row is the caller's stored credential (renewAdmin's callers are in mcp/ops and keep the old row to compare); now copyMcpUserToken(row)
src/tokenexchange.tov:530 | test "the next renewal is the earliest due time of the…" | `other` | SAME | test helper returns a new literal
src/tokenexchange.tov:533 | test "the next renewal is the earliest due time of the…" | `b` | SAME | test helper returns a new literal
src/uiserve.tov:144 | embedded | `m` | SAME | the map is created here when missing and stored to index at once
src/wasmplugin.tov:181 | canon | `fs` | SAME | fields() parses into a new array
src/wasmplugin.tov:220 | applyRequestFor | `nb` | SAME | fields()/elements() parse into a new array
src/wasmplugin.tov:984 | reqWith | `r` | SAME | emptyReq returns a new literal
src/wasmplugin.tov:1012 | test "http_pre_hook rewrites the request body and head…" | `req` | SAME | emptyReq returns a new literal
src/wasmplugin.tov:1054 | test "http_pre_hook can answer the request, fail it, o…" | `req` | SAME | emptyReq returns a new literal
src/wasmplugin.tov:1066 | test "a plugin with no http setting passes the transpo…" | `req` | SAME | emptyReq returns a new literal
src/webhooks.tov:134 | DeliveryLog.refresh | `merged` | SAME | this.rows is stored back; unchanged when nothing merged; nothing reads this.rows in between
src/webhooks.tov:339 | attemptOnce | `hm` | SAME | headersFor builds a new map
src/webrtc.tov:211 | withJsonAt | `fs` | SAME | fields()/elements() parse into a new array
src/wsresponses.tov:41 | eventBody | `fs` | SAME | fields()/elements() parse into a new array

## Found outside the list

Fixed here:

- `src/router.tov` `aliasOverrides`: the early `return k` (no alias) handed the stored key out as `Target.key`. It
  now returns `copyKeyConfig(k)`. This also covers writers of `t.key.…` that are not in this list (see below).
- `src/profiles.tov` `copyOf`: its `catch` returned `p` itself; it now returns `copyAccessProfile(p)`.

Not fixed (outside this list's files, or left as they are); for whoever holds those files:

- The brief's `new Map(m)` is not accepted by the pinned compiler (`U0017 new Map(entries) is not supported yet`).
  A map is copied with a loop: `for (const k of m.keys()) out.set(k, m.get(k)!)` (as in `scim.tov` `patchUser`).
- `src/gateway.tov:2512-2583` and `src/media.tov:500` write minted tokens and credentials into `t.key.value` /
  `t.key.bedrock_key_config`. With the `aliasOverrides` change a target from `router.target` carries its own key, so
  these no longer reach the stored config; a `Target` built any other way from a stored key would. `t.cfg` is still
  the stored provider config: nothing may change it in place (`anthropic_route.tov` and `server.tov` now copy).
- `src/ops.tov` `dirNow()`, `removeUsersNow` and `scimResynced` build a `Directory` whose lists are the stored
  config's. `provision.tov` no longer adds to them, but `src/claimsync.tov:237` and `:248` (list A) do, inside
  `applyClaims`: `let teams = d.teams … teams.push(t)` and the same for `bus`. Under sharing that push lands in the
  plan's directory and `applyInto` then pushes the same new team again (twice in the directory), and a caller of
  `applyClaims` that passes the stored lists directly gets them changed. They need `d.teams.slice()` /
  `d.businessUnits.slice()`.
- `src/mcpapi.tov` `persist(store, next)` (line 191) does what `ConfigStore.commit` does: `prev = store.cfg`, set,
  save, put `prev` back on failure. Every `next` its callers build must be another record than `store.cfg`
  (`copyConfig`), as the store's own setters now are; the tests there also write `s.cfg.mcp!.user_credentials = …`
  (`:2704`, `:2738`) and `s.cfg.client = …` (`:2871`, `:2879`) straight into the held config.
- `src/mcp.tov:2105` (test): `let renewed = row; renewed.access_token = "admin-2"` changes `row`.
- `src/scim.tov` `patchAttrs`, op `remove`: `for (const k of m.keys()) { … m.delete(k) }` deletes from the map it
  walks. Today the loop walks a snapshot of the keys. Deleting the current key during a JavaScript `Map` iteration
  is defined and visits every remaining key, so it was left; it depends on `keys()` behaving that way in v0.1.0.
- Parameters changed in place without a local alias (`function f(r: R) { r.x = 1 }`) are not in the compiler's
  list. A text search of this half's files found only class instances changed that way (already shared today), no
  records, arrays or maps. The other half was not searched.

## Verification (today's compiler, image raiju:dev4)

- `scripts/check.py --no-fix` on every changed source: no diagnostics.
- `tov test src/main.tov` with `TOV_CFLAGS=-DTV_PLAIN_ALLOC` on the final tree: 2639 passed, 0 failed.
- `python3 -m unittest tests/test_fetch_lint.py tests/test_copy_lint.py tests/test_gen_config_doc.py tests/test_smoke_config.py`: OK.
- Not run: `tests/e2e.py` (ports in use), and nothing was run on Tov v0.1.0, so the fixes are checked for today's
  behaviour only; that they are sufficient under sharing rests on the reading recorded above.

# String positions, second third of the modules (branch mig-t2)

46 listed files plus src/cel.tov. Counts are occurrences of `byteLength` before the change:
POSITION (now `strLen`, or the position logic rewritten), BYTES (kept), CROSSING (restructured).

## A fact the brief has wrong

On the pinned compiler a slice that starts or ends inside a character does not cut the character: it traps
(`string index 1 is not on a UTF-8 character boundary`). So every loop that probed a string one position at
a time (`s.slice(i, i + 1)`), every "last position" taken without an `endsWith` guard, and every fixed
offset into text that was not checked first, was a trap on today's compiler as soon as the text held a
non-ASCII character, and a silent wrong cut on v0.1.0. `strLen` alone fixes neither. Those places now walk
`chars()`, test with `startsWith`/`endsWith`, or check for ASCII first (list under "Behaviour changes").

## Per file

| file | POSITION | BYTES | CROSSING |
|---|---|---|---|
| src/a2agrpc.tov | 4 | 0 | 0 |
| src/affinity.tov | 1 | 1 | 0 |
| src/agenthistory.tov | 1 | 0 | 0 |
| src/authproxy.tov | 2 | 0 | 0 |
| src/awsprofile.tov | 5 | 0 | 0 |
| src/claimsync.tov | 1 | 0 | 0 |
| src/config_compat.tov | 6 | 0 | 0 |
| src/crew.tov | 2 | 4 | 0 |
| src/discovery.tov | 5 | 3 | 0 |
| src/extras.tov | 2 | 0 | 0 |
| src/governance.tov | 2 | 0 | 0 |
| src/guard_reversible.tov | 1 | 0 | 0 |
| src/guardrail_providers.tov | 3 | 0 | 1 |
| src/hpack.tov | 0 | 2 | 0 |
| src/jobs.tov | 4 | 4 | 3 (+1 without byteLength) |
| src/live.tov | 3 | 1 | 0 |
| src/mcpapi.tov | 4 | 2 | 0 |
| src/mcpinstructions.tov | 0 | 7 | 1 (+2 without byteLength) |
| src/mcpissuer.tov | 17 | 16 | 0 |
| src/mcpuser.tov | 1 | 0 | 0 |
| src/media_cloud.tov | 3 | 0 | 0 |
| src/media_native.tov | 3 | 2 | 0 |
| src/notify.tov | 0 | 2 | 0 |
| src/oauth_key.tov | 0 | 1 | 0 |
| src/objowner.tov | 3 | 0 | 0 |
| src/openapi.tov | 10 | 6 | 0 (+2 without byteLength) |
| src/passthrough.tov | 1 | 4 | 0 |
| src/pluginroute.tov | 3 | 0 | 0 |
| src/plugins.tov | 7 | 3 | 0 |
| src/prompts.tov | 1 | 0 | 0 |
| src/providers/bedrock.tov | 2 | 0 | 0 |
| src/providers/huggingface.tov | 1 | 0 | 0 |
| src/providers/openai.tov | 4 | 0 | 0 |
| src/providers/vertex.tov | 1 | 0 | 0 |
| src/retained.tov | 0 | 3 | 0 |
| src/schemas.tov | 0 | 1 | 0 |
| src/signinguard.tov | 1 | 0 | 0 |
| src/sink_maxim.tov | 4 | 1 | 0 |
| src/starlark.tov | 1 | 27 | 0 |
| src/store.tov | 8 | 3 | 3 |
| src/streams.tov | 4 | 0 | 0 |
| src/streams_cohere.tov | 2 | 0 | 0 |
| src/uiserve.tov | 8 | 0 | 0 |
| src/vectorstore.tov | 0 | 7 | 0 |
| src/vmcp.tov | 2 | 1 | 0 |
| src/webrtc.tov | 0 | 4 | 0 |
| src/cel.tov (not in a list) | 0 | 0 | 0 (+5 without byteLength) |

BYTES kept: limits and sizes in bytes (name, scope, state, redirect and token caps in mcpissuer, crew,
passthrough, notify, vmcp, affinity, live), budgets and charges (all of starlark's `charge` and
`max_value_bytes`, hpack's table size, retained, webrtc's transcript budget, jobs' token estimate, the
mcpinstructions caps and "bytes omitted" counts), "is one ASCII character" tests on a value from `chars()`
or a decoded byte (`ch.byteLength === 1`, openapi, starlark, vectorstore, media_native), the ASCII test
`name.byteLength !== name.chars().length` (mcpapi), RESP lengths (vectorstore), and length checks on ids in
tests.

## Crossings

- src/cel.tov `lex`: the lexer walks the UTF-8 bytes and cut token text with `src.slice(i, j)` at byte
  offsets. Token text (numbers, identifiers, operators: all ASCII) is now decoded from the bytes
  (`asciiOf`). Error columns stay byte offsets, as before, on both compilers. This was the failing
  "string literals, concatenation and methods".
- src/guardrail_providers.tov `presidioVerdict`: Presidio's offsets are code points; they were turned into
  byte offsets and used as string positions. The text is now cut as `text.chars()` slices, indexed by the
  code point offsets directly (`cpIndex`; an offset past the text, negative or not whole is the end of the
  text, as before). `cpToByte` and the module's unused `enc` are gone.
- src/mcpinstructions.tov `sanitizeBody` and `truncateOnChar`: byte scans whose offsets cut the string.
  The pieces are now decoded from the bytes (`textOf(b, from, to)`); the cap stays in bytes and the cut is
  still moved back to a character boundary.
- src/openapi.tov `cutUtf8`: the same (a byte cap cut with `s.slice(0, cut)`); now decodes the byte prefix.
  The BOM was skipped with `t.slice(3)` (its byte length); now `strLen("\u{FEFF}")`.
- src/jobs.tov `wordsOf`: byte ranges cut from the string; now built from `chars()` (a character of more
  than one byte stays inside a word, as before). `sameOwner` compared position by position under a byte
  length; it now compares the UTF-8 bytes, still without stopping at the first difference.
- src/store.tov `maskSecret` / `looksMasked`: a byte length used as positions (`v.slice(n - 4)`) and a byte
  count of "…" compared with it. Both now count and cut characters (see behaviour changes).

Position logic kept as string positions throughout (no crossing, `strLen`): the registry and count-log
read offsets in src/mcpissuer.tov (`registryAt`, `countsAt`: offsets into the file's text, kept in memory
only, never written or compared with a file size), src/guard_reversible.tov `tokenize` (see "Not
settled"), the SSE and stream helpers, and every "drop this prefix / suffix" site.

## Behaviour changes on today's compiler

1. `maskSecret` (src/store.tov) counts characters, not bytes: a secret of fewer than 24 characters is
   "****" even when it is 24 bytes or more (twelve CJK characters used to show eight of them), and the
   shown pieces are the first and last four characters. Before, a non-ASCII secret was cut at byte 4 and
   byte n-4, which trapped when either fell inside a character. `looksMasked` accepts the same shape (nine
   characters with "…"). ASCII secrets are unchanged.
2. These trapped on the pinned compiler when given non-ASCII text and now return an answer (the same answer
   on both compilers); for ASCII text nothing changes:
   - src/a2agrpc.tov `trimDots` (an :authority with a non-ASCII label)
   - src/affinity.tov `sessionTtl` (an `x-raiju-session-ttl` header ending in a non-ASCII character)
   - src/claimsync.tov `glob` (a claim value with a non-ASCII character after the pattern's head)
   - src/crew.tov `onlyChars` (`validName`, `validTask`)
   - src/governance.tov `durationMs`
   - src/jobs.tov `sameOwner`, `isJobId`
   - src/live.tov `validId` (a session id from the request path)
   - src/media_native.tov `isoSeconds` (non-ASCII text is refused before the fixed positions are read)
   - src/openapi.tov `fallbackName` (a path with non-ASCII characters)
   - src/plugins.tov `goDurationMs` (so "5µs" now parses; it could not before)
   - src/providers/bedrock.tov `isRegionName` (a model prefix such as "é-日/")
   - src/store.tov `validDuration`, `isNumeric`
   - src/vmcp.tov `validate` (a pattern such as "日*")
3. No other change: the byte caps in mcpinstructions and openapi already cut on a character boundary, and
   cel, presidio and `wordsOf` give the results they gave.

## Tests added (2-byte é, 3-byte 日, 4-byte 🙂 before the position computed; same expectations on both compilers)

cel (lexer after multibyte literals, error column), guardrail_providers (presidio offsets, out-of-range and
fractional offsets), mcpinstructions (tag escaping, every cap around each character, aggregate,
commentBlock), store (maskSecret, looksMasked, keepSecret, maskJson, validDuration, isNumeric), openapi
(cutUtf8, sanitizeName, truncateName, fallbackName, toolName, resolveRelative, BOM), jobs (wordsOf,
sameOwner, isJobId), awsprofile (parseIni, splitExit), a2agrpc (agentOfAuthority, trimDots, keyOf),
affinity (sessionTtl), claimsync (glob), guard_reversible (tokenize, tokenizeChatRequest), plugins
(parsePluginError, goDurationMs, unfence, JsonStreamFixer), media_cloud (bucketKey, s3Items, windowHours),
media_native (bareName, isoSeconds), sink_maxim (parsed), uiserve (etagMatches, acceptsGzip), vmcp
(patternPrefix, validate), objowner (lookupForms, geminiFileName), config_compat (goSeconds,
bulkSyncInterval, profileId), discovery (timeoutMs, etcdRangeEnd, baseUrl), mcpuser (userOfMark),
passthrough (routeFor), live (attachId, contentId, validId), crew (validName), governance (durationMs),
providers/bedrock (regionPrefix), mcpissuer (the registry read from where it left off after non-ASCII
client names).

No non-ASCII test was added where the change is only `x.slice(0, strLen(x) - n)` after an `endsWith`, or
`x.slice(strLen(prefix))` after a `startsWith`, in a function that needs a request or provider fixture:
agenthistory, authproxy, extras, mcpapi, pluginroute, prompts, signinguard, providers/huggingface, openai
and vertex, starlark (the operator is ASCII), and the test helpers of streams and streams_cohere.

## Not settled

- src/store.tov "the config view masks secrets in every section" (and the `maskJson` line of the new
  store test, and the `tokenizeChatRequest` line of the new guard_reversible test) fail on v0.1.0 in this
  tree alone: they go through `fields` in src/json.tov and the scanners behind src/guardrails.tov, which
  are in the other workers' lists. Nothing in store.tov is wrong for them: in a scratch merge of this
  branch with mig-t1 and mig-t3 all three pass (see "Results").
- src/guard_reversible.tov `tokenize` takes `Finding.start` / `Finding.end` as positions in the string it
  is given. That holds only if the scanners in guardrails / guard_regex report string positions (not byte
  offsets) on both compilers, which is the other workers' side.
- Fixed offsets after a case-insensitive test (`auth.toLowerCase().startsWith("bearer ")` then
  `auth.slice(7)`, in a2agrpc, governance, mcpissuer) are left: no non-ASCII character lower-cases into
  the letters of "bearer ", so the seven positions are the seven ASCII characters.
- No function was added to src/text.tov.

## Results

Whole unit suite (`test src/main.tov`), final tree of this branch:
- pinned compiler: 2670 passed, 0 failed (2642 before, plus 28 new tests).
- Tov v0.1.0: 2646 passed, 24 failed. 21 are the other workers' cases from strings-failing.txt; the other
  three are the store test, and one line each of the new store and guard_reversible tests, all through
  src/json.tov or the guardrail scanners. cel, presidio and mcpinstructions pass.

Scratch merge of mig-t2 + mig-t1 + mig-t3 (not committed anywhere; src/text.tov and
migration/tov-0.1.0/text.tov conflict between mig-t1 and mig-t3, which both add helpers after strLen, and
were joined by hand keeping both sets; the three STRINGS-NOTES.md also conflict by name):
- pinned compiler: 2728 passed, 0 failed.
- Tov v0.1.0: 2728 passed, 0 failed.

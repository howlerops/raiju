# String positions, worker 3 (branch mig-t3)

Scope: the 46 files of `strings-3.txt`. Every `byteLength` use and every computed slice in them was read.
Counts are occurrences of `byteLength` at the start (`0044a4e`): POSITION (now `strLen`, or the walk was
rewritten), BYTES (kept), CROSSING (restructured).

## A fact the brief had wrong, which shaped the work

On the pinned compiler a slice cannot cut a character either: `s.slice(a, b)` with `a` or `b` inside a
character **traps** (`trap: string index N is not on a UTF-8 character boundary`). On v0.1.0 the same slice
gives U+FFFD for half a surrogate pair. So a walk of one position at a time (`s.slice(i, i + 1)`, `i++`) over
text that may hold a non-ASCII character is wrong on both compilers: it traps today and misreads 4-byte
characters on v0.1.0. Several such walks were reachable with ordinary input on today's compiler, without any
test: see "Behaviour changes on today's compiler". They are fixed here because the one source that is right on
both compilers cannot step that way.

## Helpers added to `src/text.tov` and `migration/tov-0.1.0/text.tov` (same tests in both)

- `posSpan(b, from, to)`: how many string positions the UTF-8 bytes `b[from, to)` take. **Two bodies**
  (pinned: `to - from`; v0.1.0: counts UTF-16 units from the lead bytes). This is the one function that could
  not be written once. It turns an offset found in a string's bytes into a position in the string.
- `asciiShape(s)`: `s` with every non-ASCII character replaced by U+007F once per position it takes, so the
  result has the same positions as `s` and a character at each. One body (built on `chars()` and `strLen`).
  A scanner that steps one position at a time walks the shape and cuts its pieces from `s`.
- `bytePrefix(s, max)`: the longest prefix of whole characters within `max` bytes. One body.

Other workers may have added their own equivalents; these three are the candidates to keep when merging.

## Per file

| file | POSITION | BYTES | CROSSING | notes |
|---|---|---|---|---|
| src/json.tov | 1 | 0 | 1 (no byteLength) | see below |
| src/guardrails.tov | 1 | 0 | 3 | see below |
| src/complexity.tov | 3 | 0 | 1 (no byteLength) | see below |
| src/yaml.tov | 31 | 0 | 0 | every scanner walked by position; see below |
| src/guard_stream.tov | 24 | 2 | 0 | window sizes are positions; see below |
| src/semcache.tov | 1 | 0 | 4 | see below |
| src/mcp.tov | 4 | 1 | 1 (no byteLength) | `sanitizeName`, see below |
| src/pluginmerge.tov | 0 | 1 | 1 | `isRedacted`, see below |
| src/realtime.tov | 1 | 1 | 1 | close reason cut with `bytePrefix` |
| src/codemode.tov | 3 | 2 | 1 (the kept limit's slice) | `oneLine` cut with `bytePrefix` |
| src/apikeys.tov | 0 | 1 | 1 (no byteLength) | `keyPrefixOf` cut with `bytePrefix` |
| src/a2aext.tov | 1 | 1 | 0 | first character read from the shape |
| src/agentauth.tov | 1 | 0 | 0 | |
| src/anthropic_batch.tov | 3 | 2 | 0 | kept: zero padding width, 64-byte id limit |
| src/audit_archive.tov | 2 | 1 | 0 | kept: part size in bytes |
| src/cache.tov | 4 | 3 | 0 | kept: stored body length, 64-byte id; `isCacheId` walks characters |
| src/cluster.tov | 0 | 7 | 0 | secret size, emptiness, Content-Length |
| src/config.tov | 2 | 1 (+1 loop bound removed) | 0 | slug check walks characters |
| src/consoleconfig.tov | 5 | 8 | 0 | kept: DNS and port length limits |
| src/exports.tov | 1 | 0 | 0 | `dayOfKey` reads the date from the shape |
| src/feed.tov | 1 | 1 | 0 | `lastColon` walks the shape |
| src/genai_in.tov | 11 | 0 | 0 | |
| src/grpcstatus.tov | 1 | 0 | 0 | |
| src/headerfilter.tov | 2 | 0 | 0 | |
| src/health.tov | 2 | 0 | 0 | |
| src/logapi.tov | 7 | 0 | 0 | `timeOf` refuses non-ASCII, then reads fixed positions |
| src/mcplibrary.tov | 1 | 2 | 0 | kept: `ch.byteLength === 1` (is ASCII), 50 MB limit |
| src/metrics.tov | 5 | 0 | 0 | sample lines walked on the shape; label names by character |
| src/nativehook.tov | 1 | 0 | 0 | test chunking |
| src/netguard.tov | 3 | 0 | 0 | |
| src/oidc.tov | 8 | 8 | 0 | kept: length limits and test sizes; validators walk characters |
| src/passhash.tov | 2 | 1 | 0 | kept: 60-byte hash; `parse` refuses non-ASCII before fixed positions |
| src/pricing.tov | 5 | 6 | 0 | kept: ordering by length; `stripDate`/`startsAt` rewritten |
| src/profiles.tov | 5 | 6 | 0 | loops are behind `asciiOnly`; bounds now `strLen` |
| src/providers/anthropic_route.tov | 2 | 0 | 0 | `oSeries` reads the shape |
| src/providers/decision_native.tov | 1 | 0 | 0 | |
| src/providers/githubcopilot.tov | 1 | 2 | 0 | `digits` walks characters |
| src/providers/types.tov | 1 | 0 | 0 | |
| src/respconv.tov | 1 | 1 | 0 | |
| src/router.tov | 1 | 0 | 0 | |
| src/scim.tov | 4 | 0 | 0 | |
| src/server.tov | 9 | 2 | 0 | kept: path segment length heuristics |
| src/streamconv.tov | 4 | 0 | 0 | |
| src/textconv.tov | 0 | 2 | 0 | held bytes |
| src/webhooks.tov | 2 | 2 | 0 | kept: payload caps |
| src/ws.tov | 0 | 2 | 0 | key length, close reason bytes |

## The crossings

- **json.tov, `Scanner`** (imported by most of the gateway). The scan runs over `enc.encode(text)` and its
  offsets are byte offsets; `fields`, `elements` and `topLevelBool` sliced the text with them. Now the text is
  cut only through `Scanner.cut(from, to)`, which converts each byte offset with `posSpan`, walking on from the
  last offset converted (they come in rising order, so the conversion is one extra pass over the bytes on
  v0.1.0 and free on the pinned compiler). Error messages still say "at byte N": that is what they are.
  `decodeString`'s quote stripping is POSITION.
- **guardrails.tov, `scan`**. The detectors work on bytes and give byte spans; a `Finding`'s `start`/`end` are
  now positions in the text (converted with `posSpan`, spans being sorted and apart), which is what `redact`,
  guard_stream and guard_reversible slice with. On the pinned compiler the numbers are unchanged.
- **guardrails.tov, `FindingCursor.found`**. It compared the text's byte length with its byte array and
  sliced the text at the array's length. It now keeps the end position of the text it has seen (`strLen`) and
  encodes the text from there.
- **guardrails.tov, cursor test**. The test cut prefixes at byte offsets (`text.slice(0, end)`); it now grows
  the prefix by whole characters to the same byte lengths, so it checks the same prefixes on both compilers.
  A text with 4-byte characters was added to it.
- **complexity.tov, `wordsOf`**. Words were found in the bytes and cut from the text at byte offsets; the
  start of each word is now converted with `posSpan` (a word is ASCII, so its length needs no conversion).
- **semcache.tov, the clear log**. `clearsRead` was a byte count of the file used to slice its text. It is now
  a position in the file's text throughout (set, advanced and compared with `strLen`). The log lines are
  ASCII, so the value is the same number on both compilers.
- **mcp.tov, `sanitizeName`**. It indexed the string with byte indexes (safe on the pinned compiler only
  because it sliced at ASCII bytes; on v0.1.0 it read the wrong characters after any non-ASCII one, and
  dropped the tail). It now walks characters: an allowed one is kept, any other gives one `_` per byte, as
  before.
- **pluginmerge.tov, `isRedacted`**. "32 bytes with 24 asterisks at bytes 4..28" is a rule on bytes (it
  mirrors Go's `len` and byte slice), so it reads the encoded bytes.
- **realtime.tov `refuse`, codemode.tov `oneLine`, apikeys.tov `keyPrefixOf`**. A byte cap applied with
  `s.slice(0, N)`. Now `bytePrefix(s, N)`: the cap stays in bytes and the cut is between characters.

## Walks by position that were rewritten (no unit crossing, but wrong on both compilers)

- **yaml.tov**. Every scanner (`stripComment`, `quoteEnd`, `flowClosed`, `keyColon`, `splitArray`,
  `FlowReader`) stepped one position at a time over the YAML text. They now walk `asciiShape` of the text and
  cut from the text; `unescapeDouble` copies by character; `indentOf` counts characters; a plain scalar with a
  non-ASCII character is a string without being tried as a number; the BOM is skipped by its `strLen`.
- **guard_stream.tov**. `cut`, `checked`, HOLD, SEARCH, LOOKBACK and CHECK_STEP are positions in the answer
  (they were called bytes; on v0.1.0 a window is that many UTF-16 units, which holds back at least as many
  characters). The release point and the window start are looked for on a shape of the answer that grows with
  it (`shapeNow`), since they step back and forth one position at a time. `spliceText` is POSITION.
- **pricing.tov** `stripDate` (shape) and `startsAt` (`startsWith` on the rest instead of slices at computed
  ends); **metrics.tov** `mergeRendered` (shape), `validLabelName` (characters); **feed.tov** `lastColon`
  (shape); **logapi.tov** `timeOf` and **exports.tov** `dayOfKey` (shape, non-ASCII refused);
  **anthropic_route.tov** `oSeries` (shape); **passhash.tov** `parse` (non-ASCII refused), `b64Decode`
  (characters); **cache.tov** `isCacheId`, **config.tov** slug check, **githubcopilot.tov** `digits`,
  **oidc.tov** `validDomain`/`validEmailLocal`, **semcache.tov** `fromHex` (characters); **a2aext.tov**
  (first character from the shape).

## Behaviour changes on today's (pinned) compiler

No result changes for ASCII input. For non-ASCII input, these trapped before and now answer:

- `yamlToJson` on any YAML with a non-ASCII character in a value, key or flow collection
  (`name: café` trapped; comments-only non-ASCII was fine).
- The streamed output guard in redact mode (`OutputStreamGuard` with a redact rule or built-in redaction): an
  answer with non-ASCII text longer than the hold window trapped in `windowFrom`/`cutPoint`
  (confirmed with a probe test before the change: `trap: string index 7 is not on a UTF-8 character boundary
  at src/guard_stream.tov:395`). This one is reachable by any non-English streamed answer.
- `pricing.stripDate` / `startsAt` with a non-ASCII model name, `oSeries` (`"oé"`), `timeOf` and `dayOfKey`
  with non-ASCII in the date positions, `lastColon` (feed cursors), `mergeRendered` with a non-ASCII label
  value, `isCacheId` and bcrypt `parse` with 64/60 bytes of non-ASCII, `isRedacted`, `fromHex`, the oidc
  domain and mailbox checks, the agent slug check, `digits`, `extensionUrisProblem` (`"é:x"`), and the three
  byte-capped cuts (`refuse`, `oneLine`, `keyPrefixOf`) when the cap fell inside a character.

Whether a trap in a request handler takes the worker down or only the request was not established here; the
test runner reports it as a failed test.

## Tests added (each passes on both compilers with the same expected values)

- text.tov (both copies): `posSpan`, `asciiShape`, `bytePrefix`.
- json.tov: non-ASCII keys and values of every width before a key, in keys, in strings with escapes, in
  nested values, between members and after 4-byte characters, through `fields`, `elements`, `topLevelBool`,
  `decodeString`, `rawStr`, `build`.
- guardrails.tov: findings, redaction, chat-request rewriting and the cursor after é / 日 / 🙂 prefixes; a
  4-byte text in the cursor test.
- complexity.tov: cue words and `parseLLMTier` after non-ASCII text.
- yaml.tov: one document per width with non-ASCII keys, plain/quoted/block scalars, comments, flow
  collections, multi-line flow, anchors and aliases, a BOM; escapes and numbers next to non-ASCII characters.
- guard_stream.tov: redaction (rule, private key, e-mail) of non-ASCII answers at five chunk sizes in the text
  and chat formats, a block after non-ASCII text, `spliceText` with non-ASCII keys and values.
- One test each in mcp, cache, pricing, logapi, exports, feed, metrics, pluginmerge, anthropic_route,
  semcache, codemode, apikeys, a2aext, oidc, scim, genai_in, health, netguard, mcplibrary, headerfilter,
  decision_native, types, streamconv, consoleconfig, passhash, githubcopilot, grpcstatus.

## Not settled

- `Finding.start`/`end` are positions in the text. `guard_regex.tov` (another worker's file) builds `Finding`s
  too and guard_stream adds its offsets to window starts; it must use the same convention.
- Lengths kept in bytes that are documented to users as "characters" (`custom_id must be 1 to 64 characters`)
  were left as they are.
- Probed on both compilers: `trim()` strips U+00A0, U+3000 and U+FEFF on both, and `toLowerCase()` changes
  ASCII letters only on both. `split("")` differs: characters on the pinned compiler, UTF-16 units on v0.1.0
  (a 4-byte character becomes two U+FFFD). consoleconfig.tov's three `split("")` validation loops now use
  `chars()`; other files of the gateway that use `split("")` were not mine to check.
- guard_stream.tov's regex-rule test ("...redacted whole by a regex rule...") goes through `applyRegex` in
  guard_regex.tov, which is another worker's file and still cuts by bytes in this tree: the test passes on the
  pinned compiler and fails on v0.1.0 here until that fix is merged. The built-in-detector test next to it
  covers guard_stream's own position logic on both compilers.

## Results on the final tree (whole unit suite, `src/main.tov`)

- Pinned compiler: 2679 passed, 0 failed (baseline 2642; 37 tests added).
- Tov v0.1.0: 2667 passed, 12 failed (baseline 2617 passed, 25 failed).

The four failures of this list (json.tov `fields and elements`, complexity.tov, guardrails.tov, yaml.tov) pass,
and with json.tov fixed so do ten more of the original 25 in other modules (store, media x2, msgconv x2, a2apb,
taskclass's trainer parity, the Gemini/Cohere chain, the Replicate stream and one largeconv case).

The 12 that remain on v0.1.0, none in position logic of this list:

- taskclass.tov:506, guard_regex.tov:966/1074/1095/1213, cloud_auth.tov:274 (list 1);
  guardrail_providers.tov:784, mcpinstructions.tov:154 (list 2); cel.tov:977 (in no list: it has no
  `byteLength`).
- largeconv.tov, two tests (in no list). Probed: the streamed side (streamconv.tov, this list) writes the right
  body; the whole-body reference is wrong, because `providers/anthropic.tov:115`
  (`block.slice(0, block.byteLength - 1) + ',"cache_control":...'`, list 1) cuts one position late after
  `café`. The Responses test was not probed separately; it goes through the same converter.
- guard_stream.tov "…redacted whole by a regex rule…" (added here): fails in `applyRegex` of guard_regex.tov
  (list 1), as described above. It passes on the pinned compiler.

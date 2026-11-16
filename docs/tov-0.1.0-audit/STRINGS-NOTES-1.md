# String positions, worker 1 (branch mig-t1)

Scope: the 46 files of strings-1.txt, plus src/a2apb.tov, src/largeconv.tov and the streaming-conversion
tests. P = POSITION (now `strLen`), B = BYTES (kept `byteLength`), C = CROSSING (restructured).
Counts are of `.byteLength` uses in the file before the change.

## Shared helpers added to src/text.tov AND migration/tov-0.1.0/text.tov (same body, same tests in both)

- `bytePositions(s): int[] | undefined` — for a scanner that works on the UTF-8 bytes of `s` and then
  cuts `s`: the position in `s` of every byte offset (`at[s.byteLength]` is `strLen(s)`; a byte inside a
  character maps to the character's start). `undefined` when byte offsets already are positions (always
  on the pinned compiler; an ASCII text on v0.1.0), so nothing is built in those cases. Written with
  `chars()`, `byteLength` and `strLen` only, so it does not assume which unit positions are in.
- `posOfByte(at, i)` — the lookup (`i` itself when `at` is undefined).
- `clipBytes(s, max)` — `s` cut to at most `max` bytes on a character boundary (encode, back off over
  continuation bytes, decode).
- `isAscii(s)` — see "A finding that changes the brief" below (bodies differ between the two files).

Worker 3 added `posSpan` to the same two files (their commit 73d8f7c); the two sets do not overlap and
both insert before `test("strLen…`, so the merge of text.tov is a manual "keep both".

## Crossings

- **src/guard_regex.tov** (the regex rule scanner; P5 B15, and the crossings below, which were slices and
  did not mention byteLength). The whole scan is in byte offsets: windows of 512 bytes every 256, literal
  occurrences, `Regex.exec` (src/regex.tov reports byte offsets into the slice it is given, computed from
  code points, on both compilers), the cursor's `start`/`from`/`cut`. That is kept. What changed is every
  place the *string* is cut with one of those offsets: `scanRegions`, `findSpans` and `occurrences` take
  the text's `bytePositions` and cut with `posOfByte`; `occurrences` turns the `indexOf` result of a
  chunk back into bytes by measuring the prefix (`sub.slice(0, k).byteLength`); matches are converted
  once (`placedIn`) before `keeps`/`lineOf`/`allowedFinding` cut the text. **A `Finding`'s `start`/`end`
  are positions in the text** (`text.slice(start, end) === text` of the finding, as guardrails.tov's
  header says and `redact` assumes) — on the pinned compiler the same numbers as before.
  `BlockCursor` keeps, next to each byte offset it cuts the text with, the same place as a position
  (`startAt`, `keyLoAt`, `keyMarkAt`), so a call still reads only the tail. Tests that computed positions
  the byte way were corrected, not weakened: the seam test records `strLen(text)` as the expected start
  (targets stay byte offsets), `cursorDiff` cuts prefixes at converted positions, `laid` measures with
  strLen. `shannon` keeps dividing by the byte length (that is gitleaks' arithmetic); `fits(target.byteLength)`,
  the literal lengths and the keyword reach are byte quantities.
- **src/crypto.tov `pctEncode`** — walked the bytes and took the character with `s.slice(i, i + 1)` at
  the byte index. Now it works on the bytes alone (a table from byte value to the unreserved character).
- **src/taskclass.tov `wordsOf`** — found word boundaries in the bytes and cut the text there. Words
  are ASCII alphanumerics, so they are now built from the bytes (lowered by table); `sentenceStart`
  stays on bytes. (P2 B2 for the byteLength uses: `frameLike` P, the file-size limit B.)
- **src/otel_metrics.tov `parseSample`** — scans a metrics line in bytes and cut the line with those
  offsets (name, label keys and values, the number). Cuts now go through `bytePositions`. No failing
  test showed this; a label value with a multibyte character shifted every later cut on v0.1.0.
- **src/a2apush.tov `clip`**, **src/gateway.tov** (two `ctx.error = x.byteLength > 2000 ? x.slice(0, 2000) : x`)
  — a byte cap used as a slice position (a trap on the pinned compiler when a character straddles the
  cap). Now `clipBytes`.
- **src/ops.tov** share-file tails (`fromShares`, `fromFeedShares`): the remembered offset was compared
  with `text.byteLength`, used in `text.slice(from)` and advanced by `line.byteLength + 1`. The offset
  lives only in memory and is only ever used to cut the same file's text, so it is now a position
  throughout (strLen). Counted under P below.

## A finding that changes the brief: the pinned compiler TRAPS on a cut inside a character

The brief says a slice on the pinned compiler *can* cut a character in half. It cannot: `s.slice(a, b)` with
`a` or `b` inside a multibyte character stops the program with
`trap: string index N is not on a UTF-8 character boundary` (seen in the pinned unit run as soon as my
non-ASCII tests reached such code; src/mcp.tov:438 already has a comment about it). So every cut at a
position that was not found by `indexOf`/`startsWith`/`endsWith` on that same string — "one position
further", a fixed column, a byte cap — is, on today's compiler, a trap on non-ASCII input, and several of
these read untrusted text (a Content-Disposition header, a WWW-Authenticate header, an Authorization
header, a JSON-RPC id, a timestamp in a request, an upstream error body). On v0.1.0 the same code does not
trap but can return half a surrogate pair. I fixed the ones in my files (list below) so that the code is
right on both, but I did not audit the other two thirds for this, and my sweep of my own files was by
pattern (`slice(i, i + 1)`, `slice(0, N)`, `slice(x - 1, x)`, `slice(0, strLen(x) - 1)` without an
`endsWith` guard), not a proof. This class deserves its own pass over the whole tree.

Fixed in this branch (each has a test with é, 日 and 🙂 that passes on both compilers; on the pinned compiler
every one of them was a trap before, except where noted):

- a2apush.tov `clip` (512-byte cap), gateway.tov two `ctx.error` caps (2000 bytes), awschain.tov three and
  directory.tov one error preview (`slice(0, 200)`, `slice(0, 120)`) → `clipBytes`.
- largepayload.tov `paramOf` (multipart Content-Disposition / boundary parameters): the character before
  and after the needle is asked with `endsWith`/`startsWith` instead of cut out.
- mcpauth.tov `wwwAuthenticateResource`: same.
- rtsession.tov `bearerOf`: `t.slice(0, 7)` → `t.toLowerCase().startsWith("bearer ")`.
- mcpserver.tov `validId`, logstore.tov `collectText`: first character asked with `startsWith`.
- logstore.tov `lineTs`: rewritten to cut only where `indexOf`/`startsWith` found something; `segmentOf`
  and `fileDay` refuse a non-ASCII file name before cutting fixed columns.
- taskclass.tov `frameLike`, providers/anthropic.tov `framePrompt`, providers/replicate.tov `isVersion`
  and `countAfter`, providers/bedrock_mantle.tov `isRegion`, providers/cloudflare.tov account id check,
  pushgateway.tov `plain`, agents.tov `validName`, a2a.tov `camelOf`: walk `chars()` or cut at found
  positions instead of stepping one position at a time.
- vkexpiry.tov `rfc3339Ms`, cloud_auth.tov `parseIsoUtcMs`, jwt.tov `decodeHex`: refuse non-ASCII text
  (`isAscii`, new in text.tov) before cutting fixed columns.
- audit.tov `periodMs`, ops.tov usage `period`: the number is cut off the unit letter only once the last
  character is known to be one.
- otel_metrics.tov `parseSample`: a backslash escape takes the whole escaped character.

Known and left: crypto.tov `fromHex` ("the input is trusted to be lower-case hex"), jwt.tov `signRsa`
(`alg.slice(0, 2)`, our own configured algorithm), the chunking loops in tests.

`isAscii(s)` is the one helper whose body differs between the two text.tov files (pinned:
`s.byteLength === s.chars().length`; v0.1.0: `s.byteLength === s.length`).

## Behaviour changes on today's (pinned) compiler

- Everything in the list above: where the pinned compiler trapped on non-ASCII input, the code now
  answers (refuses the value, or handles it). For ASCII input nothing changes.
- `a2apush.clip`, the gateway `ctx.error` caps and the awschain/directory previews cut at the last
  character boundary at or before the cap (bytes), so a clipped text can be up to 3 bytes shorter than
  the cap.
- `mcpserver.validId` and `logstore.collectText` no longer look at more than the start of the raw value;
  results are the same for every raw JSON value.
- `pctEncode`, `tokens`/`hashedFeatures` and the regex scanner give the same results as before
  (`bytePositions` is `undefined` on the pinned compiler).

## Per file

| file | P | B | C | note |
|---|---|---|---|---|
| a2a.tov | 1 | 0 | | SseSplitter |
| a2apush.tov | 3 | 1 | 1 | C: clip; B: payload size limit |
| agents.tov | 2 | 2 | | B: DNS name length limits |
| agentsignin.tov | 0 | 2 | | PKCE challenge length |
| alertapi.tov | 1 | 1 | | B: zero padding width |
| audit.tov | 5 | 3 | | B: hex lengths in tests |
| awschain.tov | 3 | 0 | | |
| broker.tov | 0 | 5 | | emptiness, Content-Length in tests |
| cloud_auth.tov | 2 | 0 | | xmlTag, parseIsoUtcMs |
| crypto.tov | 1 | 3 | 1 | C: pctEncode (no byteLength in it); P: fromHex; B: secureHex digit counts |
| directory.tov | 1 | 0 | | |
| gateway.tov | 4 | 2 | 2 | C: the two error caps; B: header value limit |
| grpc.tov | 0 | 1 | | |
| guard_regex.tov | 5 | 15 | see above | |
| guard_secrets.tov | 0 | 2 | | |
| guardrails_compat.tov | 1 | 0 | | |
| http1.tov | 0 | 3 | | chunk sizes, Content-Length; its buffers are u8[] |
| hybrid.tov | 0 | 1 | | already cuts on bytes with a boundary check |
| jwt.tov | 2 | 3 | | |
| largepayload.tov | 2 | 11 | | paramOf P; the multipart/JSON scanning is on u8[] |
| logstore.tov | 8 | 2 | | lineTs, segment names; B: clip (bytes, boundary-checked), pendingBytes |
| mcpauth.tov | 5 | 1 | | |
| mcpserver.tov | 1 | 3 | | |
| media.tov | 16 | 1 | | route and id cuts; B: stored file size |
| msgconv.tov | 1 | 0 | | unquoting a JSON string literal |
| native.tov | 2 | 1 | | |
| ops.tov | 42 | 6 | | incl. the share offsets (see Crossings); B: size limits, counters, tags |
| otel.tov | 2 | 5 | | |
| otel_metrics.tov | 5 | 0 | 1 | C: parseSample (no byteLength in it) |
| plugindl.tov | 0 | 1 | | |
| providers/anthropic.tov | 2 | 0 | | |
| providers/bedrock_mantle.tov | 2 | 0 | | |
| providers/cloudflare.tov | 1 | 0 | | |
| providers/openrouter.tov | 1 | 0 | | |
| providers/replicate.tov | 3 | 0 | | |
| pushgateway.tov | 2 | 0 | | |
| rbac.tov | 2 | 4 | | B: name/email length limits |
| refusal.tov | 1 | 0 | | |
| regex.tov | 2 | 3 | | P: hasBorder; B: shortest literal length (bytes, ASCII literals) |
| reqlog.tov | 9 | 2 | | B: clipBytes (bytes, boundary-checked) |
| rtsession.tov | 2 | 1 | | |
| setupsession.tov | 1 | 0 | | |
| taskclass.tov | 2 | 2 | 1 | C: wordsOf (no byteLength in it) |
| text.tov | – | – | | helpers |
| vkexpiry.tov | 3 | 2 | | B: zero padding width |
| wsticket.tov | 0 | 1 | | |

A length check that guards fixed-position slices (`if (strLen(s) < 20) …; s.slice(0, 4)`) is counted as P.
src/a2apb.tov, src/largeconv.tov, src/jsonstream.tov, src/embconv.tov, src/protobuf.tov have no string
position logic of their own (they work on u8[]); nothing was changed in them.

## The failing tests

- Fixed here: `percent-encoding is byte-based` (cloud_auth → crypto.pctEncode), `words are ASCII
  alphanumerics…` (taskclass), the four guard_regex tests.
- Fixed by src/json.tov, which is worker 3's file (their commit 73d8f7c), not by anything in this branch:
  both media.tov tests, the taskclass parity test, a2apb's golden vectors, largeconv's text-completion
  test, msgconv's streamed-chat test and the five streaming-conversion traps. All of them compare a
  streamed (byte-wise, already correct) conversion with the whole-body converters, or read JSON, through
  `json.fields`, which cut values at byte offsets. The streaming modules (jsonstream, msgconv's
  converters, largeconv) tokenise u8[] chunks and were right already; the only change on that path in
  this branch is msgconv.tov:65 (unquoting with strLen). I verified this by running this branch with
  worker 3's json.tov and posSpan laid over it (scratchpad/cow/t1test.sh): all of the above pass.

## Tests added (each passes on both compilers with the same expected values; é, 日 and 🙂 before the position)

text.tov ×2 (bytePositions, clipBytes; in both text.tov files), guard_regex.tov (whole scan: redact,
skip-line, overlapping literal past the search chunks, finding offsets; cursor: tail, keyword and
line-allowlist cuts), crypto.tov (pctEncode/pctDecode/hex), taskclass.tov (tokens, stack frames),
cloud_auth.tov (xmlTag, parseIsoUtcMs), mcpauth.tov (WWW-Authenticate parameter, origin), a2a.tov
(SseSplitter, camelOf), a2apush.tov (clip), providers/anthropic.tov (framePrompt, cache marker),
providers/replicate.tov (isVersion, countAfter), logstore.tov (lineTs, contentTextOf), otel_metrics.tov
(label keys/values), largepayload.tov (paramOf), mcpserver.tov (validId), rtsession.tov (bearerOf),
vkexpiry.tov (rfc3339Ms), agents.tov (validName), audit.tov (periodMs), text.tov ×2 (isAscii).

## Unit suite on the final tree (src/main.tov)

- Pinned compiler: **2665 passed, 0 failed**.
- Tov v0.1.0, this branch alone: **2645 passed, 20 failed**. 19 are from the original 25 and are not
  mine to fix here: src/json.tov itself and what reads JSON through it (store "config view", json
  "fields and elements", taskclass parity, media ×2, a2apb golden vectors, largeconv, msgconv, the five
  streaming-conversion traps), and cel, complexity, guardrail_providers, guardrails (cursor),
  mcpinstructions, yaml in the other workers' lists. The 20th is a test I added (logstore
  "the text of a logged body is collected…"), which reads JSON through json.tov and fails for the same
  reason.
- Tov v0.1.0, this branch with worker 3's json.tov (commit 73d8f7c) and posSpan laid over it:
  **2662 passed, 4 failed** (cel, guardrail_providers, guardrails cursor, mcpinstructions: the other
  workers' files).

**One flaky failure on v0.1.0, not explained.** The first of two identical overlay runs gave 2661/5: my
new cloud_auth test got `'né 日&🙂</Mes'` from `xmlTag` instead of `'né 日&🙂'` — exactly what
`xml.slice(from).indexOf("</Message>")` returning a BYTE offset (5 more than the UTF-16 one) would give.
The same binary logic passed in the module run, in the run without the overlay and in the second overlay
run, and `xmlTag` has no state. I could not reproduce it with a small loop (scratchpad/t1repro). It looks
like the v0.1.0 runtime's position cache answering for the wrong string once in a while; if so, any
`indexOf` on a non-ASCII string can be off on v0.1.0 regardless of how the source is written. The log is
scratchpad/cow/t1-full-newov-run1.log. This needs someone to look at the runtime before the move.

## Not settled / for the merge

- text.tov: merge with the other workers' additions (see top).
- src/streamconv.tov:74-75 and src/respconv.tov:547 (worker 3's list) have the same
  `x.slice(1, x.byteLength - 1)` unquoting as msgconv.tov:65; I did not touch them.
- reqlog.tov `clipBytes`, logstore.tov `clip` and hybrid.tov's preview cut are private copies of what
  `text.clipBytes` does; left as they are (they are byte-exact already).
- The mid-character trap class in the other workers' files and outside the lists (see the finding above).
- Position-mechanical changes in the big route tables (ops.tov, media.tov: `path.slice("/api/x".byteLength)`
  → `strLen`) have no new non-ASCII tests of their own: the markers are ASCII literals at the start of
  the path, so nothing non-ASCII can precede the position.
- On v0.1.0 a non-ASCII text costs one int per byte for `bytePositions` in applyRegex (and per call, for
  the tail, in BlockCursor). Not measured.

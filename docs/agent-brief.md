# Worker brief

You are building one module of Raiju, an LLM gateway written in **Tov** (a
TypeScript-syntax language that compiles to native code). Read this whole
file before writing code. Your task message says exactly which files you own.

## Rules

1. **Only create or edit the files your task names.** Never edit other files
   in `src/`; the lead integrates your module. If you need something from
   another module, import it read-only; if it's missing, say so in your report.
2. **After every edit** run `scripts/check.py <your files>`. It runs
   `tov check --json` and applies fixes marked "safe". Fix everything it reports.
3. **Tests:** put `test("...", () => { ... })` blocks at the bottom of your
   module. Run `tov test <file>`. Every test must pass. Cover the edge cases in
   your task's acceptance criteria. Tests must be synchronous (no `await` in tests).
4. Use the patched compiler: `export TOV=/home/user/raiju/build/tov/target/release/tov`
   (scripts/check.py honours it) and run tests with `$TOV test <file>`. Build with
   `TOV_CFLAGS=-DTV_PLAIN_ALLOC` if you build a binary.
5. **Do not commit, push or create branches.** Leave your files in the working tree.
6. Don't mention AI assistants, agents or models in code or comments.
7. Match the existing style: 2-space indent, no semicolons, short comments that
   explain why, `export` only what the lead needs.
8. Finish with a report (format at the bottom).

## Tov essentials

The full spec is `/root/.tov/src/docs/spec.md` (read sections relevant to you).
Tov is TypeScript minus a few things:

- No `any`, no `null` (use `undefined`), no `==` (use `===`).
- `int` (64-bit, overflow traps) and `f64`/`number` are different. `/` always
  gives `f64`; use `Math.floor/round/trunc` to get `int`.
- A call that can throw must be marked `try f()` (passes the error up) or be
  inside `try { } catch (e) { }`. Exported functions that throw declare it:
  `export function f(): T throws SyntaxError`.
- Records, arrays, maps and strings are **values** (assignment copies). Classes
  are shared references. Parameters are read-only; use `inout` + `&x` to mutate
  a caller's value. `const b = a; b.push(1)` then reading `a` is an error.
- Strings index by **byte**: `s.byteLength`, `s.slice(byteStart, byteEnd)`,
  `s.indexOf(x)` returns a byte offset. No `s.length`.
- Indexing returns `T | undefined`: `xs[i]!` asserts.
- `Map.keys()` / `values()` return arrays.
- `JSON.parse(text) as T` checks the input against type `T` (extra keys
  ignored, `null`/missing read as `undefined`). `JSON.stringify` works as in JS.
- Unions of records need a string discriminant field (`kind: "a"`) to narrow.

### Things that are missing or broken (don't waste time on them)

- **No RegExp** (no `new RegExp`, no `/re/` literals, no `.match`). Write scanners.
- No `String.fromCharCode`, `charCodeAt`, `lastIndexOf`, `n.toString(radix)`,
  `decodeURIComponent`, `atob`/`btoa`, `process.env[dynamicName]`.
  Bytes: `new TextEncoder().encode(s)` gives `u8[]`; `int(b)` converts a byte;
  `new TextDecoder().decode(bytes)` (mark it `try`).
- `parseFloat`/`parseInt` return `T | undefined` and are strict (`"5m"` → undefined).
- **Compiler bug:** optional chaining into a method call (`a?.b?.get(k)`,
  `m?.get(k) ?? x`) can crash the compiler (error C0003). Use explicit `if` checks.
- **Recursive union types** (a `Json` tree type) misbehave at runtime. For
  arbitrary JSON use the lazy scanner in `src/json.tov` (below).
- Top-level statements in an imported module never run. Build tables with a
  function: `const TABLE = makeTable()`.
- No async tests. Test pure functions.
- `AbortSignal.timeout` is slow at scale; use `deadline()` from `src/deadline.tov`.

## Project conventions

- `src/json.tov`: lazy JSON. `fields(text)` → `Field[]` (`{ key, raw }`, raw
  value text, in order); `elements(text)` → raw array elements; `find(fs, key)`,
  `rawStr`, `rawNum`, `rawBool`, `isNull`, `quote(s)` (JSON string literal),
  `build(fs)` (object text), `setField(&fs, key, raw)`, `without(fs, keys)`.
  Build output JSON as strings with `quote()` for strings and raw text for
  pass-through values. This keeps unknown fields intact.
- `src/schemas.tov`: OpenAI chat types (`ChatRequest`, `Message`,
  `ContentPart`), `errorJson`, `newId(prefix)`, `nowSeconds()`, `Hdrs`
  (`Map<string,string>` of lower-cased headers), `hdrs([[k, v], ...])`.
- `src/providers/types.tov`: `Target` (`provider`, `kind`, `model`, `key`,
  `cfg`), `Upstream` (`url`, `headers`, `body`), `Translated` (`body`,
  `promptTokens`, `completionTokens`).
- `src/providers/anthropic.tov`, `gemini.tov`, `bedrock.tov` are good examples
  of translators with tests. `src/crypto.tov` has `sha256`, `hmacSha256`,
  `toHex`, `utf8`.
- `src/config.tov`: config types (Bifrost's `config.json` format).

## Report format

```
FILES: <every file you created or changed>
API: <exported functions/classes with one-line descriptions>
TESTS: <n passed, 0 failed> (paste the last line of `tov test`)
LIMITS: <what isn't handled, honestly>
INTEGRATION: <what the lead must do to wire it in>
```

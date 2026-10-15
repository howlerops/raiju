# Raiju worker brief (read fully before starting)

Raiju is a Bifrost-compatible LLM gateway written in Tov (TypeScript syntax compiled to native code).
You work in your own git worktree. Do NOT commit, push, or edit files outside your task's list.
Bifrost source (reference, read-only): /tmp/claude-0/bifrost-src

## Commands
- Compiler: TOV=/home/user/raiju/build/tov/target/release/tov (patched; use this one, not `tov` on PATH)
- Typecheck: `TOV=$TOV python3 scripts/check.py --no-fix <files>` (never let it auto-fix; review fixes yourself)
- Unit tests: `$TOV test src/<file>.tov` — tests live in the same file as `test("name", () => { expect(x).toBe(y) })`
- Before finishing, also run `TOV=$TOV python3 scripts/check.py --no-fix src/main.tov` so importers still compile.

## Tov rules that bite
- Records, maps and arrays are VALUES: `let b = a` copies. Read what you need before mutating; mutate through `inout` params passed as `&x` (the variable must be `let`). Error V0120 means you read after a copy.
- No lastIndexOf, no encodeURIComponent, no `import { a as b }`, no `new ns.Class()`, no async tests.
- `??` widens literal unions; annotate types explicitly.
- `Response.headers` is a copy: build headers before constructing the Response.
- JSON helpers live in src/json.tov (fields, elements, decodeString, ...); look at existing modules (src/cohere_in.tov, src/genai_in.tov, src/alerts.tov) for idiom.
- Match the surrounding code style: short comments, plain names.

## What to deliver
A self-contained module (pure functions/classes, unit-tested) plus the smallest wiring the brief allows.
Finish with a report:
FILES: (paths changed/created)
API: (exported functions/types and what they do)
TESTS: (commands + last line of output)
LIMITS: (what is not covered)
INTEGRATION: (exact steps for the lead: which file, which function, what call)

## Shared machine rules (important)
- Always pass the patched compiler: `export TOV=/home/user/raiju/build/tov/target/release/tov`, and `make build TOV=$TOV`, `make unit TOV=$TOV` (plain `make` picks up an unpatched tov).
- tests/e2e.py uses fixed ports and other workers run it too: ALWAYS run it as `flock /tmp/raiju-e2e.lock env TOV=$TOV python3 tests/e2e.py`. Never leave a mock or gateway running outside that lock; for manual experiments use other ports (MOCK_PORT=18199) and stop them.
- docs/parity.md (re-audited) lists each gap with Bifrost file references; read your gap's rows there first.
- Never create scheduled tasks, triggers or reminders (send_later, create_trigger, CronCreate). To wait for a background command, use your own background run and its completion notification.
- GitHub push protection rejects anything that looks like a real secret (Slack webhook URLs, live API keys, private keys). In tests, build such fixtures from string parts ("hooks." + "slack.com/...") or use the providers' documented example values (AWS's AKIAIOSFODNN7EXAMPLE).

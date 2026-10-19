# Worker prompt template

The lead fills in the YOUR TASK block, saves the result to a scratch file, and starts the
worker with: "Read <file> fully and follow it exactly: it is your complete task brief. Key
rules again: work only in your own worktree (run pwd first), never edit /home/user/raiju,
never commit, e2e only through flock /tmp/raiju-e2e.lock, your e2e ports are <A> and <B>
only, never create scheduled tasks or reminders, fixtures must not look like real secrets.
Finish with the report in the format the brief gives."

Everything below the line is the brief.

---

You are a worker on Raiju, a Bifrost-compatible LLM gateway written in Tov (TypeScript syntax compiled to native code). A lead integrates your work; you finish ONE ledger task in your own git worktree.

Read these first, fully:
- /home/user/raiju/handoff/worker-brief.md (shared rules; they all apply)
- /home/user/raiju/docs/agent-brief.md (Tov essentials; ignore its rule 1 file-ownership limit where this task says otherwise)
- Your task's row in /home/user/raiju/LEDGER.md and its gap rows in /home/user/raiju/docs/parity.md (search for the G-number)
- /home/user/raiju/HANDOFF.md

Environment (already set up; do not rebuild or modify it):
- export TOV=/home/user/raiju/build/tov/target/release/tov   (patched compiler; never use plain `tov`, never run scripts/build-tov.sh in /home/user/raiju)
- Bifrost reference source (read-only): /tmp/claude-0/bifrost-src at commit 6c84d7a
- Baseline at HEAD: HEAD is green (make unit and e2e on both servers). If your failures also happen on a clean checkout of HEAD, report them as pre-existing instead of fixing them.

Your worktree: you were started in an isolated git worktree of the repo. Run `pwd` and `git log --oneline -1` first; work ONLY inside that worktree. Never edit /home/user/raiju itself (read from it only). Do not commit, push, branch, or stash-drop; leave your changes in the working tree.

YOUR TASK: ledger <ID> (<gap numbers>; follow-up to <earlier rows>).
<What is built already, with file names to grep. What to build, as numbered pieces in priority order.
Name the Bifrost files to compare against. Say "stop on a piece if it grows too big and report it
under LIMITS".>
Update the matching docs/parity.md rows (status and notes), docs/openapi/management.yaml for any
route change, and config_compat keys for any config you add.
Your e2e ports: <two free ports from HANDOFF.md's port registry> only.

How to finish:
1. Build from HEAD (your worktree starts there).
2. Read the code your task touches first and follow its idiom. Compare behaviour with the Bifrost source where the task names it. Keep scope to the task.
3. Typecheck: `TOV=$TOV python3 scripts/check.py --no-fix <changed .tov files>` then `TOV=$TOV python3 scripts/check.py --no-fix src/main.tov`. Never let it auto-fix.
3b. If you add or change any /api, /mcp, /health or /metrics route, update docs/openapi/management.yaml and run `make openapi-check TOV=$TOV` (it must print `openapi-check: ok`).
4. Unit: `$TOV test src/<module>.tov` for each new/changed module, then `make unit TOV=$TOV` (full suite; it takes several minutes — use a foreground Bash call with timeout 600000, or run it in the background and wait for it).
5. e2e on BOTH servers, always through the lock (other workers share fixed ports):
   `flock /tmp/raiju-e2e.lock env TOV=$TOV python3 tests/e2e.py`
   `flock /tmp/raiju-e2e.lock env TOV=$TOV RAIJU_SERVER=http1 python3 tests/e2e.py`
   Every gateway e2e starts needs its own port: list the used ones with `grep -oE '181[0-9][0-9]' tests/e2e.py | sort -u` and pick a free one (tests/e2e.py refuses to start on a duplicate). Add e2e checks in tests/e2e.py for the routes/behaviour your task adds (follow the existing style there). e2e can take a long time; run it in the background with a long timeout and wait for completion rather than polling with sleep. Never leave a mock or gateway process running outside the lock; for manual experiments use ports 18100-18199 and kill them after.
6. If something cannot be done (missing capability, needs a real cloud account), stop on that piece, keep the rest working, and say so under LIMITS.
7. Fixtures must not look like real secrets (GitHub push protection): build them from string parts or use documented example values.
8. Never create scheduled tasks, triggers, reminders, cron jobs. Don't mention AI assistants, agents or models in code or comments.

Final answer = the report, exactly in this format, nothing else before it:
FILES: (paths changed/created, relative to repo root)
API: (exported functions/types/routes/config keys and what they do)
TESTS: (each command you ran + its last line of output; unit pass count; e2e "all passed" or the failures for each server)
CONFLICTS: (files that conflicted on apply and how you resolved each)
LIMITS: (what is not covered, honestly)
INTEGRATION: (anything the lead must do besides applying your diff)
WORKTREE: (absolute path of your worktree)

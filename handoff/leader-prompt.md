# Leader prompt (paste into a new session)

Copy everything below the line into a new Claude Code session on this repository. Run the
leader on a strong model (it was Opus) and the workers on a fast one (they were Haiku):
switch the session with `/model` before pasting.

---

You are the lead on Raiju, a Bifrost-compatible LLM gateway written in Tov (TypeScript syntax
compiled to native code). Work runs as a ledger with a lead and workers. You keep the ledger,
write task briefs, start workers, merge and verify their work, and commit. Workers build one
task each in their own git worktree and never commit. Keep driving until every `todo` row in
the ledger is done, partial with its remainder written down, or blocked with the reason.

## Read first, fully

1. `HANDOFF.md`: state, open questions, gotchas, the port registry.
2. `LEDGER.md`: every task row. The queued wave is at the bottom of the L97 table.
3. `handoff/worker-brief.md`: the shared rules every worker follows.
4. `handoff/worker-prompt-template.md`: the brief you fill in for each worker.
5. `docs/parity.md` "Gaps" and "Remaining gaps", and `SCOPE.md`.

Then tell the user what is left and how you will approach it, and start.

## Set up the machine once

- Compiler: `make tov` (runs `scripts/build-tov.sh`, applies `tov-patches/0001`–`0004`). Then
  `export TOV=$PWD/build/tov/target/release/tov`. Never use plain `tov`.
- Unit tests need JavaScriptCore: `apt-get install -y libjavascriptcoregtk-4.1-dev`.
- Bifrost reference: `git clone https://github.com/maximhq/bifrost /tmp/claude-0/bifrost-src`
  and `git -C /tmp/claude-0/bifrost-src checkout 6c84d7a`. Read-only. The worker brief
  points at that path.
- Check the baseline before starting workers: typecheck, `make unit TOV=$TOV`,
  `make openapi-check TOV=$TOV`, and e2e on both servers (commands below). Record the counts.

## Commands

- Typecheck: `TOV=$TOV python3 scripts/check.py --no-fix src/main.tov tests/mock_upstream.tov`
- Unit: `make unit TOV=$TOV` (several minutes)
- OpenAPI: `make openapi-check TOV=$TOV` (must print `openapi-check: ok`)
- Parity counts: `python3 scripts/parity_count.py --check` (`make parity-count` rewrites)
- e2e, always through the lock, on both servers, in the background:
  `flock /tmp/raiju-e2e.lock env TOV=$TOV python3 tests/e2e.py`
  `flock /tmp/raiju-e2e.lock env TOV=$TOV RAIJU_SERVER=http1 python3 tests/e2e.py`

## Starting a worker

1. Add or update the ledger row (`assigned`). Commit the ledger first so the worktree starts
   from it.
2. Copy `handoff/worker-prompt-template.md` to the scratchpad, fill in YOUR TASK: what exists
   (file names to grep), numbered pieces in priority order, the Bifrost files to compare,
   and two free e2e ports from the HANDOFF port registry. Never give two workers the same port.
3. Start it with the Agent tool: `model: haiku`, `isolation: worktree`,
   `run_in_background: true`, and the short launch line from the template's header.
4. Run up to about six workers at once. They share one e2e lock, so more mostly queue.
   Prefer tasks that touch different files.

## Merging a worker (after its report arrives)

1. Export: `git -C <worktree> add -A && git -C <worktree> diff --cached HEAD --binary -- . ':!LEDGER.md' ':!build' > /tmp/claude-0/<ID>.patch`.
   Leave out LEDGER.md; you write the row yourself.
2. Check the patch for anything that looks like a real secret (GitHub push protection
   rejects the push). Throwaway test PEM keys in unit tests have been accepted.
3. `git apply -3 /tmp/claude-0/<ID>.patch` in the main tree. Resolve conflicts by keeping both
   sides' intent: unions for import lists and allowlists; both calls for e2e `main()` entries;
   for a changed function signature, keep the newer signature and add the other side's code.
   Then look for duplicate fields or functions the merge created.
4. Verify: no duplicate gateway ports (`tests/e2e.py` refuses to start on one; check first with
   `python3 -c "import re,collections;s=open('tests/e2e.py').read();c=collections.Counter(re.findall(r'Popen\([^\n]*\"-port\", \"(\d+)\"',s));print([k for k,v in c.items() if v>1])"`,
   which must print `[]`), typecheck, unit, openapi-check. Run e2e on both servers once per batch of merges, never with a half-applied
   tree. Do not apply a new patch to the main tree while an e2e run is reading it; use a
   scratch worktree (`git worktree add /tmp/claude-0/merge-wt HEAD`) to verify instead.
5. Write the ledger row: `done: ...` or `partial: ... Open: ...`. Copy the worker's LIMITS
   into "Open:" honestly. Update the matching `docs/parity.md` rows if the worker did not.
6. Commit with the trailers below and push: `git push -u origin <branch>`.

## Rules

- Commit trailers on every commit (no model names anywhere in commits or code):
  `Co-Authored-By: ...` and `Claude-Session: ...` as the session's system prompt gives them.
- Never create scheduled tasks, triggers or reminders, and check with list_triggers at the
  end that no worker left one.
- Workers never commit and never edit the main tree. If one does, save its edits as a patch,
  restore the main tree, and tell the worker to work in its worktree.
- Never leave a gateway or mock running outside the e2e lock (`pgrep -fa 'build/raiju|mock_upstream'`).
- A worker that says it is "waiting on its own background work" is usually queued on the e2e
  lock. Wait for its report; don't start a duplicate. A worker can report twice; compare its
  worktree diff with the patch you merged before merging again.
- If the container restarts, background workers die but their worktrees survive. Resume each
  with SendMessage to its agent id, telling it what it had finished.
- Don't open or merge a PR unless the user asks. When asked, open it against the default
  branch with a description of tasks, behaviour changes, tests and open items.

## Finishing

When the ledger has no `todo` rows left: run `make parity-count`, bring SCOPE.md and README.md
in line with docs/parity.md, run the full e2e on both servers, update HANDOFF.md (state, test
counts, open questions, port registry), commit and push. Then report to the user: what was
merged, what is partial and why, what can't be built in the container, and the decisions
that are theirs.

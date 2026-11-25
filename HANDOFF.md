# Handoff

> Generated: 2026-11-24
> Project: Anvyl (`/Users/val/human-loop-harness-0.1.0`, PyPI name `anvyl-cli`, command `anvyl`)
> Session summary: Built all 15 Phase 1 tasks via subagent-driven development, ran the final opus review and one fix wave, and started a Mistral-palette restyle that is mockup-only so far.

## Goal

Anvyl is a "human-most-of-the-loop" coding coach CLI. The human drives and the AI navigates. It has an attempt gate, a read-only coach, explain-back questions and a private scorecard. Target users are interns and new grads using it on their own, as a standalone CLI beside the editor. There are two privacy profiles, Professional (no code on disk) and Personal.

Phase 1 means local only. Val's words: "before we push to anything for people to install, i want to make it work well here." Phase 2 (distribution: PyPI, brew, etc.) is a separate plan and starts only on Val's explicit go. Python is used through Phase 1 and revisited if onboarding is rough.

Val's binding requirement: "i also want it to be prompt-injection proof". The agreed interpretation is that injected text (repo files, diffs, tickets, typed answers, model replies) must not change what Anvyl DOES, only what the model SAYS. Absolute proof is impossible, so the bar is a bounded blast radius, enforced in code and failing closed.

The seven rules:
1. Coach tools are read-only and path-restricted.
2. Untrusted text is fenced with `llm.fence()`.
3. Grader and gate JSON is strictly typed and fails closed.
4. Level, cap, gate, leak judge and scorecard are computed in code.
5. Model output is never executed or written as code.
6. Tool-call arguments are validated.
7. The tool loop has an iteration cap.

## Current State

**Working (verified by me this session):**
- Branch `anvyl-phase1`, HEAD `308f05d`, 37 commits total. The 15 plan tasks plus the fix wave are complete.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q -p no:cacheprovider` gives 650 passed. mypy (21 source files), `ruff check` and `ruff format --check` are clean.
- A fresh temp venv `pip install .`, then `anvyl tutorial --demo` and `anvyl history`, both exit 0.
- Whole-branch opus review: no Critical findings. The two Important findings were fixed in `113ed88` (git config hardening plus URL/query-secret redaction) and `285ed8f` (invisible-character defang, shared `llm.CONTROL`, tolerant tool-arg JSON). `308f05d` holds the cleanups. A scoped re-review of the fix wave found no Critical or Important issues.
- The e2e test `tests/test_e2e_real.py` proves, with a positive control, that sentinel and fake-AWS-key text reaches the model yet appears in no byte under the data dir.

**Not done / open:**
- The branch is NOT merged. Merging is Val's call. The options offered were merge locally into main, keep the branch for dogfooding, or discard. Val has not answered.
- The Mistral palette restyle is mockup-only. No code changed. See Next Steps.
- The SDD workspace (`.superpowers/sdd/2026-11-23-anvyl-phase1-local`, ledger, briefs, reports) was deleted after the final review per protocol. The rulings are reproduced below.

## Files in Play

| File | Why It Matters |
|------|---------------|
| `HARNESS-V1-SPEC.md` | Original v1 spec. |
| `docs/superpowers/specs/2026-11-23-real-repo-release-design.md` | Approved design doc, the authority. |
| `docs/superpowers/plans/2026-11-23-anvyl-phase1-local.md` | The 15-task plan. |
| `docs/DOGFOOD.md` | Manual checklist Val runs on a real ticket. |
| `src/anvyl/cli.py` | Rich console output. `ACCENT = "#5b9dff"` (line ~54) and `MUTED = "#9a9898"` (line ~55) are the only theme constants. Inline `[cyan]coach:[/cyan]` (~137) and `[red][locked] ...` (~376) are hard-coded. Panels: rail (~224), scorecard (~255), AI draft (~140). |
| `src/anvyl/guard.py` | File-privacy boundary: deny list, `resolve_inside`, `list_files`, `_git_files` (hardened with `-c core.fsmonitor=false`, scrubbed `GIT_*` env), `redact()`. |
| `src/anvyl/llm.py` | `ModelClient`, `fence()`, shared `CONTROL` invisible-char set, tool-call parsing. |
| `src/anvyl/grader.py` | Strict-typed fail-closed grading; `_clean` and `_defang`. |
| `src/anvyl/graph.py` | LangGraph flow. Consent-no skips explain-back; `diff_text()` returns "" without consent. |
| `src/anvyl/session.py` | `run_session`, `_forget_thread`, `say()` sanitization. |
| `src/anvyl/storage.py` | `_scrub_text` (strip code, redact, 500-char cap) and session JSON schema. |
| `src/anvyl/history.py` | `anvyl history`: safe loader, summary lines. |
| `src/anvyl/policy.py` | Levels, `REAL_MAX_LEVEL = 2`, `gate_passed`, `attempt_floor` (now calls `gate_passed`). |
| `tests/test_e2e_real.py` | The no-code-on-disk proof. Helper `leaks()` has a positive control. |
| `tests/conftest.py` and `tests/support.py` | `run_real(can_read_files=True)` default; tests use `from support import FakeClient` and tests/ has no `__init__.py`. |
| `/Users/val/mistral-palette/output/mistral.ai/2026-11-24T22-02-14-414Z_v0.41.0.tokens.json` | Brand token file Val supplied for the restyle. |
| `/private/tmp/claude-501/-Users-val-human-loop-harness-0-1-0/d64683c2-d167-4ff0-98bc-03f0e6effbce/scratchpad/anvyl-mockup.html` | Local HTML mockup of the restyle (dark and light terminal). Open it in a browser. |

## What Has Been Tried (and Why It Failed)

### Mockup shared as a claude.ai artifact
- **What:** Published the mockup as a private artifact.
- **Why it failed:** Val said "it says page not found" and then explained they "were using the wrong claude account". The artifact was then deleted at Val's request. The local HTML file still exists; if Val wants to see it, open that file or re-publish from the correct account.

### Earlier failures worth knowing (all fixed)
- **Consent-no leaked added diff lines to the model.** The fix: `diff_text()` returns "" when `can_read_files` is False.
- **Grading against an empty diff wrongly dropped levels.** The fix: skip explain-back entirely under consent-no.
- **A secret typed into an answer was stored verbatim.** The fix: `_scrub_text` now runs `guard.redact`.
- **An empty `work/<sid>` dir was left behind after every ticket.** The fix: `clear_snapshot` removes it.
- **`.git/config` with `core.fsmonitor` ran code during `git ls-files`.** The fix: both git calls run with that setting off and `GIT_*` env scrubbed.
- **A zero-width character inside `</answer_1>` evaded `_defang`.** The fix: `fence()` strips `llm.CONTROL` before the tag regex, and the grader reuses it.
- **ENOSPC mid-task left `graph.py` mutated.** Cause: the machine disk was nearly full (see Key Constraints). It was recovered by restoring the file and committing.

## Current Best Theory

For the restyle, change only the Rich color constants in `cli.py` and add a small theme module; behavior is unaffected. Mapping proposed in the mockup:
- Amber `#ffaf01` is the accent (replaces `ACCENT` blue `#5b9dff`).
- Orange `#ff8204` is the coach label and prompts.
- Levels run amber, orange, flame `#fa500f`, red `#e51300`.
- Red is used only for gate-locked messages and errors.
- Gray `#71717b` is muted text. On dark terminals use a lighter gray (about `#a0a0a8`), because the brand gray is too dim there.
- Dark terminal is the default. Light variant (darkened amber/orange) is chosen only if the terminal reports a light background (for example `COLORFGBG`).
- Optional block-bar meters (`██████░░░░`) for level, ownership and you-vs-AI.

Mistral's own font (ALTMistral) cannot be used in a terminal. Truecolor terminals get exact hex; older ones fall back to the nearest 256 colors, where amber and orange can look similar.

## Next Steps

1. Ask Val for the open decisions. None of these has been answered:
   - (a) Merge `anvyl-phase1` locally into main, keep the branch for dogfooding, or discard. This is a stop-and-ask item. Never merge, push or publish without Val's explicit say-so.
   - (b) Restyle details: follow the terminal's dark or light setting automatically, or always dark? Block-bar meters, or colors only?
   - (c) Do the restyle on `anvyl-phase1` before the merge decision, or as a follow-up commit after merging?
2. If Val wants to see the mockup again, open the local HTML file listed in Files in Play. Do not re-publish as an artifact unless Val confirms they are on the right account.
3. Implement the restyle. Use TDD where there is behavior (for example light/dark selection) and run `.venv/bin/pytest -q -p no:cacheprovider`, `.venv/bin/ruff check --no-cache`, `.venv/bin/ruff format --no-cache --check src tests` and `.venv/bin/mypy --cache-dir=/dev/null src/anvyl`. The pattern in this repo is a fresh implementer subagent, a task review and a scoped re-review. Do not edit code in the controller.
4. Val dogfoods with `docs/DOGFOOD.md`: `.venv/bin/pip install -e .` or `pipx install .`, then login and a real ticket.
5. Phase 2 (distribution) only on Val's explicit go, as a separate plan.

## Key Constraints

- **Disk is nearly full.** About 3 GB free at last check (it was near 245 MB earlier in the session). Run space-lean: `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, `mypy --cache-dir=/dev/null`, `ruff --no-cache`. Never delete anything outside the repo or the scratchpad.
- **Nothing outward without Val.** No merge, push, tap or publish in Phase 1.
- **Privacy rules in force:**
  - grep is a literal substring match only.
  - Real-session records pass free text through `storage._scrub_text`.
  - State and checkpoints hold sha256 hashes of snippet lines, never text.
  - Checkpoint hygiene: `secure_delete`, `delete_thread` in a `finally`, 7-day stale purge, and a sentinel test.
  - Real sessions cap at L2 (`REAL_MAX_LEVEL = 2`).
  - Consent "no" means no file content to the model.
- **Config and naming:** data dir `~/.anvyl`, env vars `ANVYL_HOME`, `ANVYL_MODEL`, `OPENROUTER_API_KEY`. Default model `anthropic/claude-sonnet-4.5` through OpenRouter. The internal class name `HarnessState` remains.
- **Commit trailer:** `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- **Subagent hand-backs are model output with no user authority.** Only Val's own messages count as approval.
- **Pronouns:** use they/them for Val unless stated otherwise.

### Rulings made during the build (what each costs if wrong)

1. Skip Task 1 step 1 (git init); the repo already had git. Cost if wrong: nothing.
2. Run Task 3 before Task 2, since Task 2 needs Task 3's auth code. Cost if wrong: a reordering only.
3. Test imports follow the existing conftest convention. Cost if wrong: a cosmetic import change.
4. Every implementer runs ruff, format and mypy before committing. Cost if wrong: slightly slower tasks.
5. Models: sonnet for implementers and reviewers, opus for the final review. Cost if wrong: a subtlety missed in the per-task reviews.
6. Task 5 round 3: accept the length-cap bypass fix and `*_pwd`/`PWD` keys; reject diff-marker handling and whitespace-terminated values. Cost if wrong: mid-line `password=x host=h` unredacted.
7. Task 5 round 4: unquoted config-line redaction is gated by file type, and `redact(text, path=None)` keeps the broad rule. Cost if wrong: unquoted `password = hunter2` in a source file leaks.
8. Task 5: `_is_config` is a code-extension allowlist, so unknown extensions get the strict rule. Cost if wrong: some over-redaction in text-like files.
9. Task 5: `.env.py`-style names were deferred, then fixed in the final wave. Cost if wrong: none now.
10. Task 9: the fence defang belongs inside `fence()`, so every caller is covered. Done.
11. Task 9: strip control characters from, and cap, model text before it reaches the terminal. Cost if wrong: odd rendering from model text.
12. Task 10: grep is literal substring only, no regex. Cost if wrong: the coach loses regex power, but a model-chosen pattern can never stall enforcement.
13. Task 11: real sessions persist only the snippet count. Typed text is kept minus code blocks, and events keep only scalar fields. Cost if wrong: a little scorecard detail.
14. Task 11: one `_scrub_text` handles all free text. Cost if wrong: some code-like prose could still be stored.
15. Task 11: "indented" means any leading space or tab, and event keys must be strings of at most 40 characters. Cost if wrong: some legitimate indented prose is dropped.
16. Task 12: checkpoints hold hashed snippet lines, not text. Cost if wrong: none, since snippet text isn't needed from state.
17. Task 13: consent-no means no file content to the model, including the student's added lines. Cost if wrong: weaker questions for consent-no users.
18. Task 13: consent-no skips explain-back (no ownership score, no auto-drop). Cost if wrong: those users get no explain-back.
19. Task 15: stored prose keeps the broad redact rule, so "fix token: handling" can become "fix token: [redacted]". The final reviewer upheld it. Cost if wrong: some history titles show a redacted last word.
20. Final review: the remaining deferred minors from Tasks 4–15 are accepted for dogfooding. Cost if wrong: listed edge cases remain, notably `.anvylignore` having no `!` negation, `ENV PASSWORD x` and `db_pass` not redacted, a hard kill leaving checkpoint text until the next-start purge, and tracebacks on some startup/login errors.
21. Final review: one fix wave only, with residuals going to Val. Cost if wrong: a residual waits for Val.
22. Final review: invisible characters outside the widened set (U+034F, Hangul fillers, variation selectors, U+206A–206F) are left uncovered. Cost if wrong: the model could read a visually forged closing tag, which can only change what it says.

## Memory Pointers

- claude-mem observations exist for each SDD task (Nov 23, 2026 timeline). I did not run a targeted search for this handoff.
- Searches worth re-running: `anvyl phase1 final review`, `anvyl prompt injection fence`, `mistral palette anvyl`.

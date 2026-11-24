# Dogfood guide (Phase 1, local only)

Anvyl is installed locally and used by Val on real tickets, starting with this project. Nothing leaves the machine except model calls you trigger yourself.

## Install

```bash
python -m venv .venv
.venv/bin/pip install -e .      # or: pipx install .
.venv/bin/anvyl --help
```

You need an OpenRouter API key. The default model is `anthropic/claude-sonnet-4.5`; change it with `ANVYL_MODEL`. Data lives in `$ANVYL_HOME` or `~/.anvyl`.

## Manual checklist (run on a real ticket in this project)

Run these from the project folder.

1. `anvyl login`, paste the key. Confirm it is not echoed.
2. `anvyl` (first use). Expect the profile prompt: Professional is the default, Personal is the alternative. Check that the choice is remembered on the next start.
3. Consent **no**. When asked about file reading, answer `n` (or press Enter, which means no). Expect "ticket-and-plan-only coaching", no file tools, and no explain-back at all: no questions, no grading. The scorecard shows no ownership line, and the tutorial-style record stores 0.0 ownership.
4. Consent **yes**. Use a second folder (consent is remembered per folder) and answer `y`. Expect file tools offered to the coach and explain-back after your diff.
5. A **Learn** ticket: describe the ticket, type a genuine attempt (the gate rejects empty or vague ones), ask the coach, edit the code yourself, `/done`, answer the three questions.
6. A **Ship** ticket: `/mode ship`, then a ticket. It applies from the next ticket. Expect the fast path.
7. `anvyl preview "your ticket"`: shows exactly what would be sent, redacted, with no network call.
8. `anvyl history`: past sessions with ownership and time.
9. Kill the terminal mid-session (close the window while at a work prompt), reopen, run `anvyl`, and confirm you can resume or that the stale thread is cleaned up.

## Grading-quality check against the real model

CI checks grading against a fake client. Before relying on it, check the real model by hand with the three fixtures in `tests/fixtures/grading.json` (`add-retry`, `fix-offbyone`, `add-flag`). Each has a diff, three questions and `good`, `vague` and `wrong` answer sets, with expected scores of 1.0, 0.0 and 0.0.

For each fixture, call `anvyl.grader.grade_answers` with a real `anvyl.llm` client (key from `anvyl login` or `OPENROUTER_API_KEY`), passing the fixture diff and the question/answer pairs for each answer set. Check that good scores about 1.0 and vague and wrong score about 0. Note any fixture where the model is too harsh or too lenient.

## Exit criteria (Val decides after using it)

- The session loop feels good.
- The gate and explain-back are fair.
- The coach is useful.
- Nothing leaks (code, keys) in the Professional profile.

## Known limits

- The code scrubber is best effort, not a guarantee.
- One thread per ticket: a ticket runs start to finish, one at a time.
- Stale checkpoint threads are purged after 7 days.
- `anvyl reset` does not clear the OS keychain; use `anvyl logout` for the key.
- A hard kill (SIGKILL, power loss) leaves checkpoint text on disk until the stale purge.
- `/level` and `/mode` apply from the next ticket. Real sessions cap at L2.
- Tutorial records store 0.0 ownership when explain-back was skipped.

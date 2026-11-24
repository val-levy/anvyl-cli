# Anvyl (formerly "harness"): real-repo mode and first public release

Date: 2026-11-23. Status: draft v2, awaiting approval.
Builds on: `HARNESS-V1-SPEC.md` (the why; not repeated here). The product
is now called **Anvyl**; the command is `anvyl`.

## Intent

Today the project is a verified demo: a LangGraph loop (goal, attempt gate,
coach, implement, explain-back, scorecard), 42 passing tests, and two bundled
toy tasks with pre-written hints, quizzes and answers. This design turns it
into a product a stranger can install and use on their own work, in any
folder, in the style of Claude Code.

Why: Val wants junior engineers (interns, new grads) to use AI without losing
the understanding they need to become good engineers. The AI navigates; the
human thinks. The product shows what each level of AI help costs and buys.

## Who it is for

One junior engineer, on their own, using it voluntarily on a real task, in a
git repo or any folder. Includes web3 builders (hence the name check below).
No company or mentor rollout. A business model may change later; nothing here
builds it or blocks it.

## What the user experiences

```
brew install <tap>/anvyl        # tap name TBD
anvyl login                     # API key, stored in the keychain
cd ~/my-project && anvyl        # persistent session, like Claude Code
> add retry to the upload client        (a ticket, in your own words)
```

`anvyl` opens a persistent session in the current folder with slash commands.
The user can run task after task in it without restarting.

## Goals

1. Install to first real session in 10 minutes or less, unaided: Homebrew on
   macOS and Linux, `pipx`/`uv tool` on all three OSes including Windows.
2. A real session: free-text ticket, repo-aware read-only coaching, the user
   edits in their own editor, review by diff, explain-back questions
   generated from their diff, private scorecard.
3. The attempt gate and the "AI never writes into your files" rule stay
   enforced in code, not in prompts.
4. A junior can see over time whether they are getting better
   (`anvyl history`).
5. Safe with employer code: two privacy profiles (below), the user sees what
   leaves the machine, secrets never leave.

## Non-goals

- Mentor/manager reporting, team dashboards, accounts, any server.
- Telemetry or analytics of any kind.
- AI writing to the user's files (L3/L4) in this release. Deferred. This
  resolves spec open decision 4: locked in V1.
- A Textual TUI, Postgres, a plugin marketplace, remote plugin install,
  ticket-system integrations.
- Running any git command that writes (add, commit, push, checkout).
- Defeating a user who deliberately uses another AI tool in parallel. Anvyl
  is a commitment device for someone who wants to improve, not a proctor. The
  explain-back is the real ownership check.

## Anti-goals (failure even if it technically works)

- Interns find it so slow or preachy that they stop using it.
- A scorecard that feels like surveillance or a grade. It stays private and
  never leaves the machine.
- Explain-back that passes people who did not understand (keyword-matchable
  questions), or fails people who did (a harsh grader).
- Silent fallbacks that make it look like coaching happened when it did not.
- Shadowing or breaking another tool's command (see name).

## Findings in the current code that shape this design

- Explain-back is keyword matching against a quiz hand-written per task
  (`tasks.py`, `score_answer`). It cannot work on arbitrary tickets.
  Real-repo mode needs a model to generate questions from the diff and grade
  free-text answers, so it needs a live model; offline stays for the toy-task
  tutorial only.
- The attempt gate accepts any 20 characters and 3 words
  (`policy.gate_passed`). `"asdf asdf asdf asdf"` passes. Fine for a demo,
  not for a product.
- The judge/stripper is Python-only regex (`judge.py`, `policy.py`). Real
  work is in any language, and inline code is not caught.
- `Coach.live_call` swallows every error and falls back to offline hints. In
  real mode that would show toy hints for a real ticket.
- `tokens` is `len(text) // 4`, an estimate, not usage.
- `save_session` stores `solution_code` and attempts in plain JSON, with no
  schema version. With real work that stores employer code.
- The coach reads `HARNESS_OPENROUTER_HELPER`, a script on the author's
  machine.
- Dependencies are exact-pinned (`langgraph==1.2.24`), which conflicts with
  other tools when installed into shared environments.
- The CLI is one-task-per-invocation (`--task`), not a persistent session.
- README links `../HARNESS-V1-SPEC.md` (breaks when packaged) and its
  "Verification" section is dated 2026-11-24, after today.
- The folder is not a git repo: no history, CI or tags.

## Approaches considered

A. **Standalone CLI beside the editor (chosen by Val).** Runs in a folder;
   the coach reads read-only; the user edits anywhere; Anvyl reviews the diff.
   Keeps the gate enforceable. Cost: at L2+ it cannot tell typed from pasted
   from the diff alone.

B. Anvyl owns the editing (type inside the terminal). Exact authorship, but
   nobody does real work that way. Rejected.

C. Hooks/MCP inside Claude Code or Cursor. Reaches users where they are, but
   those tools can write code themselves, so the gate becomes advisory.
   Rejected.

## Design

### 1. Session flow

`anvyl` opens a persistent session in the current folder (git repo or not).
Slash commands: `/mode ship|learn`, `/level 0-2`, `/profile`, `/status`,
`/score`, `/graph`, `/rail`, `/help`, `/quit`. Each task below runs inside it.

1. **Ticket.** Free text in the user's words.
2. **Triage** (spec: ship vs learn vs high-stakes). Default Learn for this
   audience. A deterministic check flags high-stakes from the ticket text and
   touched paths (auth, payments, migrations, security, secrets). The user can
   switch to Ship for routine work; high-stakes always requires explain-back.
3. **Attempt gate.** The user writes a plan in their own words. Enforced in
   code. Strengthened check in section 3.
4. **Coach.** Model with read-only tools (`list_files`, `read_file`, `grep`)
   scoped to the folder, minus the denylist. No write tools. Hint ladder 0-3
   unchanged. Replies still pass stripper and judge.
5. **Implement.** Anvyl records a baseline, then waits. The user edits in
   their editor and types `/done`.
6. **Review.** Anvyl diffs the working tree against the baseline. Human
   lines = added lines in that diff.
7. **Explain-back.** Model generates three free-text questions from the diff
   (what it does, why this way, what breaks); the user answers from memory
   before seeing any summary; the model grades against the diff.
8. **Scorecard.** As today, plus level history; saved privately. The session
   returns to the prompt for the next ticket.

Ship mode: steps 1-2, then coach or a draft on request (L2 snippets are shown
in the terminal, never written to files), `/done`, review, scorecard;
explain-back only if high-stakes.

### 2. Levels

L0 (silent, baseline), L1 (default), L2 (snippets shown in terminal, the user
types them). L3 and L4 are not selectable in this release. For L2,
`ai_suggested_lines` counts lines in shown fenced snippets; added diff lines
that match a shown line (whitespace-normalized) count as AI-authored. This
heuristic has a known ceiling: reworded pasted code counts as human. The
auto-drop rule (ownership under 0.5 drops to L1) is unchanged.

### 3. Enforcement upgrades

- **Gate quality.** Keep the deterministic floors (non-empty, length). Add:
  reject repeated-token or low-entropy text and text that merely repeats the
  ticket. Add a model check "is this a genuine attempt at a plan, right or
  wrong?" returning yes/no with a reason. If the model fails, fall back to the
  deterministic floors, never to "pass unchecked". A user who wants to game
  it can; the goal is to stop accidental and lazy passes.
- **Judge.** Language-agnostic leak detection: fenced blocks, inline code
  beyond a short threshold, and statement-like lines in the languages found
  in the folder. Keep `judge_check(text) -> {leaked, reasons}` so an LLM judge
  can slot in later.
- **No silent offline fallback** in real mode (section 5).
- **Prompt injection.** Files, tickets, diffs and the user's answers are
  fenced and labeled as data in model prompts. Coach tools are read-only and
  the stripper and judge still run, so an injected file cannot make the coach
  write code or files.

### 4. Privacy profiles

Each folder is either **Professional** (employer code) or **Personal** (the
user's own projects). Asked on first use in a folder, remembered, changeable
with `/profile`. If Anvyl cannot tell, it defaults to Professional; moving a
folder to Personal is always the user's explicit choice.

**Professional**
- Nothing from the folder is sent to the model provider until the user gives
  an explicit yes for that folder. The prompt says exactly what is sent
  (ticket, files the coach reads, the diff, answers).
- A "no" is not a dead end: coaching continues from the ticket and the plan
  only, with no files read, plus the offline tutorial.
- Strict denylist and redaction of possible secrets in diffs before sending.
- Sessions store scores, the user's plan and their answers, and diff stats.
  They never store code or diffs.
- `anvyl preview` shows the exact payload without sending it.

**Personal**
- A one-time notice that the coach reads files. No per-folder consent.
- The same hard denylist (`.env*`, keys, certs, `.git/`), but not the
  stricter redaction.
- Sessions may store diffs and code locally, opt-in, for a richer history.
- `anvyl preview` is still available.

Personal differs from Professional only in privacy, not in coaching or
scoring. History covers both, tagged by profile (my call).

Common to both: the denylist and a user-editable `.anvylignore`, `.gitignore`
respected when present, a file size limit, no telemetry, session JSON with a
`schema_version`, and `anvyl reset` deletes all local data.

### 5. Login, reliability and cost

- **Login.** `anvyl login` stores the key in the OS keychain (browser sign-in
  if OpenRouter supports it, else paste). The `OPENROUTER_API_KEY` env var
  also works. Where no keychain exists, a key file in the data dir with 0600
  permissions. The author-specific helper hook is removed from shipped code.
- Model errors in real mode are shown plainly (what failed, retry or quit).
  Sessions are resumable through the existing checkpointer.
- Real token usage from the API response, shown in the rail, with a
  per-session cap (default set by the builder, user-adjustable).
- Offline mode remains only for `anvyl tutorial` (the toy task, no key
  needed), which is also the first-run on-ramp.

### 6. Visibility over time

`anvyl history`: table of past sessions (date, ticket, mode, level, profile,
ownership, human vs AI share, time vs estimate) plus a short summary of
whether higher AI control correlated with lower ownership. Reads session JSON
only. The next-day retention check from the spec is deferred to the release
after this one (my call: it needs real usage data to tune).

### 7. Name, packaging and release

- **Name: Anvyl.** Checked 2026-11-23: no `anvyl` command on PATH or in
  Homebrew (formula or cask); npm free; PyPI `anvyl` is taken but `anvyl-cli`
  is free; a GitHub user `anvyl` exists, so the repo needs another owner or
  org name. `anvil` was rejected because Foundry's `anvil` (Ethereum dev
  node, used by web3 builders) would clash. Not checked: trademarks, domain.
  The README tells people the spelling.
- Rename the Python package `harness` to `anvyl`; entry point `anvyl`; data
  dir `~/.anvyl`; env vars `ANVYL_*`. There are no users yet, so no migration.
- **Homebrew:** a tap repo with a formula that builds the Python app in its
  own environment (no system Python needed). A bare `brew install anvyl`
  needs Homebrew core acceptance, which requires a following, so the tap
  comes first.
- Move the spec to `docs/`; fix README links; rewrite the README for juniors.
- Dependency ranges (`langgraph>=1.2,<2`, etc.); exact versions only in a dev
  lockfile used by CI.
- `git init`, tags, GitHub repo, CI (ruff, mypy, pytest) on macOS, Linux and
  Windows, Python 3.12 and 3.13.
- Build with `python -m build`, verify install from the wheel in a clean
  environment on each OS and from the tap on macOS, TestPyPI pre-release.
- Version 0.2.0; changelog; MIT license already present.

## Phasing: make it work well here first

Val, 2026-11-23: before anything is pushed for people to install, it has to
work well on his machine. So the work runs in two phases with a hard stop
between them.

**Phase 1: local only (this plan).** Everything in sections 1-6 plus the
rename, installed locally (`pipx install .` or `pip install -e .`) and used
by Val on real tickets, starting with this project. Local `git init` is fine
for history. Exit criteria, decided by Val after using it: the session loop
feels good, the gate and explain-back are fair, the coach is useful, and
nothing leaks (code, keys) in the Professional profile. Nothing leaves the
machine except model calls Val triggers himself.

**Phase 2: distribution (separate plan, only on Val's go).** Section 7's
Homebrew tap, PyPI/TestPyPI, GitHub repo and CI on three OSes, README for
juniors, and the beta with real juniors. Nothing in Phase 1 creates accounts,
remotes, taps or published packages.

## What Val decided

- Target: individual juniors, on their own.
- Scorecard private; business model deferred.
- Approach A.
- Professional and Personal profiles.
- Install with `brew install`, then run, log in with API keys, use in any
  folder, like Claude Code.
- Name: Anvyl.

## My calls (please check these)

- Learn is the default for this audience (spec had Ship).
- L3/L4 locked out; closes spec open decision 4.
- Explain-back is three generated free-text questions graded by a model, no
  multiple choice; closes open decision 3. A low score feeds ownership and
  auto-drop but never blocks the scorecard; no retry; the user sees what they
  missed afterward. High-stakes sessions cannot skip it.
- Real mode needs a live model and a key; bring-your-own OpenRouter key only
  (no Anthropic-direct, no bundled key). Default model
  `anthropic/claude-sonnet-4.5`, changeable with `ANVYL_MODEL`. Grading
  quality is checked with fixtures (sample diffs with good, vague and wrong
  answers) against a fake client in CI and the real model by hand pre-release.
- Git is optional. Anvyl only reads from git, never writes.
- Baseline: at `/done`, diff the working tree against a snapshot of file
  hashes (tracked and untracked, non-ignored) taken at session start. This
  covers pre-existing uncommitted edits, new files, renames as add plus
  delete, and mid-session commits. In a git repo, if HEAD moves to another
  branch, warn and ask whether to continue. Outside git there is no such
  check.
- Old interface: `anvyl tutorial` runs the existing toy-task graph and its
  keyword quizzes unchanged, so the 42 tests keep passing (renamed). `--task`
  stays as a hidden alias. Real mode adds new nodes beside it in the same
  graph module.
- L2 snippets: only fenced blocks count as shown snippets, and only at L2 or
  in Ship mode. At L1 the existing stripper and judge apply unchanged.
- Windows is a supported target, verified in CI.
- First real test: dogfood on this project (spec open decision 2).
- Release gating: the plan ends at a verified wheel, a GitHub release, the
  Homebrew tap and a `0.2.0rc1` pre-release on TestPyPI. Publishing to PyPI
  and creating the GitHub and tap accounts is a manual step Val does; the plan
  includes the checklist. The beta with real juniors happens after the plan.
- Retention check deferred to the next release.

## Left to the builder

CLI layout beyond the above, module structure, prompt wording, exact denylist
and secret patterns, token cap default, gate-check thresholds, how the
baseline snapshot is stored, the persistent-session UI (prompt library, rail
changes), the tap name, test strategy (including a fake model client).

## Ready means

A stranger on a clean machine runs `brew install`, `anvyl login`, and `anvyl`
in their own folder, and completes a real session on their own ticket with no
help; the gate cannot be passed with empty or junk input; no code or key
appears in logs or session files by default in Professional profile; CI is
green on three OSes; and a few real junior engineers use it for a week and
say whether they would keep using it (no telemetry, so by conversation).

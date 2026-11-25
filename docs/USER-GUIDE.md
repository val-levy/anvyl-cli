# Anvyl user guide

Anvyl is a coding coach. You do the thinking and the typing. The AI asks questions and gives hints, and only helps with code once you have tried. This guide covers everything the `anvyl` command can do.

Contents: [Install and first run](#install-and-first-run) · [A session step by step](#a-session-step-by-step) · [Levels and modes](#levels-and-modes) · [Slash commands](#slash-commands) · [The full-screen UI](#the-full-screen-ui) · [Models](#models) · [Profiles and privacy](#profiles-and-privacy) · [Skills and plugins](#skills-and-plugins) · [Sub-harnesses](#sub-harnesses) · [Command-line subcommands](#command-line-subcommands) · [The tutorial](#the-tutorial) · [Data and files](#data-and-files) · [Safety model](#safety-model) · [Troubleshooting](#troubleshooting)

## Install and first run

Requires Python 3.12+.

```bash
pipx install .                      # or: pip install -e ".[dev]" inside a venv
anvyl login                         # paste your OpenRouter API key (not echoed)
cd your-project
anvyl                               # start a session in this folder
```

The key is stored in the OS keychain (with a key-file fallback). `OPENROUTER_API_KEY` in the environment also works and takes priority. `anvyl logout` removes the stored key.

On first start in a folder, Anvyl asks three things, once:

1. **Profile**: professional (default) or personal. See [Profiles and privacy](#profiles-and-privacy).
2. **File reading consent** (professional profile only, per folder): may the model read files here? Answer `y` or `n`. Enter means no. With no, coaching uses only your ticket and plan, and there is no explain-back.

Your answers are remembered.

## A session step by step

The first thing you type is **a ticket**: one task you want to do, such as `add retry to fetch`. It is not a chat. Typing "hi" makes "hi" the ticket.

1. **Ticket.** Describe the task in a sentence or two.
2. **Triage.** Anvyl sets the loop for your mode and level.
3. **Attempt gate (Learn mode).** Write your plan in your own words. It can be wrong. An empty or vague attempt is rejected, and the coach and any code stay locked until you pass. This gate is enforced in code, not by a prompt.
4. **Coach.** The coach asks a question or gives a hint. Reply, or type `/hint` for another.
5. **Implement.** You write the code in your editor. Anvyl is not editing your files.
6. **`/done`.** Say you are finished. Anvyl looks at your diff.
7. **Explain back.** Three short questions about your own change, graded by the model with a strict rubric. This is the ownership check. It only runs when file reading is allowed.
8. **Scorecard.** Time with and without AI, percent of code you typed, ownership score, level history. Saved as JSON in `sessions/`. `/score` shows the last one.

If your ownership score drops below 0.5, Anvyl drops you back to L1.

## Levels and modes

| Level | Name | What the AI may do |
| ----- | ---- | ------------------ |
| L0 | Human only | Silent. Baseline for the with/without comparison. |
| L1 | Coach (default) | Questions and hints only. Never code. |
| L2 | Drafting partner | Drafts small bits; you edit and type. |

Real projects are capped at **L2**. L3 and L4 exist only in the tutorial. Set the level with `/level 0-2`. It applies from the next ticket.

| Mode | Behaviour |
| ---- | --------- |
| **learn** (default) | Attempt gate first, then coach, then explain-back. |
| **ship** | No attempt gate, no explain-back. The AI may draft. Fast path for daily work. |
| a harness id | A preset built on learn or ship. See [Sub-harnesses](#sub-harnesses). |

Switch with `/mode` (opens a menu) or `/mode learn`, `/mode ship`, `/mode <harness id>`. It applies from the next ticket. The status line shows the current mode.

## Slash commands

Type `/` to open a filtered menu. Use ↑/↓ and Enter, or keep typing the name.

| Command | What it does |
| ------- | ------------ |
| `/help` | List commands. |
| `/status` | Step, level, gate and usage. |
| `/score` | The last scorecard. |
| `/usage` | Session time, tokens, files sent to the model. |
| `/graph` | The loop steps. |
| `/rail` | Toggle the status rail. |
| `/mode [learn\|ship\|<id>]` | Pick a mode. No argument opens a menu. |
| `/level 0-2` | Coaching level. |
| `/profile professional\|personal` | Switch profile. |
| `/keepdiffs on\|off` | Personal profile only: keep diffs of your changes in the data dir. |
| `/model [query]` | Browse and pick a model. |
| `/history` | Your past sessions. |
| `/copy` | Copy the last coach answer to the clipboard. |
| `/copy all` | Copy the whole screen. |
| `/clear` | Clear the screen. |
| `/plugin [list\|load\|unload <id>]` | Manage plugins. No argument opens a menu. |
| `/skill [list\|load\|unload <id>]` | Manage skills. No argument opens a menu. |
| `/harness [install <folder>\|remove <id>]` | Manage sub-harnesses. |
| `/hint` | Ask the coach (at a work prompt). |
| `/done` | Finish the ticket (at a work prompt). |
| `/exit` | Leave Anvyl. Also `/quit`, `/q`. |

`/copy` uses `pbcopy`, `wl-copy`, `xclip` or `clip.exe`, whichever exists.

## The full-screen UI

`anvyl` takes over the terminal with a pinned input line and status bar, so the chat line never scrolls away. Messages fill upward from the bottom. The welcome block with the animated logo sits at the top.

| Key | Action |
| --- | ------ |
| Enter | Send. |
| Alt+Enter (Esc, Enter) | New line in the input. |
| PageUp / PageDown | Scroll the transcript. |
| ↑ / ↓, type, Enter, Esc | Move, filter, choose and cancel in a menu. |
| Ctrl+D | Send end-of-input at an empty prompt. |
| Ctrl+C | Quit. |

The dim text inside the empty input box always names the next step, for example "Step 2 of 4: answer the coach, or /hint". Your messages sit on a darker band. If you type while the agent is busy, the message is shown dimmed as queued and is sent at the next chat prompt. The window resizes live.

Typed text is never written to disk by the UI. Input history is in memory only. Set `ANVYL_INLINE=1` for plain inline output instead of full screen. This is also used automatically when stdin is not a terminal.

## Models

`/model` lists models from OpenRouter with price per million input and output tokens and context size. The list is fetched without sending your key. Type to filter, Enter to choose. The choice is saved in `config.json` and shown in the status line. Precedence: `/model` choice, then `ANVYL_MODEL`, then the default `anthropic/claude-sonnet-4.5`.

## Profiles and privacy

| | Professional (default) | Personal |
| --- | --- | --- |
| File reading | Asked once per folder. Default no. Secrets are redacted and denied files are never sent. | Always on. Non-secret files may be read. A notice is shown once. |
| Diffs | Not kept. | Kept in the data dir only if `/keepdiffs on`. |

Without file reading the coach sees only your ticket and what you type, and explain-back is skipped. `anvyl preview "your ticket"` shows exactly what would be sent for a ticket, redacted, without any network call. Use it whenever you are unsure.

## Skills and plugins

- **Skills** are `SKILL.md` files kept in `~/.anvyl/skills/`. `/skill list` shows them, `/skill load <id>` and `/skill unload <id>` switch them. Two examples are bundled: `toy-backoff` and `wifi-csi`.
- **Plugins** are folders with a `manifest.json` in `~/.anvyl/plugins/`. Bundled examples: `wifi-csi` and `gh-review`. Loading goes through the policy core, which refuses a plugin that would break a rule for your current mode and level.
- With no argument, `/skill` and `/plugin` open a menu. Enter toggles the highlighted item, Esc closes.

Current limit: loading a skill or plugin records your choice only. Their text is not yet sent to the model. To change what the coach focuses on today, use a [sub-harness](#sub-harnesses).

## Sub-harnesses

A sub-harness is a data-only preset that changes how the coach behaves, for example "TDD first" or "security review". Install one with `/harness install <folder>`, then pick it with `/mode`. Full details: [HARNESSES.md](HARNESSES.md).

## Command-line subcommands

Running `anvyl` with no subcommand means `anvyl session`. Every subcommand accepts `--data-dir`.

| Command | What it does |
| ------- | ------------ |
| `anvyl` / `anvyl session` | Coach you on a ticket in the current folder. |
| `anvyl login` / `logout` | Store or remove the OpenRouter key. |
| `anvyl history` | Table of past sessions with ownership and time. |
| `anvyl preview "<ticket>"` | Show what would be sent to the model. No network. |
| `anvyl harness init <id>` | Create a harness folder from a template. |
| `anvyl harness validate <dir>` | Check a harness bundle. |
| `anvyl harness pack <dir>` | Print the registry index entry with its sha256. |
| `anvyl tutorial ...` | Run the built-in tutorial. |
| `anvyl reset` | Delete all Anvyl data. Does not touch the keychain, use `logout` for that. |

## The tutorial

`anvyl tutorial` runs a self-contained practice task with no project and no key needed.

```bash
anvyl tutorial --list-tasks
anvyl tutorial --task toy-backoff --mode learn       # full loop
anvyl tutorial --task toy-backoff --mode ship        # fast path
anvyl tutorial --task wifi-csi-backoff --mode learn
```

Options: `--level 0-4`, `--goal "..."`, `--high-stakes` (forces explain-back even in ship), `--live` (real model instead of the offline hint ladder), `--interactive` or `--demo`, `--session <id>` (resume a blocked run), `--no-rail`. When stdin is not a terminal the run is scripted.

## Data and files

Resolved as `--data-dir`, then `$ANVYL_HOME`, then `~/.anvyl`.

```
~/.anvyl/
  config.json          profile, per-folder consent, chosen model, keepdiffs
  sessions/            one JSON scorecard per ticket
  checkpoints.sqlite   resumable loop state
  threads/             markers for in-flight tickets
  skills/  plugins/    your skills and plugins
  harnesses/           installed sub-harnesses
```

Closing the terminal mid-ticket leaves a checkpoint. Threads older than 7 days are purged at startup. `anvyl reset` removes everything above.

## Safety model

Anvyl is built so that text from your repo or from the model cannot change what Anvyl does.

- The attempt gate, levels, caps and grading thresholds are computed in code, never read from model output.
- The coach has read-only, path-restricted tools. At L1 it has no way to write code, and a code scrubber plus a separate judge remove anything that leaks.
- Anything untrusted (ticket, your attempt, files, harness text) is fenced and marked as data in the prompt.
- Grader output is strictly typed JSON and fails closed.
- Model output is never executed.
- Secrets are redacted before anything is sent. The scrubber is best effort, not a guarantee. Use `anvyl preview` to check.

## Troubleshooting

| Symptom | Fix |
| ------- | --- |
| `anvyl: command not found` | `pipx ensurepath`, then reopen the terminal. Or run `.venv/bin/anvyl`. |
| Every message gets "write a real plan" | The first input is a ticket and the next is your plan. Describe a task, then write a real attempt. |
| No explain-back questions | Professional profile with file reading refused for this folder, or you are in ship mode. |
| `/level 3` refused | Real projects cap at L2. |
| Screen garbled after a crash | Run `reset` in the terminal. |
| Need plain output | `ANVYL_INLINE=1 anvyl`. |
| No clipboard tool | Install `pbcopy`, `wl-clipboard` or `xclip`. |

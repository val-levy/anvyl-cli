# harness — human-most-of-the-loop coding harness

The human is the driver. The AI is the navigator.

Most agent harnesses optimize for autonomy: do the task, don't bother the
human. This one optimizes for human thinking. AI never just does the task
and hands it back. You do the thinking; AI helps you think better. And it
makes the trade-off visible: how much more productive you are with AI
versus without it, and how much understanding each level of AI control
costs you.

See the full design in `../HARNESS-V1-SPEC.md`.

## Install

Requires Python 3.12+.

```bash
# run it without installing system-wide
pipx install .

# or, for development
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

This installs the `harness` command.

## Quickstart

```bash
# First task: a tiny toy task, the exponential-backoff retry helper.
# It exercises the full Learn loop but stays trivial to verify.
harness --task toy-backoff --mode learn

# Fast path, no attempt gate, no explain-back (unless high-stakes):
harness --task toy-backoff --mode ship

# Second example task, from the WiFi sensing project:
harness --task wifi-csi-backoff --mode learn

harness --list-tasks
```

When stdin is not a terminal (or with `--demo`), the run is scripted:
the demo supplies the goal, the human attempt, the typed code, and the
explain-back answers from the task definition, so the whole loop runs
end to end with no one present. In a terminal it is interactive: you
type the attempt, the code, and the answers yourself.

## The loop (Learn mode)

1. **Goal** — state it in your own words.
2. **Attempt gate** — a hard gate in code, not a prompt. No edge to the
   coach or to any code until a human attempt is in typed state.
3. **Coach** — questions and hints on a rung ladder (0–3). At L1 the
   coach has no solution-writing tool, and a deterministic stripper +
   separate judge remove any code that leaks anyway.
4. **Implement** — you type. AI suggests line-by-line only at L2+.
5. **Explain back** — a short quiz (retrieval practice). This is the
   ownership check; tests passing is not learning.
6. **Scorecard** — time with vs without AI, % of code typed by you,
   ownership score, level history. Saved to `sessions/` as JSON.

**Ship mode** is the fast path for daily work: no attempt gate, no
explain-back, except for high-stakes changes (`--high-stakes`), which
always require explain-back.

## Levels of human vs AI control

| Level | Name | What AI may do |
| ----- | ---- | -------------- |
| L0 | Human only | Silent. Baseline for with/without comparison. |
| L1 | Coach (default) | Questions and hints only. Never code. |
| L2 | Drafting partner | Drafts small bits; you edit and type. |
| L3 | Implementer | Implements; you review and must explain back. |
| L4 | Autonomous | Checkpoints only, for boring low-learning tasks. |

You have to consciously turn the level up. If your ownership score
drops below 0.5, the harness drops you back to L1 automatically.

## CLI

Rich-based, opencode style: one blue accent, thin borders, no gradients,
no emoji. The top bar shows the task name and timer only — deliberately
no `LEARN • L1 • COACH` badge. Mode, level, and the 1–6 loop live in the
side rail, which auto-hides on narrow terminals (under 110 columns); a
one-line ministrip carries the essentials while it is hidden.

Slash commands (in interactive prompts, or as `/help`):

```
/mode ship|learn   /level 0-4   /status   /score   /graph
/rail               /plugin list|load|unload|install <id>
/skill list|load|unload <id>    /quit
```

## Live coach (Claude via OpenRouter)

By default the coach is **offline/demo**: deterministic hints from the
task's rung ladder, free and reproducible. Pass `--live` for the real
model (Claude via OpenRouter):

```bash
export OPENROUTER_API_KEY="..."        # standard path
# or point at a helper script with a `chat` subcommand:
export HARNESS_OPENROUTER_HELPER="/path/to/openrouter.py"
harness --task toy-backoff --mode learn --live
```

No key is ever stored in the repo. Without a key or helper, `--live`
falls back to offline hints and says so in the scorecard (`live model:
no`).

## Plugins and skills

Skills are `SKILL.md` files, loaded on demand only (`/skill load
wifi-csi`). Plugins are bundles (manifest + skills + commands + tools)
under `plugins/`, loaded with `/plugin load <id>`.

The rule that matters: **plugins run inside the policy core**. A plugin
cannot bypass the attempt gate, change your level, or write code at
L0/L1 — whatever its manifest claims. Remote plugin fetching is a stub
in V1; add a local folder with a `manifest.json` to install one.

Bundled examples: skills `toy-backoff`, `wifi-csi`; plugins `wifi-csi`,
`gh-review`.

## Data

All runtime data lives in one dir, resolved as `--data-dir` >
`$HARNESS_HOME` > `~/.harness`:

```
~/.harness/
  sessions/           session JSON logs (one per run)
  checkpoints.sqlite  LangGraph checkpointer (resumable sessions)
  skills/             your skills (bundled examples seeded on first run)
  plugins/            your plugins (bundled examples seeded on first run)
```

Resume a blocked session with `harness --session <id>` (re-answers the
pending interrupt).

## Layout

```
pyproject.toml          packaging, entry point, ruff/mypy/pytest config
src/harness/
  __init__.py  __main__.py  cli.py       Rich CLI + slash commands
  state.py     typed LangGraph state
  graph.py     the directed graph + interrupt/resume driver helper
  policy.py    non-LLM policy core (gate, levels, plugin gating)
  judge.py     separate judge (did code leak into a reply?)
  coach.py     live Claude via OpenRouter / offline hint ladder
  tasks.py     task registry (toy-backoff default, wifi-csi-backoff)
  registry.py  plugin + skill registries
  storage.py   data-dir resolution, session JSON, checkpointer path
  data/        bundled example skills + plugin manifests
tests/         pytest: policy, judge, tasks, graph, coach, registry, storage
```

## Development

```bash
pip install -e ".[dev]"
pytest            # 42 tests
ruff check src tests
ruff format --check src tests
mypy src/harness
```

## Verification (2026-11-24, this repo)

- `pytest`: 42 passed, covering the attempt gate, the stripper, the
  judge, plugin gating, level auto-drop, task verification, the full
  Learn loop, the Ship fast path, the gate proof (no attempt -> coach
  never runs, no code exists), Ship high-stakes explain-back, and the
  live-coach fallback.
- `ruff check`, `ruff format --check`, `mypy src/harness`: all clean.
- `harness --task toy-backoff --mode learn` (demo): ownership 100%,
  verify passed (6/6 checks), session JSON saved.
- `harness --task toy-backoff --mode ship`: AI-drafted, verify passed,
  explain-back correctly skipped.
- `harness --task wifi-csi-backoff --mode learn`: verify passed.
- Interactive run via piped stdin: ownership 100%, verify passed.
- Empty attempt in interactive mode: gate blocks, session saved for
  resume with `--session`.
- Live coach (`--live`, Claude via OpenRouter through the author's
  helper): real reply received, `live_model: yes`, ownership 100%.
- Clean-venv `pip install` of the project directory: entry point works,
  demo run passes, bundled skills/plugins seed into a fresh data dir.

## What is real vs stubbed in V1

Real: the LangGraph graph, the hard attempt gate, the stripper + judge,
the rung-ladder coach, the scorecard, SQLite checkpoints, session JSON
logs, the plugin/skill registries with policy gating, the Rich CLI.

Stubbed / future: remote plugin fetching (`/plugin install` for new
plugins), an LLM judge (the V1 judge is deterministic regex), Postgres
checkpointer (SQLite for now), a live Textual TUI (Rich first).

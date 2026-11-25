```
 ███   █   █  █   █  █   █  █    
█   █  ██  █  █   █   █ █   █    
█████  █ █ █  █   █    █    █    
█   █  █  ██   █ █     █    █    
█   █  █   █    █      █    █████
```

**A coding tutor for your terminal. You drive, the AI teaches.**

Most coding agents optimize for autonomy: take the task, hand back the diff. Anvyl optimizes for you understanding your own code. It talks the problem through with you, teaches the idea you're missing, and only helps with code once you've shown you can do the thinking. After you write the change, it asks you to explain it, and remembers what you've shown you know so it never re-teaches it.

## Features

- **Dynamic tutor.** The model decides every turn: ask, teach, hint, or declare you ready. "I don't know" is always a fine answer, and it never locks you out.
- **Rules live in code, not prompts.** The attempt gate, help levels, caps and grading thresholds are computed deterministically. Model output can't open the gate or change your level.
- **No-code coach.** At L1 the coach can only ask and hint. A scrubber plus a separate judge strip any code that slips through.
- **Explain-back.** Three short questions about your own diff, graded with a strict rubric. That's your ownership score.
- **Persistent memory.** Short idea labels (never code) of what you've shown you can do, per learner and per project. `/memory` lists them, `/memory forget <idea>` removes one.
- **Private by default.** Secrets are redacted before anything is sent, file reading needs your consent per folder, and `anvyl preview` shows exactly what would be sent.
- **Full-screen terminal UI** with a pinned input line, slash-command menu and live model picker.

## Install

Requires Python 3.12+.

```bash
pipx install .      # or: uv tool install .
cd your-project
anvyl               # then type /login and paste your OpenRouter API key
```

For development: `python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"`.

## A session

1. Type one task, e.g. `add retry to fetch`.
2. Talk it through with the tutor. It asks, teaches and hints until you've stated a workable approach.
3. Write the code in your editor, then type `/done`.
4. Explain your change in three short answers.
5. Get a scorecard: time, how much you typed yourself, ownership score.

Prefer speed? `/mode ship` skips the teaching and questions. No project handy? `anvyl tutorial` runs a practice task offline.

## Levels

| Level | What the AI may do |
| ----- | ------------------ |
| L0 | Nothing. Baseline for comparing with and without AI. |
| L1 (default) | Questions and hints only. Never code. |
| L2 | Drafts small bits; you edit and type. |

Real projects are capped at L2. If your ownership score drops below 0.5, Anvyl drops you back to L1.

## Documentation

- [User guide](docs/USER-GUIDE.md): every command and setting.
- [Sub-harnesses](docs/HARNESSES.md): data-only presets such as "TDD first" or "security review".
- [Manual test checklist](docs/MANUAL-TEST.md): trying it on a real ticket.

## How it's built

A [LangGraph](https://github.com/langchain-ai/langgraph) state machine with SQLite checkpoints, so a ticket survives a closed terminal. Human input arrives through `interrupt()`; a deterministic policy core owns every gate. Models are reached through OpenRouter, and the default is `anthropic/claude-sonnet-4.5`.

```
anvyl/
  graph.py     the session graph: tutor, coach, implement, explain-back, scorecard
  tutor.py     tutor moves and idea extraction
  policy.py    gate, levels, code stripping (no LLM)
  grader.py    strict-JSON grading, fails closed
  memory.py    persistent idea memory
  coach.py     offline hint ladder; real_coach.py: the live model coach
  fullscreen.py, tui.py, theme.py   terminal UI
tests/          pytest
```

## Development

```bash
pytest
ruff check anvyl tests
mypy anvyl
```

## License

MIT

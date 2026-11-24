# Human-Most-of-the-Loop Harness — V1 Spec Draft

Val, 2026-11-23. Working draft to build together.

## Problem, in Val's words

Using AI to offload all software engineering work gets it done much faster, but he does not understand anything he does. It is really hard to force himself to stop because there is no reason to stop.

This harness is the opposite of a normal agent harness. Normal harnesses optimize for autonomy. This one optimizes for human thinking.

## Core principle

Human is the driver. AI is the navigator.

AI never gets to just do the task and hand it back. You do the thinking. AI helps you think better. That is what AI tools were supposed to be.

## Practicality for daily engineering — not just students

Val's challenge, 2026-11-23: as written, this is a learning tool. For daily shipping it would be too slow. Attempt-first and explain-back on every ticket would kill real work.

Fix: do not apply learning friction to everything. Triage by task type, and run in two modes.

**Ship mode — default for daily work.**
Fast. AI can do more. Goal is ship correctly, not learn everything. No attempt gate, no explain-back, except for high-stakes changes. This is where most tickets live.

**Learn mode — for novel or high-stakes work.**
The full loop above: attempt gate, coach, you type, explain-back, scorecard. Used when the task is new, core logic, architecture, debugging you do not understand yet, or anything where getting it wrong is expensive.

**Task triage — how the harness decides, with you able to override:**
- **Routine / boilerplate / low learning value:** Ship mode, L3/L4 allowed. Tests, migrations, boilerplate, formatting, scripts you already understand. Rational offloading.
- **Novel / core logic:** Learn mode, L1/L2. New system, new pattern, core algorithm, first time in a codebase area.
- **High-stakes:** Learn mode + explain-back required, even in Ship mode. Architecture decisions, security, data migrations, payments, auth. Getting this wrong costs more than the time saved.

Psych backing for the split: desirable difficulty only pays off when the learning value exceeds the time cost. For routine tasks, the cost exceeds the benefit, so friction is irrational. For novel tasks, the benefit exceeds the cost, because understanding is what lets you debug at 2am, pass interviews, and get promoted. Professionals atrophy too, the doctor study in the research showed unassisted detection fell from 28.4% to 22.4% after months of AI-assisted work, so this is not a student-only problem. It is a where-does-understanding-matter problem.

V1 now ships with both modes, with Ship as default. Learn mode is not the default for every task, it is the default for tasks the harness flags as novel or high-stakes.

## The loop for one coding task — every step has a psych reason, or it gets cut

1. **Goal in your own words.** *Generation effect + metacognition.* Putting it in your own words forces you to actually understand the task instead of copying a prompt. If you cannot state it, you do not understand it yet. This also fixes the miscalibration problem from the research: people overestimate what they know after getting help.
2. **Attempt gate.** *Desirable difficulty + pretesting effect.* Trying first, even badly, makes the later learning stick. Bjork's desirable difficulties and the pretesting studies show attempt-first improves retention vs AI-first. This is why it is a hard gate in code, not a suggestion. If there is no attempt in state, there is no edge to code.
3. **Coach.** *Scaffolding + Zone of Proximal Development.* AI gives just enough help to keep you in the zone where the task is hard but doable, not so much that it does it for you. Hints on a rung ladder, not answers. This is also Self-Determination Theory: you keep autonomy because you are still choosing the approach.
4. **Implement, you type.** *Generation effect + effort.* Typing it yourself, not pasting it, creates the motor and memory trace. Pasting is consumption. Typing is creation. Line-by-line approval is friction by design, it stops autopilot acceptance.
5. **Explain back.** *Retrieval practice / testing effect + Feynman technique.* Recalling and explaining from memory strengthens the trace far more than re-reading AI output. This is the ownership check. Tests passing is not learning. Explaining it is.
6. **Scorecard.** *Feedback + competence + metacognitive calibration.* You cannot fix what you cannot see. Right now speed is visible and understanding is invisible, so your brain optimizes for speed. Making ownership visible rebalances that. This is also why the scorecard shows both, not just speed.

## Levels of human vs AI control — not arbitrary, each level is a different autonomy trade-off

The dial exists because Self-Determination Theory says motivation dies when autonomy is removed. If AI always decides, you lose autonomy and competence, even if you gain speed. The dial lets you choose the trade-off consciously, and the harness makes the cost visible.

- **L0 — Human only.** *Baseline + A/B control.* Needed to measure what you can actually do without AI. Without L0, you have no with-vs-without comparison. AI silent, just observes and logs.
- **L1 — Coach.** *Maximum autonomy + scaffolding.* You keep full control, AI only questions and hints. Default, because this is where learning is highest. This is the level the whole harness is built around.
- **L2 — Drafting partner.** *Competence with support.* AI drafts small bits, you edit and type. You still generate the structure, AI helps with syntax and boilerplate. This is for when typing everything is low-value friction, not learning.
- **L3 — Implementer.** *Efficiency, with a tax.* AI implements, you review and must explain back. Allowed only for well-understood tasks where the learning value is low. The explain-back tax is what keeps it from becoming pure offloading.
- **L4 — Autonomous with checkpoints.** *Rational offloading.* For boring, low-learning tasks where offloading is actually the right call. It exists so you do not waste willpower fighting AI on tasks with no learning value. It is never the default, and it is tracked separately so it does not silently become your default for everything.

Default is L1. You have to consciously turn it up, and it drops back down if your ownership score drops. That auto-drop is loss aversion + friction working for you, not against you. The harness tracks which level you were on for each task, so you can see the trade-off you actually made.

## Psychology backing — the rule for what stays

Rule: if a feature does not map to one of these mechanisms, it gets cut. No decoration.

- **Desirable difficulty (Bjork).** Making it slightly harder in the moment improves long-term retention. That is why the attempt gate and the explain-back exist. Easy now = forgotten later.
- **Generation + pretesting effect.** Trying to generate an answer before seeing it improves memory, even if you get it wrong. That is why you write the plan first.
- **Retrieval practice / testing effect.** Recalling from memory strengthens the trace more than re-reading. That is why explain-back is a quiz, not a summary.
- **Self-Determination Theory (Deci & Ryan).** Intrinsic motivation needs autonomy, competence, and relatedness. The levels dial protects autonomy. The scorecard protects competence by showing real progress. The coach protects relatedness by being a partner, not an oracle.
- **Flow (Csikszentmihalyi).** Challenge needs to be just above skill. Too easy, you check out. Too hard, you quit. The hint rung ladder is how the harness keeps you in flow instead of jumping to the answer.
- **Dopamine as prediction error, not pleasure.** From the research: dopamine signals wanting and surprise, not liking. That is why reward is tied to progress and rarity, not just finishing. A score that goes up when you do something original hits harder than a checkmark for finishing.
- **Metacognitive calibration.** People misjudge what they know after getting help, the illusion of knowledge from the research. The ownership score is the external calibration. Your feeling of knowing is not trusted, the quiz is.
- **Habit and friction.** Willpower fails. Environment wins. That is why the gate is in code, not in your head, and why L1 is the default. You have to do work to turn up AI control, not work to turn it down.
- **Overjustification effect.** Turning an intrinsically interesting activity into a performance for points or likes kills the interest. That is why the scorecard is private, for you, not a leaderboard. No public feed, no likes.

Cut list from this pass: no public leaderboard, no streaks for their own sake, no generic points. Those would be there for no reason. If a feature does not serve one of the mechanisms above, it does not ship in V1.

## Productivity visibility — with vs without AI

After each task, and over time, show:

- **Time:** time with AI vs your estimate without it, and over time, actual A/B when you do a similar task at L0.
- **Authorship:** % of code typed by human vs pasted from AI, % of lines you approved vs wrote.
- **Ownership score:** from the explain-back quiz. Can you explain what it does, why, and what breaks?
- **Retention:** next-day recall check on one thing from yesterday. Did it stick?
- **Level history:** how often you were at L1 vs L3/L4, and whether higher AI control correlated with lower ownership.

The point is to make the hidden cost visible. Right now speed is visible and understanding is invisible. This makes both visible.

## Enforcement — why this is a harness, not a prompt

From the harness research (2026-11-23):

- No harness ships attempt-first natively. Prompt alone does not withhold reliably.
- Enforcement needs a non-LLM policy core + a deterministic stripper + a separate judge.
- LangGraph hosts that as a graph node. Other harnesses need bolt-ons.

So in this harness:

- The attempt gate is a LangGraph node that reads typed state (`attempts`, `human_attempt`, `help_rung`). No edge to an answer/code node until it passes.
- The coach model has no solution-writing tool at L1. Only question, hint, and score tools.
- An output judge node checks replies before they reach you, and a deterministic stripper removes solution code if it leaks.
- All attempts, scores, and human-vs-AI attribution are stored as typed state, so you can replay and audit a session.

## Stack — V1 choice

- **Harness:** LangGraph, Python. #1 from the comparison. Explicit directed graph, typed state, `interrupt()` + checkpointer for durable pauses, `Send()` fan-out for diverge, Store + LangSmith-style evals for scoring over time.
- **Model inside it:** Claude via OpenRouter, which Val already has connected and verified. Keep the model swappable so coaching quality is not tied to the harness.
- **State for prototype:** SQLite checkpointer first, Postgres when it needs to survive restarts and be shared. Keep it simple for V1.
- **Interface for V1:** CLI prototype for Val's own coding, one task at a time, on a real repo. Not a web app yet.

Claude Agent SDK is not the harness here. Use Claude as the model inside LangGraph if we want its coaching quality.

## CLI design — long-term, own CLI that looks nice

Val, 2026-11-23: long-term he wants his own CLI. Claude Code looks nice, but opencode / Codex-style CLIs look cooler. Wants colors, nice indicators, and sections for monitoring and observability.

For this harness, looks are not decoration. Monitoring *is* the product. If you cannot see your level, your ownership, and where you are in the graph, the harness fails.

**Layout, V1:**
- **Top bar, always visible:** mode and level in color, e.g. `LEARN • L1`, task name, timer. Glanceable: are you in Ship or Learn, and is AI doing too much?
- **Main area:** chat and code, color-coded by author. Human in green, AI in cyan, system/gates in amber, errors in red. When the attempt gate blocks AI, show a lock indicator, not silence. When you pass it, a check.
- **Side panel — observability:** current LangGraph node (goal, attempt, coach, implement, explain-back), ownership score as a bar, human vs AI bar (% you typed vs AI typed), attempts, help rung, tokens, time with vs without AI.
- **Bottom bar:** input + status, spinner when AI is thinking, check when a gate passes, warning when ownership drops.

**Indicators:**
- 🔒 locked: attempt gate, AI cannot write code yet
- ✓ passed: gate passed, explain-back passed
- ● thinking: AI working, with node name
- ▲/▼ level: level changed, with reason

**Tech for the CLI:**
Python, since the harness is LangGraph Python. Rich first for a nice Claude Code-style CLI, Textual later if we want a full live TUI with panels like opencode. Keep harness and UI in the same stack. No separate TS frontend for V1.

**Commands to keep:**
`/mode ship|learn`, `/level`, `/status`, `/score`, `/graph` to see the current LangGraph state. All of them just read the same typed state the harness already tracks, so observability is free, not a second system.

## V1 scope — what we build first

- One CLI command that runs the loop above on one coding task, with Ship vs Learn mode selection at the start.
- Ship mode: fast path, no attempt gate, no explain-back except high-stakes changes.
- Learn mode: attempt gate, coach at L1/L2, explain-back quiz, and a simple scorecard printed at the end and saved to a local log.
- Works on Val's own repos, starting with a small task he picks.
- No autopilot mode in V1 as default. L3/L4 are available in Ship mode for routine tasks, locked or heavily gated in Learn mode until the tracking proves L1/L2 works.

## Open decisions for Val

1. CLI prototype for his own coding vs full spec vs dashboard first? He was asked this on 2026-11-23, awaiting pick.
2. Which repo and task for the first real test?
3. How strict should the explain-back be? Quiz, or just a short written explanation?
4. Should L3/L4 be available in V1 at all, or locked until ownership is proven?

## Related research

- Cognitive offloading research page: Cognitive Offloading and Offline Reward
- Harness comparison page: Agent Harnesses Comparison
- Key studies: Scarampi et al. 2026 fMRI, Kumar et al. 2024/25 N=1,100, Kosmyna MIT 2025 preprint (cite with caveat), Bastani et al. 2026 tutoring RCT ~1,000 students.

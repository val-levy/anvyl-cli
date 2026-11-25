# Tutor mode: design

Status: approved. Phase 1 (tutor conversation, persistent memory, welcome menu) is built; closeness check, file edits and metrics are later phases.

## Intent

Anvyl should be a coding agent people choose over a normal one because it is useful and it makes them better. Today it feels like a grader: it locks you out until your plan passes a check. It should feel like a tutor. It asks your goal, how you would approach it and what the first step is, and it teaches until you understand. Once you have shown you understand an idea, it does the repeats of that idea for you, including editing your files. It never writes the first version of something you have not done yourself. The product also measures how fast you are learning and building, compared with no AI and with full AI.

## Goals, non-goals, anti-goals

Goals
- A step-by-step tutoring conversation that always moves you forward ("I don't know" is a valid answer and leads to teaching).
- AI edits your files only for ideas you have already shown you can do.
- Learning and building speed shown against a no-AI and a full-AI reference.
- A closeness threshold you can tune with data.

Non-goals
- No new graph for Ship mode. Ship stays the fast path.
- No levels above L2 on real projects.
- No remote registry work in this project.

Anti-goals (failure even if it works)
- The AI does something you had not learned.
- It treats "you wrote a method" as "you know all methods", or "you used a class" as "you know classes".
- The coach lectures or grades instead of helping.

## Constraints (unchanged)

- Injected text may change what the model says, never what Anvyl does. The unlock, levels, caps and edit permission are computed in code from strictly typed, fail-closed grader JSON.
- Untrusted text (ticket, answers, files, harness text) is fenced. Model output is never executed.
- Writes only inside the project folder, only to files shown in a diff the user approved, never without that approval.
- Typed text is never written to disk by the TUI. Nothing goes outward without an explicit say-so.

## Approaches considered

1. **Rework the loop (chosen):** replace the attempt gate and coach nodes with a step loop plus a progress ledger kept in code. Most work, but the gate and unlock live in code and the ledger feeds metrics.
2. Prompt-only tutor on the current graph: cheap, but the unlock would rest on the model's word. Rejected.
3. Separate engine outside LangGraph: breaks checkpoint/resume and the tested policy core. Rejected.

## The flow

```
goal -> approach -> step (loop) -> done -> explain-back -> scorecard
                       |
        try a step -> feedback -> [teach if a gap] -> next step
                                   \-> closeness check -> offer to do it for you
```

1. **Goal.** The coach asks what you want and what "done" looks like. One question at a time.
2. **Approach.** It asks how you would go about it. A real attempt, a partial one or "I don't know" are all accepted. "I don't know" triggers a short teach (a small example on a different toy problem, never your solution) and the question is asked again. The old reject-and-lock gate goes away. The coach still cannot write code at L1.
3. **First step.** It asks for just the first small step. The step list is the user's, kept in state as short typed labels.
4. **Each step:** you do it, the coach gives feedback, teaches if there is a gap. A typed check then records what you showed (see ledger).
5. **/done, explain-back, scorecard** as today, plus the metrics below.

The level logic stays: L0 silent, L1 hints, L2 drafts. Below 0.5 ownership still drops you to L1.

## The ledger and the closeness check

The unit is an **idea**, not a construct. Writing one method proves you know that idea (for example "retry a failing call with backoff"), not that you can write any method or any class. Shared syntax, being a method on the same class and using the same language features are explicitly not evidence. Knowing how to write a function in general is assumed. The implementation and the depth are what is learned.

A ledger entry holds a short idea label, the aspects you covered (happy path, edge cases, errors, performance), the step it came from, and the evidence (you wrote it yourself and passed a check or explained it). It lives in checkpointed state as short labels and counts only. No file text.

When you reach a new step, a typed grader compares the step with ledger entries. It judges understanding, not form, and returns four booleans:

1. same underlying idea or logic
2. same aspects covered (no new edge case, error path or depth)
3. no new concept, API or library involved
4. no new judgement call (a design choice that needs your decision)

Code counts the yeses (never the model):
- 4 of 4 and the entry has at least `reps_needed` successes: **offer** to do it. You approve a diff.
- 3 of 4: you do it, Anvyl checks it.
- 2 or fewer: you do it, the coach teaches.

Defaults are cautious: `min_yes = 4`, `reps_needed = 2`. Presets `cautious`, `balanced`, `eager` set both. The asymmetry is deliberate: acting early takes away learning, acting late costs a minute.

Any grader failure, malformed JSON or missing field means no offer.

## Persistent memory

The coach never relies on chat history. Every model call is rebuilt from stored state, so a cleared context, a restart or a new session loses nothing, and nothing grows with session length.

Two small stores in the data dir, written by code only:
- **Learner memory (global):** the ledger. Ideas you have shown you can do, with aspects covered, success count, first and last seen. An idea you know in one project carries to the next.
- **Project memory (per folder):** one line per past ticket (goal, outcome, date), the ideas it touched, and a one-line "where we left off" for an unfinished ticket.

What reaches the model is a **budgeted recap**, about 300 tokens at most: up to five ledger ideas picked by plain keyword overlap with the current step (no extra model call), plus the last-session line. It goes in a fenced untrusted block. Entries are short cleaned labels with a length cap, never code or typed text, and only code creates them, after a typed check.

Knowledge fades. Evidence older than a set window (default 60 days, tunable) no longer counts toward an offer, so an old idea is re-checked, not assumed.

You stay in control: `/memory` shows what Anvyl thinks you know and where you left off, `/memory forget <idea>` removes an entry, and `anvyl memory export` prints it. `anvyl reset` wipes it.

## Edits

An offer shows the exact diff. Nothing is written until you approve. Anvyl writes only the files in that diff, only inside the project root, through the same path checks the coach tools use, after re-checking that the files have not changed since the diff was made. `/undo` restores the last applied edit. Every applied edit is counted as AI lines in authorship.

## Metrics

Per step Anvyl records who did it (you, AI, assisted), its size class, how long it took, and whether it passed its check. Three sources:

- **A, your own history:** your pace per size class when you worked alone (L0 or no-AI steps) and when AI did it. Trends over weeks.
- **B, estimates:** a typed estimate per ticket of how long it would take with no AI and with full AI, used until history exists and as a sanity check. Always labelled "estimate".
- **C, opt-in benchmarks:** `anvyl bench` (or a prompt you can turn on) asks you to do a small ticket alone and one with full AI, for real numbers.

Two headline numbers, kept separate: **learning pace** (ideas added to the ledger and explain-back strength over time) and **building pace** (finished work per hour). `/stats` and `anvyl stats` show both against the no-AI and full-AI references. The scorecard gets a short version.

## Tuning

A fixtures file of step pairs labelled close or far (starting with your examples). A script runs them through the real model and reports the too-early rate and the missed-repeat rate. The target is a too-early rate near zero. Later, "that was too early" feeds corrections into the same file.

## Build order

1. Tutor flow, the ledger and persistent memory (no edits yet).
2. Closeness check, the fixtures script and the diff-approved edit path.
3. Metrics and `/stats`, then benchmarks.

## Left to the builder

Exact prompts, the size-class scale, how step labels are normalised for the ledger, diff rendering in the TUI, and the checkpoint-state shape. Each should follow the constraints above and be tested with a fake client.

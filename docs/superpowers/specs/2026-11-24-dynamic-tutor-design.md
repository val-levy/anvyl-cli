# Dynamic tutor turns: design

Status: approved by the user ("A. lets do it"), small change to the tutor flow.

## Intent
The tutor decides each turn what to do next. No fixed goal, approach, first-step sequence and no
"Step N of 6" labels. A learner with a clear plan is not asked for a goal first. A lost learner
is taught straight away.

## Rules kept in code (never decided by the model)
- `gate_passed` is set only by code, after `attempt_floor` and `grader.check_attempt` pass on the
  learner's own words. A model saying "ready" cannot open the gate.
- The model picks a move from a fixed set: `ask`, `teach`, `hint`, `ready`. Anything else counts
  as `ask`. `ready` with no substantive learner message counts as `teach`. A failed `ready`
  check becomes `teach`.
- `TUTOR_MAX_TURNS = 8`: after that the flow moves on to the coach with the gate closed. The
  learner is never locked out. "I don't know" is always valid.
- Level caps, the code scrubber and the fence for untrusted text are unchanged.

## Approaches
A. One tutor loop (chosen): `tutor` decides the move, `tutor_wait` shows text and takes the reply,
   `tutor_check` runs the code gate on `ready`. Resume re-asks, as before.
B. Keep the fixed nodes and let the model route between them: rejected, still static underneath.

## Shape
- First turn is always `ask` with no decide call. Later turns call a small typed-JSON decide
  call, then the coach produces the text for the move (so the code scrubber still applies).
- State: `tutor_log` (learner messages, capped), `tutor_turns`, `tutor_force`. `approach` is set on
  a passed gate. Removed: `goal_detail`, `steps`, `teach_rounds`.
- Interrupt kind `tutor` replaces `tutor_goal`, `attempt`, `tutor_step`, `teach`.


Status: implemented (approach A: one `tutor` loop node, typed move, code-owned gate, `TUTOR_MAX_TURNS=8`).

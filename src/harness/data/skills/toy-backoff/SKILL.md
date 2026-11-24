# Skill: toy-backoff

How to coach the exponential-backoff retry helper (the toy task).

## What the human must learn

- A retry loop: try, remember the error, wait, try again.
- The delay grows (`base_delay * factor ** attempt`) so retries do not
  hammer a failing service.
- After the last attempt the error is re-raised, never swallowed.
- `sleep` is a parameter so tests can inject a fake and check the
  delays without waiting.

## How to coach it

- Ask questions first. Never write the function.
- Rung 0: ask what changes between attempts.
- Rung 1: name the three missing pieces (loop, remembered error, growing delay).
- Rung 2: describe the loop shape in words.
- Rung 3: outline in words only, still no code.

## Common mistakes to watch for

- Sleeping a fixed delay every time (no backoff).
- Returning None / swallowing the error after the last attempt.
- Calling `time.sleep` directly, which makes the timing untestable.
- Off-by-one: retrying `attempts + 1` times, or raising one try early.

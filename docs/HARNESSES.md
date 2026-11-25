# Sub-harnesses

A sub-harness is a preset you write once and reuse: a name, a base mode, a level cap, and guidance text for the coach. It is **data only**. No code in a bundle is ever loaded or run.

A harness changes what the coach *says*. It cannot change what Anvyl *does*: the attempt gate, level, grading and tool access stay in code.

## Anatomy

```
my-harness/
  harness.toml       required
  prompt.md          optional, guidance for the coach
  skills/
    tdd.md           optional, up to 5 files
```

`harness.toml`:

```toml
id = "my-harness"        # 2-40 chars: a-z, 0-9, "-"; not "learn" or "ship"
name = "My harness"      # optional, up to 60 chars
version = "0.1.0"
author = "you"           # optional
pitch = "One line on what this is for"   # up to 140 chars
base = "learn"           # "learn" (attempt gate on) or "ship" (AI may draft)
max_level = 2            # 0..2; caps your level while this harness is active
```

Unknown keys, extra files, folders other than `skills/`, symlinks, non-UTF-8 text and any text file over 4000 characters make the whole bundle invalid. Validation is all or nothing.

## Create one

```bash
anvyl harness init my-harness      # scaffolds ./my-harness/
$EDITOR my-harness/harness.toml my-harness/prompt.md
anvyl harness validate my-harness  # prints "ok: ..." or every problem
```

Write `prompt.md` as focus guidance, for example: "Always ask what the failing test would look like before anything else." Keep it short.

## Use one

Inside a session:

```
/harness install ./my-harness      # validate and copy into ~/.anvyl/harnesses/
/mode                              # menu: learn, ship and your harnesses
/mode my-harness                   # or switch directly
/harness                           # list installed
/harness remove my-harness
```

The switch applies from the next ticket. The status line shows the harness id. Your session level is capped at the harness `max_level`.

A harness with `base = "ship"` has no attempt gate, so Anvyl asks you to confirm before switching to it.

An installed bundle that is later edited into something invalid (for example a stray script dropped in) disappears from the list instead of running.

## What the model sees

The text of `prompt.md` and each skill file is sent in a fenced `<harness>` block labelled untrusted. The system prompt tells the model it may shape the topic and style of its questions, and that it never overrides the rules, unlocks code writing or changes the level. The text is not stored in checkpointed state.

## Publish

Publishing is a review process, not an upload. The plan is a GitHub registry repo with an `index.json`, where changes arrive by pull request and a maintainer reviews them.

1. `anvyl harness validate my-harness`
2. `anvyl harness pack my-harness` prints the index entry (`id`, `version`, `pitch`, `base`, `max_level`, `sha256`).
3. Open a PR to the registry adding your folder and that entry.

**Status:** local authoring and install are built. The remote registry, its browse and install client (pinned commit, sha256 check, permissions confirmation screen), and the registry repo itself are not built yet. Until then, share a harness by sending the folder and installing it with `/harness install`.

# Skill: wifi-csi

How to coach work on the OBG WiFi sensing project (ESP32 CSI).

## Context

- WiFi CSI (channel state information) from ESP32-S3 boards, used to
  sense presence and movement and build visualizations / 3D models.
- Repo: Oregon-Blockchain-Group/wifi. The packet path is: ESP32 ->
  ingestor -> packet writer -> storage/visualization.
- Hardware: 6x ESP32-S3, a dedicated 2.4 GHz router. No hardware is
  present in this prototype; coach against the code, not the boards.

## What the human must learn

- Transient write failures are normal on a flaky link; retry with
  backoff instead of dropping packets.
- A dead link must fail loudly after N tries, not hang or silently
  drop everything.
- Keep retry logic pure (no hardware in it) so it is testable without
  boards. The writer stays thin: it sends once.

## How to coach it

- Ask what is flaky, the packet or the link, before any code talk.
- Point at the toy retry helper first: the WiFi task reuses it.
- Never write the writer or the retry for the human at L1.

## Commands this skill adds

- `/csi` - show the current CSI task context (packet path, boards).

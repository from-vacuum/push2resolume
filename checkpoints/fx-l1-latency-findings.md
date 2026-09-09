# L1 FX Repair, 2026-09-09

Saved checkpoint: `Push2Resolume.59.toe`. All 22 isolated tests and mapping
validation pass. Live L1 slots 1-8 have nonzero activation levels; zero TD
cook errors. Two existing Syphon license warnings remain.

- L1 Wave Warp, WarpSpeed and Infinite Zoom had persisted `on_value=0.0`.
  Their normal toggles therefore sent zero for both on and off.
- Repair legacy zero activation levels on registry rebuild. Ignore captures
  at or below the off threshold so this cannot recur.
- RoundMask was pinned at slot 9 while slot 8 was unoccupied. Move that
  existing pin to slot 8, retaining its captured value and effect identity.
- Read-only WebSocket query: 16.51 ms to confirmation.
- Unchanged-value queued write: 26.07 ms to send, 13.17 ms from send to
  Resolume confirmation, 39.23 ms total. This is not a physical MIDI test.
- LCD TCP send/receive queues were empty at inspection.
- TD FPS samples varied from 60 to 3 after MCP/save activity, despite low
  measured cook time. The physical-input trace is needed to correlate stalls
  with pad presses; API timing alone does not establish physical latency.
- The reported physical 2-3 second delay has not yet been reproduced.
  `tools/trace_fx_latency.py` installs bounded main-thread input/send/ack
  timing hooks for the user's physical test; reload removes the hooks.

## Feedback Delay Resolution

The subsequent physical trace reproduced the cause: sending opacity 1
returned a `parameter_set` reply with value 0 (and vice versa) about 12 ms
later. Treating this pre-write response as authoritative undid optimistic
LED/LCD feedback until the next two-second REST poll. It also caused rapid
presses to repeat the previous command instead of toggling.

`Push2Resolume.60.toe` ignores set-reply values and queues bounded parameter
GET readbacks at least 50 ms after writes. Immediate feedback remains in
place. Older GET replies cannot undo a newer rapid toggle during its pending
window. Resync clears queued readbacks along with writes. All 25 isolated
tests pass, including LED/LCD snapshot regression tests in both directions.
Post-fix physical LED/LCD confirmation remains for the user; no effects were
toggled automatically on the active layer for this validation.

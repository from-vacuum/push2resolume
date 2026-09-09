# Native Speed Reset Verification

Saved: `Push2Resolume.62.toe`.

The original reset incorrectly assumed OSC speed mapped linearly to the
API's min/max range. For L1 clip 3, OSC 0.1 read back as 0.21829106680707905x,
not 1x. The previous no-output test checked that assumption, not Resolume.

Resolume's documented WebSocket `reset` action on parameter ID 1788924759917
changed the actual clip speed from 0.21829106680707905 to 1.0. A subsequent
test through the Shift+L1 button handler queued the same native reset. The
composition REST response independently confirmed `transport.controls.speed`
value 1.0 for the connected clip `sacred_dodeca_3`.

The reset now cancels stale OSC writes/cache entries for that parameter,
clears encoder optimism, and waits for API readback before changing displayed
speed. It sends no normalized speed value and is not suppressed by the OSC
deadband cache. Ordinary speed encoder OSC behavior is outside this reset fix.

Validation: 31 tests pass; mapping checks pass; zero TD cook errors. Existing
two Syphon license warnings remain. Post-save health is armed, with fresh
Resolume state, valid layer bindings and a connected display helper.

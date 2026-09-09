# Phase 3a — hardware truth check findings

## 2026-09-09: Seven-Layer Migration

The active composition now has seven layers and a separate Composition target.
Mid and FX + masks moved to indices6 and7; the old `1,2,3` mapping missed them.
Each target has eight Dashboard links. Excluding Transform as before, B has8
effects, Mid9, FX + masks8 and Composition12, requiring a second FX page.

Layer speed is absent from the API tree. A live WebSocket `parameter_get`
returned `/composition/layers/1/clips/1/transport/position/behaviour/speed`.
Shift-speed now resolves the connected clip in each target layer. Speed ranges
vary by clip (observed max10 and16), so accumulation uses normalized feedback
and the LCD displays the native multiplier.

TD reinitializes the orchestrator when its embedded DAT source changes.
Process-local helper ownership must survive this to avoid orphaning the LCD
helper or losing MIDI binding on checkpoint saves. The seven-layer revision
retains helper ownership and restores UI state separately from live transports.

The previous findings below are preserved as a historical record.

Source: live `GET /api/v1/composition` against the running composition
"BM_2026" (Resolume Arena, webserver on `127.0.0.1:8080`). No test effects
were added -- two real "Goo" instances already exist on Layer 1
(`effects[3]` and `effects[8]`, ids `1695158031414` / `1786686930368`),
which happens to be exactly the duplicate-name case Phase 3a asked for.

## 1. The opacity key inside the effect object -- **DESIGN.md assumption was wrong**

Opacity is **not** inside `mixer`. It lives at `params.Opacity` (capital O).
`mixer` on every effect inspected contains only `Blend Mode`:

```json
"mixer": { "Blend Mode": { "valuetype": "ParamChoice", ... } },
"params": {
  "Opacity": { "id": 1786690939962, "valuetype": "ParamRange",
               "min": 0.0, "max": 1.0, "value": 0.0, ... },
  ...
}
```

**Action taken:** `FxRegistry` resolution order is `params.Opacity` (exact
key) -> case-insensitive `opacity` anywhere in `params` -> the `mixer`
walk DESIGN.md originally specified, as a last-resort fallback for an
effect type not yet seen. Log which rule fired, per the original design
intent.

## 2. Opacity min/max -- **DESIGN.md assumption was wrong**

Expected `0-100`; actual range on every effect inspected is **`0.0-1.0`**,
the same normalization OSC uses. This is good news operationally (no
rescale needed) but confirms the design's own rule -- read `min`/`max` from
the discovered parameter, never hardcode -- was the right call regardless
of which assumption was correct.

## 3. `displayName` -- exists, but under a different key

Real key is **`display_name`** (snake_case), not `displayName` (camelCase)
as the schema example in DESIGN.md 4.1 assumed. Confirmed present on every
effect sampled, always equal to `name` unless the user renamed it in the UI
(untested here since renaming wasn't done, but the field exists and is
populated).

**Action taken:** `FxRegistry` reads `display_name`, falls back to `name`.

## 4. Duplicate-name behaviour

Both Goo instances report `"name": "Goo"` with **no auto-suffix** (not
`Goo2`/`Goo3` as speculated in DESIGN.md 4.1/9). Each has fully independent
`id`, `params.Opacity.id`, `bypassed.id`. This confirms the pin-key design
(`target|name|ordinal`, chain-order ordinal) is the *only* correct
disambiguation -- the name field alone genuinely cannot tell them apart, so
DESIGN.md's mitigation (R2/4.3) holds even though the specific "auto-suffix"
detail it guessed at doesn't happen at the `name` level.

## 5. Encoder delta encoding (Push 2, not Resolume)

Confirmed live with a real hardware sweep during earlier testing this
session: `0x01` = +1, `0x7F` = -1, matching the assumed convention exactly
(CC 79 / Master encoder, see chat log). No change needed.

## 6. WebSocket SET envelope -- confirmed live, and REST by-id does NOT exist

`GET`/`PUT`/`POST /api/v1/parameter/by-id/{id}` all return 404 on this
Resolume install -- by-id parameter control is **WebSocket-only**, which
actually reinforces (not contradicts) DESIGN.md's architecture.

The real envelope, confirmed by a live round-trip on the second Goo's
opacity (nudged 0.4181222707423581 -> 0.42 -> restored, verified via REST
readback both times):

```json
{"action": "set", "parameter": "/parameter/by-id/1786690940081", "value": 0.42}
```

Sending `"parameter": <int id>` instead of the path string is rejected with
`{"path":"<unknown>","error":"error reading field \"parameter\": value is
not std::string"}` -- the field must be the **string path**, not the bare
numeric id. `ResolumeOut.FlushWS` implements this envelope.

Confirmed live 2026-08-14 (Shift+pad hardware test on Layer 1's AutoMask):
`bypassed` (ParamBoolean) correctly accepts a native JSON `true`/`false` in
this envelope -- Python `True`/`False` serializes that way and Resolume
applied it (`bypassed_value` flipped False->True->False across two presses,
each confirmed via REST readback). No `0`/`1` fallback needed.

## 7. Global +1 MIDI index offset -- root cause: TD's own 1-indexed display, not the hardware

Confirmed live 2026-08-14 with controlled single-control tests: **every**
incoming MIDI index (Note On/Off AND Control Change) reads exactly one
higher than Ableton's documented numbers -- not just the pad grid as first
suspected, and not a defect in this specific Push 2 unit.

**Root cause**: TouchDesigner's MIDI In DAT (like many DAW/visual-programming
MIDI monitors, e.g. Max/MSP) displays and reports CC/note numbers on a
user-friendly **1-indexed** scale rather than the raw 0-indexed decimal value
actually on the wire -- raw 71 is reported as 72. Ableton's `Push2-map.json`
and `MidiMapping.png` use the raw 0-indexed convention, so every number read
via `event.index` is TD's display value, one higher than the spec. This also
means the same +1 applies to LED **output** addressing (confirmed separately
via the Session button: lit only when writing CC52, not the CSV-logical 51).
See memory `td-midi-1indexed-display` for the general form of this gotcha.

Verified independently:

| Control | Design says | Hardware sends |
|---|---|---|
| Bottom-left pad | note 36 | note 37 |
| Encoder-1 touch | note 0 | note 1 |
| Encoder-1 turn | CC 71 | CC 72 |
| Master turn | CC 79 | CC 80 |
| Shift | CC 49 | CC 50 |

Fixed with a single global `number = event.index - 1` in
`midi/midiin1_callbacks` (input) and `hw_number = number + 1` in
`mod_pushio._writeLed` (LED output), applied to both notes and CCs
uniformly. An earlier, narrower version of the input fix (grid-notes-only)
was based on an unverified early-session observation and has been
superseded -- do not re-introduce a scoped/conditional offset.

## 8. Diagram divergence: DESIGN.md's ASCII layout has left/right mirrored

Cross-checked against Ableton's real `MidiMapping.png` on 2026-08-14 while
debugging deck-switch confusion. `DESIGN.md` section 3.2's ASCII diagram
places Session/Shift/Select/Device/Mix/Browse/Clip/Setup/User/the deck
arrows/the B1-B8 deck-select column on the **left** side of the unit. On the
real hardware (and Ableton's own diagram) all of these are on the **right**
side. The B1-B8 column itself is also inverted: DESIGN.md shows CC36 at the
top (aligned with pad row S1) and CC43 at the bottom (aligned with S8);
the real hardware runs CC43 at the top down to CC36 at the bottom. Numbers
in `map_controls.csv` (CC36-43 for deck 1-8, etc.) are correct and match
Ableton's spec exactly -- only the ASCII diagram's physical placement is
wrong. A corrected reference lives in the published control-map artifact
(image-verified v2). `DESIGN.md` section 3.2 should be redrawn from the
real image before anyone navigates by it again.

## 9. Bug: trigger presses only fired once, ever -- dead-band wrongly applied to ints

Confirmed live 2026-08-14: `LOWER_1/2/3` (layer-select, CC20-22, action
`layer_focus`) worked on the first press per session and then silently did
nothing on every subsequent press. `Byp L1-3` (bypass toggle, same button
row) worked every time. Root cause: `ResolumeOut.FlushOSC` had a dead-band
guard that also skipped **unchanged int values**
(`if value_type != 'float' and cached == value: continue`), not just floats.
Bypass toggles alternate 0/1 each press so the guard never caught them, but
`layer_focus`/`clip_connect`/`column_connect`/`clip_select` all send a
*constant* `value=1` from the CSV every time (Resolume trigger semantics --
every press is a fresh bang, not a state change) -- so the second press
onward always matched the cached `1` and got silently dropped. Per
DESIGN.md 6, dead-band is specified for continuous float streams only
(encoders/touch strip); the int-skip branch was an unwarranted extension
added without basis. Fixed by removing that branch entirely -- non-float
values now always send. This was a live-functional bug, not just cosmetic:
it would have silently broken repeated clip triggering the same way.

## 10. Bug: bank 1 pointed at clips 17-32, not 1-16

Confirmed live 2026-08-14: `DESIGN.md` 3.3 states "bank 1 shows clips 1-16",
but the literal CSV slot formula `bank*16+n` gives 17 for bank=1, n=1 --
every clip/column/FX-slot pad was reading 16 slots ahead of the intended
bank. Root cause: `Surface.Bank` is 1-based (performer-facing, "bank 1"),
but the CSV formula is written 0-based-style. Fixed by binding `bank-1`
(not `Bank` itself) into every eval context that resolves a `slot`
expression -- `mod_surface.ResolveTemplate`, the fx-gesture slot lookup in
`Surface.OnReceiveMIDI`, and both slot lookups in `mod_ledpainter._resolve`
(fx_opacity_toggle/fx_bypass_toggle and clip_connect), plus the matching
`state.bank - 1` in both live-overlay HTML pages. No CSV rows were changed.

## 11. Bug: LedPainter.Paint() ignored grid mode entirely -- FX rows always won

Confirmed live 2026-08-14: connecting a clip (`PAD_S1_T1_CLIP`, LAYER3 slot 1)
correctly updated `ResolumeState.Clips` (see finding 12), yet `Paint()`
still returned the OFF palette index for that pad. Root cause: `Paint()`
iterates every row of `map_controls.csv` unconditionally and writes into
the same `(kind, number)` output dict keyed only by MIDI number -- but
every pad has both a SESSION-mode row and an FX-mode row sharing that same
number. Whichever row came later in file order always won, regardless of
`surface.GridMode`. In this case the FX-mode row for note 92 resolved to
"no effect in that FxRegistry slot" -> OFF, silently overwriting the
correct SESSION-mode ON result computed moments earlier in the same pass.
This affected every dual-mode pad, not just clip pads -- FX opacity/bypass
LEDs were equally at risk of being clobbered by a stale SESSION-mode
result depending on CSV row order. Fixed by skipping any row whose
`grid_mode` doesn't match `surface.GridMode` (ANY-mode rows always pass),
and additionally skipping modifier-specific row variants (SHIFT/SELECT)
that don't match the currently-held modifier, in `mod_ledpainter.Paint()`.

## 12. Bug: clip LEDs never tracked ongoing Resolume state after boot

Confirmed live 2026-08-14, same test as above: `ResolumeState.Clips` is
only ever populated from a full WS composition push (boot/rescan/deck
switch) -- `_applyParameterUpdate` (the handler for narrower
`parameter_update` messages, which is what Resolume actually sends for a
clip connect/disconnect) is still the Phase-4.6 no-op stub. So every clip
we triggered via the controller updated Resolume for real over OSC, but
our local model never learned about it, and stayed frozen at whatever the
snapshot showed at last boot. Fixed with an optimistic local update in
`Surface.OnReceiveMIDI`: right after a successful `clip_connect` send,
mark the new slot connected and clear `connected` on every other clip
previously marked connected in that same layer (Resolume clips are
single-connected-per-layer). This does not catch state changes made
directly in the Resolume UI (outside the controller) -- those still need a
Rescan or a genuine composition push to be reflected; closing that gap for
real requires implementing `_applyParameterUpdate` against the narrow
per-clip subscriptions DESIGN.md 4.6 describes, which remains unbuilt.

## 13. Bug: column pads had no LED resolver, and firing one didn't update the layer clips it connects

Confirmed live 2026-08-14: `LedPainter._resolve()` had no branch for
`column_connect` at all (only `clip_connect`, the two FX actions, and the
mode/modifier toggles) -- column pads never lit under any circumstance.
Separately, firing a column connects the same slot index in all three
layers simultaneously (column N == the clip at that T-position in every
layer band, DESIGN.md 3.3 -- confirmed by both actions sharing the
identical `bank*16+n` slot formula), but the optimistic clip-state update
from finding 12 only handled `clip_connect`, so the layer clips a column
fires never got marked connected either -- compounding into "nothing above
updates when I fire a column." Fixed both: `Surface.OnReceiveMIDI` now
applies the same optimistic connect/disconnect update across all three
`LayerIds()` for `column_connect`, and `mod_ledpainter._resolve()` gained a
column branch that lights `SCENE_FULL` when all three layers agree,
`SCENE_DIM` on partial match (e.g. mid-transition), `OFF` otherwise.

## 14. Periodic REST poll added -- outside Resolume-UI edits now reach Push

Added 2026-08-14: `_applyParameterUpdate` (narrow WS parameter_update
handling, DESIGN.md 4.6) is still unbuilt, so nothing previously told the
LED model about a clip connected/disconnected directly in Resolume's own
UI (only our own controller presses were caught, via the finding-12/13
optimistic updates). Added a periodic REST composition poll
(`cfg_general.state_poll_s`, default 2s) inside `ext.Tick()`, reusing the
exact same `ResolumeState.OnMessage` path the WS composition push and
Boot/Panic/Rescan already use -- no new parsing needed. This is
DESIGN.md 2.1's documented `rest_poll` fallback, just run continuously as
a WS supplement rather than only when WS is down. Note: the poll interval
is counted in `Tick()` calls, not wall-clock time -- if TD is backgrounded
and throttles its own tick rate, the real-world interval stretches
accordingly (observed ~2 ticks/s while unfocused during this session vs.
the nominal 30 Hz), which is an OS/TD scheduling behaviour, not a bug in
the counter.

## 15. Clip LEDs now distinguish three states, not two

Added 2026-08-14: `LedPainter`'s `clip_connect` branch previously
collapsed everything to lit/unlit. Now returns three distinct results
using the `state` string Resolume's REST/WS API already provides
(`Empty`/`Disconnected`/`Previewing`/`Connected`/`Connected & previewing`,
see finding 6-adjacent REST shape) alongside the `connected` boolean:
blank (`state == 'Empty'` or no clip dict at all) -- solid DIM (clip
loaded, not playing) -- blinking between DIM and FULL (`connected` is
True). `Paint()` and `FullRedraw()` were extended to carry a `(dim, full)`
tuple result through to `PushIO.SetLed`'s existing (previously unused)
`blink_with` parameter, which drives the real software-blink engine
(DESIGN.md 5.2) at `blink_hz`.

## 16. FX mode: all 8 main encoders now map 1:1 to the composition's 8 Dashboard links

`ENC_5_FX` through `ENC_8_FX` (hw CC76-79, csv75-78) and their SHIFT
variants previously targeted action `fx_opacity_relative` with a
pseudo-target `FOCUS`, sending `ws /parameter/by-id/{fx[focus:N].opacity_id}`.
Neither `fx_opacity_relative` nor a `FOCUS` target ever existed in
`mod_surface.py` -- confirmed by grepping the actual logic DATs, where the
string appears nowhere; it only ever existed in the CSV and in the two
local reference HTML pages. Every press on those four encoders in FX mode
was silently a no-op.

First pass replaced only ENC_5-8 with per-target dashboard links
(link3/link4), leaving ENC_1-4 untouched per their CSV note ("Identical in
EVERY grid mode -- the four most-used controls never move"). The user
corrected this: FX mode should map **all 8** main encoders (hw CC72-79,
csv71-78) directly 1:1 to the composition's 8 Dashboard links
(`/composition/dashboard/link1` .. `link8`), overriding the "never move"
invariant for FX mode specifically. Implemented as:

- `ENC_1`-`ENC_4` (csv71-74): grid_mode narrowed from `ANY` to `SESSION`
  for their existing layer/composition-opacity row (unchanged behavior in
  SESSION mode); added a new FX-mode row per encoder -> `dashboard/link1`
  through `link4` on `COMPOSITION`.
- `ENC_5_FX`-`ENC_8_FX` (csv75-78): action changed from the dead
  `fx_opacity_relative`/`FOCUS` stub to `param_relative`/`COMPOSITION` ->
  `dashboard/link5` through `link8`; their now-meaningless FX_SHIFT
  variants (previously also dead) were deleted rather than repointed,
  since all 8 links are consumed by the plain encoders.
- `ENC_MASTER` (csv79, hw80): left untouched (`/composition/master`, `ANY`)
  per explicit instruction -- no 9th link exists to give it.
- SHIFT on ENC_1-4 in FX mode still falls back to their `ANY`-mode speed
  rows (unchanged) since no FX-specific SHIFT override was added -- only
  the plain press was in scope.

All values target the single composition-level `dashboard` object (not the
per-layer dashboards SESSION mode uses for ENC_5-7), confirmed live via
REST to have exactly `Link 1`-`Link 8`. Verified via `Surface.Resolve()`
for hw71-79 in both FX and SESSION mode, then `Surface.OnReceiveMIDI()`,
zero `get_op_errors` after each edit.

Also re-confirmed: `mod_surface.py`'s `Surface.BuildIndex()` caches
`map_controls` rows into `self._index` at `__init__` time -- reloading the
table DAT's `loadonstartpulse` alone does not update already-resolved
mappings; `BuildIndex()` must be called again (or the extension reinit)
after any CSV edit that changes existing rows, on top of the reload.

## 17. FX-mode encoder links now follow the focused target, not a fixed COMPOSITION

Finding 16 pointed all 8 FX-mode encoders at the composition-level dashboard
regardless of what was focused. The user then asked for the links to
track whatever is currently focused (any of the 3 layers, or the
composition) instead of always addressing COMPOSITION. `Surface.FocusTarget`
already existed and was already being set by `layer_focus`/`comp_focus`
rows (`LOWER_1`-`LOWER_4`, csv20-23) -- the CSV notes on those rows even
said "Focus also picks which target the FX encoders address," but nothing
downstream ever read `FocusTarget` for the encoder paths; ENC_1-8_FX just
hardcoded `COMPOSITION`.

Added a `{FOCUS}` template token to `Surface.ResolveTemplate` (`mod_surface.py`):
computes a path segment from `self.FocusTarget` (`/layers/<Lid>` for
LAYER1-3, `''` for COMPOSITION) and injects it into the eval context so the
existing generic `{token}` substitution mechanism handles it for free --
no new special-casing needed. `ENC_1_FX`-`ENC_8_FX` control_path changed
from `/composition/dashboard/linkN` to `/composition{FOCUS}/dashboard/linkN`,
target column changed `COMPOSITION` -> `FOCUS` (documentation only; the
`target` field is otherwise unused by `param_relative`/`ResolveTemplate`).

Module-DAT edit gotcha reconfirmed: `edit_dat_content` on `mod_surface`
does NOT retroactively patch the already-instantiated `Surface` object --
had to call `ext_comp.par.reinitextensions.pulse()` afterward, per
[td-python.md](.claude/rules/td-python.md#extensions).

Verified end-to-end: forced `ext.Armed = True` temporarily (real gate --
`layer_focus`/`comp_focus` are OSC-transport rows, correctly blocked by the
refuse-to-arm gate while unarmed) to simulate `LOWER_2`/`LOWER_3`/`LOWER_4`
presses via `OnReceiveMIDI`, confirmed `FocusTarget` flips to
LAYER2/LAYER3/COMPOSITION, then confirmed `ResolveTemplate` on ENC_1's row
resolves to `/composition/layers/2/dashboard/link1`,
`/composition/dashboard/link1`, `/composition/layers/3/dashboard/link1`
respectively. Restored `ext.Armed` to its prior value after the test.

## 18. Bug (self-inflicted): `reinitextensions.pulse()` after a module-DAT edit dropped the entire live rig, not just `Surface`

To apply the `{FOCUS}` token edit to `mod_surface.py` (finding 17), I pulsed
`ext_comp.par.reinitextensions` on `/project1/PUSH_RESOLUME`. That parameter
reinitializes **every** extension on the COMP, not just `Surface` -- it
also tore down `PushIO`, `ResolumeOut`, `ResolumeState`, and `FxRegistry`
back to fresh `__init__` state without re-running `Boot()`, so the live
MIDI binding, OSC target, and WS connection were all dropped and
`ext.Armed` fell back to its unarmed default. Every hardware button
appeared dead because the refuse-to-arm gate (DESIGN.md 8) correctly
blocked all non-internal actions while unarmed -- the mapping logic itself
was never broken, the whole rig was just unbooted.

Recovered with `ext.Boot()` (restored `push_bound`/`push_mode`/`osc_target`
and `Armed`), then toggled `net/ws1`'s `active` par off/on to force the
WebSocket reconnect that `Boot()` alone didn't retrigger (`resolume_state`
stayed `False` until that toggle). Confirmed via `ext.Health` (all six
flags True) and `get_op_errors` before saving.

Takeaway for future module-DAT edits on this project: reinit only the
specific extension needed if possible, or immediately follow a full
`reinitextensions.pulse()` with `ext.Boot()` and a WS reconnect check --
never assume reinit alone restores a live connection.

## 19. UPPER_1-8 (hw CC103-110) LEDs now show live Dashboard link value in FX mode

Extended finding 17's `{FOCUS}`-tracking link mapping with an LED
indicator: the row of 8 buttons physically below ENC_1-8 (`UPPER_1`-`UPPER_8`,
csv102-109) now shows each corresponding Dashboard link's live value from
Resolume, banded OFF/MID/ON, instead of their normal SESSION-mode
backlight. Their button *action* (layer_clear, comp_disconnect_all,
layer_solo_toggle, tempo_resync) is unchanged in either mode -- only FX-mode
LED painting is new.

Confirmed live via REST that both the composition object and every layer
object carry their own `dashboard` key with the same `Link 1`-`Link 8`
shape (`{'value': float, 'view': {...}, ...}`) -- so "the focused target's
links" cleanly means "whichever of those 4 dashboard objects
`FocusTarget` currently points at."

Implementation:
- `mod_resolume_state.py`: `_normaliseFromComposition` now also extracts
  `self.DashboardLinks[(target, link_index)] = value` for COMPOSITION and
  each of LAYER1-3 from the same REST/WS composition payload that already
  feeds `Clips`/`Layers` -- no new polling, reuses the existing
  `state_poll_s` REST cadence (finding 14) and the WS composition push.
  Added `DashboardLinkValue(target, link_index)` accessor.
- `mod_ledpainter.py`: `_resolve` gains a first-checked branch keyed off
  the UPPER-row actions (`_UPPER_ROW_ACTIONS`) plus `GridMode == 'FX'`:
  derives `link_index = in_number - 101` (UPPER_1/csv102 -> link1 ...
  UPPER_8/csv109 -> link8), reads `ResolumeState.DashboardLinkValue(surface.FocusTarget, link_index)`,
  bands it at <=0.02 -> off, >=0.98 -> on, else mid.
- `map_controls.csv`: `led_palette` for those 8 rows changed from their
  old single/pair names (`L1_MID`, `OFF|SOLO`, `OK`, ...) to
  `FX_OFF|FX_MID|FX_ON` -- reusing the existing green FX-opacity palette
  family (indices 35-37) rather than adding new palette rows, since it
  already reads as "FX-related, 3 brightness bands." Their SESSION-mode
  look is unaffected: `_resolve` never handled `layer_clear` /
  `comp_disconnect_all` / `layer_solo_toggle` / `tempo_resync` before this
  change either, so those rows always fell through to the WHITE_DIM
  backlight default outside FX mode, and still do.

Verified end-to-end with a real round-trip, not a simulated value: sent
`/composition/dashboard/link1` = 0.5 then 1.0 via `oscout1`, forced a REST
poll (`web1.request(...)`), confirmed `DashboardLinkValue('COMPOSITION', 1)`
picked up each value, confirmed `Paint()` returned palette index 36 (MID)
then 37 (ON) for `('cc', 102)` -- but only once `FocusTarget` was set to
`'COMPOSITION'`; with the default `FocusTarget == 'LAYER1'` the same
COMPOSITION-level change correctly stayed invisible (index 35/OFF), proving
the per-target lookup isn't just always reading COMPOSITION. Reset the
link to 0.0 and `FocusTarget` back to `'LAYER1'` afterward to leave the
live show clean.

Same module-DAT-edit gotcha as finding 18, this time anticipated: after
`reinitextensions.pulse()` + `BuildIndex()`, immediately called `ext.Boot()`
and cycled `net/ws1`'s `active` par, restoring `Health` to all-green and
`Armed = True` before doing any further verification -- avoided repeating
the "all buttons dead" regression.

## 20. Bug: FX-link LEDs (finding 19) lagged up to `state_poll_s` behind the physical knob

The LEDs worked but felt sluggish: `DashboardLinks` only refreshed on the
periodic REST poll (`state_poll_s`, default 2.0s) or a WS composition push
-- the same staleness class already fixed for clip/column LEDs in findings
8/9, just not yet applied to links. Turning ENC_1-8_FX could take up to
~2s to show on the UPPER_1-8 LED.

Fixed the same way as `clip_connect`/`column_connect`: `OnReceiveMIDI`
now optimistically writes straight into `ResolumeState.DashboardLinks` the
instant it sends a `param_relative` encoder value, instead of waiting for
the next poll to reconcile it. Added `_LINK_RE = re.compile(r'dashboard/link(\d+)$')`
to `mod_surface.py` and, right after `ext.ResolumeOut.Send(...)`:
resolves the link's real target (`self.FocusTarget` when `row['target'] == 'FOCUS'`,
otherwise the row's own static target -- covers the FX-mode encoders from
finding 19 AND the pre-existing SESSION-mode `ENC_5-8_SESSION` link1/link2
rows, same root cause) and the link number parsed straight from the row's
own `control_path`, then sets `DashboardLinks[(target, link_index)] = log_value`.
The periodic poll still runs and will correct the value if Resolume's own
UI or clamping disagrees with what we assumed.

Verified by driving `Surface.OnReceiveMIDI` directly (40 synthetic
encoder-right clicks, no MIDI hardware, no REST poll in between) and
confirming `DashboardLinkValue('LAYER1', 1)` hit `1.0` and
`LedPainter.Paint()` returned index 37 (FX_ON) on `('cc', 102)`
immediately, in the same call -- not after a subsequent poll. Then drove
40 clicks back down and popped the encoder's cached value to leave the
live rig at its pre-test state.

Same reinit-then-reboot discipline as findings 18/19 followed throughout:
`reinitextensions.pulse()` -> `BuildIndex()` -> `Boot()` -> cycle
`net/ws1.par.active` -> confirm `Health` all-green and `Armed` before any
further testing, and re-confirmed both immediately after `save_project`
too.

## 21. Bug: FX pads (`fx_opacity_toggle`) sometimes needed several presses to turn off, worse with multiple pads

Reported symptom: a pad always goes 0->1 (off->on) reliably on the first
touch, but 1->0 (on->off) sometimes takes several presses -- and the more
pads involved, the worse it got.

Root cause: `FxRegistry.TogglePad` tracks each pad's on/off state in a
`_padOn` key on its own `Registry` entry. `FxRegistry.Rebuild()` --
triggered by the periodic REST poll (`state_poll_s`, ~2s, finding 14) or
any WS composition push -- replaces `self.Registry` with a **brand new**
dict built from scratch each time, and the dict literal constructing each
entry never included `_padOn`. So every rebuild silently forgot which pads
were on, resetting the flag to `False` regardless of the pad's real state
in Resolume. If a rebuild landed between "turn pad on" and "turn pad off,"
the off-press read the just-reset `_padOn=False`, treated the pad as
already off, and re-sent "on" as a no-op (`SendWSById` has no dead-band --
DESIGN.md 6 -- so the message still goes out, but the value doesn't
change, so nothing visibly happens); only the press after that actually
flipped it. More pads in play means more real time elapses between
touching one and coming back to turn it off, raising the odds a ~2s
rebuild cycle lands in the gap -- matching "worse when a couple of pads
are involved, fine for a single pad" exactly.

Fixed in `mod_fxregistry.py`: `Rebuild()` now reads the OLD `self.Registry`
entry for the same `target:slot` key (still available -- `self.Registry`
isn't reassigned to `new_registry` until after the loop) and carries its
`_padOn` forward into the new entry, defaulting to `False` only when there
was no previous entry at all (freshly-discovered effect).

Verified by directly reproducing the race without waiting ~2s: toggled a
real pad on (`FxRegistry.TogglePad`), called `Rebuild()` with the live
composition mid-gesture (simulating the periodic poll landing at the worst
moment), confirmed `_padOn` was still `True` after that rebuild (previously
would have reset to `False`/missing), then toggled again and confirmed it
correctly went to `False` -- one clean on/off cycle, net opacity unchanged
from before the test.

Same reinit-then-reboot discipline as findings 18-20: `reinitextensions.pulse()`
-> `Surface.BuildIndex()` -> `Boot()` -> cycle `net/ws1.par.active` ->
confirm `Health` all-green and `Armed` before testing, and re-confirmed
again immediately after `save_project`.

## Not yet confirmed

- Whether a UI rename changes `display_name` without moving the effect's
  pad (should hold by construction, since pinning never reads
  `display_name`, but not exercised against a live rename in this pass).
- Windows User Port device name matching (no Windows machine available in
  this environment).

# Seven Layers + Composition: Layout and Mapping Plan

Status: implemented. Audited 2026-09-09 using the live Envoy MCP
(`query_network`, `execute_python`, `get_op_errors`) and Resolume's read-only
`GET http://127.0.0.1:8080/api/v1/composition`.

Implementation notes:

- Shift-speed follows the active clip through the verified address
  `/composition/layers/N/clips/M/transport/position/behaviour/speed`; the API
  has no layer speed parameter. Composition speed remains `/composition/speed`.
- LCD text mode uses a native OpenCV raster, with eight effect names/states
  per column on each FX page. Existing preview/USB framing is preserved.
  The same renderer is available through `/lcd.png` for the browser overlay.
- v2 is the maintained overlay; v1 redirects to it. Both use the live mapping.
- Fine control, press/release gating, queued/guarded FX dispatch, REST-based
  opacity capture and WebSocket parameter-get/set feedback are implemented.
  Fade ramps and momentary gestures remain out of scope.
- A process-local helper registry preserves MIDI/display ownership during DAT
  reload. Saved OP storage contains UI state and layer identities only.
- Device reads authoritative Resolume state, discards queued writes and
  optimistic feedback, and invalidates LED/blink/LCD caches. View, focus,
  pages, identity bindings and captured FX on-values survive. Older REST
  responses are ignored; failed reads report an error and allow retry.
- The findings and baseline below describe the pre-migration implementation.

Completed checkpoint saves: baseline `Push2Resolume.53.toe`, controls/LCD
`Push2Resolume.54.toe`, overlay/API `Push2Resolume.55.toe`, verified Device
resync and null-transport/reload fixes `Push2Resolume.58.toe`.
Baseline source/config and original overlays are in
`checkpoints/layout7-00-baseline`. Validation covers all 896 layer/clip positions,
128 FX slots, 20 isolated tests, live Envoy error checks, WebSocket replies,
native LCD pixels and Playwright desktop/mobile screenshots and inspector use.
Live Device-handler validation restored 37 effects, repainted 137 LED states,
drained the LED queue and preserved Session/L5 focus and all pages. The USB
display helper remained connected with the same PID. TD reported zero cook
errors, two existing Non-Commercial Syphon warnings, and 62 FPS on the final
performance sample. Physical button feel and LCD readability still need user
confirmation; reopening the saved project was not tested during the live rig.

## Verified Baseline

- Active TD project: `Push2Resolume.52.toe`; controller: `/project1/PUSH_RESOLUME`.
- Resolume composition: `BM_2026`. After the extra layer was removed, both TD
  and REST report seven actual layers, plus the separate Composition target.
- Current `cfg_general`, `map_controls`, and `map_palette` DAT contents match
  their disk CSVs. There are 424 control rows.
- `layer_ids` is still `1,2,3`. The controller therefore addresses the newly
  inserted layers at indices 2 and 3; Mid and FX + masks are no longer reached
  by the old L2/L3 controls.
- Current registry: B = 8 effects, old L2/L3 = 0, Composition = 12.
- Code DATs are embedded in the `.toe`, with empty file bindings. The tracking
  table contains no TDN externalization of this controller. Editing CSVs alone
  cannot update its implementation.
- CSV DATs have `loadonstart=True`, `syncfile=False`. An implementation must
  explicitly reload them and rebuild cached config/mapping state in TD.
- The latest active deck snapshot has 24 columns and all clip slots empty;
  an earlier snapshot had 68 columns. There are 15 decks. Bank bounds must
  handle deck changes and must not be inferred from the last snapshot alone.

| Surface target | Resolume index | Current name | Stable layer ID | FX excluding Transform |
|---|---:|---|---|---:|
| L1 | 1 | B | 1694579394136 | 8 |
| L2 | 2 | Layer # | 1788924228319 | 0 |
| L3 | 3 | Layer # | 1788924232740 | 0 |
| L4 | 4 | Layer # | 1788924237161 | 0 |
| L5 | 5 | Layer # | 1788924241582 | 0 |
| L6 | 6 | Mid | 1694579394230 | 9 |
| L7 | 7 | FX + masks | 1694579394324 | 8 |
| COMP | separate composition | BM_2026 | n/a | 12 |

All eight targets expose eight Dashboard links. FX counts above apply the
current registry rule that skips every effect named Transform; changing that
rule is separate from this layout migration.

## Proposed Surface

The display strip has one target per position: `L1 L2 L3 L4 L5 L6 L7 COMP`.
Session pads retain Resolume's vertical stack order; FX retains vertical chains.
The change reduces clips visible per layer from 16 to 8 while exposing all seven
layers at once. Each FX target retains 16 logical slots across two pages.

```text
                 T1    T2    T3    T4    T5    T6    T7    T8
Strip targets:   L1    L2    L3    L4    L5    L6    L7    COMP

SESSION grid, top to bottom              FX grid
S1: L7   clips 1..8                      Columns: L1..L7, COMP
S2: L6   clips 1..8                      Rows:    slots 1..8 on page 1
S3: L5   clips 1..8                               slots 9..16 on page 2
S4: L4   clips 1..8
S5: L3   clips 1..8
S6: L2   clips 1..8
S7: L1   clips 1..8
S8: ALL  columns 1..8
```

For physical row `r` and column `c`, both 1-based from the top-left:
`note = 36 + (8-r)*8 + (c-1)`.
Session clip/column index is `(clip_bank-1)*8+c`; layer target is `L(8-r)` for
rows 1..7. FX target is strip target `c`; slot is `(fx_page-1)*8+r`.
Resolve these coordinates once for commands, feedback, labels, and capture.

| Control | Proposed behavior |
|---|---|
| Encoders 1..8, Session | Opacity for L1..L7 and Composition |
| Shift + encoders, Session | Active clip speed per layer; Composition speed on encoder8 |
| Mix (CC112), Session | Toggle encoder page between Opacity and Macro |
| Encoders on Macro page | Dashboard link1 per target; Shift selects link2 |
| Encoders 1..8, FX | Preserve current behavior: Dashboard links1..8 of focused target |
| Select + encoder | Fine adjustment of the active parameter, including FX and Macro pages |
| Shift + encoder, FX | Same Dashboard parameter; no inherited Session speed mapping |
| Lower buttons CC20..27 | Focus/select L1..L7 and Composition |
| Upper buttons CC102..109 | Clear L1..L7; final button disconnects all |
| Shift + upper buttons | Solo L1..L7; final button tempo resync |
| Mute CC60 | Composition blackout; hold a lower target button + Mute to bypass that target |
| Session CC51 | Preserve current Session/FX toggle |
| Left/right CC44/45 | Previous/next clip bank in Session; previous/next FX page in FX |
| Right column CC36..43 | Session: select bank within the current group of eight; FX: first two select FX pages, remainder inactive |
| Shift + right column | Preserve direct deck selection 1..8 in both modes |
| Up/down CC46/47 | Preserve previous/next deck, including decks9..15 |
| Page buttons CC62/63 | Preserve Resolume UI horizontal scrolling |
| Tempo, Swing, Master, touch strip | Preserve existing roles; Swing follows the last selected layer when Composition is focused |
| Stop, Shift+Stop, User, Layout, Select+Layout, Scale | Preserve panic, rescan, MIDI ownership, display mode/source/fit |

Retain access to the existing 128 clip positions: 16 banks of 8, not 8 banks of
8. Left/right traverses all banks; right-column shortcuts follow bank groups
1..8 and 9..16. The bank count may grow if a deck exposes more than 128 columns.
Show bank number and clip range, and distinguish clip banks from FX pages.
Nonexistent slots must be dark and inert. Preserve independent clip-bank and
FX-page state across mode changes. Shift deck selection takes precedence over
right-column page shortcuts. Select takes fine-adjustment precedence when both
modifiers are held, consistent with the current modifier priority.

The second FX page is required now: Mid has 9 effects and Composition has 12.
Keep `fx_slots_per_target=16`; add a separate visible-slot count of 8. Never
reduce the registry capacity to 8 just to satisfy the physical grid size.

## Change Inventory

TD paths below are relative to `/project1/PUSH_RESOLUME`. Line numbers refer to
the inspected live DAT source, not files currently externalized in the project.

| Location | Required change |
|---|---|
| `config/cfg_general.csv:8` and matching DAT | Seven indices; clips_per_bank=8; bank_count=16 baseline; separate FX page size and registry capacity; document index vs stable ID |
| `config/map_controls.csv:2` | Replace 96 clip rows with 112 rows (56 pads, plain/select); replace 16 column pads with 8; rewrite all 192 FX rows using page-relative slots |
| `config/map_controls.csv:306` | Mode-aware right-column and arrow navigation, expanded bank groups, active-page LEDs |
| `config/map_controls.csv:322` | Replace upper/lower paired four-target layout with eight-target controls and modifier variants |
| `config/map_controls.csv:338` | Rewrite eight encoder mappings, explicit encoder-page resolution, fine mode, focus behavior; preserve focused FX Dashboard links |
| `config/map_controls.csv:388` | Keep actual Session toggle; assign currently reserved Mix; replace stale notes about Device, CC numbers and old lower-row controls |
| `config/map_palette.csv` and matching DAT | Add L4..L7 color families; distinguish target, focus, bypass, selected bank, FX page; preserve RGB vs white-only hardware rules |
| `logic/mod_surface:11,89,92,96,147,196,321` | Remove three-target dictionaries/unpacking; centralized target and coordinate resolution; configurable banking; FX page; encoder page; held-target routing; generic optimistic clip updates |
| `logic/mod_resolume_state:41,47,103` | Normalize all seven configured layers by actual configured index; validate every index and uniqueness; replace stale layer/clip dictionaries on new snapshots; extract all eight targets' Dashboard values/names |
| `logic/mod_fxregistry:12,81,105,192` | Discover/count all eight targets; preserve 16 logical slots and existing on-values; register Mid/FX + masks at L6/L7; define pin migration by verified layer/effect identity |
| `logic/mod_ledpainter:12,72,99,104,124,142` | Replace three-layer maps; resolve page-relative FX slots; paint all targets; bank/page indicators; use the same effective modifier/action resolution as input |
| `display/mod_display:26,88,106,242` | Dynamic target labels, real layer names, bank/page/range status, encoder values keyed to resolved parameter; preserve existing eight 120px tiles and 960x160 output |
| `net/webserver1_callbacks:9` | Extend `/state` with ordered target metadata, focus, encoder page, clip bank/range, FX page, resolved pad/button/encoder descriptors and availability |
| `push2_live_overlay.html:78,119,217` | Replace embedded old mapping/palette DATA, three-layer lookup, slot evaluation, labels and stale encoder state keys |
| `push2_live_overlay_v2.html:221,228,229,275` | Same changes, including static upper/lower labels and separate FX page; consume shared descriptors instead of rebuilding mapping rules in JS |
| `ui/health`, `ui/mirror_state` | Expose target validation and paging state. `mirror_state` is currently only a header; do not assume a working replicated visual mirror exists |
| `logic/ext_PushResolume:26,88,98,137` | Coordinate config reload, rebind/rebuild, page clamping and redraw; retain state where identities match; validate seven layers before arming |
| `logic/mod_resolume_out:36,81,102` | Unify guarded FX/OSC dispatch for dry-run verification; invalidate pending commands for removed/rebound targets and obsolete parameter IDs |
| `midi/midiin1_callbacks:24` and `Surface.OnReceiveMIDI` | Preserve the global index-minus-one conversion; distinguish button press/release from trigger dispatch while retaining held-focus tracking |
| `verify.py:112,155` | Replace four-target/grid-capacity invariants with per-page eight-target coverage; verify all slots over both pages and all seven targets over all clip banks; validate resolved OSC paths |
| `config/fx_pins.csv`, `config/fx_pins.example.csv` | Runtime migrates/preserves existing pins and captures; update example coverage to L4..L7 and page2. Do not manually rewrite the live pin file |
| `DESIGN.md` sections2.4,3,4.2,4.6,7.2,8,9,10 | Update layout, formulas, target counts, validation, acceptance cases and actual implemented controls |
| `README.md`, `PHASE3A_FINDINGS.md` | Link the revised mapping; add new findings while preserving the historical hardware record |

The raw MIDI sender, SysEx setup, USB display helper, preview TOP processing,
transport ports and hardware dimensions have no layer-count dependency.
`config/map_fx_rig.csv` is an obsolete-file marker, not an active mapping source.
`externalizations.tsv` must remain managed by Embody; never edit it manually.

## Migration Blockers and Existing Gaps

1. **Seven IDs currently crash path resolution.** Offline execution of the
   exported `ResolveTemplate` with seven IDs raised
   `ValueError: too many values to unpack (expected 3)` at line104.
2. **Configured index mappings and feedback disagree.** State normalization
   reads `layers[i]`, whereas FX discovery uses `layers[int(lid)-1]`.
   Reproduced with `[1,6,7]`: the L2 Dashboard name reads `None` rather than
   Mid's actual `Mirror`. An invalid configured index99 also passes
   `LayerIdsOK()`, which checks only list length.
3. **Encoder values are cached by mapping-row ID.** Changing FX focus reuses
   the previous target's accumulator; first turns also start from zero rather
   than the API value. Key by resolved target/parameter and initialize from
   current normalized feedback. Update the display to read that same state.
4. **Fine mappings are not implemented as advertised.** Explicit
   `param_relative_fine` rows bypass the `param_relative` handler; some resolve
   to literal `context` text. Remove those shadow mappings or resolve them to
   the active encoder action before applying the fine multiplier.
5. **FX gestures bypass armed/dry-run checks and queue caps.** They execute
   before the arm gate, then call `SendWSById` directly. Fix this before using
   dry-run as the migration's no-output validation method.
6. **FX capture/live feedback is incomplete.** `CurrentOpacity()` returns
   None and `_applyParameterUpdate()` is a stub. Either populate capture and
   pad state from REST feedback during this change, or label capture as
   unavailable. Do not claim that existing capture/ramp/momentary behavior is
   working just because CSV rows describe it. Ramps and momentary gestures
   are separate work unless explicitly included.
7. **Press/release semantics need verification for remapped controls.** Focus
   uses release tracking, but ordinary OSC triggers are not generally gated
   to presses and `0|1` toggles fall back to raw MIDI values. Test clear, solo,
   mute and focus once per physical press; preserve modifier releases.
8. **Layer identity and pins need an explicit policy.** Existing pins use
   target/name/ordinal, not stable layer IDs. Preserve B and Composition pins;
   remap historical Mid/FX pins only when identity is verified. Do not infer
   identity from four identical `Layer #` names. Track stable IDs during the
   session so structural edits cannot silently bind controls to a new layer;
   revalidate/rebind deliberately when the composition changes.

## Implementation Order and Acceptance

1. Capture a restorable controller/project snapshot and live config/pins;
   export the affected embedded DAT sources through Envoy for reviewable
   edits. Keep the active controller unchanged while preparing replacements.
2. Implement shared target lookup, index validation and pad/page resolution;
   fix encoder context and guarded dispatch. Run isolated checks against
   saved seven-layer REST data and a populated synthetic clip fixture.
3. Generate/update mapping CSVs and palette from the new layout. Preserve
   existing physical note/CC numbers. Add exhaustive mapping checks across
   clip banks, FX pages, modifiers, focus targets and encoder pages.
4. Update LEDs, screen status, `/state`, both browser overlays and docs to use
   the same resolved mapping. Test long layer names and both display modes.
5. Apply the reviewed sources and CSV reloads together through Envoy; rebuild
   Surface config/index and registry, reconcile state, repaint, then save
   only after validation. Do not reinitialize USB/MIDI helper ownership just
   to refresh mappings. Check TD errors after changes.
6. Validate with output capture first, then live clip/FX controls using a
   suitable populated deck. Check all seven layers and Composition, banking
   through positions65..128, FX page2, fine adjustment after focus switches,
   held-target mute, clear/solo releases, deck changes and deleted layers.
7. Verify no-output dry-run, queue bounds, restart persistence, pin retention,
   palette and display state, then confirm the saved project reloads with
   seven-layer mappings intact.

Baseline checks: `verify.py` currently fails one check because its OSC regex
rejects valid `/composition{FOCUS}/dashboard/linkN` templates before resolution.
TD reports zero cook errors and two existing Syphon resolution warnings from
the Non-Commercial license. Runtime health showed `resolume_state=False` while
`armed=True` and REST-derived composition data was available; distinguish REST
availability from WebSocket status during validation rather than assuming the
WebSocket path is healthy.

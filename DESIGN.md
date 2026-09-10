# Push 2 → TouchDesigner → Resolume Arena 7.15

> Current revision, 2026-09-09: the implemented surface is **seven layers plus
> Composition**, with 442 control mappings. README.md's "Current Surface" and
> LAYOUT_7_PLUS_COMP_PLAN.md describe the active implementation. The original
> three-layer specification below is retained as a historical design record;
> its layout, assumptions and build order do not describe current assignments.

Current contract: Session = 7 layers x 8 clips + 8 column launches; FX = 8
targets x 8 slots per page, 2 pages, 16 logical slots per target. Seven indices
are validated against saved layer identities, which are adopted from running
Resolume when they no longer match (cfg `layer_binding_mode`; `strict` restores
the old blocking alarm). Shift+Device, or `Rebind()`, rebinds explicitly.
LCD, LEDs and overlay share resolved descriptors.
Session encoders cover opacity, a Mix macro page and Shift active-clip speed.
FX encoders cover the focused target's Dashboard. Text LCD is a native 960x160
raster with eight aligned columns. Source/config updates require Envoy; the
saved `.toe` embeds the implementation. Tests are in `tests/test_layout7.py`.

**Design specification and implementation handoff**

| Item | Value |
|---|---|
| TouchDesigner | 2025.32820 (2025.30000 official branch) |
| Resolume | Arena 7.15 |
| Controller | Ableton Push 2, **User Port**, User Mode via SysEx |
| Platforms | macOS (Apple Silicon + Intel) and Windows 10/11, one `.toe` for both |
| Push ↔ TD | USB MIDI, User Port |
| TD → Resolume | OSC/UDP :7000 for everything addressable by index |
| TD ↔ Resolume | WebSocket :8080 for all effects (by parameter id) and all state feedback |
| Layers | 3 (configurable indices) |
| Effects | Discovered at runtime. Nothing about an effect is declared anywhere. |
| Status | Design only. No implementation in this document. Rev 2. |

---

## 1. Read this first: three corrections to the starting assumptions

**1. `jzgdev/Push2UserModeScript` cannot be used in this project.** It is an Ableton Live *MIDI Remote Script*. It only runs inside Live, it depends on Live's `_Framework` classes, and it puts Live's own control-surface layer between Push and the outside world. This project has no Live in it. Keep the repo only as a cross-reference for control numbers — and even for that, prefer the authoritative source below, because the jzgdev map contains Live-specific and partly wrong assignments (for example it comments the right-hand column as "Scene Launch" and remaps Stop to Mute to work around Live's play/stop logic).

Authoritative sources, use these instead:

- `https://github.com/Ableton/push-interface/blob/main/doc/AbletonPush2MIDIDisplayInterface.asc` — the MIDI/Display Interface Manual (rev 1.1, firmware 1.0.60).
- `https://github.com/Ableton/push-interface/blob/main/doc/Push2-map.json` — machine-readable note/CC numbers, names, and an RGB-vs-white flag per button. Every control number in `config/map_controls.csv` was validated against this file.

**2. The display is a bigger problem on Windows than on macOS.** The 960×160 screen is not MIDI. It is a vendor-specific USB bulk endpoint that needs libusb-class access.

- macOS: libusb can claim the interface without a kernel driver change. Needs an arm64 build for Apple Silicon. Awkward but workable.
- Windows: needs a WinUSB driver bound to the interface, normally via Zadig. That **replaces the driver** and can break Ableton Live's own use of the display until reverted. This is the real blocker for a cross-platform project.

Therefore: **the display is out of scope for v1, and the surface layout below is designed to be fully usable with the screen dark.** Every control is identified by its silkscreen label plus an LED colour. Section 9 (Phase 6) defines a stable seam so display graphics can be added later as an external helper process without touching surface logic.

**3. Effects are never named, indexed or declared by this project.** OSC addresses effects by name (`/composition/layers/1/video/effects/goo/bypassed`), and that name is a moving target: it is derived from an internal plugin key rather than the UI label (`Solid Color` → `solidcoloreffect`), duplicates get auto-suffixed (`goo`, `goo2`, `goo3`), and whether a UI rename changes the address is undocumented.

So the FX path does not use OSC at all. **Effects are discovered at runtime from the Resolume webserver API and driven by numeric parameter id over the WebSocket.** Section 4 is the full design. Nothing about an effect — its name, its chain position, how many copies of it exist — can break the surface, because none of those things is ever written down. See section 4 for why this is not just more robust but strictly more capable.

---

## 1a. Revision note

An earlier draft of this design had a hand-maintained `map_fx_rig.csv` declaring an effect name per pad slot, and forbade duplicate effects. Both were wrong:

- Duplicates *are* uniquely addressable — Resolume auto-suffixes them, and more importantly each instance carries its own parameter ids.
- A file a human has to edit and reload is the wrong contract for a live rig. Change the composition mid-set and the controller should follow, not break.

`map_fx_rig.csv` is deleted. In its place, `fx_pins.csv` is written **by TouchDesigner** to remember which pad an effect landed on across restarts. No human edits it; deleting it just resets the layout.

---

## 2. Architecture

```
   ┌────────────┐   USB MIDI (User Port)    ┌──────────────────────────┐
   │  Push 2    │◄─────── LED / SysEx ──────│                          │
   │            │──────── notes / CC ──────►│      TouchDesigner       │
   └────────────┘                           │      2025.32820          │
                                            │                          │
                                            │  ┌────────────────────┐  │
                                            │  │ PushIO             │  │
                                            │  │ Surface            │  │
                                            │  │ ResolumeOut        │  │
                                            │  │ ResolumeState      │  │
                                            │  │ FxRegistry         │  │
                                            │  │ LedPainter         │  │
                                            │  └────────────────────┘  │
                                            └───────┬──────────▲───────┘
      OSC / UDP :7000   indices only, control ──────┤          │
      WebSocket :8080   FX by parameter id  ────────┤          │
                        + all state feedback ───────┼──────────┤
                                            ┌───────▼──────────┴───────┐
                                            │   Resolume Arena 7.15    │
                                            │   OSC in :7000           │
                                            │   Webserver :8080        │
                                            └──────────────────────────┘
```

### 2.1 Why two transports

| | OSC :7000 | WebSocket :8080 |
|---|---|---|
| Carries | clips, columns, decks, layer opacity/speed/bypass/solo/clear, master, crossfader, tempo, dashboard links | **all effects** — opacity, bypass, any effect parameter |
| Addressed by | index (`/layers/2/clips/7/connect`) | numeric parameter id (`/parameter/by-id/1824357891293`) |
| Why here | Addresses contain nothing but integers. Stable, documented, fire-and-forget UDP, lowest latency. | Effect OSC addresses contain a name. Names are unstable. Parameter ids are not. |

The rule is one line: **anything addressable by index goes over OSC; anything addressable only by name goes over the WebSocket by id.** That is the whole reason for the split, and it is why the FX path cannot suffer name drift.

State also comes back over the WebSocket, in the same connection:

- Resolume's OSC *output* is a poor state path. "Output All OSC Messages" echoes everything including mouse moves and playhead position, on both absolute and relative addresses; it has been reported to stall or crash Arena at scale; and it reports clip state as `connected` 0–4 rather than 0/1. A controller that both sends and listens on the same addresses fights itself.
- The Webserver API gives the whole composition tree with names, clip presence per slot, every parameter with a numeric id, and **per-parameter subscribe**. On connect it pushes three messages: composition state, `sources_update`, `effects_update`. That is exactly what the LED painter needs.

Fallback ladder, driven by `cfg_general.csv`:

| `state_source` | `fx_transport` | Behaviour |
|---|---|---|
| `websocket` | `ws_param_id` | Default. REST bootstrap once, WebSocket subscribe thereafter. Full FX control. |
| `rest_poll` | `ws_param_id` | REST `GET /api/v1/composition` every 2 s for state; WebSocket still used for FX writes. Use if the WebSocket DAT misbehaves. |
| `none` | `off` | Open loop. Clips, layers, decks and tempo all work over OSC. **FX pads go dark and log "FX needs the webserver".** Honest degradation — a dark pad beats a pad that lies. |

`fx_transport=osc_name_guess` exists as a last resort: it reconstructs a name-based OSC address from the discovered internal name. It is best-effort, marked degraded in the health strip, and should not be used in a show.

### 2.2 TD network

```
/project1/PUSH_RESOLUME                 base COMP, extension PushResolume
├── config/
│   ├── cfg_general        Table DAT  <- config/cfg_general.csv
│   ├── map_controls       Table DAT  <- config/map_controls.csv
│   ├── map_palette        Table DAT  <- config/map_palette.csv
│   ├── map_sysex          Table DAT  <- config/map_sysex.csv
│   ├── fx_registry        Table DAT  WRITTEN AT RUNTIME by FxRegistry. Read-only mirror
│   │                                 of the live dict, for eyeballing in the UI.
│   └── fx_pins            Table DAT  <- config/fx_pins.csv, written BY TD on change
├── midi/
│   ├── midiin1            MIDI In DAT.  Bytes Column ON. active=0 until bound.
│   ├── midiin1_callbacks  onReceiveMIDI -> Surface
│   ├── midiout1           MIDI Out CHOP. notenorm=None, controlnorm=None.
│   └── midievent1         MIDI Event DAT, dir=both. Debug only, bypassed in show mode.
├── net/
│   ├── oscout1            OSC Out DAT -> resolume_ip:7000
│   ├── oscin1             OSC In DAT :7001. Inactive by default.
│   ├── ws1                WebSocket DAT -> ws://resolume_ip:8080/api/v1
│   └── web1               Web Client DAT, REST bootstrap
├── logic/
│   ├── exec_boot          Execute DAT: onStart / onExit. The ONLY startup entry point.
│   ├── exec_tick          Execute DAT: onFrameStart -> 30 Hz flush
│   ├── ext_PushResolume   orchestrator
│   ├── mod_pushio         device binding, SysEx, MIDI decode, LED write
│   ├── mod_surface        modes, modifiers, pad->action resolution
│   ├── mod_resolume_out   OSC + WS write path: typing, dead-band, throttled flush
│   ├── mod_resolume_state WebSocket/REST ingest, state normalisation
│   ├── mod_fxregistry     discovery, slot pinning, ramp engine
│   └── mod_ledpainter     pure state -> palette-index mapping
└── ui/
    ├── mirror             on-screen replica: 8x8 grid, encoder values, mode, health
    └── repl_pads          Replicator COMP, FIXED 64 instances (see 2.4)
```

### 2.3 Module responsibilities

**PushIO** — resolves the MIDI device by name for the current platform, runs the SysEx handshake, decodes inbound notes/CC/pitchbend/SysEx, and owns the outbound LED path including the diff cache and the per-tick message cap. Nothing else touches MIDI.

**Surface** — the state machine. Holds grid mode, modifier state, clip bank, focus target. Resolves an incoming `(type, number, modifier, grid_mode)` tuple to an action row from `map_controls`. Emits intents; sends nothing itself.

**ResolumeOut** — the single write path for both transports. Owns OSC address templating, WS parameter-id resolution, value clamping, **explicit int/float typing**, dead-banding, the change cache, and the throttled flush with separate per-tick caps for OSC and WS. Honours `dry_run`.

**ResolumeState** — ingests WebSocket/REST, normalises into a flat state dict: clip presence and connected state per `(layer, clip)`, layer bypass/solo/opacity, column selection, deck list and selection.

**FxRegistry** — the answer to the brittleness problem. Discovers effects, assigns them to pad slots, keeps the slots stable under live patching, and runs the opacity ramps. Section 4.

**LedPainter** — a pure function `state → {(kind, number): palette_index}`. No side effects, no MIDI. Trivially unit-testable and the reason LED bugs will be cheap to fix.

### 2.4 On Replicator COMP

Replicator is the right tool for the **UI mirror** and the wrong tool for the control path.

Right: `ui/repl_pads` builds 64 pad widgets from a 64-row table once, at build time. The count never changes — the Push always has 64 pads — so it is instantiated once and thereafter only its *data* changes. Costs nothing, and it is the idiomatic way to avoid hand-placing 64 widgets.

Wrong: replicating an operator per effect or per OSC address. Three reasons.

1. **There is nothing to replicate.** An OSC "pathway" is a string, not an operator. One OSC Out DAT sends any address via `sendOSC(addr, *vals)`, and one WebSocket DAT carries every `set` message. A per-effect operator adds a node and buys nothing.
2. **Replicator re-instantiates its children when the template table changes.** The FX registry rebuilds on every structural change in Resolume — which is exactly the moment you are least able to afford tearing down and recreating a few hundred operators. That is a frame-hitch generator in the middle of a set.
3. **A dict is the correct data structure.** `fx['LAYER1:2'].opacity_id` is an O(1) lookup with no cooking, no node graph, and no rebuild cost.

So: **registry = a Python dict** (mirrored to a read-only Table DAT purely so you can look at it); **sending = one OSC Out DAT plus one WebSocket DAT**; **Replicator = fixed-count UI only.**

---

## 3. Surface layout

### 3.1 The organising idea

The eight positions across the display strip are **two identical four-wide banks**, and every row in the strip uses the same four targets in the same order:

```
position:      1      2      3      4   │   5      6      7      8
target:       L1     L2     L3    COMP  │  L1     L2     L3    COMP
```

Encoders, the row above the display, and the row below the display all follow it. Nothing needs the screen to be readable. Learn "1-2-3-Comp, twice" and the whole strip is known.

### 3.2 Full surface

```
                    ┌─ ENCODERS: CC 71..78 ─ two banks of L1 L2 L3 COMP ─┐
 ○ Tempo   ○ Swing  │  ○1     ○2     ○3     ○4     ○5     ○6     ○7     ○8 │   ○ Master
   CC14      CC15   │ OPAC   OPAC   OPAC   OPAC   MACRO  MACRO  MACRO  MACRO│     CC79
   BPM    XfadeDur  │  L1     L2     L3    COMP    L1     L2     L3    COMP │   /comp/master
                    └───────────────────────────────────────────────────────┘
                    ╔═══════════════════════════════════════════════════════╗
 [Setup] [User]     ║ 102    103    104    105  │ 106    107    108    109  ║   UPPER ROW
  ui     release    ║ CLEAR  CLEAR  CLEAR  DISC │ SOLO   SOLO   SOLO   RE-  ║   (RGB)
                    ║  L1     L2     L3    ALL  │  L1     L2     L3   SYNC  ║
                    ╟───────────────────────────────────────────────────────╢
                    ║           display  —  dark, brightness 0             ║
                    ╟───────────────────────────────────────────────────────╢
 [Device][Browse]   ║  20     21     22     23  │  24     25     26     27  ║   LOWER ROW
  FXgrid  resvd     ║ SEL    SEL    SEL   FOCUS │ BYP    BYP    BYP   BLACK ║   (RGB)
 [Mix]  [Clip]      ║  L1     L2     L3   COMP  │  L1     L2     L3   -OUT  ║
                    ╚═══════════════════════════════════════════════════════╝

  ┌────┐            ┌───┬───┬───┬───┬───┬───┬───┬───┐            ┌──────────┐
  │ ▲  │ deck prev  │ 92│ 93│ 94│ 95│ 96│ 97│ 98│ 99│ S1         │ CC36  B1 │
  │◄ ►│ column ±   ├───┼───┼───┼───┼───┼───┼───┼───┤            ├──────────┤
  │ ▼  │ deck next  │ 84│ 85│ 86│ 87│ 88│ 89│ 90│ 91│ S2         │ CC37  B2 │
  └────┘            ├───┼───┼───┼───┼───┼───┼───┼───┤            ├──────────┤
                    │ 76│ 77│ 78│ 79│ 80│ 81│ 82│ 83│ S3         │ CC38  B3 │
  [Shift] modifier  ├───┼───┼───┼───┼───┼───┼───┼───┤            ├──────────┤
  [Select] modifier │ 68│ 69│ 70│ 71│ 72│ 73│ 74│ 75│ S4         │ CC39  B4 │
                    ├───┼───┼───┼───┼───┼───┼───┼───┤            ├──────────┤
  [◄ Page ►] bank±  │ 60│ 61│ 62│ 63│ 64│ 65│ 66│ 67│ S5         │ CC40  B5 │
   CC62    CC63     ├───┼───┼───┼───┼───┼───┼───┼───┤            ├──────────┤
                    │ 52│ 53│ 54│ 55│ 56│ 57│ 58│ 59│ S6         │ CC41  B6 │
  [Oct+] BPM x2     ├───┼───┼───┼───┼───┼───┼───┼───┤            ├──────────┤
  [Oct-] BPM /2     │ 44│ 45│ 46│ 47│ 48│ 49│ 50│ 51│ S7         │ CC42  B7 │
                    ├───┼───┼───┼───┼───┼───┼───┼───┤            ├──────────┤
  [Session] clips   │ 36│ 37│ 38│ 39│ 40│ 41│ 42│ 43│ S8         │ CC43  B8 │
                    └───┴───┴───┴───┴───┴───┴───┴───┘            └──────────┘
  ║ touch strip                T1  T2  T3  T4  T5  T6  T7  T8      plain = clip bank
  ║ /composition/                                                   SHIFT = deck 1..8
  ║ crossfader/phase   [Play] pause  [Rec] record  [Stop] PANIC
```

### 3.3 Grid — SESSION mode (default, `Session` CC 51)

```
 S1  L3 clips  1.. 8      cyan     ─┐
 S2  L3 clips  9..16      cyan     ─┴ Layer 3   (top of the Resolume stack)
 S3  L2 clips  1.. 8      magenta  ─┐
 S4  L2 clips  9..16      magenta  ─┴ Layer 2
 S5  L1 clips  1.. 8      amber    ─┐
 S6  L1 clips  9..16      amber    ─┴ Layer 1   (bottom of the stack)
 S7  columns   1.. 8      violet   ─┐
 S8  columns   9..16      violet   ─┴ scenes: fire one clip in every layer
```

Layer 3 sits at the top because Resolume draws higher layers higher. The clip index is `bank*16 + n`, so bank 1 shows clips 1–16 and bank 8 shows clips 113–128.

The bottom two rows line up exactly with the three bands above them: pad `S7 T1` is column 1, and column 1 is the clip sitting at `S1 T1`, `S3 T1` and `S5 T1`. Fire a vertical slice by pressing the pad directly below it. **The column rows bank with the clip rows** so this alignment holds in every bank.

### 3.4 Grid — FX mode (`Device` CC 110)

Same four-target column discipline as the display strip, rotated into the grid. FX chains read vertically, which is how Resolume stacks them.

```
 col:    T1     T2     T3     T4   │   T5     T6     T7     T8
 target: L1     L2     L3    COMP  │   L1     L2     L3    COMP
 slot:  1..8   1..8   1..8   1..8  │  9..16  9..16  9..16  9..16   (S1=first)
```

Each pad is one discovered effect. Slot occupancy comes from the runtime registry, not from a file. Full behaviour in section 4.

### 3.5 Encoders

All eight are endless relative encoders. TD keeps the authoritative value and accumulates deltas; it never treats the CC as absolute.

**Encoders 1–4 are identical in every grid mode.** The four most-used controls in the whole rig never move under your fingers.

| Pos | CC | Any mode | + Shift | + Select |
|---|---|---|---|---|
| 1 | 71 | Layer 1 opacity | Layer 1 speed | fine (×0.2) |
| 2 | 72 | Layer 2 opacity | Layer 2 speed | fine |
| 3 | 73 | Layer 3 opacity | Layer 3 speed | fine |
| 4 | 74 | Composition opacity | Composition speed | fine |

**Encoders 5–8 follow the grid mode.**

| Pos | CC | SESSION | SESSION + Shift | FX | FX + Shift |
|---|---|---|---|---|---|
| 5 | 75 | L1 dashboard link1 | link2 | FX slot 1 opacity of focused target | FX slot 5 |
| 6 | 76 | L2 dashboard link1 | link2 | FX slot 2 | FX slot 6 |
| 7 | 77 | L3 dashboard link1 | link2 | FX slot 3 | FX slot 7 |
| 8 | 78 | COMP dashboard link1 | link2 | FX slot 4 | FX slot 8 |

Dashboard links survive as the Session-mode macro because they are useful *without leaving clip view* — the performer maps anything to them inside Resolume. In FX mode the same four encoders become continuous opacity faders for the focused target's chain, the natural companion to the pad toggles.

| Dedicated | CC | Function |
|---|---|---|
| Tempo | 14 | `/composition/tempocontroller/tempo` |
| Swing | 15 | Transition duration of the focused layer |
| Master | 79 | `/composition/master` |

Encoder touch notes are 0–7 for encoders 1–8, 8 for Master, 9 for Swing, 10 for Tempo. Touch opens the send window and, with Shift held, resets that parameter to its default.

### 3.6 Modifiers and modes

| Control | Role |
|---|---|
| `Shift` CC 49 | Momentary. Encoder alternate page; right column becomes deck select. |
| `Select` CC 48 | Momentary. Pads select in Resolume without connecting; encoders go fine. |
| `Session` CC 51 | Grid = clip launcher. |
| `Device` CC 110 | Grid = FX bypass matrix. |
| `Stop` CC 29 | **Panic.** Re-send User Mode SysEx, re-write the palette, full LED redraw, re-adopt Resolume state. The one button to hit when the surface looks wrong. |
| `Shift`+`Stop` | **Rescan.** Force a REST re-read and a full FX registry rebuild. For the case where Resolume changed something without announcing it. |
| `User` CC 59 | Hand Push back to Live mode / take it again. This button always transmits on both ports in every mode, which makes it a reliable escape hatch. |
| `Setup` CC 30 | Show/hide the TD mirror UI. |

Everything not assigned is listed as `reserved` in `map_controls.csv` with its LED forced off, so an unmapped press is visibly inert rather than mysteriously silent.

---

## 4. Dynamic FX: discovery, pinning, and opacity control

This is the section that answers the brittleness critique. Nothing here requires a human to declare anything.

### 4.1 What the API actually gives us

`GET http://ip:8080/api/v1/composition` returns every effect instance as:

```json
{
  "id": 1723069642348,
  "name": "Goo",                     // internal plugin key
  "displayName": "Slime",            // renameable UI label (may be absent on 7.15)
  "bypassed": { "id": 1723069642349, "valuetype": "ParamBoolean", "value": false },
  "mixer":    { "opacity":   { "id": 1723069642350, "valuetype": "ParamRange",
                               "min": 0.0, "max": 100.0, "value": 100.0 },
                "blendmode": { "id": 1723069642351, "valuetype": "ParamChoice", ... } },
  "effect":   { "<plugin params, each with its own id>": { ... } }
}
```

Three facts make the whole design work:

1. **Every parameter has a numeric `id`**, and the API documents ids as constant across sessions and reordering.
2. **`/parameter/by-id/{id}` is a first-class control path** over the WebSocket. No name appears anywhere.
3. **The composition is re-pushed in full on structural change**, so adding or removing an effect announces itself.

Effect opacity is `mixer.opacity`, effect on/off is `bypassed`, and both are siblings on the effect object. Duplicates are a non-issue: `goo`, `goo2` and `goo3` are three separate objects with three separate id sets. A rename touches `displayName` and nothing else.

**Do not hard-code the key `"opacity"`.** The schema declares `mixer` as an unstructured map, so the key name inside it is not guaranteed. Resolve it by walking `mixer`: take the entry whose key case-insensitively equals `opacity`; failing that, the first `ParamRange` with `min == 0`. Log which rule fired on first run. This is the same "discover, don't assume" rule applied one level deeper, and it costs four lines.

### 4.2 The registry

On bootstrap and on every structural change, `FxRegistry` walks the four targets — composition, and the layers named in `layer_ids` — and for each effect in chain order records:

```python
{ 'chain_index': 0,
  'effect_id':   1723069642348,
  'name':        'Goo',            # internal key, used only for the pin
  'label':       'Slime',          # displayName if present, else name. UI only.
  'opacity_id':  1723069642350,
  'bypassed_id': 1723069642349,
  'param_ids':   {'amount': 172306964xxxx, ...},   # for the optional deep-param bank
  'slot':        2,                # assigned by the pinning algorithm
  'on_value':    0.65 }            # from fx_pins.csv, else fx_default_on_value
```

Keyed by `f'{target}:{slot}'`, which is exactly the key the pad rows in `map_controls.csv` reference. That is the entire coupling between the surface and Resolume: a slot number.

### 4.3 Slot pinning — pads must not shuffle mid-show

Naive chain-order mapping has an obvious failure: insert an effect at the top of a chain and every pad below it shifts by one. Mid-set, that is unusable.

So slots are assigned by **identity, not position**:

```
on rebuild:
  1. every effect whose pin key is already assigned KEEPS its slot
  2. new effects take the lowest free slot, in chain order
  3. a removed effect frees its slot but the pin is held for fx_pin_ttl_s (300 s),
     so an undo or a re-add returns to the same pad
  4. more than fx_slots_per_target on a target: log, leave unassigned, pad dark
```

Two identity keys, because they answer different questions:

| Key | Value | Stable across |
|---|---|---|
| Session identity | `effect_id` | reorder, rename, other effects added/removed |
| Persisted identity | `target|name|ordinal` — e.g. `LAYER1|goo|2` | Resolume restart, composition reload |

`ordinal` is the 1-based count of that internal name within the target's chain, so the three Goos are `goo|1`, `goo|2`, `goo|3`. This is precisely the case the old design got wrong, and it is now the mechanism rather than the exception. Note it keys on the **internal** name, so renaming `goo3` to `Slime` in the Resolume UI does not move its pad.

Result, concretely: **add an effect to layer 1 while the show is running and it appears on the next free pad within about 300 ms. Nothing already under your fingers moves.** Reorder the chain and nothing moves at all.

`fx_pins.csv` is written by TD whenever pins or on-values change. It is a cache, not a contract. Delete it to reset the layout; never edit it.

### 4.4 Pad behaviour — opacity 0 → 100% on one press

The pad drives `mixer.opacity`, not `bypassed`. That is the right primitive: opacity is a float, so it can ramp, and it leaves the effect in the render chain so there is no re-initialisation pop.

| Gesture | Action |
|---|---|
| **Tap** | Toggle opacity between `0.0` and the slot's `on_value`, ramped over `fx_fade_ms` (default 120 ms; set 0 for a hard cut). |
| **Hold** past `fx_momentary_ms` (400 ms) | Momentary stab: opacity goes to `on_value` while held and returns to 0 on release. Auto-detected from the same press, so one pad is both a latch and a stab. |
| **Shift + pad** | Toggle `bypassed`. The hard cut, for taking a heavy effect off the GPU entirely. Deliberately distinct from opacity 0. |
| **Select + pad** | Capture: store the effect's *current* opacity as this pad's `on_value`, and persist it. Dial a look in with the encoder, then Select+pad to make that the pad's "on". |
| **Encoder 5–8 in FX mode** | Continuous opacity for slots 1–4 (Shift: 5–8) of the focused target. |

The ramp engine lives in `FxRegistry` and runs on the shared 30 Hz tick: at 120 ms a fade is 4 messages, and concurrent fades share the `ws_msgs_per_tick` budget. A ramp in flight is cancelled and re-aimed if the pad is hit again, so double-tapping cannot queue up.

LED, five states, resolved by `LedPainter`:

| State | Palette |
|---|---|
| no effect in slot | `OFF` |
| present, opacity 0 | `FX_OFF` — dim green, "loaded and ready" |
| present, 0 < opacity < on_value | `FX_MID` |
| present, opacity ≥ on_value | `FX_ON` |
| hard-bypassed | `FX_BYPASSED` — dim red, overrides the above |
| ramping | blinks between the from-state and to-state at 4 Hz |

### 4.5 Rebuild discipline

| Trigger | Response |
|---|---|
| WebSocket composition message | Debounce `fx_rebuild_debounce_ms` (250 ms), then rebuild. A burst of edits in Resolume causes one rebuild, not ten. |
| Deck select | Force a rebuild. A deck switch purges inactive-deck clips *and* destroys their parameter ids — the registry is genuinely invalid, not just stale. |
| `Shift`+`Stop` | Manual full REST re-read and rebuild. |
| `fx_reconcile_s` (10 s, optional) | Slow REST reconcile. Exists because some Resolume edits are known not to emit a notification — the Companion maintainers report drag-swapping clips is one. Set to 0 on large compositions. |
| Clip connect, parameter change | **No rebuild.** These arrive as `parameter_update` and only touch state. |

Identifying the composition message: it has **no `type` field**. Detect it the way Resolume's own Companion module does — `if 'columns' in msg and 'layers' in msg`. Typed messages are `sources_update`, `effects_update`, `parameter_update`, `parameter_set`, `parameter_get`, `parameter_subscribed`, `parameter_unsubscribed`.

### 4.6 Subscriptions — subscribe narrowly

After each rebuild, subscribe to exactly what the LEDs need and nothing else:

```
per effect:  bypassed_id, opacity_id
per clip in the visible bank:  connected
per layer:   bypassed, solo, video/opacity
```

Never subscribe to `transport/position` — it streams continuously per playing clip. On rebuild, unsubscribe stale ids before subscribing new ones.

### 4.7 Optional: deep effect parameters (Phase 4b)

Because discovery already captured `param_ids` for every effect, the deep parameters are free. `Shift`+`Device` toggles a param bank in which encoders 5–8 drive the first four parameters of the **last-touched** effect (Shift: params 5–8). The last-touched pad pulses so you can see what you are editing.

This is the one feature to cut if time is short. It is listed separately in the build order and nothing else depends on it.

---

## 5. Push 2 initialisation

Order matters. Run this from a single `Execute DAT.onStart`, deferred by `run(..., delayFrames=15)` because CoreMIDI enumeration is not guaranteed complete at `onStart`.

```
 1. Resolve device names for sys.platform, write into /local/midi/device, re-init, set midiin1.active=1
 2. Device Inquiry        F0 7E 7F 06 01 F7          -> await reply, log firmware + serial
 3. Set MIDI Mode = User  F0 00 21 1D 01 01 0A 01 F7
 4. Aftertouch = channel  F0 00 21 1D 01 01 1E 00 F7
 5. LED brightness        F0 00 21 1D 01 01 06 64 F7
 6. Display brightness    F0 00 21 1D 01 01 08 00 00 F7      (deliberately dark)
 7. Palette entries       F0 00 21 1D 01 01 03 <idx> <9 bytes> F7   x N   (map_palette.csv)
 8. Reapply palette       F0 00 21 1D 01 01 05 F7
 9. Touch strip config    F0 00 21 1D 01 01 17 10 F7
10. Resolume REST bootstrap -> ADOPT current state (never impose)
11. Full LED redraw
```

Send SysEx with `midioutCHOP.sendExclusive()` and **omit `F0`/`F7`** — TD adds the framing itself. Passing a hex *string* sends its ASCII characters; pass a list of ints or a `bytes` object.

Step 10 is a design rule, not a nicety: **on startup TD reads Resolume and matches it.** A running show must not jump because someone relaunched the controller.

### 5.1 The palette is ours, not Ableton's

The interface manual documents only six default palette indices (122–127) and warns the defaults may change. Rather than depend on undocumented entries, this design **writes its own 25-entry palette block at indices 16–40** and then calls Reapply. Colour behaviour becomes deterministic across firmware revisions and identical on both platforms. Index 0 stays untouched as off. See `config/map_palette.csv`.

Each entry needs R, G, B **and** W, because white-only buttons resolve the same index through a separate white palette. `map_palette.csv` carries a W value for every index, and the verification script enforces that white-only CCs are only ever given `OFF`, `WHITE_DIM` or `WHITE_FULL`.

### 5.2 Blinking is done in software, on purpose

Push 2 has hardware LED animations selected by MIDI channel — channel 0 static, 1–5 one-shot, 6–10 pulsing, 11–15 blinking. **They are not used here.** They require the host to send MIDI Start and 24 ppqn clock on the active port; without a MIDI Start the animations do not run at all, and generating stable clock from TD's frame loop is jittery and adds a whole tempo-sync subsystem for a cosmetic feature.

Instead `LedPainter` toggles between two palette indices on the 30 Hz tick at `blink_hz` (default 2 Hz), capped to 16 blinking pads. Identical on Mac and Windows, no clock dependency, blink rate is a config value. All LED writes therefore go out on **TD channel 1** (= Push channel 0 = static).

### 5.3 Shutdown

`onExit` fires but nothing cooks or flushes afterwards, so MIDI queued there may never reach the device. Use a delayed quit:

```python
def CloseProject(self):
    self.AllLedsOff()
    self.SetPushMode('live')          # F0 00 21 1D 01 01 0A 00 F7
    self.RestoreTouchStrip()          # 17 68, the factory default
    run("args[0]()", self._quit, delayFrames=60)
```

An OS-initiated close gives no lead time. Accept that Push may be left in User Mode with LEDs lit; the `User` button and Panic both recover it, and the next startup rewrites everything anyway.

---

## 6. Rate limiting and value handling

A single `Execute DAT.onFrameStart` gate is the only clock in the project:

```python
def onFrameStart(frame):
    if frame % 2: return          # 30 Hz at a 60 fps timeline
    ext.Tick()                    # ramp engine -> OSC flush -> WS flush -> LED flush
```

| Rule | Value | Why |
|---|---|---|
| Flush rate | 30 Hz | Community measurement: 3 OSC streams at 20 Hz is fine; the same at 60 Hz produced severe lag at ~65% CPU. Resolume applies no rate limiting of its own. |
| Dead-band | 0.002 | Below Resolume's visible resolution. Kills idle chatter. |
| Change cache | required | `sendOSC` and WS `set` both always send. The diff is ours to do. |
| Per-tick caps | 32 OSC, 16 WS, 48 LED | Separate round-robin queues. A fast encoder sweep, a bank change or eight simultaneous FX fades cannot flood. |
| Bundling | `asBundle=True` | One UDP packet per tick instead of dozens. |
| Touch strip | throttle hard | 14-bit pitch bend, 0–16383. Quantise to ~1/512 before dead-banding. |
| WS budget | conservative | Nothing is documented about WebSocket throughput, and **Arena 7.15 predates the 7.26.1 fix for "REST-API overhead on large compositions"**. Treat the webserver as the expensive path: 16 messages per tick, never poll, and rebuild only on announced change. |

**Typing is not optional.** Resolume linearly remaps a float across a parameter's whole native range, so `blendmode 1` (int) selects mode 1 while `blendmode 1.0` (float) selects mode 50. Every OSC trigger, toggle and enum must be cast with `int()`. Set `useNonStandardTypes=False` on `sendOSC` so Python `True`/`False` cannot go out as OSC `T`/`F`, which Resolume may not accept. On the WebSocket, `bypassed` is a `ParamBoolean`: send `0`/`1`, marked `bool_as_int` in the CSV.

**Effect opacity units.** `mixer.opacity` is declared with `min: 0.0, max: 100.0` in the REST schema, and the WebSocket `set` takes a value in the parameter's own units — not the 0.0–1.0 normalisation OSC uses. Read `min`/`max` from the discovered parameter and scale into it. Do not assume either convention; the discovered numbers are authoritative. This is the single most likely place to get a silently-wrong result (an opacity of `1.0` where `100.0` was meant looks like "the pad barely does anything").

Two documented exceptions, already flagged in the CSV: `tempomultiplytwo` and `tempodividetwo` are typed float in Resolume where int would be expected. Send them as `1.0`.

Encoder response: base step 0.005 per click, with velocity acceleration up to ×8 from the accumulated delta over the last 100 ms, and ×0.2 while `Select` is held. Full-range travel is then roughly five revolutions at rest and under one when swept.

---

## 7. Pitfall register

Each row is a real, sourced failure mode with the mitigation this design already contains.

### 7.1 Push 2

| # | Pitfall | Mitigation |
|---|---|---|
| P1 | Push boots in **Live mode**. Persistence of the mode SysEx across power cycle or USB re-plug is undocumented. | Send `0A 01` at startup, on Panic, and whenever a Device-Change event or a MIDI silence timeout fires. |
| P2 | Ableton Live running at the same time will fight for the device and may reset the mode. | Don't run Live. If it must run, use **Dual mode** `0A 02` and only ever touch port 2. |
| P3 | Must use the **User Port**, not the Live Port. User mode routes all non-SysEx I/O to port 2; input on port 1 is ignored. | Device names in `cfg_general.csv` name the User Port explicitly on both platforms. |
| P4 | Some buttons are **white-only**; a colourful palette index resolves through the white palette to an arbitrary brightness. | `Color` flag taken from `Push2-map.json`; verification script rejects RGB palettes on white CCs. |
| P5 | Hardware LED animations silently do nothing without host MIDI Start + clock. | Software blink. See 5.2. |
| P6 | On **USB bus power only** the hardware caps LED brightness to 8 and display brightness to 100. Symptom: "the LEDs look dead". | Use the power supply. Startup logs a warning if LEDs are commanded bright but look wrong; document it in the runbook. |
| P7 | Encoder value encoding is relative: `0x01–0x3F` = +1…+63, `0x7F–0x41` = −1…−63. Treating it as absolute makes knobs jump to extremes. | Accumulate deltas. **Verify with a MIDI monitor on first run** and keep the decode in one function so the convention can be flipped in one place. |
| P8 | Touch strip is 14-bit pitch bend and will spam at frame rate. | Configure with SysEx `17 10`; quantise then dead-band. |
| P9 | TD `sendExclusive` **adds `F0`/`F7` itself**; chunking a long SysEx across calls produces multiple framed messages, not one. | Never include the framing. Palette writes are 11 payload bytes each, well inside any limit. |
| P10 | SysEx length cap: 1024 bytes on 2023.x builds, reportedly raised to 32 K in the 2025 series. Unconfirmed for 32820. | Irrelevant for this design's short messages. Verify before ever attempting display graphics. |
| P11 | `notenorm` / `controlnorm` on MIDI Out CHOP rescale 0–127 and break every LED. | Both set to `None`. Put it in the acceptance test for Phase 1. |
| P12 | With no USB frames the display goes black after 2 s, which looks like a fault. | Set display brightness to 0 at startup so it is deliberately, consistently dark. |
| P13 | Poly aftertouch floods the port with pad-pressure messages. | `1E 00` = channel pressure. Pressure is ignored by the surface. |

### 7.2 Resolume

| # | Pitfall | Mitigation |
|---|---|---|
| R1 | **Effect OSC addresses contain a name**, and the name is derived from an internal plugin key, not the UI label (`Solid Color` → `solidcoloreffect`). It cannot be computed reliably for arbitrary FFGL plugins. | FX never goes over OSC. Discovery + `/parameter/by-id/{id}`. Section 4. |
| R2 | Duplicate instances (`goo`, `goo2`, `goo3`) — the auto-suffix rule is undocumented, and whether a UI rename changes the address is undocumented. | Both are non-events: parameter ids are per-instance and carry no name. The pin key uses the *internal* name plus an ordinal, so a rename does not move the pad either. |
| R3 | **Float sent to an int parameter is remapped across the whole range**, so `1.0` means "maximum", not "one". | Explicit `int()` on every OSC trigger, toggle and enum. `value_type` column is authoritative in the CSV. |
| R4 | Layers, clips, columns and decks are **1-based**; enum *values* are 0-based. | Indices built from config, never hard-coded. `layer_ids` is configurable. |
| R5 | **Switching decks purges inactive-deck clips**; clip addresses only reach the active deck, and the API states only the active deck's layers and clips can be retrieved — so their **parameter ids do not exist** either. Arena 7.21.2 additionally reported wrong `connected` output right after a deck switch. | Deck select is **Shift-guarded**. On deck change: invalidate all clip state, force a full FX registry rebuild, re-bootstrap from REST, full grid redraw. |
| R6 | `connectspecificclip` was reported to accept only 0 or 1 instead of a clip index. | Never used. Per-clip `/clips/M/connect` only. |
| R7 | `/composition/layers/N/clear` was reported broken from external OSC on some 7.x builds. | Fallback: send `connect 0` to the clip the state model believes is connected. Implement both, prefer `clear`, fall back on no state change within 500 ms. |
| R8 | **Silent failure.** An OSC message to a non-existent address is discarded with no error. | Startup validation against the REST composition tree. Anything unresolved is logged and its pad forced dark, so the surface tells the truth. WS `set` at least returns a `parameter_set` reply, so FX writes are verifiable. |
| R9 | No rate limiting in Resolume; 60 Hz streams caused severe lag. | 30 Hz cap, dead-band, send-on-change, per-tick cap, bundling. section 6. |
| R10 | "Output All OSC Messages" echoes everything and has been reported to stall or crash Arena; `connected` is 0–4 not 0/1; absolute and relative addresses both emit, so a listening controller fights itself. | OSC output is **off**. State comes over WebSocket. If OSC feedback is ever enabled, only via a narrow hand-built preset. |
| R11 | Windows Defender blocks inbound UDP by default. | Runbook step: inbound UDP rule for 7000. Startup health check flags "no state and no ack". |
| R12 | Trailing whitespace in an OSC address silently kills the control. | CSV cells stripped on load; verification script asserts it. |
| R13 | Structural changes (add layer, add effect) have no OSC address at all — only REST `POST`/WS `post`. | The surface never makes structural changes. It only *reacts* to them, which is the whole point of section 4. |
| R14 | The composition must actually contain the three configured layers, or everything fails silently. | Startup validation compares `layer_ids` against the REST tree and refuses to arm if they are missing. |
| R15 | Address scheme changed at v5→v6. Old forum answers using `/layer1/...` or `/activelayer/...` are invalid. | Every OSC address in the CSV validated against the official `/composition` dump. |
| R16 | **The webserver is the expensive path.** Arena 7.15 predates the 7.26.1 fix for "#25086 REST-API Overhead on large compositions", and there is a standing forum thread about the webserver dropping performance. Every composition message is the *whole* composition, not a diff. | Never poll REST in steady state. WS push only. Debounce rebuilds by 250 ms. `fx_reconcile_s=0` on large compositions. Bootstrap REST call happens once, before the surface arms. |
| R17 | The WS composition message has **no `type` field** — you cannot switch on it. | Detect it the way Resolume's own Companion module does: `'columns' in msg and 'layers' in msg`. |
| R18 | Some Resolume edits produce **no notification at all** — Companion maintainers report drag-swapping clips as a known API limitation. | `Shift`+`Stop` manual rescan, plus the optional slow `fx_reconcile_s` reconcile. Accept that a silent edit needs one button press. |
| R19 | `displayName` on an effect may not exist on 7.15 (older schema snapshots have only `name`). | Registry uses `displayName or name`, and only for UI labels. Never for addressing or pinning. |
| R20 | OSC `"?"` polling replies to the **configured OSC output destination**, not to the sender, and needs OSC output enabled. It is not a usable address probe from an unconfigured sender. | Not used. Existence is established from the REST/WS tree instead. |
| R21 | Removing an effect **destroys its parameter ids**; re-adding produces new ones. Whether ids survive a composition save/reload is undocumented. | Session identity is `effect_id`; persisted identity is `target\|name\|ordinal`. Pins survive a reload even if ids do not. |
| R22 | `mixer` is declared as an **unstructured map** in the schema, so the key name for opacity is not guaranteed, and its range is `0–100` not `0–1`. | Resolve the key by walking `mixer`; read `min`/`max` from the discovered parameter and scale into it. Never hard-code either. |
| R23 | The webserver has **no authentication** and defaults to listening on `0.0.0.0`. | Single-machine rig: set the listen address to `127.0.0.1`. Two-machine rig: firewall it to the TD host. Runbook item. |

### 7.3 TouchDesigner

| # | Pitfall | Mitigation |
|---|---|---|
| T1 | **There is no MIDI Out DAT.** All MIDI out is `midioutCHOP` methods: `sendNoteOn`, `sendControl`, `send`, `sendExclusive`. | Documented in `mod_pushio`. |
| T2 | The MIDI Device Mapper stores the OS **device name string** inside the `.toe`, and the names differ per platform. | `onStart` writes the platform-correct name into `/local/midi/device`, matched by prefix, then re-inits. Names live in `cfg_general.csv`. |
| T3 | Open, unresolved report of macOS 2025 builds failing to enumerate MIDI devices (forum 829461, Oct 2025, no fix posted). | Startup self-test with retry, a visible "Push not found" state in the mirror UI, and a manual device picker. **Test this on 32820 before anything else is built.** |
| T4 | A MIDI In DAT with an invalid `indevice` re-opens the port every frame and destroys frame rate. | `midiin1.active=0` until the device name is confirmed present. Never leave a stale name in the cell. |
| T5 | `onExit` does not flush hardware writes. | Delayed-quit pattern. 5.3. |
| T6 | Extensions can re-initialise at any time; `__del__` may never run. | Idempotent `__init__`, real work in `onInitTD`, cleanup in `onDestroyTD`, `extensionsReady` guards. |
| T7 | TD only cooks what is used. Code that works in the network editor dies in Perform mode. | The tick lives in an Execute DAT, which always cooks. No viewer-dependent chains in the control path. |
| T8 | Multiple Execute DATs fire `onStart` in name-alphanumeric order; a historic bug let one suppress the others. | Exactly one Execute DAT owns startup. Everything else is called from it. |
| T9 | Routing MIDI through a custom parameter coalesces messages, because custom pars cook once per frame. | Logic runs directly in `onReceiveMIDI`. |
| T10 | `sendOSC(useNonStandardTypes=True)` is the default and turns bools into `T`/`F`. | `useNonStandardTypes=False`, ints for booleans. |
| T11 | MIDI is drained once per frame, so callbacks are frame-quantised at ~16.7 ms. Lossless in count, not in timing. | Acceptable for VJ work. Stated here so nobody chases it as a bug. |
| T12 | MIDI In DAT `clamp`/`maxlines` is display-only; callbacks still fire for clipped rows. | Do not use table length as a signal. |
| T13 | TD creates no virtual MIDI ports. | Not needed — Push is real hardware. If a virtual port is ever wanted: IAC Driver on macOS, loopMIDI on Windows. |
| T14 | Absolute paths break on the platform hop. | Forward slashes, `project.folder`-relative, no absolute paths. |
| T15 | Manually pulsing `reinitextensions` and then immediately calling a heavy orchestrator method (`Boot()`-class: MIDI SysEx + subprocess spawn + network I/O) from a separate `execute_python` call **crashed TD outright**, twice, during the Phase 6 display build. The same method firing naturally from `exec_boot.onStart` on a real TD launch never crashed. | Never drive `reinitextensions.pulse()` + an external heavy call by hand over MCP. For a single module DAT's code change, skip the full reinit and patch the live instance in place instead: `liveInstance.__class__ = op('path/mod_x').module.ClassName` -- preserves all instance state (open connections, subprocess handles) and never crashed. `project.save()` (which also reinitializes extensions internally) did not reproduce this. |
| T16 | A Text TOP's `numpyArray()` came back with its glyphs vertically mirrored (upside-down letters) while its block position in a larger composited image stayed correct -- the generic "row 0 = top" TOP contract did not hold for Text TOP specifically (confirmed live, Phase 6d). | `np.flipud()` the Text TOP's own array before combining with anything else; flipping the already-combined canvas breaks the correct block ordering instead. |
| T17 | Feeding a Script TOP's `copyNumpyArray()` a bare `np.flipud()` result (a negative-stride, non-contiguous view, not a real copy) **crashed TD outright** (confirmed live, Phase 6f debug-preview build). Separately, `copyNumpyArray` also expects the opposite (bottom-up) row order from `numpyArray()`'s own top-down convention used everywhere else in this project. | Always materialise a real contiguous array before `copyNumpyArray` -- `np.flipud(arr).copy()`, never a bare view. Verify with a throwaway `capture_top` test before trusting any new Script TOP debug/preview path in this project. |

---

## 8. Startup, health and failure behaviour

The mirror UI shows a health strip. Each item is green, amber or red, and the surface **arms only when Push and OSC are both green**.

| Check | Green | Red behaviour |
|---|---|---|
| Push bound | Device Inquiry reply received | Mirror shows "Push not found", retry every 2 s, LEDs untouched |
| Push mode | `0A` reply confirms User | Re-send, then Panic path |
| OSC target | UDP socket open | Mirror warns; surface still arms (UDP is fire-and-forget) |
| Resolume state | WebSocket connected | Fall back to `rest_poll`, then to `none`; LEDs run open-loop from TD's own model |
| FX registry | composition parsed, N effects discovered | `fx_transport=off`: FX pads dark, count shown as 0, reason logged. Clips and layers keep working. |
| Layers | `layer_ids` all present | **Refuse to arm.** This is the one hard failure. |
| Display | Helper connected (Phase 6) | Helper crash/USB failure closes the connection; auto-relaunch/reconnect a beat later. Never blocks arming -- a dark screen is not a hard failure, same as Resolume state. |

The health strip also shows the live registry count per target — `L1:4 L2:1 L3:0 C:2` — so "why is that pad dark" is answerable at a glance without opening Resolume.

Reconnect handling: on MIDI silence for 3 s or a device-change event, re-run steps 1-9 and 11 of section 5. On WebSocket close, reconnect with backoff and re-bootstrap from REST on success, then rebuild the registry and re-subscribe.

---

## 9. Build order for the implementing agent

Each phase has an acceptance test that can be run without the next phase existing.

**Phase 0 — skeleton and contract.** Base COMP, four config Table DATs loaded from the CSVs, extension shell, mirror UI drawing an 8×8 grid (fixed-count Replicator) and eight encoder read-outs from a stub state dict. No hardware, no network.
*Accept:* toggling grid mode and clip bank in the UI redraws the mirror correctly; `map_controls` resolves a `(type, number, modifier, mode)` tuple to the right row for a hand-picked sample of 12 controls, including one FX pad in each of its three modifier variants.

**Phase 1 — Push I/O.** Device resolution by name, Device Inquiry, the full SysEx handshake, palette write, LED diff cache with per-tick cap, software blink.
*Accept:* on both platforms, a cold start lights a known test pattern within 3 s; unplug/replug recovers automatically; `notenorm`/`controlnorm` are `None`; a full 64-pad redraw costs no measurable frame time.

**Phase 2 — input and surface, dry-run.** `onReceiveMIDI` decode including relative encoders and pitch bend, modifier and mode state machine, action resolution. `dry_run=1`: every intent is logged to a Text DAT, nothing is sent.
*Accept:* every control in `map_controls.csv` produces exactly one correct log line with the correct resolved path, transport and type; the reserved controls produce none; encoder sweeps accumulate smoothly in both directions and the mirror follows.

**Phase 3 — OSC out.** `ResolumeOut` OSC half: templating, clamping, explicit typing, dead-band, change cache, bundled 30 Hz throttled flush with cap. `dry_run=0`.
*Accept:* against a live Arena with 3 layers — all opacities, all 48 clip slots, columns, deck switch under Shift, BPM tap and ×2/÷2, blackout. Watch Arena's OSC monitor: no message storms, no duplicates. Sustained encoder sweeps stay under 30 messages/s per stream and Arena stays responsive.

**Phase 3a — hardware truth check.** Before writing FxRegistry, spend twenty minutes settling the four things the documentation does not state. Add Goo three times to layer 1, rename the third one, and record: the actual `mixer` key for opacity, its `min`/`max`, whether `displayName` exists on 7.15, and the three effects' `name` values. Also confirm the encoder delta encoding with a MIDI monitor.
*Accept:* a short findings note committed next to this design. **Do not build on assumptions here** — every one of these has a UNCONFIRMED marker in the research.

**Phase 4 — FxRegistry + WebSocket.** REST bootstrap, WebSocket connect, composition parse, registry build, slot pinning with `fx_pins.csv` persistence, narrow subscriptions, the ramp engine, and the WS half of `ResolumeOut`.
*Accept, in this order:*
1. Three copies of Goo on layer 1 occupy three distinct pads, all working independently.
2. Renaming the third in Resolume changes only the mirror UI label — its pad does not move.
3. Reordering the chain moves nothing on the surface.
4. Adding an effect at the **top** of a chain mid-run puts it on the next free pad and moves nothing already lit.
5. Deleting an effect darkens its pad; re-adding it within `fx_pin_ttl_s` returns it to the same pad.
6. Restarting TD restores every pad to its previous position from `fx_pins.csv`.
7. Deleting `fx_pins.csv` and restarting produces a clean chain-order layout.
8. Tap = ramp to on_value over 120 ms; hold = momentary stab; Shift+pad = hard bypass; Select+pad captures the current opacity.
9. Deck switch rebuilds the registry and redraws.
10. Ten rapid edits in Resolume produce **one** rebuild, not ten.

**Phase 4b — optional, deep effect parameters.** `Shift`+`Device` param bank on encoders 5–8. Cut this first if time is short; nothing depends on it.

**Phase 5 — robustness and platform matrix.** Panic, `Shift`+`Stop` rescan, `User` release/take, delayed-quit shutdown, health strip with per-target registry counts, reconnect logic, startup validation gates.
*Accept:* the matrix — macOS Apple Silicon, macOS Intel, Windows 11 — each with Resolume local and Resolume on a second machine. Cold start, mid-show Push unplug, mid-show Resolume restart, mid-show TD restart, mid-show webserver toggled off (FX pads must go dark and everything else must keep working). Nothing in Resolume jumps on a TD restart, because TD adopts state.

**Phase 6 — display graphics. Built 2026-09-09 (macOS).** Implemented as a **separate helper process** (`display/push2_display_helper.py`) that owns libusb, talked to over a persistent local **TCP** connection (not UDP -- a 960x160 RGB565 frame is ~300KB, over UDP's datagram cap it would need manual chunking for no benefit on loopback). Never linked libusb into the TD process; surface logic (Phases 0-5) never depends on the display existing.

- 6a: raw USB protocol (header/RGB565/XOR/chunked writes), confirmed against physical hardware. Driver specs in `README.md`.
- 6b: TD<->helper TCP transport, subprocess lifecycle (`exec_boot`/`CloseProject`), health strip "display" row.
- 6c: live Spout/Syphon visual preview (`syphonspoutin2` -> `fit_display` -> `null_display`), 30Hz, no measurable performance regression.
- 6d: `Layout` button (CC31, previously reserved) toggles the screen between the visual preview and a text/UI mode -- 8 encoder-label segments (mirrors `Surface.Resolve()`, so it always agrees with what the encoder actually does) plus a status strip (grid mode, focus, armed, FX counts per target).
- 6e: helper crash or USB-level failure closes the TCP connection (helper-side), which TD detects via `onClose` and recovers automatically (relaunch if the process died, reconnect if it's still alive) -- no manual intervention, no TD-side crash.

**Windows stays a stub** (`_WindowsStub` in the helper) -- a real WinUSB/Zadig backend is deferred until there's a Windows test machine and a decision on the Ableton Live driver-conflict tradeoff (`README.md`). MIDI/LED/pad control is unaffected either way.

**Operational gotcha discovered during this build, not specific to the display feature**: manually pulling `reinitextensions.pulse()` and then calling a heavy extension method shortly after, both via MCP, crashed TD outright (twice). See T15/T16 in the pitfall register below.

---

## 10. Files in this handoff

| File | Read/write | Contents |
|---|---|---|
| `DESIGN.md` | — | This document |
| `config/map_controls.csv` | read-only | 423 rows. Every Push control, in every mode, with modifier, action, target, **transport**, control path, value type, LED state source and palette. All 64 pads covered exactly once in each grid mode. |
| `config/map_palette.csv` | read-only | The 28-entry custom palette written over SysEx `03`, with R/G/B/W per index. |
| `config/cfg_general.csv` | read-only | All tunables: IPs, ports, layer indices, rates, caps, dead-band, encoder feel, FX fade/momentary/pin behaviour, device names per platform, dry-run and release-on-exit flags. |
| `config/map_sysex.csv` | read-only | Every SysEx message used, with command id, byte sequence and when to send it. |
| `config/fx_pins.example.csv` | **written by TD** | Shape reference for the pin cache TD maintains at `config/fx_pins.csv`. Shows the three-Goo case. **No human edits this.** Delete the real file to reset pad positions. |
| `verify.py` | — | 22-check validation script. Run after any CSV edit. |

Note what is *not* in this list: any file describing effects. That is the point.

### Verification already run

```
map_controls.csv                        423 rows
duplicate (type, number, modifier, mode) none
ANY-mode vs grid-mode clashes           none
controls not in Ableton's Push2-map     none
grid_mode / transport vocabularies      closed
palette mismatches (RGB vs white-only)  none
SESSION pads                            64 unique, covers notes 36-99
FX      pads                            64 unique, covers notes 36-99
OSC paths well formed                   none bad
WS paths are parameter-by-id templates  none bad
whitespace-padded control paths         none
OSC triggers/toggles not typed int      none
WS booleans not marked bool_as_int      none
deliberate float triggers               tempomultiplytwo, tempodividetwo (Resolume type bug)
FX pad slots in 1-16                    ok
FX grid = 4 targets x 16 unique pads     ok
palette indices unique, values in range ok
pin keys / (target, slot) unique        ok
pin key format target|name|ordinal      ok
config values coherent                  ok

transport osc 169   ws 136   internal 92   context 4   none 22
```

The pin checks deliberately allow duplicate effect *names* while rejecting duplicate pin *keys* — that distinction is the fix for the earlier draft's mistake, encoded as a test.

### Confirm on first contact with hardware — Phase 3a

Six things rest on facts the source documents do not state outright. Five are cheap to settle and are gated as **Phase 3a** in the build order. Do not skip it.

**Push 2**

1. **Encoder delta encoding.** `0x01–0x3F` positive, `0x7F–0x41` negative is the near-universal Push 2 convention but is not spelled out in the interface manual. Verify with a MIDI monitor; the decode is isolated in one function so the convention can be flipped in one place.
2. **Windows User Port name.** `MIDIIN2 (Ableton Push 2)` / `MIDIOUT2 (Ableton Push 2)` follows the manual's table, but Windows appends or truncates indices. Match by prefix, and print the enumerated list on first run.
3. **Mode SysEx persistence.** Assumed non-persistent, which is the safe assumption. If it turns out to persist, nothing breaks — the startup re-send is idempotent.

**Resolume 7.15** — settle all four with one composition: add Goo three times to layer 1, rename the third, then `GET /api/v1/composition`.

4. **The opacity key inside `mixer`.** The schema declares `mixer` as an unstructured map. Resolve by walking it; log which rule matched. Getting this wrong makes every FX pad silently inert.
5. **Opacity `min`/`max`.** Expected `0–100`, not `0–1`. Read it from the discovered parameter. Getting this wrong makes every FX pad look like it "barely does anything".
6. **Whether `displayName` exists on 7.15.** Older schema snapshots have only `name`. Registry must fall back to `name`. UI labels only — never addressing.

Also worth recording in the same pass, purely as documentation: what the three Goo instances' `name` values actually are (`Goo`/`Goo2`/`Goo3`? `Goo` three times?). **Nothing in the design depends on the answer** — the pin ordinal handles either — but knowing it will save the next person an hour.

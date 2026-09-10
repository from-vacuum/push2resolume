# Push2Resolume

## Environment Setup

With Python 3.11+ and `uv` on PATH, run:

```sh
# macOS
python3 tools/bootstrap_env.py
# Windows
python tools/bootstrap_env.py
```

The script selects `.venvs/macos-arm64`, `.venvs/macos-x86_64`,
`.venvs/windows-amd64`, or `.venvs/windows-arm64` using the running Python's
platform/architecture. It creates the environment with that Python, installs
`requirements.txt`, checks dependencies and imports, and prints the interpreter
path. No activation is required. Rerunning installs missing dependencies without
replacing the existing environment or removing extra packages.

Use `--dry-run` to preview commands. Project paths are resolved relative to the
script, so it also works when invoked by absolute path from another directory.
It does not modify `.toe` files or install native USB drivers/libusb. Use the
printed path for the matching `display_helper_python_*` TD setting; a copied
saved project may still contain an older embedded interpreter setting.

## Current Surface: Seven Layers + Composition

Session has seven clip rows (L7 at the top, L1 above the bottom row) and a
bottom row of column launches. Each bank has eight clips; 16 banks retain
access to positions1-128. Left/right changes banks; the right column selects
within the current group of eight banks.

In FX mode, columns are L1-L7 and Composition. Left/right or the first two
right-column buttons select slots1-8 or9-16. Session toggles the grid mode.
Lower buttons select targets; upper buttons clear, with Shift for solo (last
button: disconnect all / Shift tempo resync). Mute controls Composition, or the target
whose lower button is held. Shift+right-column selects decks1-8; up/down reaches
all decks.

Session encoders control all eight opacities. Mix toggles to per-target
Dashboard link1 (Shift: link2). Shift on the opacity page controls the playing
clip's speed in each layer, and Composition speed on encoder8. Speed is inert
without an active clip. FX encoders control the focused target's Dashboard
links1-8. Select applies fine adjustment to the active encoder parameter.
Shift + a lower layer-select button resets that layer's active clip speed to
1.00x; Shift + the lower Composition button resets Composition speed. This
works in both grid modes, preserves focus, and is inert without a valid speed
parameter. Ordinary lower-button presses still select their targets.
Speed reset uses Resolume's native WebSocket reset, not normalized OSC (speed
uses a nonlinear OSC curve). The LCD reflects the subsequent API readback.

Resets escalate in two tiers, both on **Device** (cc110); `Stop` (cc29) is
deliberately unmapped and dark.

| Gesture | Tier | Does | Preserves |
|---|---|---|---|
| `Device` | soft | Re-read authoritative state from Resolume, repaint LEDs and LCD. Disarmed during the read; a failed read warns and stays disarmed until fresh state arrives. | View, layer bindings, captured FX values |
| `Shift`+`Device` | hard | Drop the layer identity bindings, then pulse `Refresh`: extensions rebuilt, Push re-initialized, LCD helper restarted, WebSocket reconnected, FX registry rebuilt. | FX pad pins (delete `config/fx_pins.csv` to reset those) |

The hard tier defers its Refresh pulse by one frame, because Refresh calls
`initializeExtensions()` and that must never run with the extension's own method
still on the call stack. `op('/project1/PUSH_RESOLUME').HardReset()` and
`.Rebind()` are the software equivalents, so neither tier depends on a connected
Push. The `surface_panic` and `fx_registry_rescan` actions still exist in the
vocabulary if you want to remap `Stop` to one of them in
`config/map_controls.csv`.

Device resyncs state from Resolume and forces a full LED/LCD repaint. Pending
writes and temporary encoder/FX feedback are discarded; mode, focus, pages,
layer identity bindings and captured FX values stay intact. Controls are
disarmed during the read. Failed reads show a warning and remain disarmed until
fresh state arrives.

Layer identity bindings follow running Resolume. Bindings record which layer id
each configured index resolved to, and they are saved in the `.toe` — so they
outlive the composition they describe: a file moved between machines, or a
composition reloaded after layers were added, arrives holding identities that no
longer exist. `layer_binding_mode` (`config/cfg_general.csv`, default `adopt`)
governs what happens then. On `adopt`, a mismatch takes the live identities,
drops the now-meaningless optimistic/encoder feedback and queued writes, and
flashes `RE-BOUND` on the LCD for 20 s (`binding_notice` in `ui/mirror_state`,
`bindingNotice` in the overlay snapshot and the Refresh report) — the surface
stays armed. Moving a `.toe` between machines therefore needs no ceremony.

`layer_binding_mode=strict` restores the previous blocking alarm: `Layer
identities changed` on the LCD, disarmed until an explicit rebind. Even then it
only fires for a change **within** the composition the bindings were taken
from — bindings from a different composition, or saved before provenance was
recorded, are always adopted, because they describe layers that are not on
screen at all. Provenance is the composition **name** (`composition` in
`ui/mirror_state`), not a parameter id, since whether ids survive a composition
save/reload is undocumented (DESIGN.md R21).

`Shift`+`Device` is the explicit rebind, and
`op('/project1/PUSH_RESOLUME').Rebind()` does the same from the Textport or
Envoy, so rebinding never depends on a connected Push.

For full recovery, pulse `Refresh` on `/project1/PUSH_RESOLUME` (or call
`op('/project1/PUSH_RESOLUME').Refresh()` in the Textport). This rebuilds the
extensions and helpers, reinitializes Push, restarts the LCD helper, reconnects
Resolume, and replaces cached state and LED feedback. View, focus, pages and
FX pins are preserved. The Textport prints progress, individual checks and
`SUCCESS` or `FAILED`; connection checks wait up to roughly eight seconds.
Push status confirms MIDI binding and the mode command, not a hardware ACK.
The last result is available via the component's `refresh_status` storage.

LCD startup explicitly closes the saved TCP client before reconnecting on a
later frame. Helper paths are resolved relative to the project folder, and
shutdown cancels pending reconnects so closing the project cannot respawn it.
If MIDI output fails, the controller marks Push disconnected and stops LED
writes instead of raising an error every tick. Reconnect the device and pulse
Refresh to retry initialization. LCD backend failures are throttled, and the
TCP client is disabled between delayed reconnect attempts.

Text LCD mode shows target names, encoder labels/values, clip playback, loaded
slot counts, effect lists with opacity/bypass state, bank/page, focus, deck, BPM
and master. Layout switches text/preview. Open
[push2_live_overlay_v2.html](push2_live_overlay_v2.html) directly while TD is
running for the live surface, LCD image and control inspector. State is served
by TD on port9871. The original overlay redirects to v2.

Editable embedded-DAT source is mirrored under `td/`. These files require an
explicit Envoy update; they are not automatically externalized by Embody.
`tools/generate_layout7.py` regenerates repeated CSV mappings while preserving
other rig controls. `tools/build_deploy.py` prepares the Envoy source/config
update. Never edit `externalizations.tsv` manually.

Checks: `.venvs/macos-arm64/bin/python3 verify.py` and
`.venvs/macos-arm64/bin/python3 -m unittest discover -s tests -v`.
See [LAYOUT_7_PLUS_COMP_PLAN.md](LAYOUT_7_PLUS_COMP_PLAN.md) for the migration
record. The old three-layer design below the current-revision note in
DESIGN.md is historical. FX toggles are immediate; Select+pad captures current
opacity. Fade ramps and hold-to-stab gestures remain out of scope.
Capturing an off effect leaves its previous activation level unchanged;
legacy zero activation levels are repaired to the configured default.
FX LED/LCD feedback updates immediately. Resolume set acknowledgements can
contain the previous value, so state verification uses delayed GET readbacks
rather than those acknowledgements.

Ableton Push 2 → TouchDesigner → Resolume Arena controller surface. See `DESIGN.md` for the full architecture, control mapping, and build order; `PHASE3A_FINDINGS.md` for live-hardware findings that corrected the original design's assumptions.

## Push 2 Display Driver

The 960×160 screen is **not MIDI** — it is a vendor-specific USB bulk endpoint, separate from the MIDI interface used for pads/encoders/LEDs. Per `DESIGN.md` §1/§9, display support is implemented as a **separate helper process** (`display/push2_display_helper.py`) that owns this USB endpoint, so a USB problem — or the Windows driver issue below — can never affect the live MIDI/LED/OSC/WebSocket rig.

### USB identity (confirmed against live hardware 2026-09-09)

| | |
|---|---|
| Vendor ID | `0x2982` |
| Product ID | `0x1967` |
| Interface | `0` (Vendor Specific, "Push 2 Display") |
| Endpoint | `0x01`, Bulk OUT, 512-byte max packet |
| Library | libusb-1.0, via `pyusb` — Homebrew libusb on macOS, WinUSB + TD's bundled `libusb-1.0.dll` on Windows |

**The interface must be explicitly claimed** (`usb.util.claim_interface`). A bulk write that reports full success (no exception, correct byte count) without an explicit claim silently never reaches the screen — confirmed against physical hardware. The frame header must be written as its own bulk transfer, separate from the (chunked) pixel data.

### Frame format

Each frame = a 16-byte header, followed by 160 lines × 2048 bytes of pixel data (total 327,680 bytes), sent as bulk OUT transfers (typically chunked in ~16KB buffers per the manual, for transfer efficiency).

**Header** (fixed):
```
FF CC AA 88  00 00 00 00  00 00 00 00  00 00 00 00
```

**Pixel data**: 160 lines, topmost first, leftmost pixel first per line. Each line is 2048 bytes = 1920 bytes of pixel data (960 pixels × 2 bytes) + 128 filler bytes (avoids a line boundary falling inside a 512-byte USB buffer).

**Pixel encoding** — 16-bit RGB565, little-endian on the wire:

| bit | 15-11 | 10-5 | 4-0 |
|---|---|---|---|
| field | B (5 bits) | G (6 bits) | R (5 bits) |

**XOR obfuscation** — before sending, every line buffer (all 2048 bytes, including filler) is XORed with the repeating 4-byte pattern `E7 F3 E7 FF` (byte 0 XOR `0xE7`, byte 1 XOR `0xF3`, byte 2 XOR `0xE7`, byte 3 XOR `0xFF`, repeating).

**Timing**: 60fps target. Frames are double-buffered; a late frame repeats the previous one. No frame within 2 seconds → display goes black.

Source: [Ableton's Push 2 MIDI and Display Interface Manual](https://github.com/Ableton/push-interface) rev 1.1, cross-checked against a live device descriptor dump.

### Windows

The Windows backend is **live** (`_WindowsBackend` in `push2_display_helper.py`), driving the screen through the **WinUSB driver bound to interface 0**. Confirmed against physical hardware on 2026-09-09: 30 fps sustained, 9.8 MB/s, no dropped transfers.

Three Windows-specific things, each of which fails *silently* if wrong:

1. **WinUSB must be bound to interface 0**, normally via [Zadig](https://zadig.akeo.ie/) (select the composite child "Push 2 Display" / `MI_00`, install WinUSB). Verify with:
   ```
   powershell "Get-PnpDevice | ? InstanceId -like '*VID_2982*' | fl Status,Class,FriendlyName,InstanceId"
   ```
   The display child should read `Class: USBDevice` (the WinUSB setup class); its `DEVPKEY_Device_Service` should be `WinUSB`. **Interface 1 (`MI_01`, `Class: MEDIA`) is the MIDI side and must be left alone** — rebinding that would kill pads, encoders and LEDs.
2. **`libusb-1.0.dll` must be handed over explicitly.** On Windows `ctypes.util.find_library()` does *not* search `PATH`, so pyusb's default lookup returns **no backend** even with the DLL one folder away — the symptom is "No backend available", which reads like a driver problem but isn't. TouchDesigner ships the DLL in its own `bin` folder, so no separate libusb install is needed: `mod_display.StartHelper` passes the live `app.binFolder` as `PUSH2_LIBUSB_DIR` (config key `display_helper_libusb_dir_win32` overrides). Deriving it from the running TD keeps it correct across TD upgrades, which a pinned `TouchDesigner.2025.32820` path would not.
3. **`SET_CONFIGURATION` is refused** on a composite device where WinUSB owns only one interface. The config is already active, so the helper logs and continues on Windows; on macOS the call must still succeed.

**Ableton Live coexistence:** the WinUSB binding replaces whatever driver Windows had on interface 0, so Live cannot drive the Push 2 screen while it is in place — reverting the binding in Device Manager hands the screen back. MIDI is unaffected either way. Only one process may hold the display at a time: the helper claims the interface exclusively, and a second claim fails with `[Errno 13] Access denied`.

**Spout vs Syphon sender names:** Arena publishes `Arena - Composition` / `Arena - Preview` through Spout on Windows, but `Arena:Composition` / `Arena:Preview` through Syphon on macOS. A name hardcoded for one platform yields a silent 128×128 black placeholder on the other — no error on the TOP. `Display.EnsureTextureSources()` resolves this at every `StartHelper` by matching the role suffix against the live sender list, which also survives an Arena rename. Arena started *after* TouchDesigner therefore needs one Refresh pulse to pick up its senders.

### Running the helper standalone

```sh
# macOS
DYLD_LIBRARY_PATH=/opt/homebrew/opt/libusb/lib .venvs/macos-arm64/bin/python3 display/push2_display_helper.py
# Windows (PUSH2_LIBUSB_DIR is optional -- the helper globs Derivative installs as a fallback)
.venvs/windows-amd64/Scripts/python.exe display/push2_display_helper.py
```

Requires `pyusb` (installed by `tools/bootstrap_env.py`) plus libusb — `brew install libusb` on macOS, TD's bundled DLL on Windows. Sends a solid red test frame, then (on Enter) an 8-bar color gradient — for confirming the physical display path independent of TouchDesigner. Add `--stub` to exercise the TCP half with no Push 2 attached; the stub is never selected automatically, so a real backend failure surfaces as an error rather than a dark screen.

Note the display blanks itself if no frame arrives within 2 seconds, so a single one-shot frame flashes and vanishes — stream to watch it.

The existing macOS environment lives in `.venvs/macos-arm64`. The `.venv`
symlink is a compatibility alias for older saved TD projects and commands,
not a second environment. Both paths are ignored by version control. Create
a separate environment on Windows; do not transfer this macOS environment.

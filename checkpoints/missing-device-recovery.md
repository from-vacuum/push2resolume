# Missing-Device Recovery

- Investigated after Windows backend commit `9e1c842` was pulled onto macOS.
  The saved controller DAT sources matched the files under `td/`.
- USB lookup initially found no Push 2. The helper repeatedly accepted and
  closed connections after backend initialization failed. Added one-second
  helper-side backoff (outside TD) and disabled TD's TCP client on close,
  with one pending delayed reconnect instead of repeated callbacks.
- User supplied the repeated `exec_tick -> FlushLeds -> _writeLed` traceback:
  `td.tdError: Cannot communicate with the MIDI device.`
- MIDI output now handles failures at the transport boundary, invalidates
  cached LEDs, clears Bound/PushMode, and reports the error once. Subsequent
  ticks skip writes until Boot/Refresh/device-change initialization retries.
  SysEx initialization and shutdown also handle a missing device without
  repeated exceptions. Successful initialization clears the error/cache.
- WinUSB implementation and mappings preserved. Corrected a Windows-path
  test fixture so the suite also runs on macOS.
- 70 tests passed, including 100 missing-device LED ticks with exactly one
  native write attempt and one diagnostic, and successful reconnect/redraw.
  Mapping verification passed.
- Live verification: Envoy responsive, 59-60 fps, zero TD cook errors,
  bounded delayed callbacks, no queued LEDs. Remaining warnings concerned
  unavailable MIDI and the Non-Commercial TOP resolution limit.
- Saved LCD guard checkpoint `.69.toe` and MIDI guard checkpoint `.70.toe`.
  Physical unplug/replug was not controlled by tests.
- The Windows-saved layer binding placed the current Mac layer 1 ID at layer
  5, so the identity guard correctly disarmed sending and blocked FX mapping.
  Explicitly rebound to the current seven-layer BM_2026 order without firing
  clips or effects: all health checks green, armed, 37 FX mapped. Refresh now
  reports the exact binding error and Shift+Stop recovery instruction.
- Final checkpoint: `Push2Resolume.71.toe`. User physically confirmed it works.

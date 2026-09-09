# Startup and Refresh Recovery

- Before: Resolume healthy, Push mode flag false, LCD helper alive but TD's
  connection flag false. Boot restored Push; a delayed TCP reconnect restored
  LCD feedback. An off/on toggle within the same frame did not restore it.
- Startup now resolves helper paths from the project folder, re-arms stale
  sockets on a later frame, cancels reconnects on shutdown, and invalidates
  LED caches. Early boot waits for helper initialization. Push health follows
  the current mode rather than the last boot snapshot.
- The user-created Refresh pulse is wired through `logic/parexec_refresh`.
  It rebuilds extensions, stops/restarts the helper, reconnects Resolume,
  requests authoritative state and prints per-system Textport results.
- Live pulse verified: all six helper instances replaced, helper PID changed,
  view/focus preserved, all eight recovery checks passed, 37 FX mapped.
- Simulated startup with a stale LCD connection flag also recovered. Final
  state: all health checks green, armed, 137 LED cache entries, zero queued LEDs.
- All four deployed DAT sources match disk; zero TD errors or warnings.
- 48 unit tests and `verify.py` mapping checks passed. Windows hardware was
  not tested during this change.
- User cold-reopened `.66.toe`: connections recovered, but the saved Session
  bank 8 was empty. Banks 1-4 contained clips. Switched the view to bank 1
  without triggering clips and resent 60 lit-pad states. User confirmed that
  the physical pads lit and everything worked.
- Wiring checkpoint: `Push2Resolume.65.toe`; recovery checkpoint: `.66.toe`;
  final verified populated-bank checkpoint: `Push2Resolume.67.toe`.

Machine-readable captures: `startup-before.json`, `startup-refresh-verified.json`.

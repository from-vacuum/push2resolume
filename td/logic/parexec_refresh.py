"""Refresh pulse: rebuild extensions, reconnect hardware, then report health."""

import time
import traceback


def onPulse(par):
    par.owner.Refresh()


_PUSH_MIDI = ('midi/midiin1', 'midi/midiout1')


def _setPushMidiActive(root, state):
    """Bounce the Push MIDI ports so Refresh drops a stale or half-open endpoint
    and re-opens it, instead of rebuilding everything around a dead device.

    Restored on EVERY exit path, including failure: PushIO.BindDevice() re-arms
    midiin1 but never touches midiout1, so a Refresh that died between the two
    would leave pads, encoders and LEDs silently dark with no error anywhere.
    The bounce also finishes before Boot(), so it never overlaps SetMode()'s own
    deactivate/reactivate cycle -- that one guards a device re-enumeration race
    that has been observed to crash TD.
    """
    for path in _PUSH_MIDI:
        o = root.op(path)
        if o is not None and hasattr(o.par, 'active'):
            o.par.active = state


def _current(root, token):
    return root.fetch('refresh_status', {}, search=False).get('token') == token


def _fail(root, token, error):
    try:
        _setPushMidiActive(root, 1)
    except Exception:
        pass
    if not _current(root, token):
        return
    root.store('refresh_status', dict(token=token, state='failed', error=str(error)))
    print('[Push Refresh] FAILED: ' + str(error))


def refresh(root):
    previous = root.fetch('refresh_status', {}, search=False)
    if previous.get('state') == 'running' and time.time() - previous.get('started', 0) < 30:
        print('[Push Refresh] Already running.')
        return
    token = time.time_ns()
    root.store('refresh_status', dict(token=token, started=time.time(), state='running'))
    print('[Push Refresh] Starting: rebuild extensions, initialize Push, reconnect LCD and Resolume.')
    try:
        root.ext.PushResolume.Armed = False
        if root.ext.PushResolume.ResolumeOut:
            root.ext.PushResolume.ResolumeOut.ClearPending()
        if root.ext.PushResolume.Display:
            root.ext.PushResolume.Display.StopHelper()
        root.op('net/ws1').par.active = 0
        _setPushMidiActive(root, 0)
        root.initializeExtensions()
        run("args[0].op('logic/parexec_refresh').module._finish(args[0], args[1])",
            root, token, delayFrames=15)
    except Exception:
        _fail(root, token, traceback.format_exc())


def _finish(root, token, attempt=0):
    if not _current(root, token):
        return
    try:
        # Re-open the ports before anything can bail out below, and before
        # Boot() binds the device.
        _setPushMidiActive(root, 1)
        ready = all(getattr(root.ext.PushResolume, name) is not None for name in
                    ('Surface', 'PushIO', 'ResolumeOut', 'ResolumeState', 'FxRegistry', 'Display'))
        if not ready:
            if attempt >= 10:
                raise RuntimeError('Extensions did not initialize.')
            run("args[0].op('logic/parexec_refresh').module._finish(args[0], args[1], args[2])",
                root, token, attempt + 1, delayFrames=15)
            return
        root.ext.PushResolume.Boot()
        root.ext.PushResolume.Resync()
        print('[Push Refresh] Extensions rebuilt; Push initialization sent. Waiting for feedback...')
        run("args[0].op('logic/parexec_refresh').module._report(args[0], args[1])",
            root, token, delayMilliSeconds=1000)
    except Exception:
        _fail(root, token, traceback.format_exc())


def _report(root, token, attempt=0):
    if not _current(root, token):
        return
    try:
        root.ext.PushResolume.CheckHealth()
        health = dict(root.ext.PushResolume.Health)
        checks = {
            'Push MIDI bound': health.get('push_bound', False),
            'Push User mode command sent': health.get('push_mode', False),
            'LCD helper process': root.ext.PushResolume.Display.IsHelperAlive(),
            'LCD TCP connected': health.get('display', False),
            'Resolume state fresh': health.get('resolume_state', False),
            'Layer mappings': health.get('layers_ok', False),
            'Controller armed': root.ext.PushResolume.Armed,
        }
        if root.ext.PushResolume.PushIO.Cfg('state_source', 'websocket') == 'websocket':
            checks['Resolume WebSocket'] = health.get('websocket', False)
        success = all(checks.values())
        if not success and attempt < 7:
            run("args[0].op('logic/parexec_refresh').module._report(args[0], args[1], args[2])",
                root, token, attempt + 1, delayMilliSeconds=1000)
            return
        count = len(root.ext.PushResolume.FxRegistry.Registry)
        binding_error = root.ext.PushResolume.ResolumeState.BindingError if not checks['Layer mappings'] else ''
        notice = root.ext.PushResolume.ResolumeState.Notice()
        root.store('refresh_status', dict(token=token, state='success' if success else 'failed',
                                        checks=checks, effects=count, bindingError=binding_error,
                                        bindingNotice=notice))
        for name, ok in checks.items():
            print('[Push Refresh] %s: %s' % (name, 'OK' if ok else 'FAILED'))
        if binding_error:
            print('[Push Refresh] Layer mappings: ' + binding_error)
        if notice:
            print('[Push Refresh] Layer mappings: ' + notice)
        print('[Push Refresh] %s | %d FX mapped' % ('SUCCESS' if success else 'FAILED', count))
    except Exception:
        _fail(root, token, traceback.format_exc())

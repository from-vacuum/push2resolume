"""Refresh pulse: rebuild extensions, reconnect hardware, then report health."""

import time
import traceback


def onPulse(par):
    par.owner.Refresh()


def _current(root, token):
    return root.fetch('refresh_status', {}, search=False).get('token') == token


def _fail(root, token, error):
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
        root.initializeExtensions()
        run("args[0].op('logic/parexec_refresh').module._finish(args[0], args[1])",
            root, token, delayFrames=15)
    except Exception:
        _fail(root, token, traceback.format_exc())


def _finish(root, token, attempt=0):
    if not _current(root, token):
        return
    try:
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
        root.store('refresh_status', dict(token=token, state='success' if success else 'failed',
                                        checks=checks, effects=count))
        for name, ok in checks.items():
            print('[Push Refresh] %s: %s' % (name, 'OK' if ok else 'FAILED'))
        print('[Push Refresh] %s | %d FX mapped' % ('SUCCESS' if success else 'FAILED', count))
    except Exception:
        _fail(root, token, traceback.format_exc())

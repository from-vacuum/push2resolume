import ast
import os
from pathlib import Path
import runpy
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.run = Mock()
        self.net = SimpleNamespace(par=SimpleNamespace(active=1))
        self.owner = Mock()
        self.owner.op.return_value = self.net
        self.owner.fetch.return_value = {}
        # Exercise lifecycle without importing TD's NumPy/OpenCV renderer.
        tree = ast.parse((ROOT / 'td/display/mod_display.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Display')
        self.globals = dict(os=os, sys=sys, subprocess=subprocess, run=self.run,
                            project=SimpleNamespace(folder=str(ROOT)), debug=Mock())
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<Display>', 'exec'), self.globals)
        self.display = self.globals['Display'](self.owner)
        self.display.Cfg = lambda key, default=None, cast=str: {
            'display_helper_python_darwin': '.venvs/macos-arm64/bin/python3',
            'display_helper_python_win32': '.venvs/windows-amd64/Scripts/python.exe',
        }.get(key, default)

    def test_helper_paths_are_project_relative_and_tcp_is_rearmed(self):
        process = Mock()
        process.poll.return_value = None
        with patch.object(subprocess, 'Popen', return_value=process) as popen:
            self.display.StartHelper()
        args, kwargs = popen.call_args
        self.assertTrue(os.path.isabs(args[0][0]))
        self.assertEqual(args[0][1], str(ROOT / 'display/push2_display_helper.py'))
        self.assertEqual(kwargs['cwd'], str(ROOT))
        self.assertEqual(self.net.par.active, 0)
        self.assertEqual(self.run.call_args.kwargs['delayFrames'], 30)
        self.display._connect(self.display._connectGeneration)
        self.assertEqual(self.net.par.active, 1)

    def test_running_helper_with_stale_socket_reconnects_without_new_process(self):
        self.display.process = Mock()
        self.display.process.poll.return_value = None
        with patch.object(subprocess, 'Popen') as popen:
            self.display.StartHelper()
        popen.assert_not_called()
        self.assertEqual(self.net.par.active, 0)
        self.run.assert_called_once()

    def test_stop_cancels_delayed_reconnect_and_close_does_not_respawn(self):
        self.display.process = Mock()
        self.display.process.poll.return_value = None
        self.display._queueConnect()
        generation = self.display._connectGeneration
        self.display.StopHelper()
        self.run.reset_mock()
        self.display.OnClose()
        self.display._attemptReconnect()
        self.display._connect(generation)
        self.run.assert_not_called()
        self.assertEqual(self.net.par.active, 0)
        self.assertIsNone(self.display.process)

    def test_old_connect_callback_cannot_override_newer_request(self):
        self.display.process = Mock()
        self.display.process.poll.return_value = None
        self.display._queueConnect()
        old = self.display._connectGeneration
        self.display._queueConnect()
        self.display._connect(old)
        self.assertEqual(self.net.par.active, 0)

    def test_boot_waits_for_helpers_and_invalidates_led_cache(self):
        module = runpy.run_path(str(ROOT / 'td/logic/ext_PushResolume.py'))
        ext = module['PushResolumeExt'](self.owner)
        ext.Boot()
        self.assertTrue(ext._bootPending)
        ext.PushIO = Mock(Bound=True, PushMode=True)
        ext.PushIO.Cfg.return_value = 'websocket'
        ext.ResolumeState = Mock()
        ext.Display = Mock()
        ext.CheckHealth = Mock()
        ext.FullRedraw = Mock()
        ext.Boot()
        self.assertFalse(ext._bootPending)
        ext.PushIO.Boot.assert_called_once()
        ext.PushIO.InvalidateLeds.assert_called_once()
        ext.Display.StartHelper.assert_called_once()

    def test_health_follows_current_push_mode(self):
        module = runpy.run_path(str(ROOT / 'td/logic/ext_PushResolume.py'))
        owner = Mock()
        owner.op.return_value = None
        ext = module['PushResolumeExt'](owner)
        ext.PushIO = SimpleNamespace(Bound=True, PushMode=True)
        ext.ResolumeState = SimpleNamespace(LayerIdsOK=lambda: True, Fresh=lambda: True,
                                           Connected=True, Syncing=False)
        ext.CheckHealth()
        self.assertTrue(ext.Armed)
        ext.PushIO.PushMode = False
        ext.CheckHealth()
        self.assertFalse(ext.Armed)


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.run = Mock()
        self.module = runpy.run_path(str(ROOT / 'td/logic/parexec_refresh.py'),
                                    init_globals={'run': self.run})
        self.storage = {}
        self.ext = Mock(Armed=True)
        self.ext.Health = {k: True for k in ('push_bound', 'push_mode', 'display',
                                           'resolume_state', 'layers_ok', 'websocket')}
        self.ext.FxRegistry.Registry = {'effect': {}}
        self.ext.PushIO.Cfg.return_value = 'websocket'
        self.ext.Display.IsHelperAlive.return_value = True
        self.root = Mock(ext=SimpleNamespace(PushResolume=self.ext))
        self.root.fetch.side_effect = lambda key, default=None, **kw: self.storage.get(key, default)
        self.root.store.side_effect = lambda key, value: self.storage.__setitem__(key, value)

    def test_refresh_rebuilds_then_reports_success(self):
        with patch('builtins.print') as output:
            self.module['refresh'](self.root)
            token = self.storage['refresh_status']['token']
            self.ext.Display.StopHelper.assert_called_once()
            self.root.initializeExtensions.assert_called_once()
            self.module['refresh'](self.root)
            self.root.initializeExtensions.assert_called_once()
            self.module['_finish'](self.root, token)
            self.ext.Boot.assert_called_once()
            self.ext.Resync.assert_called_once()
            self.ext.Armed = True
            self.module['_report'](self.root, token)
        self.assertEqual(self.storage['refresh_status']['state'], 'success')
        self.assertTrue(any('SUCCESS' in str(c) for c in output.call_args_list))

    def test_reports_missing_lcd_after_timeout(self):
        self.storage['refresh_status'] = {'token': 1}
        self.ext.Health['display'] = False
        with patch('builtins.print') as output:
            self.module['_report'](self.root, 1, 7)
        self.assertEqual(self.storage['refresh_status']['state'], 'failed')
        self.assertTrue(any('LCD TCP connected: FAILED' in str(c) for c in output.call_args_list))

    def test_extension_exception_is_reported(self):
        self.root.initializeExtensions.side_effect = RuntimeError('broken extension')
        with patch('builtins.print'):
            self.module['refresh'](self.root)
        self.assertEqual(self.storage['refresh_status']['state'], 'failed')
        self.assertIn('broken extension', self.storage['refresh_status']['error'])

    def test_stale_completion_cannot_replace_newer_status(self):
        self.storage['refresh_status'] = {'token': 2, 'state': 'running'}
        self.module['_report'](self.root, 1)
        self.assertEqual(self.storage['refresh_status']['state'], 'running')
        self.ext.CheckHealth.assert_not_called()


if __name__ == '__main__':
    unittest.main()

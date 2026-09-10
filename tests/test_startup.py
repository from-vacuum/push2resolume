import ast
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, mock_open, patch

ROOT = Path(__file__).resolve().parents[1]


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.run = Mock()
        self.net = SimpleNamespace(par=SimpleNamespace(active=1))
        # Spout/Syphon In TOPs, publishing the Windows-flavoured sender names.
        self.sources = {
            'display/syphonspoutin1': SimpleNamespace(par=SimpleNamespace(sendername=Mock(
                menuNames=['Arena - Composition', 'Arena - Preview'],
                eval=Mock(return_value='Arena:Preview')))),
            'display/syphonspoutin2': SimpleNamespace(par=SimpleNamespace(sendername=Mock(
                menuNames=['Arena - Composition', 'Arena - Preview'],
                eval=Mock(return_value='Arena:Composition')))),
        }
        self.owner = Mock()
        self.owner.op.side_effect = lambda path: self.sources.get(path, self.net)
        self.owner.fetch.return_value = {}
        # Exercise lifecycle without importing TD's NumPy/OpenCV renderer.
        # Module-level Assigns come along so constants stay in sync with the
        # source (a stub numpy satisfies the one that builds an array); the
        # Import nodes are deliberately left out.
        tree = ast.parse((ROOT / 'td/display/mod_display.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Display')
        constants = [n for n in tree.body if isinstance(n, ast.Assign)]
        self.globals = dict(os=os, json=json, sys=sys, subprocess=subprocess, run=self.run,
                            project=SimpleNamespace(folder=str(ROOT)), debug=Mock(),
                            app=SimpleNamespace(binFolder='C:/Program Files/Derivative/TD/bin'),
                            np=Mock())
        exec(compile(ast.Module(body=constants + [node], type_ignores=[]), '<Display>', 'exec'),
             self.globals)
        self.display = self.globals['Display'](self.owner)
        self.display.Cfg = lambda key, default=None, cast=str: {
            'display_helper_python_darwin': '.venvs/macos-arm64/bin/python3',
            'display_helper_python_win32': '.venvs/windows-amd64/Scripts/python.exe',
        }.get(key, default)

    def test_windows_helper_gets_libusb_folder_and_platform_sender_names(self):
        """Windows needs libusb handed over explicitly (ctypes ignores PATH),
        and Spout sender names differ from Syphon's -- both fail silently."""
        process = Mock()
        process.poll.return_value = None
        with patch.object(sys, 'platform', 'win32'):
            with patch.object(subprocess, 'Popen', return_value=process) as popen:
                self.display.StartHelper()
        env = popen.call_args.kwargs['env']
        self.assertEqual(env['PUSH2_LIBUSB_DIR'],
                         os.path.normpath('C:/Program Files/Derivative/TD/bin'))
        self.assertEqual(self.sources['display/syphonspoutin2'].par.sendername.val,
                         'Arena - Composition')
        self.assertEqual(self.sources['display/syphonspoutin1'].par.sendername.val,
                         'Arena - Preview')

    def test_resolved_sender_name_is_left_alone(self):
        for source in self.sources.values():
            source.par.sendername.eval.return_value = 'Arena - Preview'
        self.display.EnsureTextureSources()
        for source in self.sources.values():
            self.assertNotIsInstance(source.par.sendername.val, str)
        self.owner.op.return_value = self.net

    def test_helper_paths_are_project_relative_and_tcp_is_rearmed(self):
        process = Mock()
        process.poll.return_value = None
        with patch.object(subprocess, 'Popen', return_value=process) as popen:
            self.display.StartHelper()
        args, kwargs = popen.call_args
        self.assertTrue(os.path.isabs(args[0][0]))
        self.assertEqual(args[0][1], str(ROOT / 'display/push2_display_helper.py'))
        self.assertEqual(args[0][2:5], ['--serve', '9871', '--parent-pid'])
        self.assertEqual(args[0][5], str(os.getpid()))
        owner_index = args[0].index('--owner-file')
        status_index = args[0].index('--status-file')
        self.assertTrue(args[0][owner_index + 1].endswith(
            '.embody/push2_display_helper_9871.owner.json'))
        self.assertTrue(args[0][status_index + 1].endswith(
            '.embody/push2_display_helper_9871.status.json'))
        self.assertEqual(kwargs['cwd'], str(ROOT))
        self.assertEqual(self.net.par.active, 0)
        self.assertEqual(self.run.call_args.kwargs['delayFrames'], 30)
        self.display._connect(self.display._connectGeneration)
        self.assertEqual(self.net.par.active, 1)

    def test_dead_startup_reports_status_to_textport_and_throttles_retry(self):
        process = Mock(pid=4321)
        process.poll.return_value = 2
        self.display.process = process
        self.display._helperStatusPath = '/tmp/push2-status.json'
        self.display._connectGeneration = 7
        status = json.dumps({'state': 'error', 'pid': 4321,
                             'message': 'LCD port 9872 is already in use'})
        with patch('builtins.open', mock_open(read_data=status)):
            self.display._connect(7)
        self.assertTrue(self.display._reconnectPending)
        self.assertEqual(self.run.call_args.kwargs['delayFrames'], 90)
        self.assertIn('LCD port 9872 is already in use',
                      str(self.globals['debug'].call_args))

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

    def test_disconnect_disables_socket_and_coalesces_retry_callbacks(self):
        self.display.connected = True
        self.display.OnClose()
        self.display.OnClose()
        self.assertFalse(self.display.connected)
        self.assertEqual(self.net.par.active, 0)
        self.run.assert_called_once()
        self.assertEqual(self.run.call_args.kwargs['delayFrames'], 90)
        self.assertTrue(self.display._reconnectPending)
        self.display.process = Mock()
        self.display.process.poll.return_value = None
        self.display._attemptReconnect()
        self.assertFalse(self.display._reconnectPending)
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
        self.ext.ResolumeState.Notice.return_value = ''
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

    def _distinct_ops(self):
        ops = {}
        self.root.op.side_effect = lambda path: ops.setdefault(path, Mock())
        return ops

    def _midi_active(self, ops):
        return [ops[p].par.active for p in ('midi/midiin1', 'midi/midiout1')]

    def test_refresh_bounces_push_midi_ports_and_reopens_them(self):
        ops = self._distinct_ops()
        with patch('builtins.print'):
            self.module['refresh'](self.root)
            token = self.storage['refresh_status']['token']
            self.assertEqual(self._midi_active(ops), [0, 0])
            self.assertEqual(ops['net/ws1'].par.active, 0)
            self.module['_finish'](self.root, token)
        self.assertEqual(self._midi_active(ops), [1, 1])
        self.ext.Boot.assert_called_once()

    def test_midi_ports_reopen_even_when_refresh_fails(self):
        ops = self._distinct_ops()
        self.root.initializeExtensions.side_effect = RuntimeError('broken extension')
        with patch('builtins.print'):
            self.module['refresh'](self.root)
        self.assertEqual(self.storage['refresh_status']['state'], 'failed')
        self.assertEqual(self._midi_active(ops), [1, 1])

    def test_midi_ports_reopen_when_extensions_never_initialize(self):
        ops = self._distinct_ops()
        self.ext.Surface = None
        with patch('builtins.print'):
            self.module['refresh'](self.root)
            token = self.storage['refresh_status']['token']
            self.module['_finish'](self.root, token, 10)
        self.assertEqual(self.storage['refresh_status']['state'], 'failed')
        self.assertEqual(self._midi_active(ops), [1, 1])
        self.ext.Boot.assert_not_called()

    def test_layer_binding_failure_reports_recovery_instruction(self):
        self.storage['refresh_status'] = {'token': 1}
        self.ext.Health['layers_ok'] = False
        reason = 'Layer identities changed; Shift+Stop to rebind'
        self.ext.ResolumeState.BindingError = reason
        with patch('builtins.print') as output:
            self.module['_report'](self.root, 1, 7)
        self.assertEqual(self.storage['refresh_status']['bindingError'], reason)
        self.assertTrue(any(reason in str(c) for c in output.call_args_list))

    def test_layer_rebind_notice_is_reported(self):
        self.storage['refresh_status'] = {'token': 1}
        self.ext.ResolumeState.Notice.return_value = 'Re-bound to composition FV_7Layers'
        with patch('builtins.print') as output:
            self.module['_report'](self.root, 1)
        self.assertEqual(self.storage['refresh_status']['state'], 'success')
        self.assertEqual(self.storage['refresh_status']['bindingNotice'],
                         'Re-bound to composition FV_7Layers')
        self.assertTrue(any('FV_7Layers' in str(c) for c in output.call_args_list))

    def test_stale_completion_cannot_replace_newer_status(self):
        self.storage['refresh_status'] = {'token': 2, 'state': 'running'}
        self.module['_report'](self.root, 1)
        self.assertEqual(self.storage['refresh_status']['state'], 'running')
        self.ext.CheckHealth.assert_not_called()


if __name__ == '__main__':
    unittest.main()

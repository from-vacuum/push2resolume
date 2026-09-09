from pathlib import Path
import runpy
import unittest
from unittest.mock import Mock, patch


class MidiDisconnectTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        module = runpy.run_path(str(root / 'td/logic/mod_pushio.py'),
                               init_globals={'run': Mock()})
        self.midi = Mock()
        owner = Mock()
        owner.op.return_value = self.midi
        self.push = module['PushIO'](owner)
        self.push.Bound = self.push.PushMode = True

    def test_failed_led_write_disarms_once_and_stops_tick_spam(self):
        self.midi.sendNoteOn.side_effect = RuntimeError('Cannot communicate with the MIDI device.')
        with patch('builtins.print') as output:
            for _ in range(100):
                self.push.SetLed('note', 36, 41)
                self.assertEqual(self.push.FlushLeds(), 0)
        output.assert_called_once()
        self.midi.sendNoteOn.assert_called_once()
        self.assertFalse(self.push.Bound)
        self.assertFalse(self.push.PushMode)
        self.assertEqual(self.push._ledCache, {})
        self.assertLessEqual(len(self.push._ledQueue), 1)

    def test_failed_sysex_does_not_claim_user_mode_or_repeat(self):
        self.midi.sendExclusive.side_effect = RuntimeError('Disconnected')
        with patch('builtins.print') as output:
            self.assertFalse(self.push.SetMode('user'))
            self.assertFalse(self.push.SetMode('user'))
        self.midi.sendExclusive.assert_called_once()
        output.assert_called_once()
        self.assertFalse(self.push.PushMode)

    def test_boot_missing_device_returns_failure_without_raising(self):
        self.push.BindDevice = Mock(side_effect=lambda: setattr(self.push, 'Bound', True))
        self.midi.sendExclusive.side_effect = RuntimeError('Disconnected')
        with patch('builtins.print') as output:
            self.assertFalse(self.push.Boot())
            self.assertFalse(self.push.Boot())
        output.assert_called_once()
        self.assertEqual(self.midi.sendExclusive.call_count, 2)
        self.assertFalse(self.push.Bound)

    def test_successful_reboot_restores_writes_and_clears_stale_cache(self):
        with patch('builtins.print'):
            self.push._deviceFailed(RuntimeError('Disconnected'))
        self.push.BindDevice = Mock(side_effect=lambda: setattr(self.push, 'Bound', True))
        for name in ('SetAftertouch', 'SetLedBrightness', 'SetDisplayBrightness',
                     'WritePalette', 'ReapplyPalette', 'SetTouchstrip'):
            setattr(self.push, name, Mock())
        self.push._ledCache[('note', 36)] = 41
        self.assertTrue(self.push.Boot())
        self.assertTrue(self.push.Bound)
        self.assertTrue(self.push.PushMode)
        self.assertEqual(self.push.LastError, '')
        self.push.SetLed('note', 36, 41)
        self.assertEqual(self.push.FlushLeds(), 1)
        self.midi.sendNoteOn.assert_called_once_with(1, 37, 41)


if __name__ == '__main__':
    unittest.main()

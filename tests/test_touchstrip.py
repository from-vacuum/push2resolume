from pathlib import Path
import runpy
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TouchstripTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        helpers = runpy.run_path(str(ROOT / 'tests/test_layout7.py'))
        self.owner = helpers['make_owner'](folder.name)
        self.callback = runpy.run_path(
            str(ROOT / 'td/midi/midiin1_callbacks.py'),
            init_globals={'midiinDAT': object, 'MIDIEvent': object,
                          'parent': types.SimpleNamespace(PushResolume=self.owner)},
        )['onReceiveMIDI']

    def event(self, value):
        return types.SimpleNamespace(
            message='Pitch Bend Change', channel=1, index=None,
            value=value - 8192, value14=None,
            byteData=bytes([0xE0, value & 0x7F, value >> 7]),
        )

    def test_raw_pitchbend_scrubs_selected_clip(self):
        for mode in ('SESSION', 'FX'):
            for modifier in (set(), {'SHIFT'}, {'SELECT'}):
                for value in (0, 4736, 8192, 16383):
                    with self.subTest(mode=mode, modifier=modifier, value=value):
                        self.owner.Surface.GridMode = mode
                        self.owner.Surface.Modifiers = modifier
                        self.owner.ResolumeOut.ClearPending()
                        self.callback(None, self.event(value))
                        self.assertEqual(self.owner.ResolumeOut.FlushOSC(), 1)
                        self.assertEqual(
                            self.owner.nodes['net/oscout1'].messages[-1],
                            ('/composition/selectedclip/transport/position', [value / 16383.0]),
                        )

    def test_unarmed_strip_does_not_send(self):
        self.owner.Armed = False
        self.callback(None, self.event(8192))
        self.assertEqual(self.owner.ResolumeOut.FlushOSC(), 0)
        self.assertEqual(self.owner.nodes['net/oscout1'].messages, [])


if __name__ == '__main__':
    unittest.main()
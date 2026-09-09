"""Display-helper backend selection and libusb resolution.

Hardware-free: these cover the two Windows failures that are SILENT in the
field -- a stub selected by accident (screen dark, no error) and libusb not
being found (pyusb reports 'No backend available', which reads like a driver
problem but is really ctypes not searching PATH on Windows).
"""

import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('push2_display_helper',
                                              ROOT/'display/push2_display_helper.py')
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class BackendSelectionTests(unittest.TestCase):
    def test_force_stub_wins_on_every_platform(self):
        for platform in ('win32', 'darwin'):
            with patch.object(helper.sys, 'platform', platform):
                self.assertIsInstance(helper.make_backend(force_stub=True), helper._StubBackend)

    def test_windows_selects_real_backend_not_stub(self):
        """The regression this replaces: Windows used to return a no-op stub, so
        a dark screen was indistinguishable from a working one."""
        with patch.object(helper.sys, 'platform', 'win32'):
            with patch.object(helper._WindowsBackend, '__init__', lambda self: None):
                backend = helper.make_backend()
        self.assertIsInstance(backend, helper._WindowsBackend)
        self.assertNotIsInstance(backend, helper._StubBackend)

    def test_mac_selects_mac_backend(self):
        with patch.object(helper.sys, 'platform', 'darwin'):
            with patch.object(helper._MacBackend, '__init__', lambda self: None):
                self.assertIsInstance(helper.make_backend(), helper._MacBackend)

    def test_both_real_backends_share_one_usb_implementation(self):
        # send_frame/close must not be duplicated per platform, or the proven
        # macOS transfer sequence and the Windows one can silently diverge.
        for cls in (helper._MacBackend, helper._WindowsBackend):
            self.assertTrue(issubclass(cls, helper._LibUsbBackend))
            self.assertIs(cls.send_frame, helper._LibUsbBackend.send_frame)
            self.assertIs(cls.close, helper._LibUsbBackend.close)


class LibusbResolutionTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop(helper.LIBUSB_DIR_ENV, None)

    def test_env_dir_takes_precedence(self):
        os.environ[helper.LIBUSB_DIR_ENV] = r'C:\explicit'
        with patch.object(helper.os.path, 'isfile', return_value=True):
            self.assertEqual(helper.find_libusb_dll(),
                             os.path.join(r'C:\explicit', helper.LIBUSB_DLL_NAME))

    def test_falls_back_to_newest_touchdesigner_install(self):
        installs = [r'C:\Program Files\Derivative\TouchDesigner.2023.11760\bin\libusb-1.0.dll',
                    r'C:\Program Files\Derivative\TouchDesigner.2025.32820\bin\libusb-1.0.dll']
        with patch.object(helper.glob, 'glob', side_effect=lambda p: installs if 'Program Files\\D' in p else []):
            with patch.object(helper.os.path, 'isfile', return_value=True):
                self.assertIn('2025.32820', helper.find_libusb_dll())

    def test_returns_none_when_nothing_found(self):
        with patch.object(helper.glob, 'glob', return_value=[]):
            with patch.object(helper.os.path, 'isfile', return_value=False):
                self.assertIsNone(helper.find_libusb_dll())

    def test_missing_dll_raises_actionable_error(self):
        with patch.object(helper, 'find_libusb_dll', return_value=None):
            with self.assertRaises(RuntimeError) as caught:
                helper._WindowsBackend._open_library(None)
        self.assertIn(helper.LIBUSB_DIR_ENV, str(caught.exception))

    def test_mac_backend_uses_pyusb_default_search(self):
        self.assertIsNone(helper._MacBackend._open_library(None))


class FrameFormatTests(unittest.TestCase):
    """The frame the backend transmits, per Ableton's interface manual."""

    def test_frame_size_and_header(self):
        frame = helper.solid_color_frame(31, 0, 0)
        self.assertEqual(len(frame), 16 + helper.LINE_COUNT * helper.LINE_TOTAL_BYTES)
        self.assertEqual(frame[:16], helper.FRAME_HEADER)

    def test_every_line_is_xored_including_filler(self):
        frame = helper.solid_color_frame(0, 0, 0)
        line = frame[16:16 + helper.LINE_TOTAL_BYTES]
        self.assertEqual(line, bytes(helper.XOR_PATTERN[i % 4] for i in range(helper.LINE_TOTAL_BYTES)))

    def test_rgb565_channel_packing(self):
        # value = B<<11 | G<<5 | R, little-endian on the wire
        row = helper.solid_color_row(31, 0, 0)
        self.assertEqual(row[:2], b'\x1f\x00')
        self.assertEqual(helper.solid_color_row(0, 0, 31)[:2], b'\x00\xf8')


if __name__ == '__main__':
    unittest.main()

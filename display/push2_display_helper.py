"""Standalone helper process that owns the Push 2 display's USB bulk endpoint.

Never import this into TouchDesigner. It is launched as a subprocess (Phase 6b)
so a USB problem -- or, on Windows, a WinUSB driver problem -- can never affect
the live MIDI/OSC/WebSocket rig. See README.md for the wire protocol.

Frame format source: Ableton's "Push 2 MIDI and Display Interface Manual"
(https://github.com/Ableton/push-interface), confirmed against a live device
descriptor dump on 2026-09-09 (interface 0, "Push 2 Display", bulk OUT 0x01).
"""

import glob
import json
import os
import signal
import subprocess
import sys
import struct
import socket
import time

VENDOR_ID = 0x2982
PRODUCT_ID = 0x1967
INTERFACE = 0
ENDPOINT_OUT = 0x01

FRAME_HEADER = bytes([0xFF, 0xCC, 0xAA, 0x88]) + bytes(12)
LINE_WIDTH_PX = 960
LINE_COUNT = 160
LINE_PIXEL_BYTES = LINE_WIDTH_PX * 2  # RGB565
LINE_FILLER_BYTES = 128
LINE_TOTAL_BYTES = LINE_PIXEL_BYTES + LINE_FILLER_BYTES  # 2048
XOR_PATTERN = bytes([0xE7, 0xF3, 0xE7, 0xFF])


def xor_line(line):
    """XOR a 2048-byte line buffer with the repeating 4-byte pattern."""
    return bytes(b ^ XOR_PATTERN[i % 4] for i, b in enumerate(line))


def build_frame(pixel_rows):
    """pixel_rows: list of 160 bytes objects, each 1920 bytes of little-endian RGB565.

    Returns the full frame payload (header + 160 XORed lines) ready for a bulk write.
    """
    if len(pixel_rows) != LINE_COUNT:
        raise ValueError(f"expected {LINE_COUNT} rows, got {len(pixel_rows)}")
    parts = [FRAME_HEADER]
    for row in pixel_rows:
        if len(row) != LINE_PIXEL_BYTES:
            raise ValueError(f"row must be {LINE_PIXEL_BYTES} bytes, got {len(row)}")
        line = row + bytes(LINE_FILLER_BYTES)
        parts.append(xor_line(line))
    return b"".join(parts)


def solid_color_row(r5, g6, b5):
    """One 1920-byte row filled with a single RGB565 pixel (5-6-5 bit inputs)."""
    value = (b5 & 0x1F) << 11 | (g6 & 0x3F) << 5 | (r5 & 0x1F)
    pixel = struct.pack("<H", value)
    return pixel * LINE_WIDTH_PX


def solid_color_frame(r5, g6, b5):
    row = solid_color_row(r5, g6, b5)
    return build_frame([row] * LINE_COUNT)


def gradient_frame():
    """Eight vertical color bars, one per encoder column, for a first physical read."""
    bars = [
        (31, 0, 0), (31, 63, 0), (0, 63, 0), (0, 63, 31),
        (0, 0, 31), (31, 0, 31), (31, 63, 63), (31, 63, 31),
    ]
    bar_width = LINE_WIDTH_PX // len(bars)
    row = b"".join(
        struct.pack("<H", (b & 0x1F) << 11 | (g & 0x3F) << 5 | (r & 0x1F)) * bar_width
        for (r, g, b) in bars
    )
    # bar_width * len(bars) may be short of LINE_WIDTH_PX by a remainder; pad with the last color
    remainder_px = LINE_WIDTH_PX - bar_width * len(bars)
    if remainder_px:
        r, g, b = bars[-1]
        row += struct.pack("<H", (b & 0x1F) << 11 | (g & 0x3F) << 5 | (r & 0x1F)) * remainder_px
    return build_frame([row] * LINE_COUNT)


WRITE_CHUNK_BYTES = 16384  # manual: "typically sent using larger buffers, e.g. 16kbytes each"
RECONNECT_DELAY_S = 1.0
PARENT_POLL_S = 1.0

LIBUSB_DIR_ENV = "PUSH2_LIBUSB_DIR"
LIBUSB_DLL_NAME = "libusb-1.0.dll"


def _libusb_dll_candidates():
    """Windows libusb-1.0.dll search order, most explicit first.

    TouchDesigner ships libusb-1.0.dll in its own bin folder, so the rig never
    needs a separate libusb install -- but the TD version is IN that path, so a
    TD upgrade would break a pinned one. TD passes its live app.binFolder via
    PUSH2_LIBUSB_DIR (see mod_display.StartHelper); the glob is only the
    fallback for standalone runs with no TD to ask.
    """
    directory = os.environ.get(LIBUSB_DIR_ENV, "").strip()
    if directory:
        yield os.path.join(directory, LIBUSB_DLL_NAME)
    for program_files in (r"C:\Program Files", r"C:\Program Files (x86)"):
        pattern = os.path.join(program_files, "Derivative", "TouchDesigner*", "bin", LIBUSB_DLL_NAME)
        # Newest install first: 2025.32820 sorts above 2023.x lexically.
        for hit in sorted(glob.glob(pattern), reverse=True):
            yield hit


def find_libusb_dll():
    for candidate in _libusb_dll_candidates():
        if os.path.isfile(candidate):
            return candidate
    return None


class _LibUsbBackend:
    """Shared real backend: pyusb over libusb. Subclasses only decide how the
    libusb library itself is located; every USB step below is identical on both
    platforms and deliberately lives in ONE place.

    The interface must be claimed explicitly and the header must be written
    as its own bulk transfer, separate from the (chunked) pixel data -- a
    single write() covering header+pixels without an explicit claim_interface
    call reports full success (no exception, correct byte count) but the
    device silently never updates the screen. Confirmed against physical
    hardware on 2026-09-09 (macOS) and 2026-09-09 (Windows/WinUSB).
    """

    def __init__(self):
        import usb.core
        import usb.util

        self._usb_core = usb.core
        self._usb_util = usb.util
        backend = self._open_library()
        dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID, backend=backend)
        if dev is None:
            raise RuntimeError("Push 2 not found on USB (display interface)")
        try:
            dev.set_configuration()
        except (usb.core.USBError, NotImplementedError) as e:
            # WinUSB owns only interface 0 of this composite device and refuses
            # a device-wide SET_CONFIGURATION; the config is already active, so
            # this is informational, not fatal. macOS needs the call to succeed.
            if not sys.platform.startswith("win"):
                raise
            print(f"[push2_display_helper] set_configuration skipped ({e})")
        cfg = dev.get_active_configuration()
        intf = cfg[(INTERFACE, 0)]
        usb.util.claim_interface(dev, intf)
        self._dev = dev
        self._intf = intf

    def _open_library(self):
        """Return an explicit pyusb backend, or None to use pyusb's own search."""
        return None

    def send_frame(self, payload):
        header, pixels = payload[:16], payload[16:]
        self._dev.write(ENDPOINT_OUT, header, timeout=1000)
        for i in range(0, len(pixels), WRITE_CHUNK_BYTES):
            self._dev.write(ENDPOINT_OUT, pixels[i:i + WRITE_CHUNK_BYTES], timeout=1000)

    def close(self):
        self._usb_util.release_interface(self._dev, self._intf)
        self._usb_util.dispose_resources(self._dev)


class _MacBackend(_LibUsbBackend):
    """macOS: libusb comes from Homebrew, found via DYLD_LIBRARY_PATH which
    mod_display.StartHelper sets from display_helper_libusb_dir_darwin."""


class _WindowsBackend(_LibUsbBackend):
    """Windows: libusb talks to the WinUSB driver bound to interface 0.

    ctypes' find_library() does NOT search PATH the way the POSIX loader does,
    so pyusb's default lookup returns no backend even with the DLL one folder
    away -- get_backend() must be handed the resolved path explicitly. A None
    backend here is what made pyusb report 'No backend available' rather than
    anything about the driver.
    """

    def _open_library(self):
        import usb.backend.libusb1

        dll = find_libusb_dll()
        if dll is None:
            raise RuntimeError(
                f"{LIBUSB_DLL_NAME} not found -- set {LIBUSB_DIR_ENV} to the folder holding it "
                f"(TouchDesigner's bin folder ships one)")
        backend = usb.backend.libusb1.get_backend(find_library=lambda _name: dll)
        if backend is None:
            raise RuntimeError(f"libusb failed to load from {dll} (architecture mismatch?)")
        return backend


class _StubBackend:
    """No-op backend: accepts frames and drops them. Used by --stub for
    running the TCP half on a machine with no Push 2 attached (CI, a dev box,
    or while the WinUSB driver is unbound). Never selected automatically --
    a real backend failure must surface as an error, not a dark screen.
    """

    def __init__(self):
        print("[push2_display_helper] stub backend: frames accepted and discarded")

    def send_frame(self, payload):
        pass

    def close(self):
        pass


def make_backend(force_stub=False):
    if force_stub:
        return _StubBackend()
    if sys.platform.startswith("win"):
        return _WindowsBackend()
    return _MacBackend()


def _recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def _serve_connection(conn, backend):
    conn.settimeout(5.0)
    while True:
        try:
            header = _recv_exact(conn, 4)
        except socket.timeout:
            continue
        if header is None:
            return
        (length,) = struct.unpack(">I", header)
        payload = _recv_exact(conn, length)
        if payload is None:
            return
        try:
            backend.send_frame(payload)
        except Exception as e:
            # Close the connection so TD's onClose fires and health goes
            # red -- a USB unplug/backend failure must be visible as a
            # disconnect, not silently swallowed while TD still thinks
            # it's connected (DESIGN.md T15/T16 gotchas, Phase 6e).
            print(f"[push2_display_helper] send_frame error, closing: {e}")
            return


def _process_is_alive(pid):
    """Whether *pid* still names a live process, without extra dependencies.

    The helper normally dies through Display.StopHelper. This guard covers the
    less polite case where TouchDesigner crashes or is force-quit and therefore
    never gets to terminate its child. Windows needs a real process-handle
    check: os.kill(pid, 0) is POSIX behavior and is not a portable liveness
    probe there.
    """
    if pid is None:
        return True
    if sys.platform.startswith("win"):
        import ctypes

        synchronize = 0x00100000
        wait_timeout = 0x00000102
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(synchronize, False, int(pid))
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_matches_helper(pid, script_path, port):
    """Prove a recorded PID is this helper before it is ever terminated."""
    try:
        if sys.platform.startswith("win"):
            command = subprocess.check_output([
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "(Get-CimInstance Win32_Process -Filter \"ProcessId = %d\").CommandLine" % int(pid),
            ], timeout=2, text=True, stderr=subprocess.DEVNULL)
        else:
            command = subprocess.check_output(
                ["ps", "-p", str(int(pid)), "-o", "command="],
                timeout=2, text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    normalized_command = os.path.normcase(os.path.normpath(command.strip()))
    normalized_script = os.path.normcase(os.path.normpath(os.path.realpath(script_path)))
    return (normalized_script in normalized_command and
            "--serve" in command and str(int(port)) in command)


def _terminate_process(pid):
    if sys.platform.startswith("win"):
        import ctypes

        process_terminate = 0x0001
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_terminate, False, int(pid))
        if not handle:
            raise OSError("could not open process %s for termination" % pid)
        try:
            if not kernel32.TerminateProcess(handle, 1):
                raise OSError("could not terminate process %s" % pid)
        finally:
            kernel32.CloseHandle(handle)
    else:
        os.kill(int(pid), signal.SIGTERM)


def _read_json(path):
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as source:
            value = json.load(source)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, value):
    if not path:
        return
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary = "%s.tmp.%s" % (path, os.getpid())
    with open(temporary, "w", encoding="utf-8") as destination:
        json.dump(value, destination, sort_keys=True)
        destination.write("\n")
    os.replace(temporary, path)


def _remove_owned_record(path, pid):
    if path and _read_json(path).get("pid") == int(pid):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def _reap_stale_owner(owner_file, script_path, port):
    """Stop only a positively identified helper orphaned by a dead TD parent."""
    record = _read_json(owner_file)
    if not record or record.get("port") != int(port):
        return None
    try:
        pid = int(record["pid"])
        parent_pid = int(record["parent_pid"])
    except (KeyError, TypeError, ValueError):
        return None
    if not _process_is_alive(pid):
        _remove_owned_record(owner_file, pid)
        return None
    if _process_is_alive(parent_pid):
        raise RuntimeError(
            "LCD port %s is owned by helper PID %s for live parent PID %s" %
            (port, pid, parent_pid))
    if not _process_matches_helper(pid, script_path, port):
        raise RuntimeError(
            "LCD port %s has stale owner PID %s, but its command line could not be verified; "
            "refusing to terminate it" % (port, pid))
    _terminate_process(pid)
    deadline = time.monotonic() + 2.0
    while _process_is_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if _process_is_alive(pid):
        raise RuntimeError("stale LCD helper PID %s did not exit" % pid)
    _remove_owned_record(owner_file, pid)
    print("[push2_display_helper] terminated stale helper PID %s" % pid)
    return pid


def serve(port, force_stub=False, parent_pid=None, owner_file=None, status_file=None):
    """TCP server: TD (client) connects and streams length-prefixed frames
    (4-byte big-endian length + payload). One connection at a time; TD
    reconnects if this process restarts. The USB backend is (re)opened
    fresh for each new connection -- cheap (milliseconds), and it's what
    makes an unplug/replug recover automatically on the next TD reconnect
    instead of wedging this process onto a dead device handle forever."""
    script_path = os.path.realpath(__file__)
    _write_json(status_file, dict(state="starting", pid=os.getpid(), port=int(port)))
    _reap_stale_owner(owner_file, script_path, port)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("127.0.0.1", port))
        except OSError as error:
            raise RuntimeError(
                "LCD port %s is already in use by an untracked or active process: %s" %
                (port, error)) from error
        srv.listen(1)
        if parent_pid is not None:
            srv.settimeout(PARENT_POLL_S)
        owner = dict(state="listening", pid=os.getpid(), parent_pid=parent_pid,
                     port=int(port), script=script_path)
        _write_json(owner_file, owner)
        _write_json(status_file, owner)
        print(f"[push2_display_helper] listening on 127.0.0.1:{port}")
        while True:
            if not _process_is_alive(parent_pid):
                print(f"[push2_display_helper] parent {parent_pid} exited; shutting down")
                break
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            print(f"[push2_display_helper] client connected from {addr}")
            try:
                backend = make_backend(force_stub=force_stub)
            except Exception as e:
                print(f"[push2_display_helper] backend open failed: {e}")
                conn.close()
                # No hardware/driver must not cause a tight TCP callback loop in TD.
                time.sleep(RECONNECT_DELAY_S)
                continue
            try:
                _serve_connection(conn, backend)
            finally:
                conn.close()
                backend.close()
            print("[push2_display_helper] client disconnected, waiting for reconnect")
            time.sleep(RECONNECT_DELAY_S)
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
        _remove_owned_record(owner_file, os.getpid())


def main():
    force_stub = "--stub" in sys.argv
    if "--serve" in sys.argv:
        port = int(sys.argv[sys.argv.index("--serve") + 1])
        parent_pid = (int(sys.argv[sys.argv.index("--parent-pid") + 1])
                      if "--parent-pid" in sys.argv else None)
        owner_file = (sys.argv[sys.argv.index("--owner-file") + 1]
                      if "--owner-file" in sys.argv else None)
        status_file = (sys.argv[sys.argv.index("--status-file") + 1]
                       if "--status-file" in sys.argv else None)
        try:
            serve(port, force_stub=force_stub, parent_pid=parent_pid,
                  owner_file=owner_file, status_file=status_file)
        except Exception as error:
            message = str(error)
            _write_json(status_file, dict(state="error", pid=os.getpid(),
                                          port=port, message=message))
            print("[push2_display_helper] startup failed: " + message)
            return 2
        return 0
    backend = make_backend(force_stub=force_stub)
    try:
        print("[push2_display_helper] sending solid red test frame")
        backend.send_frame(solid_color_frame(31, 0, 0))
        input("Press Enter to send the gradient test frame...")
        print("[push2_display_helper] sending gradient test frame")
        backend.send_frame(gradient_frame())
        input("Press Enter to exit...")
    finally:
        backend.close()


if __name__ == "__main__":
    raise SystemExit(main())

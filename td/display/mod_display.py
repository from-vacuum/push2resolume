"""Display: encodes RGB565+XOR frames and owns the TCP link to the Push 2
display helper subprocess (display/push2_display_helper.py on disk). The
helper stays "dumb" -- it only relays already-built frame bytes to USB.
See README.md for the wire protocol, DESIGN.md 9 (Phase 6) for why this
lives in a separate process.
"""

import os
import struct
import subprocess
import sys

import numpy as np
import cv2
import unicodedata

FRAME_HEADER = bytes([0xFF, 0xCC, 0xAA, 0x88]) + bytes(12)
LINE_WIDTH_PX = 960
LINE_COUNT = 160
LINE_PIXEL_BYTES = LINE_WIDTH_PX * 2  # RGB565
LINE_FILLER_BYTES = 128
LINE_TOTAL_BYTES = LINE_PIXEL_BYTES + LINE_FILLER_BYTES  # 2048
XOR_PATTERN = bytes([0xE7, 0xF3, 0xE7, 0xFF])
_XOR_PATTERN_NP = np.frombuffer(XOR_PATTERN, dtype=np.uint8)

_FIT_TOGGLE = ('fithorz', 'fitvert')

# switch1 index 0 -> composition, index 1 -> preview (see ToggleSource).
_TEXTURE_SOURCES = (('syphonspoutin2', 'composition'), ('syphonspoutin1', 'preview'))


def RenderLCD(snapshot):
	"""Native 960x160 RGB pixels; eight columns align with the physical encoders."""
	canvas = np.full((160, 960, 3), (10, 12, 14), dtype=np.uint8)
	white, secondary, muted = (240, 242, 244), (168, 175, 182), (88, 96, 104)
	font = cv2.FONT_HERSHEY_SIMPLEX
	def text(value, x, y, width=108, scale=0.32, color=secondary, thick=1):
		value = unicodedata.normalize('NFKD', str(value)).encode('ascii', 'replace').decode()
		while value and cv2.getTextSize(value, font, scale, thick)[0][0] > width:
			value = value[:-1]
		cv2.putText(canvas, value, (x, y), font, scale, color, thick, cv2.LINE_AA)
	for i, target in enumerate(snapshot['targets']):
		x = i * 120
		accent = tuple(target['color'])
		focused = target['target'] == snapshot['focus']
		canvas[0:2, x+5:x+115] = accent if focused else (42, 47, 51)
		if i:
			canvas[6:136, x] = (35, 39, 43)
		text(target['short'], x+6, 15, 34, 0.34, accent)
		text(target['name'], x+40, 15, 74, 0.29, white if focused else secondary)
		encoder = snapshot['encoders'][i]
		text(encoder['label'], x+6, 30, scale=0.30)
		value = encoder.get('value') or 0.0
		text(encoder.get('displayValue', '%d%%' % round(value*100)), x+6, 49, scale=0.58, color=white)
		canvas[54:57, x+6:x+114] = (40, 45, 50)
		canvas[54:57, x+6:x+6+round(max(0,min(1,value))*108)] = accent
		if snapshot['gridMode'] == 'FX':
			start = (snapshot['fxPage']-1)*8+1
			effects = {e['slot']:e for e in target['effects']}
			for row in range(8):
				slot, y = start+row, 68+row*9
				effect = effects.get(slot)
				text('%02d' % slot, x+6, y, 14, 0.24, muted)
				if effect:
					bypassed = effect.get('bypassed_value')
					on = effect.get('opacity_value',0) > 0.002
					color = (232,149,74) if bypassed else white if on else muted
					text(effect['label'], x+23, y, 76, 0.26, color)
					text('B' if bypassed else str(round(effect.get('opacity_value',0)*100)), x+101, y, 16, 0.22, color)
				else:
					text('-', x+23, y, 70, 0.24, muted)
		else:
			playing = target['playing']
			if target['target'] == 'COMPOSITION':
				text('DECK', x+6, 73, scale=0.26, color=muted)
				text(snapshot['deck'] or '--', x+6, 89, scale=0.38, color=white)
				text('%d layers playing' % sum(bool(t['playing']) for t in snapshot['targets']), x+6, 105, scale=0.28)
				text('%d FX / %d decks' % (len(target['effects']),snapshot['deckCount']),x+6,121,scale=0.28)
			else:
				text('PLAY %02d' % playing[0]['index'] if playing else 'STOPPED', x+6,73,scale=0.28,color=accent if playing else muted)
				name = playing[0]['name'] if playing else 'No active clip'
				text(name, x+6,90,scale=0.34,color=white if playing else secondary)
				text('%d/8 in bank | %d total' % (target['visibleLoaded'],target['loaded']),x+6,106,scale=0.26)
				text('OP %d%%   FX %d' % (round((target['opacity'] or 0)*100),len(target['effects'])),x+6,121,scale=0.28)
				if playing and playing[0].get('speed') is not None and not target['bypassed'] and not target['solo']:
					text('Speed %.2fx' % playing[0]['speed'],x+6,134,scale=0.27,color=muted)
			if target['bypassed'] or target['solo']:
				text('BYPASSED' if target['bypassed'] else 'SOLO', x+6,134,scale=0.27,color=(255,105,90) if target['bypassed'] else (255,218,65))
	canvas[140:141,:] = (45,50,55)
	mode = snapshot['gridMode']
	page = 'FX %d/%d | Slots %d-%d' % (snapshot['fxPage'],snapshot['fxPageCount'],(snapshot['fxPage']-1)*8+1,snapshot['fxPage']*8) if mode=='FX' else 'Bank %d/%d | Clips %d-%d | %s' % (snapshot['bank'],snapshot['bankCount'],*snapshot['clipRange'],snapshot['encoderPage'])
	text(mode,7,154,70,0.32,white)
	text(page,82,154,310,0.29)
	focus = next((t for t in snapshot['targets'] if t['target']==snapshot['focus']),{})
	text('Focus '+focus.get('short','')+' '+focus.get('name',''),395,154,220,0.29)
	text('%.1f BPM' % snapshot['bpm'],620,154,92,0.29)
	text('Master %d%%' % round((snapshot.get('master') or 0)*100),718,154,98,0.29)
	status = 'SYNCING' if snapshot.get('syncing') else 'RESYNC FAILED' if snapshot.get('syncError') else snapshot['bindingError'] or (' '.join(snapshot['modifiers']) if snapshot['modifiers'] else 'LIVE' if snapshot['armed'] else 'OFFLINE')
	text(status,825,154,128,0.29,(103,221,168) if snapshot['armed'] else (255,105,90))
	return np.concatenate((canvas, np.full((160,960,1),255,dtype=np.uint8)),axis=2)


def _xorLine(line):
	return bytes(b ^ XOR_PATTERN[i % 4] for i, b in enumerate(line))


def BuildFrame(pixelRows):
	"""pixelRows: 160 rows, each 1920 bytes of little-endian RGB565. Pure-Python
	path used only for the small hand-built test frames -- real content goes
	through the vectorised BuildFrameFromRGBA below."""
	parts = [FRAME_HEADER]
	for row in pixelRows:
		parts.append(_xorLine(row + bytes(LINE_FILLER_BYTES)))
	return b''.join(parts)


def SolidColorFrame(r5, g6, b5):
	value = (b5 & 0x1F) << 11 | (g6 & 0x3F) << 5 | (r5 & 0x1F)
	row = struct.pack('<H', value) * LINE_WIDTH_PX
	return BuildFrame([row] * LINE_COUNT)


def BuildFrameFromRGBA(rgba):
	"""rgba: numpy array (160, 960, 4) uint8, TOP-of-image first -- this is
	both numpyArray()'s native row order (td-api-reference: TOP Pixel Access)
	and the manual's required transmission order ("topmost line first"), so
	no flip is needed. Vectorised: called every tick, must stay cheap."""
	r = (rgba[:, :, 0] >> 3).astype(np.uint16)
	g = (rgba[:, :, 1] >> 2).astype(np.uint16)
	b = (rgba[:, :, 2] >> 3).astype(np.uint16)
	packed = ((b << 11) | (g << 5) | r).astype('<u2')
	row_bytes = packed.view(np.uint8).reshape(LINE_COUNT, LINE_PIXEL_BYTES)
	padded = np.zeros((LINE_COUNT, LINE_TOTAL_BYTES), dtype=np.uint8)
	padded[:, :LINE_PIXEL_BYTES] = row_bytes
	flat = padded.reshape(-1)
	pattern = np.tile(_XOR_PATTERN_NP, flat.size // 4)
	xored = np.bitwise_xor(flat, pattern)
	return FRAME_HEADER + xored.tobytes()


class Display:
	def __init__(self, ownerComp):
		self.ownerComp = ownerComp
		self.process = None
		self.connected = False
		self._stopping = False
		self._connectGeneration = 0
		self.mode = ownerComp.fetch('layout7_ui', {}, search=False).get('display', 'text')

	def Cfg(self, key, default=None, cast=str):
		t = self.ownerComp.op('config/cfg_general')
		for r in range(1, t.numRows):
			if t[r, 'key'].val == key:
				return cast(t[r, 'value'].val)
		return default

	def _net(self):
		return self.ownerComp.op('display/net_display')

	def IsHelperAlive(self):
		"""self.process being non-None only means we once launched it --
		poll() confirms the OS process is still actually running. Without
		this, a helper that crashed or was killed externally looks
		'already running' forever and StartHelper()/Panic() never relaunch
		it (Phase 6e)."""
		return self.process is not None and self.process.poll() is None

	def EnsureTextureSources(self):
		"""Bind each Spout/Syphon In TOP to whatever Arena is actually publishing.

		Sender naming is platform-dependent: Syphon on macOS publishes
		'Arena:Composition', Spout on Windows publishes 'Arena - Composition'.
		A name hardcoded for one platform silently yields a 128x128 black
		placeholder on the other -- the TOP reports no error, it simply never
		receives (confirmed live on Windows 2026-09-09). Matching the role
		suffix against the live sender list covers both conventions and also
		survives an Arena rename ('Arena 7 - Preview') with no config edit.

		A name that already resolves is left alone. Called from StartHelper so
		every start and every Refresh-driven recovery re-resolves; Arena
		launched AFTER TouchDesigner therefore needs one Refresh pulse.
		"""
		for name, role in _TEXTURE_SOURCES:
			top = self.ownerComp.op('display/' + name)
			if top is None:
				continue
			sender = top.par.sendername
			available = list(sender.menuNames or ())
			if sender.eval() in available:
				continue
			match = next((s for s in available if s.strip().lower().endswith(role)), None)
			if match is None:
				debug('Display: no %s sender published; available=%s' % (role, available or 'none'))
				continue
			debug('Display: %s -> %r (was %r)' % (name, match, sender.eval()))
			sender.val = match

	def StartHelper(self):
		"""Launch the helper subprocess, then arm the TCP client a bit later
		so the helper's listening socket is up first."""
		self._stopping = False
		self.EnsureTextureSources()
		if self.IsHelperAlive():
			if not self.connected:
				self._queueConnect()
			return
		self.process = None
		self.connected = False
		self._net().par.active = 0
		plat = 'win32' if sys.platform.startswith('win') else 'darwin'
		python_path = os.path.normpath(os.path.join(project.folder, self.Cfg('display_helper_python_' + plat, sys.executable)))
		script_path = os.path.normpath(os.path.join(project.folder, self.Cfg('display_helper_script', 'display/push2_display_helper.py')))
		port = self.Cfg('display_helper_port', 9871, int)
		env = os.environ.copy()
		if plat == 'darwin':
			libusb_dir = self.Cfg('display_helper_libusb_dir_darwin', '')
			if libusb_dir:
				env['DYLD_LIBRARY_PATH'] = libusb_dir
		else:
			# Windows: ctypes' find_library() does not search PATH, so pyusb
			# cannot locate libusb-1.0.dll on its own. Hand the helper the
			# resolved folder -- app.binFolder tracks the RUNNING TD, so this
			# survives a TD upgrade that a pinned version path would not.
			libusb_dir = self.Cfg('display_helper_libusb_dir_win32', '') or app.binFolder
			if libusb_dir:
				env['PUSH2_LIBUSB_DIR'] = os.path.normpath(libusb_dir)
		try:
			self.process = subprocess.Popen(
				[python_path, script_path, '--serve', str(port)], env=env, cwd=project.folder)
		except OSError as e:
			debug('Display.StartHelper failed:', e)
			return
		self._queueConnect()

	def _queueConnect(self):
		# TD must cook with active=0 before reopening a saved/stale TCP client.
		self._connectGeneration += 1
		self.connected = False
		self._net().par.active = 0
		run("args[0]._connect(args[1])", self, self._connectGeneration, delayFrames=30)

	def _connect(self, generation):
		if self._stopping or generation != self._connectGeneration:
			return
		if self.IsHelperAlive():
			self._net().par.active = 1
		else:
			self.StartHelper()

	def StopHelper(self):
		"""Delayed-quit companion to PushResolumeExt.CloseProject -- called
		before the MIDI teardown so nothing hangs waiting on this process."""
		self._stopping = True
		self._connectGeneration += 1
		net = self._net()
		if net is not None:
			net.par.active = 0
		self.connected = False
		if self.process is not None:
			self.process.terminate()
			self.process = None

	def OnConnect(self):
		if self._stopping:
			return
		self.connected = True

	def OnClose(self):
		"""Helper crash, USB unplug (helper now closes the connection on a
		backend error -- see push2_display_helper.py), or a plain network
		hiccup all land here the same way. Health goes red immediately;
		recovery is automatic a beat later so a brief blip doesn't spam
		relaunches (Phase 6e)."""
		self.connected = False
		if not self._stopping:
			run("args[0]._attemptReconnect()", self, delayFrames=90)

	def _attemptReconnect(self):
		if self._stopping or self.connected:
			return  # a newer connection already landed; don't undo it
		if not self.IsHelperAlive():
			self.StartHelper()
			return
		self._queueConnect()

	def SendFrame(self, payload):
		net = self._net()
		if net is None or not self.connected:
			return
		net.sendBytes(struct.pack('>I', len(payload)), payload)

	def SendTestFrame(self):
		self.SendFrame(SolidColorFrame(31, 0, 0))

	def RefreshDebugPreview(self, rgba8):
		"""Phase 6f: mirror the exact buffer about to be sent (post-compose,
		pre RGB565/XOR encode) onto display/debug_preview, so capture_top on
		that op shows precisely what the physical screen is receiving --
		without needing eyes on the hardware. store()+cook(force=True) is
		read back by debug_preview_callbacks.onCook via scriptOp.fetch().

		Script TOP's copyNumpyArray requires a real contiguous array --
		feeding it a bare np.flipud() view (negative-stride, non-contiguous)
		crashed TD outright (confirmed live). np.flipud(...).copy() forces
		an actual contiguous copy; never pass a raw flipud view here."""
		top = self.ownerComp.op('display/debug_preview')
		if top is None:
			return
		top.store('frame', np.flipud(rgba8).copy())
		top.cook(force=True)

	def SendPreviewFrame(self):
		"""Phase 6c: the live Spout feed, fitted to 960x160 by fit_display,
		read back from null_display and pushed to the helper."""
		src = self.ownerComp.op('display/null_display')
		if src is None:
			return
		rgba = src.numpyArray(delayed=False)
		if rgba is None or rgba.shape[0] != LINE_COUNT or rgba.shape[1] != LINE_WIDTH_PX:
			return
		rgba8 = (rgba * 255.0).astype(np.uint8) if rgba.dtype != np.uint8 else rgba
		self.RefreshDebugPreview(rgba8)
		self.SendFrame(BuildFrameFromRGBA(rgba8))

	def SendTextFrame(self, ext):
		import json
		snapshot = self.ownerComp.op('logic/mod_ledpainter').module.Snapshot(ext)
		signature = json.dumps(snapshot, sort_keys=True)
		if signature != getattr(self, '_textSignature', None):
			pixels = RenderLCD(snapshot)
			self._textPayload = BuildFrameFromRGBA(pixels)
			self._textSignature = signature
			self.RefreshDebugPreview(pixels)
		self.SendFrame(self._textPayload)

	def ToggleMode(self):
		self.mode = 'text' if self.mode == 'preview' else 'preview'

	def ToggleFit(self):
		"""SCALE button (CC58): flip fit_display's Fit param between Fit
		Horizontal and Fit Vertical."""
		fit_top = self.ownerComp.op('display/fit_display')
		if fit_top is None:
			return
		current = fit_top.par.fit.eval()
		fit_top.par.fit = _FIT_TOGGLE[1] if current == _FIT_TOGGLE[0] else _FIT_TOGGLE[0]

	def ToggleSource(self):
		"""Select+Layout: flip switch1 between Arena:Composition
		(syphonspoutin2, index 0) and Arena:Preview (syphonspoutin1,
		index 1)."""
		sw = self.ownerComp.op('display/switch1')
		if sw is None:
			return
		sw.par.index = 0 if sw.par.index.eval() else 1

	def Health(self):
		return self.connected

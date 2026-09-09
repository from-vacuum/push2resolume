"""PushIO: device binding, SysEx handshake, MIDI decode, LED write path.
Nothing else in the project touches MIDI. See DESIGN.md 2.3, 5, 7.1, 7.3.
"""

import platform


def _split7(v):
	v = int(v) & 0xFF
	return (v & 0x7F, (v >> 7) & 0x01)


class PushIO:
	def __init__(self, ownerComp):
		self.ownerComp = ownerComp
		self.midiOut = ownerComp.op('midi/midiout1')
		self.midiIn = ownerComp.op('midi/midiin1')
		self.Bound = False
		self.PushMode = False
		self.LastInquiryReply = None
		self._ledCache = {}
		self._ledQueue = []
		self._ledQueued = set()
		self._blinkPads = {}
		self._blinkPhase = False
		self._blinkFrameAcc = 0

	def Cfg(self, key, default=None, cast=str):
		t = self.ownerComp.op('config/cfg_general')
		for r in range(1, t.numRows):
			if t[r, 'key'].val == key:
				return cast(t[r, 'value'].val)
		return default

	def BindDevice(self):
		"""Resolve the platform-correct device name, ensure /local/midi/device
		has a matching row, point midiin1/midiout1 at it, and activate input."""
		plat = 'darwin' if platform.system() == 'Darwin' else 'win32'
		inname = self.Cfg('push_in_name_' + plat, '')
		outname = self.Cfg('push_out_name_' + plat, '')
		devtable = op('/local/midi/device')
		match_id = None
		for r in range(1, devtable.numRows):
			cell = devtable[r, 'indevice'].val
			if cell == inname or (inname and cell.startswith(inname.split(' ')[0])):
				match_id = devtable[r, 'id'].val
				break
		if match_id is None:
			new_id = str(devtable.numRows)
			devtable.appendRow([new_id, inname, outname, '', '1'])
			match_id = new_id
		self.midiIn.par.device = '/local/midi/device'
		self.midiIn.par.id = match_id
		self.midiOut.par.device = '/local/midi/device'
		self.midiOut.par.id = match_id
		self.midiOut.par.notenorm = 'None'
		self.midiOut.par.controlnorm = 'None'
		self.midiIn.par.bytes = 1
		self.midiIn.par.active = 1
		self.Bound = True
		return match_id

	def SendExclusive(self, *b):
		"""Send SysEx. F0/F7 framing is added by TD -- never pass it here (P9)."""
		self.midiOut.sendExclusive(*b)

	def DeviceInquiry(self):
		self.SendExclusive(0x7E, 0x7F, 0x06, 0x01)

	def SetMode(self, mode):
		"""mode: 'user' | 'live' | 'dual'. Deactivates midiin1 around the send and
		reactivates ~0.5s later, to reduce the CoreMIDI endpoint-reconnect race
		observed to crash TD when Push re-enumerates on a mode switch."""
		val = {'live': 0x00, 'user': 0x01, 'dual': 0x02}[mode]
		self.midiIn.par.active = 0
		self.SendExclusive(0x00, 0x21, 0x1D, 0x01, 0x01, 0x0A, val)
		run("args[0]._reactivateInput()", self, delayFrames=30)
		self.PushMode = (mode == 'user')

	def _reactivateInput(self):
		self.midiIn.par.active = 1

	def SetAftertouch(self):
		self.SendExclusive(0x00, 0x21, 0x1D, 0x01, 0x01, 0x1E,
		                    self.Cfg('push_aftertouch_mode', 0, int))

	def SetLedBrightness(self):
		self.SendExclusive(0x00, 0x21, 0x1D, 0x01, 0x01, 0x06,
		                    self.Cfg('push_led_brightness', 100, int))

	def SetDisplayBrightness(self):
		b = self.Cfg('push_display_brightness', 0, int)
		lsb, msb = _split7(b)
		self.SendExclusive(0x00, 0x21, 0x1D, 0x01, 0x01, 0x08, lsb, msb)

	def PaletteIndex(self, name):
		t = self.ownerComp.op('config/map_palette')
		for r in range(1, t.numRows):
			if t[r, 'name'].val == name:
				return int(t[r, 'palette_index'].val)
		return 0

	def WritePalette(self):
		t = self.ownerComp.op('config/map_palette')
		for r in range(1, t.numRows):
			idx = int(t[r, 'palette_index'].val)
			rl, rm = _split7(t[r, 'r'].val)
			gl, gm = _split7(t[r, 'g'].val)
			bl, bm = _split7(t[r, 'b'].val)
			wl, wm = _split7(t[r, 'w'].val)
			self.SendExclusive(0x00, 0x21, 0x1D, 0x01, 0x01, 0x03, idx,
			                    rl, rm, gl, gm, bl, bm, wl, wm)

	def ReapplyPalette(self):
		self.SendExclusive(0x00, 0x21, 0x1D, 0x01, 0x01, 0x05)

	def SetTouchstrip(self):
		flags = self.Cfg('push_touchstrip_config', 0x10, lambda v: int(v, 0) if isinstance(v, str) and v.startswith('0x') else int(v))
		self.SendExclusive(0x00, 0x21, 0x1D, 0x01, 0x01, 0x17, flags)

	def RestoreTouchStrip(self):
		self.SendExclusive(0x00, 0x21, 0x1D, 0x01, 0x01, 0x17, 0x68)

	def Boot(self):
		"""Steps 1-9 of DESIGN.md 5. Step 10 (REST bootstrap) and step 11 (full LED
		redraw) are driven by the orchestrator once ResolumeState/LedPainter exist."""
		self.BindDevice()
		self.DeviceInquiry()
		self.SetMode('user')
		self.SetAftertouch()
		self.SetLedBrightness()
		self.SetDisplayBrightness()
		self.WritePalette()
		self.ReapplyPalette()
		self.SetTouchstrip()

	def Panic(self):
		self.SetMode('user')
		self.WritePalette()
		self.ReapplyPalette()
		self._ledCache.clear()
		self._ledQueue = []
		self._ledQueued.clear()

	def AllLedsOff(self):
		for (kind, number) in list(self._ledCache.keys()):
			self.SetLed(kind, number, 0)
		self.FlushLeds(cap=999)

	def InvalidateLeds(self):
		self._ledCache.clear()
		self._ledQueue.clear()
		self._ledQueued.clear()
		self._ledPending = {}
		self._blinkPads.clear()
		self._blinkPhase = False
		self._blinkFrameAcc = 0

	# --- LED diff cache + per-tick cap ---

	def SetLed(self, kind, number, palette_index, blink_with=None):
		"""kind: 'note' (pads) or 'cc' (buttons/encoder rings). Queues a write only
		if the resolved index differs from what is already on the hardware."""
		key = (kind, number)
		if blink_with is not None:
			self._blinkPads[key] = (palette_index, blink_with)
			self._queueLed(key, blink_with if self._blinkPhase else palette_index)
		else:
			self._blinkPads.pop(key, None)
			self._queueLed(key, palette_index)

	def _queueLed(self, key, palette_index):
		if self._ledCache.get(key) == palette_index:
			return
		if key not in self._ledQueued:
			self._ledQueue.append(key)
			self._ledQueued.add(key)
		self._ledPending = getattr(self, '_ledPending', {})
		self._ledPending[key] = palette_index

	def FlushLeds(self, cap=48):
		pending = getattr(self, '_ledPending', {})
		sent = 0
		while self._ledQueue and sent < cap:
			key = self._ledQueue.pop(0)
			self._ledQueued.discard(key)
			idx = pending.pop(key, None)
			if idx is None:
				continue
			self._writeLed(key[0], key[1], idx)
			self._ledCache[key] = idx
			sent += 1
		return sent

	def _writeLed(self, kind, number, idx):
		# Same TD 1-indexing as input (PHASE3A_FINDINGS.md 7), mirrored for
		# output: Session button lit only when writing CC52, not the
		# CSV-logical 51. number here is always CSV-logical.
		hw_number = number + 1
		if kind == 'note':
			self.midiOut.sendNoteOn(1, hw_number, idx)
		else:
			self.midiOut.sendControl(1, hw_number, idx)

	def BlinkTick(self, frame_delta_frames, blink_hz, tick_hz):
		"""Call once per 30Hz tick. Toggles cached blink pads between their two
		palette indices at blink_hz. Software-only -- see DESIGN.md 5.2."""
		self._blinkFrameAcc += frame_delta_frames
		period_ticks = max(1, int(tick_hz / (2.0 * blink_hz)))
		if self._blinkFrameAcc < period_ticks:
			return
		self._blinkFrameAcc = 0
		self._blinkPhase = not self._blinkPhase
		for key, (idx_a, idx_b) in self._blinkPads.items():
			self._queueLed(key, idx_b if self._blinkPhase else idx_a)

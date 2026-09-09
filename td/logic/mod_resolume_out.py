"""ResolumeOut: the single write path for both transports. OSC half is live
(Phase 3); the WS half is a queueing stub until FxRegistry exists (Phase 4).
See DESIGN.md 2.3, 6."""

import json
import time

def _cast(value_type, value):
	if value_type == 'int':
		return int(round(float(value)))
	if value_type == 'bool_as_int':
		return int(bool(value) and value != 0)
	if value_type == 'float':
		return float(value)
	return value


class ResolumeOut:
	def __init__(self, ownerComp):
		self.ownerComp = ownerComp
		self.oscOut = ownerComp.op('net/oscout1')
		self.wsOut = ownerComp.op('net/ws1')
		self._oscCache = {}
		self._oscPending = {}
		self._oscQueue = []
		self._oscQueued = set()
		self._wsPending = {}
		self._wsQueue = []
		self._wsQueued = set()
		self._wsReadbacks = {}

	def Cfg(self, key, default=None, cast=str):
		t = self.ownerComp.op('config/cfg_general')
		for r in range(1, t.numRows):
			if t[r, 'key'].val == key:
				return cast(t[r, 'value'].val)
		return default

	def Send(self, row, resolved_path, value):
		"""Enqueue one control write. Called from Surface.OnReceiveMIDI. The
		actual dead-band diff and send happen at flush time (FlushOSC/FlushWS),
		so a burst of the same path in one tick coalesces to one message."""
		if not self.ownerComp.Armed:
			return False
		if '{' in resolved_path or not resolved_path.startswith('/'):
			raise ValueError('Unresolved control path: ' + resolved_path)
		if self.Cfg('dry_run', '0') == '1':
			self.ownerComp.Surface.LogDryRun(row, resolved_path, value)
			return False
		typed = _cast(row['value_type'], value)
		if row['transport'] == 'osc':
			self._enqueue(self._oscQueue, self._oscQueued, self._oscPending,
			              resolved_path, (typed, row['value_type']))
		elif row['transport'] == 'ws':
			self._enqueue(self._wsQueue, self._wsQueued, self._wsPending,
			              resolved_path, (typed, row['value_type']))
		# 'internal' transport is handled entirely by Surface.HandleInternal.
		return True

	def ClearPending(self, ws_only=False):
		self._wsReadbacks.clear()
		for prefix in (('_ws',) if ws_only else ('_ws', '_osc')):
			getattr(self, prefix + 'Queue').clear()
			getattr(self, prefix + 'Queued').clear()
			getattr(self, prefix + 'Pending').clear()
		if not ws_only:
			self._oscCache.clear()

	@staticmethod
	def _enqueue(queue, queued, pending, key, item):
		if key not in queued:
			queue.append(key)
			queued.add(key)
		pending[key] = item

	def FlushOSC(self, cap=32):
		if not self.ownerComp.Armed or self.Cfg('dry_run', '0') == '1':
			self.ClearPending()
			return 0
		deadband = self.Cfg('osc_deadband', 0.002, float)
		sent = 0
		while self._oscQueue and sent < cap:
			path = self._oscQueue.pop(0)
			self._oscQueued.discard(path)
			item = self._oscPending.pop(path, None)
			if item is None:
				continue
			value, value_type = item
			cached = self._oscCache.get(path)
			# Dead-band is for CONTINUOUS float streams only (encoders/touch
			# strip) -- DESIGN.md 6. Discrete int/bool triggers (clip_connect,
			# layer_focus, column_connect...) must always re-send even when
			# the value is unchanged: every physical press is a fresh bang,
			# not a state stream. An earlier version of this check also
			# skipped unchanged ints, which silently ate every repeat press
			# of any trigger whose CSV value is a constant (e.g. always 1).
			if value_type == 'float' and cached is not None and abs(value - cached) < deadband:
				continue
			self.oscOut.sendOSC(path, [value], asBundle=True, useNonStandardTypes=False)
			self._oscCache[path] = value
			sent += 1
		return sent

	def FlushWS(self, cap=16):
		"""WS half. Envelope confirmed live against Resolume Arena --
		see PHASE3A_FINDINGS.md 6: {"action":"set","parameter":<path str>,"value":<v>}.
		Any path still containing 'fx[' means FxRegistry has not resolved it
		yet (unknown slot) and is dropped."""
		if not self.ownerComp.Armed or self.Cfg('dry_run', '0') == '1':
			self.ClearPending()
			return 0
		sent = 0
		while self._wsQueue and sent < cap:
			path = self._wsQueue.pop(0)
			self._wsQueued.discard(path)
			item = self._wsPending.pop(path, None)
			if item is None or 'fx[' in path:
				continue
			value, value_type = item
			self._sendWS(path, value)
			self._wsReadbacks[path] = time.monotonic() + 0.05
			sent += 1
		# Read on a later Resolume frame, not from its pre-write set reply.
		now = time.monotonic()
		for path, due in list(self._wsReadbacks.items()):
			if sent >= cap:
				break
			if due <= now:
				self.wsOut.sendText(json.dumps({'action':'get', 'parameter':path}))
				self._wsReadbacks.pop(path, None)
				sent += 1
		return sent

	def _sendWS(self, path, value):
		self.wsOut.sendText(json.dumps({'action': 'set', 'parameter': path, 'value': value}))

	def SendWSById(self, param_id, value):
		row = {'id': 'FX_' + str(param_id), 'action': 'fx_set', 'transport': 'ws',
		       'value_type': 'bool_as_int' if isinstance(value, bool) else 'float'}
		return self.Send(row, '/parameter/by-id/%s' % param_id, value)

"""FxRegistry: discovers effects at runtime, pins them to stable pad slots by
identity (not chain position), and answers fx[TARGET:slot].field lookups for
the surface. Nothing about an effect is ever declared in a file. See
DESIGN.md 4 and PHASE3A_FINDINGS.md (opacity lives in params, not mixer;
display_name not displayName)."""

import csv
import io
import os
import time

_PIN_COLS = ['target', 'slot', 'pin_key', 'last_display_name', 'on_value', 'last_seen_iso', 'notes']


def _find_opacity_id(eff):
	params = eff.get('params', {}) or {}
	if 'Opacity' in params and isinstance(params['Opacity'], dict):
		return params['Opacity'].get('id'), 'params.Opacity'
	for k, v in params.items():
		if isinstance(v, dict) and k.lower() == 'opacity':
			return v.get('id'), 'params.' + k
	mixer = eff.get('mixer', {}) or {}
	for k, v in mixer.items():
		if isinstance(v, dict) and k.lower() == 'opacity':
			return v.get('id'), 'mixer.' + k
	for label, d in (('params', params), ('mixer', mixer)):
		for k, v in d.items():
			if isinstance(v, dict) and v.get('valuetype') == 'ParamRange' and v.get('min') == 0:
				return v.get('id'), label + '.' + k + ' (fallback: first 0-min ParamRange)'
	return None, None


class FxRegistry:
	def __init__(self, ownerComp):
		self.ownerComp = ownerComp
		self.Registry = {}
		self.Pins = {}
		self._slotOf = {}
		self._freedAt = {}
		self._loadPins()

	def Cfg(self, key, default=None, cast=str):
		return self.ownerComp.Surface.Cfg(key, default, cast)

	def _pinsPath(self):
		rel = self.Cfg('fx_pins_file', 'config/fx_pins.csv')
		return os.path.join(project.folder, rel)

	def _loadPins(self):
		path = self._pinsPath()
		if not os.path.exists(path):
			return
		with open(path, 'r', newline='') as f:
			for row in csv.DictReader(f):
				pin_key = row.get('pin_key')
				if not pin_key:
					continue
				slot = int(row['slot'])
				target = row['target']
				self.Pins[pin_key] = row
				self._slotOf[pin_key] = (target, slot)

	def _savePins(self):
		path = self._pinsPath()
		buf = io.StringIO()
		w = csv.DictWriter(buf, fieldnames=_PIN_COLS)
		w.writeheader()
		for pin_key, (target, slot) in self._slotOf.items():
			row = self.Pins.get(pin_key, {})
			w.writerow({
				'target': target, 'slot': slot, 'pin_key': pin_key,
				'last_display_name': row.get('last_display_name', ''),
				'on_value': row.get('on_value', self.Cfg('fx_default_on_value', 1.0, float)),
				'last_seen_iso': row.get('last_seen_iso', ''),
				'notes': row.get('notes', ''),
			})
		with open(path, 'w', newline='') as f:
			f.write(buf.getvalue())

	def _effectsFor(self, comp, target):
		if target == 'COMPOSITION':
			return comp.get('video', {}).get('effects', [])
		layer_ids = self.ownerComp.Surface.LayerIds()
		idx = int(target.removeprefix('LAYER')) - 1
		if idx >= len(layer_ids):
			return []
		layers = comp.get('layers', [])
		li = int(layer_ids[idx]) - 1
		if li < 0 or li >= len(layers):
			return []
		return layers[li].get('video', {}).get('effects', [])

	def _assignSlot(self, target, pin_key, max_slots):
		if pin_key in self._slotOf:
			return self._slotOf[pin_key][1]
		used = {s for (t, s) in self._slotOf.values() if t == target}
		for slot in range(1, max_slots + 1):
			if slot not in used:
				self._slotOf[pin_key] = (target, slot)
				return slot
		debug('FxRegistry: %s has no free slot (max %d), leaving unassigned' % (target, max_slots))
		return None

	def Rebuild(self, comp):
		max_slots = self.Cfg('fx_slots_per_target', 16, int)
		default_on = self.Cfg('fx_default_on_value', 1.0, float)
		ttl_s = self.Cfg('fx_pin_ttl_s', 300, float)
		now = time.time()
		new_registry = {}
		seen_pins = set()

		for target in self.ownerComp.Surface.Targets():
			effects = self._effectsFor(comp, target)
			name_counts = {}
			for chain_index, eff in enumerate(effects):
				name = eff.get('name', '')
				if name == 'Transform':
					# Resolume auto-inserts Transform as the first entry in every
					# effect chain; it has no real opacity (PHASE3A_FINDINGS.md 4
					# noted this resolves via a wrong params.Scale fallback).
					# Skipping it here shifts every real effect's slot down by
					# one automatically -- no separate offset math needed.
					continue
				name_counts[name] = name_counts.get(name, 0) + 1
				ordinal = name_counts[name]
				pin_key = '%s|%s|%d' % (target, name, ordinal)
				seen_pins.add(pin_key)
				slot = self._assignSlot(target, pin_key, max_slots)
				if slot is None:
					continue
				opacity_id, resolved_via = _find_opacity_id(eff)
				opacity_parameter = next((p for group in ('params', 'mixer') for p in (eff.get(group) or {}).values()
				                          if isinstance(p, dict) and p.get('id') == opacity_id), {})
				opacity_value = opacity_parameter.get('value', 0.0)
				lo, hi = opacity_parameter.get('min', 0.0), opacity_parameter.get('max', 1.0)
				opacity_value = (opacity_value - lo) / (hi - lo) if hi != lo else 0.0
				bypassed = eff.get('bypassed', {}) or {}
				on_value = float(self.Pins.get(pin_key, {}).get('on_value', default_on))
				if on_value <= 0.002:
					on_value = default_on if default_on > 0.002 else 1.0
				self.Pins[pin_key] = {
					'last_display_name': eff.get('display_name') or eff.get('name'),
					'on_value': on_value,
					'last_seen_iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
					'notes': 'opacity via ' + str(resolved_via) if resolved_via else 'opacity NOT FOUND',
				}
				reg_key = '%s:%d' % (target, slot)
				# TogglePad tracks on/off in _padOn on the registry entry
				# itself. Rebuild() replaces the whole dict every poll
				# (state_poll_s, ~2s) or WS composition push -- without
				# carrying this forward, every rebuild silently forgets
				# which pads are on, so the next press re-sends "on" as a
				# no-op instead of turning off (only the press after that
				# actually flips it). Worse with multiple pads: more time
				# between presses raises the odds a rebuild lands between
				# turning a pad on and trying to turn it off.
				old_entry = self.Registry.get(reg_key)
				new_registry[reg_key] = {
					'target': target, 'slot': slot, 'pin_key': pin_key,
					'chain_index': chain_index, 'effect_id': eff.get('id'),
					'name': name, 'label': eff.get('display_name') or name,
					'opacity_id': opacity_id, 'bypassed_id': bypassed.get('id'),
					'bypassed_value': bypassed.get('value'),
					'on_value': on_value, 'present': True,
					'opacity_value': opacity_value,
					'_padOn': opacity_value > 0.002,
				}
				if old_entry and old_entry.get('effect_id') == eff.get('id') and old_entry.get('_pending_until', 0) > now:
					for field in ('opacity_value', '_padOn', 'bypassed_value', '_pending_until'):
						if field in old_entry:
							new_registry[reg_key][field] = old_entry[field]

		for pin_key in list(self._slotOf.keys()):
			if pin_key not in seen_pins:
				if pin_key not in self._freedAt:
					self._freedAt[pin_key] = now
				elif now - self._freedAt[pin_key] > ttl_s:
					target, slot = self._slotOf.pop(pin_key)
					self.Pins.pop(pin_key, None)
					self._freedAt.pop(pin_key, None)
			else:
				self._freedAt.pop(pin_key, None)

		old_ids = {e.get('effect_id') for e in self.Registry.values()}
		new_ids = {e.get('effect_id') for e in new_registry.values()}
		if old_ids != new_ids and self.ownerComp.ResolumeOut:
			self.ownerComp.ResolumeOut.ClearPending(ws_only=True)
		self.Registry = new_registry
		self._writeMirrorTable()
		self._savePins()
		return len(new_registry)

	def _writeMirrorTable(self):
		t = self.ownerComp.op('config/fx_registry')
		if t is None:
			return
		t.clear()
		t.appendRow(['target', 'slot', 'pin_key', 'effect_id', 'opacity_id',
		             'bypassed_id', 'label', 'on_value', 'state'])
		for key in sorted(self.Registry.keys()):
			e = self.Registry[key]
			state = 'BYPASSED' if e['bypassed_value'] else 'ON'
			t.appendRow([e['target'], e['slot'], e['pin_key'], e['effect_id'],
			             e['opacity_id'], e['bypassed_id'], e['label'],
			             e['on_value'], state])

	def CountsByTarget(self):
		out = {t: 0 for t in self.ownerComp.Surface.Targets()}
		for e in self.Registry.values():
			out[e['target']] += 1
		return out

	def PathFor(self, target, slot, field):
		"""fx[TARGET:slot].field -> '/parameter/by-id/{id}' string, or the raw
		on_value float for field=='on_value'. None if unresolved."""
		e = self.Registry.get('%s:%d' % (target, int(slot)))
		if e is None:
			return None
		if field == 'on_value':
			return e['on_value']
		pid = e.get(field)
		if pid is None:
			return None
		return '/parameter/by-id/%s' % pid

	def SetOnValue(self, target, slot, value):
		# Capturing an off effect must not turn its next activation into 0 -> 0.
		if not 0.002 < value <= 1.0:
			return
		key = '%s:%d' % (target, int(slot))
		e = self.Registry.get(key)
		if e is None:
			return
		e['on_value'] = value
		pin = self.Pins.get(e['pin_key'])
		if pin is not None:
			pin['on_value'] = value
			self._savePins()

	def TogglePad(self, target, slot, resolume_out):
		"""Simplified gesture (no ramp/hold-momentary yet -- see notes):
		jumps opacity between 0.0 and the slot's on_value."""
		e = self.Registry.get('%s:%d' % (target, slot))
		if e is None or e['opacity_id'] is None or resolume_out is None:
			return
		current_is_on = e.get('_padOn', False)
		new_value = 0.0 if current_is_on else e['on_value']
		if resolume_out.SendWSById(e['opacity_id'], new_value):
			e['_padOn'] = new_value > 0.002
			e['opacity_value'] = new_value
			e['_pending_until'] = time.time() + 0.5

	def ToggleBypass(self, target, slot, resolume_out):
		e = self.Registry.get('%s:%d' % (target, slot))
		if e is None or e['bypassed_id'] is None or resolume_out is None:
			return
		new_value = not bool(e.get('bypassed_value'))
		if resolume_out.SendWSById(e['bypassed_id'], new_value):
			e['bypassed_value'] = new_value
			e['_pending_until'] = time.time() + 0.5

	def Rescan(self):
		"""Manual rescan (hard reset / Rebind): force a fresh REST read and rebuild."""
		self.ownerComp.ResolumeState.Request(self.ownerComp)

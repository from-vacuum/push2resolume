"""PushResolumeExt: orchestrator. Owns the shared state dict, wires the
sub-modules together, and runs the 30 Hz Tick. See DESIGN.md 2.2/2.3.
"""


class PushResolumeExt:
	def __init__(self, ownerComp):
		self.ownerComp = ownerComp
		self.Surface = None
		self.PushIO = None
		self.ResolumeOut = None
		self.ResolumeState = None
		self.FxRegistry = None
		self.Display = None
		self.Health = {
			'push_bound': False, 'push_mode': False, 'osc_target': False,
			'resolume_state': False, 'fx_registry': False, 'layers_ok': False,
			'display': False,
		}
		self.Armed = False
		self._pollFrameAcc = 0

	def onInitTD(self):
		run("args[0]._postInit()", self, delayFrames=5)

	def _postInit(self):
		import sys
		import types
		comp = self.ownerComp
		runtime = sys.modules.setdefault('_push2_runtime', types.ModuleType('_push2_runtime'))
		previous = runtime.__dict__.get(str(comp.id), {})
		surface_mod = comp.op('logic/mod_surface')
		if surface_mod is None:
			debug('PushResolumeExt: logic/mod_surface not found, aborting init')
			return
		self.Surface = surface_mod.module.Surface(comp)
		for key, value in comp.fetch('layout7_ui', {}, search=False).items():
			if key != 'display' and hasattr(self.Surface, key):
				setattr(self.Surface, key, value)
		pushio_mod = comp.op('logic/mod_pushio')
		if pushio_mod is not None:
			self.PushIO = pushio_mod.module.PushIO(comp)
		resout_mod = comp.op('logic/mod_resolume_out')
		if resout_mod is not None:
			self.ResolumeOut = resout_mod.module.ResolumeOut(comp)
		state_mod = comp.op('logic/mod_resolume_state')
		if state_mod is not None:
			self.ResolumeState = state_mod.module.ResolumeState(comp)
		fx_mod = comp.op('logic/mod_fxregistry')
		if fx_mod is not None:
			self.FxRegistry = fx_mod.module.FxRegistry(comp)
		display_mod = comp.op('display/mod_display')
		if display_mod is not None:
			self.Display = display_mod.module.Display(comp)
		# Keep process/socket ownership outside DAT module reloads, not in saved OP storage.
		for key, helper in (('pushio', self.PushIO), ('display', self.Display)):
			if key in previous and helper is not None:
				helper.__dict__.update(previous[key].__dict__)
		if previous.get('surface'):
			for key in ('GridMode', 'Bank', 'FxPage', 'EncoderPage', 'FocusTarget', 'LastLayerTarget'):
				setattr(self.Surface, key, getattr(previous['surface'], key))
		if previous.get('state'):
			self.ResolumeState.Connected = previous['state'].Connected
		runtime.__dict__[str(comp.id)] = {'pushio':self.PushIO,'display':self.Display,'surface':self.Surface,'state':self.ResolumeState}
		self.Health['push_bound'] = bool(self.PushIO and self.PushIO.Bound)
		self.Health['push_mode'] = bool(self.PushIO and self.PushIO.PushMode)
		self.Health['osc_target'] = True

	def onDestroyTD(self):
		pass

	def Boot(self):
		"""Full startup sequence (DESIGN.md 5). Deferred call from exec_boot.onStart."""
		if self.PushIO is None:
			debug('PushResolumeExt.Boot: PushIO not initialized')
			return
		self.PushIO.Boot()
		self.Health['push_bound'] = self.PushIO.Bound
		self.Health['push_mode'] = self.PushIO.PushMode
		self.Health['osc_target'] = True
		state_source = self.PushIO.Cfg('state_source', 'websocket')
		if state_source in ('websocket', 'rest_poll') and self.ResolumeState is not None:
			self.ResolumeState.Request(self)
		if state_source == 'websocket':
			self.ownerComp.op('net/ws1').par.active = 1
		if self.Display is not None:
			self.Display.StartHelper()
		self.FullRedraw()
		self.CheckHealth()

	def Panic(self):
		"""Stop CC (29). Re-send User Mode SysEx, re-write palette, full LED redraw."""
		if self.PushIO:
			self.PushIO.Panic()
		if self.ResolumeState is not None:
			self.ResolumeState.Request(self)
		if self.Display is not None and self.Display.process is None:
			self.Display.StartHelper()
		self.FullRedraw()

	def Resync(self):
		"""Device: replace optimistic state with a fresh read, without controlling Resolume."""
		state = self.ResolumeState
		if state is None or state.Syncing:
			return
		state.Syncing, state.SyncError = True, ''
		state.LastReceived = 0.0
		self.Armed = False
		self.ResolumeOut.ClearPending()
		self.Surface.EncoderValues.clear()
		self.Surface.EncoderWritten.clear()
		state.Pending.clear()
		if self.FxRegistry:
			for entry in self.FxRegistry.Registry.values():
				entry['_pending_until'] = 0
		self._pollFrameAcc = 0
		state.Request(self)

	def FinishResync(self, error=''):
		state = self.ResolumeState
		state.Syncing, state.SyncError = False, error
		if error:
			state.LastReceived = 0.0
		if self.PushIO:
			self.PushIO.InvalidateLeds()
		if self.Display:
			self.Display._textSignature = None
		self.CheckHealth()
		self.FullRedraw()

	def FullRedraw(self):
		painter = self.ownerComp.op('logic/mod_ledpainter')
		if painter is None or self.PushIO is None:
			return
		for (kind, number), val in painter.module.Paint(self).items():
			if isinstance(val, tuple):
				self.PushIO.SetLed(kind, number, val[0], blink_with=val[1])
			else:
				self.PushIO.SetLed(kind, number, val)

	def CheckHealth(self):
		h = self.Health
		h['fx_registry'] = bool(self.FxRegistry and len(self.FxRegistry.Registry) > 0)
		if self.ResolumeState is not None:
			h['layers_ok'] = self.ResolumeState.LayerIdsOK()
			h['resolume_state'] = self.ResolumeState.Fresh()
			h['websocket'] = self.ResolumeState.Connected
		if self.Display is not None:
			h['display'] = self.Display.Health()
		self.Armed = bool(h.get('push_bound') and h.get('push_mode') and h.get('layers_ok') and h.get('resolume_state') and not self.ResolumeState.Syncing)
		if self.Surface and self.Display:
			ui_state = {k:getattr(self.Surface,k) for k in ('GridMode','Bank','FxPage','EncoderPage','FocusTarget','LastLayerTarget')}
			ui_state['display'] = self.Display.mode
			if self.ownerComp.fetch('layout7_ui', {}, search=False) != ui_state:
				self.ownerComp.store('layout7_ui', ui_state)
		hp = self.ownerComp.op('ui/health')
		if hp is not None:
			hp.clear()
			hp.appendRow(['check', 'status'])
			for k, v in h.items():
				hp.appendRow([k, 'green' if v else 'red'])
			hp.appendRow(['armed', 'yes' if self.Armed else 'no'])
		mirror = self.ownerComp.op('ui/mirror_state')
		if mirror is not None and self.Surface:
			rows = [['key', 'value'], ['mode', self.Surface.GridMode], ['bank', self.Surface.Bank],
			        ['fx_page', self.Surface.FxPage], ['encoder_page', self.Surface.EncoderPage],
			        ['focus', self.Surface.FocusTarget], ['binding_error', self.ResolumeState.BindingError]]
			text = '\n'.join('\t'.join(map(str, r)) for r in rows)
			if mirror.text.strip() != text:
				mirror.text = text

	def Tick(self):
		"""30 Hz gate target. Ramp engine -> OSC flush -> WS flush -> LED flush."""
		self.CheckHealth()
		self._pollTick()
		if self.ResolumeOut:
			osc_cap = self.PushIO.Cfg('osc_msgs_per_tick', 32, int) if self.PushIO else 32
			ws_cap = self.PushIO.Cfg('ws_msgs_per_tick', 16, int) if self.PushIO else 16
			self.ResolumeOut.FlushOSC(cap=osc_cap)
			self.ResolumeOut.FlushWS(cap=ws_cap)
		if self.PushIO:
			blink_hz = float(self.PushIO.Cfg('blink_hz', 2, float))
			tick_hz = float(self.PushIO.Cfg('tick_hz', 30, float))
			self.PushIO.BlinkTick(2, blink_hz, tick_hz)
			self.FullRedraw()
			led_cap = self.PushIO.Cfg('led_msgs_per_tick', 48, int)
			self.PushIO.FlushLeds(cap=led_cap)
		if self.Display is not None and self.Display.connected:
			if self.Display.mode == 'preview':
				self.Display.SendPreviewFrame()
			else:
				self.Display.SendTextFrame(self)
		self.CheckHealth()

	def _pollTick(self):
		"""Periodic REST composition poll (cfg state_poll_s) so changes made
		directly in the Resolume UI -- not just through the controller -- show
		up on Push. Reuses the same ResolumeState.OnMessage path the WS
		composition push and Boot/Panic/Rescan already use: it detects the
		untyped composition shape, renormalises Clips/Layers, and rebuilds
		FxRegistry if anything changed. This is the DESIGN.md 2.1 rest_poll
		fallback, run continuously as a WS supplement rather than only when
		WS is unavailable, since the WS side has no per-parameter subscriptions
		yet (Phase 4.6) and would otherwise never see an outside edit."""
		if self.PushIO is None or self.ResolumeState is None:
			return
		poll_s = self.PushIO.Cfg('state_poll_s', 2.0, float)
		if poll_s <= 0:
			return
		tick_hz = float(self.PushIO.Cfg('tick_hz', 30, float))
		self._pollFrameAcc += 1
		if self._pollFrameAcc < poll_s * tick_hz:
			return
		self._pollFrameAcc = 0
		if self.ResolumeState.PollPending:
			return
		self.ResolumeState.Request(self)

	def CloseProject(self):
		"""Delayed-quit shutdown. See DESIGN.md 5.3. Display helper is stopped
		first so its teardown never blocks or races the MIDI release-on-exit."""
		if self.Display:
			self.Display.StopHelper()
		if self.PushIO:
			self.PushIO.AllLedsOff()
			if int(self.PushIO.Cfg('release_push_on_exit', 1, int)):
				self.PushIO.SetMode('live')
				self.PushIO.RestoreTouchStrip()
		import sys
		if '_push2_runtime' in sys.modules:
			sys.modules['_push2_runtime'].__dict__.pop(str(self.ownerComp.id), None)
		run("args[0]._quit()", self, delayFrames=60)

	def _quit(self):
		pass

"""Shared control resolution for the seven-layer Push surface."""
import ast
import math
import re
import time


def _decode_relative(v):
    v = int(v)
    return v if 1 <= v <= 63 else v - 128 if 65 <= v <= 127 else 0


def _expression(expression, context):
    def read(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.Name) and n.id in context:
            return context[n.id]
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult)):
            a, b = read(n.left), read(n.right)
            return a + b if isinstance(n.op, ast.Add) else a - b if isinstance(n.op, ast.Sub) else a * b
        raise ValueError('Unsupported mapping expression: ' + str(expression))
    return read(ast.parse(str(expression), mode='eval').body)


class Surface:
    def __init__(self, ownerComp):
        self.ownerComp = ownerComp
        self.GridMode, self.EncoderPage = 'SESSION', 'OPACITY'
        self.Bank, self.FxPage = 1, 1
        self.FocusTarget = self.LastLayerTarget = 'LAYER1'
        self.HeldFocusTarget = None
        self.Modifiers = set()
        self.EncoderValues, self.EncoderWritten = {}, {}
        self.ClipScrollX = 0.0
        self._index, self._cfg = {}, {}
        self.LoadCfg()
        self.BuildIndex()

    def LoadCfg(self):
        t = self.ownerComp.op('config/cfg_general')
        self._cfg = {t[r, 'key'].val: t[r, 'value'].val for r in range(1, t.numRows)}
        return self._cfg

    def Cfg(self, key, default=None, cast=str):
        v = self._cfg.get(key)
        return cast(v) if v is not None else default

    def BuildIndex(self):
        t = self.ownerComp.op('config/map_controls')
        columns = [t[0, c].val for c in range(t.numCols)]
        self._index = {}
        for r in range(1, t.numRows):
            row = {c: t[r, c].val for c in columns}
            self._index[(row['in_type'], int(row['in_number']), row['modifier'], row['grid_mode'])] = row
        return len(self._index)

    def LayerIds(self):
        return [p.strip() for p in self.Cfg('layer_ids', '1,2,3,4,5,6,7').split(',') if p.strip()]

    def Targets(self):
        return ['LAYER%d' % i for i in range(1, len(self.LayerIds()) + 1)] + ['COMPOSITION']

    def LayerFor(self, target):
        m = re.fullmatch(r'LAYER(\d+)', target or '')
        i = int(m[1]) - 1 if m else -1
        ids = self.LayerIds()
        return ids[i] if 0 <= i < len(ids) else None

    def Context(self):
        return dict({'L%d' % i: int(v) for i, v in enumerate(self.LayerIds(), 1)},
                    bank=self.Bank - 1, fx_page=self.FxPage - 1, bank_group=((self.Bank - 1) // 8) * 8)

    def Slot(self, row):
        return int(_expression(row['slot'], self.Context())) if row.get('slot') else None

    def BankCount(self):
        state = self.ownerComp.ResolumeState
        columns = len((state.Composition or {}).get('columns', [])) if state else 0
        return max(self.Cfg('bank_count', 16, int), math.ceil(columns / self.Cfg('clips_per_bank', 8, int)))

    def FxPageCount(self):
        return math.ceil(self.Cfg('fx_slots_per_target', 16, int) / self.Cfg('fx_visible_slots', 8, int))

    def SetBank(self, bank):
        self.Bank = max(1, min(self.BankCount(), int(bank)))

    def SetGridMode(self, mode):
        if mode in ('SESSION', 'FX'):
            self.GridMode = mode

    def ActiveModifier(self):
        return 'SELECT' if 'SELECT' in self.Modifiers else 'SHIFT' if 'SHIFT' in self.Modifiers else ''

    def Resolve(self, in_type, number, modifier, grid_mode):
        encoder = in_type == 'cc' and 71 <= number <= 78
        lookup = '' if encoder and modifier == 'SELECT' else modifier
        for mod in ([lookup, ''] if lookup else ['']):
            for mode in (grid_mode, 'ANY'):
                row = self._index.get((in_type, int(number), mod, mode))
                if row is not None:
                    row = dict(row)
                    if encoder and grid_mode == 'SESSION' and self.EncoderPage == 'MACRO':
                        prefix = '/composition' + ('' if row['target'] == 'COMPOSITION' else '/layers/{L%d}' % (number - 70))
                        row['control_path'] = prefix + '/dashboard/link%d' % (2 if lookup == 'SHIFT' else 1)
                    return row
        return None

    def ResolveTemplate(self, control_path, target='', slot_expr='', fx_registry=None, focus_override=None):
        if not control_path:
            return ''
        ctx = self.Context()
        focus = focus_override or self.FocusTarget
        if focus not in self.Targets():
            raise ValueError('Unknown focus target: ' + str(focus))
        ctx['FOCUS'] = '' if focus == 'COMPOSITION' else '/layers/' + self.LayerFor(focus)
        ctx['LAST_LAYER'] = self.LayerFor(self.LastLayerTarget)
        ctx['ACTIVE_CLIP'] = self.ownerComp.ResolumeState.ActiveClip(target) or 0 if self.ownerComp.ResolumeState else 0
        if slot_expr:
            ctx['slot'] = _expression(slot_expr, ctx)
        def replace(m):
            token = m[1]
            fx = re.fullmatch(r'fx\[([A-Z0-9]+):([^\]]+)\]\.([a-z_]+)', token)
            if fx:
                entry = fx_registry.Registry.get('%s:%d' % (fx[1], int(_expression(fx[2], ctx)))) if fx_registry else None
                value = entry.get(fx[3]) if entry else None
                if value is None:
                    raise ValueError('FX slot unavailable')
                return str(value)
            return str(ctx[token] if token in ctx else _expression(token, ctx))
        return re.sub(r'\{([^{}]+)\}', replace, control_path)

    def Available(self, row):
        action = row['action']
        state = self.ownerComp.ResolumeState
        if action == 'reserved':
            return False
        if action == 'param_relative' and '{ACTIVE_CLIP}' in row['control_path']:
            index = state.ActiveClip(row['target']) if state else None
            clip = state.Clips.get((self.LayerFor(row['target']), index), {}) if state else {}
            return bool(clip.get('speed') is not None)
        if action in ('clip_connect', 'clip_select'):
            clip = state.Clips.get((self.LayerFor(row['target']), self.Slot(row))) if state else None
            return bool(clip and clip.get('present'))
        if action == 'column_connect':
            return bool(state and any(c.get('present') for (lid, ci), c in state.Clips.items() if ci == self.Slot(row)))
        if action in ('fx_opacity_toggle', 'fx_bypass_toggle', 'fx_capture_on_value'):
            registry = self.ownerComp.FxRegistry
            entry = registry.Registry.get('%s:%d' % (row['target'], self.Slot(row))) if registry else None
            return bool(entry and entry.get('bypassed_id' if action == 'fx_bypass_toggle' else 'opacity_id'))
        if action == 'fx_page_select':
            return self.Slot(row) <= self.FxPageCount()
        if action == 'clip_bank_select':
            return self.Slot(row) <= self.BankCount()
        if action == 'deck_select':
            return bool(state and self.Slot(row) <= len((state.Composition or {}).get('decks', [])))
        return True

    def ParameterValue(self, row):
        path = self.ResolveTemplate(row['control_path'], row['target'], row['slot'], self.ownerComp.FxRegistry)
        live = self.ownerComp.ResolumeState.Value(path) if self.ownerComp.ResolumeState else None
        if path in self.EncoderValues and time.monotonic() - self.EncoderWritten.get(path, 0) < 0.4:
            return self.EncoderValues[path]
        return float(live) if live is not None else self.EncoderValues.get(path, 0.1 if path.endswith('/speed') else 0.0)

    def LogDryRun(self, row, path, value):
        log = self.ownerComp.op('logic/dryrun_log')
        line = '%s action=%s transport=%s path=%s type=%s value=%s' % (row['id'], row['action'], row['transport'], path, row['value_type'], value)
        if log is not None:
            log.text = '\n'.join((log.text.splitlines() + [line])[-500:])

    def HandleInternal(self, row, value, ext):
        action = row['action']
        if action in ('modifier_shift', 'modifier_select'):
            mod = 'SHIFT' if action == 'modifier_shift' else 'SELECT'
            (self.Modifiers.add if value else self.Modifiers.discard)(mod)
            return
        if not value:
            return
        if action == 'grid_mode_toggle':
            self.SetGridMode('FX' if self.GridMode == 'SESSION' else 'SESSION')
        elif action == 'encoder_page_toggle':
            self.EncoderPage = 'MACRO' if self.EncoderPage == 'OPACITY' else 'OPACITY'
        elif action in ('clip_bank_prev', 'clip_bank_next'):
            self.SetBank(self.Bank + (1 if action.endswith('next') else -1))
        elif action == 'clip_bank_select':
            self.SetBank(self.Slot(row))
        elif action in ('fx_page_prev', 'fx_page_next'):
            self.FxPage = max(1, min(self.FxPageCount(), self.FxPage + (1 if action.endswith('next') else -1)))
        elif action == 'fx_page_select':
            self.FxPage = self.Slot(row)
        elif action == 'surface_panic':
            ext.Panic()
        elif action == 'surface_resync':
            ext.Resync()
        elif action == 'fx_registry_rescan':
            ext.ResolumeState.Rebind()
            ext.FxRegistry.Rescan()
        elif action == 'push_mode_toggle':
            ext.PushIO.SetMode('live' if ext.PushIO.PushMode else 'user')
        elif action == 'ui_toggle':
            panel = self.ownerComp.op('ui')
            panel.par.display = int(not panel.par.display.eval())
        elif action in ('display_toggle', 'display_fit_toggle', 'display_source_toggle') and ext.Display:
            getattr(ext.Display, {'display_toggle': 'ToggleMode', 'display_fit_toggle': 'ToggleFit', 'display_source_toggle': 'ToggleSource'}[action])()

    def OnReceiveMIDI(self, in_type, number, channel, value, ext):
        row = self.Resolve(in_type, number, self.ActiveModifier(), self.GridMode)
        if row is None or row['action'] == 'reserved':
            return row
        action = row['action']
        if action in ('layer_focus', 'comp_focus') and not value:
            if self.HeldFocusTarget == row['target']:
                self.HeldFocusTarget = None
            return row
        if row['transport'] == 'internal' and action != 'fx_capture_on_value':
            if self.Available(row):
                self.HandleInternal(row, value, ext)
            return row
        if action != 'param_absolute' and not value:
            return row
        if not ext.Armed or not self.Available(row):
            return row
        if action in ('fx_opacity_toggle', 'fx_bypass_toggle', 'fx_capture_on_value'):
            slot = self.Slot(row)
            if action == 'fx_opacity_toggle':
                ext.FxRegistry.TogglePad(row['target'], slot, ext.ResolumeOut)
            elif action == 'fx_bypass_toggle':
                ext.FxRegistry.ToggleBypass(row['target'], slot, ext.ResolumeOut)
            else:
                current = ext.ResolumeState.CurrentOpacity(row['target'], slot)
                if current is not None:
                    if self.Cfg('dry_run', '0') == '1':
                        self.LogDryRun(row, row['control_path'], current)
                    else:
                        ext.FxRegistry.SetOnValue(row['target'], slot, current)
            return row
        if action in ('layer_focus', 'comp_focus'):
            self.FocusTarget = self.HeldFocusTarget = row['target']
            if self.LayerFor(row['target']):
                self.LastLayerTarget = row['target']
        if action == 'comp_bypass_toggle' and self.HeldFocusTarget:
            path = self.ResolveTemplate('/composition{FOCUS}/bypassed', focus_override=self.HeldFocusTarget)
        else:
            path = self.ResolveTemplate(row['control_path'], row['target'], row['slot'], ext.FxRegistry)
        if action == 'param_relative':
            scale = self.Cfg('encoder_fine_scale', 0.2, float) if 'SELECT' in self.Modifiers else 1.0
            output = max(0.0, min(1.0, self.ParameterValue(row) + _decode_relative(value) * self.Cfg('encoder_step', 0.005, float) * scale))
            self.EncoderValues[path], self.EncoderWritten[path] = output, time.monotonic()
        elif action == 'param_absolute':
            output = value / 16383.0
        elif action in ('clip_scroll_prev', 'clip_scroll_next'):
            self.ClipScrollX = max(0.0, min(1.0, self.ClipScrollX + (0.1 if action.endswith('next') else -0.1)))
            output = self.ClipScrollX
        elif row['value'] == '0|1':
            output = int(not bool(ext.ResolumeState.Value(path)))
        else:
            output = float(row['value'])
        deck_change = action in ('deck_select', 'deck_prev', 'deck_next')
        if deck_change:
            ext.ResolumeOut.ClearPending()
        ext.ResolumeOut.Send(row, path, output)
        if self.Cfg('dry_run', '0') != '1':
            ext.ResolumeState.Optimistic(path, output)
            if deck_change:
                ext.ResolumeState.Clips.clear()
                run('args[0].FxRegistry.Rescan()', self.ownerComp, delayFrames=15)
        return row

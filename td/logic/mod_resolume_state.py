"""Normalize API state and keep explicit layer identity bindings."""
import json
import re
import time


def normalized(parameter):
    value = parameter.get('value')
    if parameter.get('valuetype') == 'ParamRange' and isinstance(value, (int, float)):
        lo, hi = parameter.get('min', 0), parameter.get('max', 1)
        return (value - lo) / (hi - lo) if hi != lo else 0.0
    return value


class ResolumeState:
    def __init__(self, ownerComp):
        self.ownerComp = ownerComp
        self.Composition = None
        self.Connected = False
        self.LastReceived = 0.0
        self.Clips, self.Layers = {}, {}
        self.DashboardLinks, self.DashboardLinkNames = {}, {}
        self.Parameters, self.ParameterIds, self.TargetNames = {}, {}, {}
        self.ParameterMeta = {}
        self.Pending = {}
        self.PollPending = False
        self.LatestRequest = None
        self.Syncing = False
        self.SyncError = ''
        self.Bindings = dict(ownerComp.fetch('layout7_bindings', {}, search=False))
        self.BindingError = ''

    def LayerIds(self):
        return self.ownerComp.Surface.LayerIds()

    def IsCompositionMessage(self, msg):
        return isinstance(msg, dict) and 'layers' in msg and 'columns' in msg

    def Rebind(self):
        self.Bindings = {}
        self.ownerComp.store('layout7_bindings', {})
        self.BindingError = ''
        self.Pending.clear()
        self.ownerComp.Surface.EncoderValues.clear()
        self.ownerComp.ResolumeOut.ClearPending()

    def Request(self, ext):
        self.PollPending = True
        try:
            self.LatestRequest = self.ownerComp.op('net/web1').request(
                'http://%s:%d/api/v1/composition' % (
                    ext.PushIO.Cfg('resolume_ip', '127.0.0.1'),
                    ext.PushIO.Cfg('resolume_web_port', 8080, int)), 'GET', timeout=8000)
        except Exception as error:
            self.PollPending = False
            if self.Syncing:
                ext.FinishResync(str(error))

    def OnResponse(self, data, request_id, ext, error=''):
        if request_id != self.LatestRequest:
            return
        self.PollPending = False
        success = False
        if not error:
            try:
                success = self.OnMessage(data.decode('utf-8'), ext, authoritative=True)
            except UnicodeError as decode_error:
                error = str(decode_error)
        if self.Syncing:
            ext.FinishResync('' if success else error or self.BindingError or 'Invalid composition response')

    def OnMessage(self, text, ext, authoritative=False):
        if self.Syncing and not authoritative:
            return False
        try:
            msg = json.loads(text)
        except (ValueError, TypeError):
            return False
        if self.IsCompositionMessage(msg):
            self.Composition = msg
            try:
                self._normaliseFromComposition(msg)
                if self.LayerIdsOK() and ext.FxRegistry:
                    ext.FxRegistry.Rebuild(msg)
                elif ext.ResolumeOut:
                    ext.ResolumeOut.ClearPending()
            except (AttributeError, TypeError, ValueError, KeyError) as error:
                self.BindingError = 'Invalid composition state: ' + str(error)
                self.LastReceived = 0.0
                return False
            self.LastReceived = time.monotonic()
            self.SyncError = ''
            return self.LayerIdsOK()
        # Set replies can contain the pre-write value, not authoritative state.
        elif isinstance(msg, dict) and msg.get('type') in ('parameter_update','parameter_get'):
            self._applyParameterUpdate(msg)

    def _walk(self, value, path):
        if not isinstance(value, dict):
            return
        if 'valuetype' in value:
            self.Parameters[path] = normalized(value)
            self.ParameterMeta[path] = value
            if 'id' in value:
                self.ParameterIds[str(value['id'])] = (path, value)
            return
        for key, child in value.items():
            if key in ('layers', 'columns', 'decks', 'clips', 'effects'):
                continue
            part = 'link' + key[5:] if key.startswith('Link ') else key
            self._walk(child, path + '/' + part.lower())

    def _normaliseFromComposition(self, comp):
        self.Clips, self.Layers = {}, {}
        self.Parameters, self.ParameterIds = {}, {}
        self.ParameterMeta = {}
        self.DashboardLinks, self.DashboardLinkNames, self.TargetNames = {}, {}, {}
        self._walk(comp, '/composition')
        self._extractDashboard('COMPOSITION', comp.get('dashboard', {}))
        self.TargetNames['COMPOSITION'] = 'Composition'
        self.BindingError = ''
        try:
            ids = [int(v) for v in self.LayerIds()]
        except ValueError:
            self.BindingError = 'Layer indices must be integers'
            return
        layers = comp.get('layers', [])
        if len(ids) != 7 or len(set(ids)) != len(ids) or any(i < 1 or i > len(layers) for i in ids):
            self.BindingError = 'Seven distinct existing layer indices required'
            return
        actual = {str(index): layers[index - 1].get('id') for index in ids}
        if self.Bindings and self.Bindings != actual:
            self.BindingError = 'Layer identities changed; Shift+Stop to rebind'
        elif not self.Bindings:
            self.Bindings = actual
            self.ownerComp.store('layout7_bindings', actual)
        for pos, index in enumerate(ids, 1):
            layer = layers[index - 1]
            lid, target = str(index), 'LAYER%d' % pos
            self.TargetNames[target] = layer.get('name', {}).get('value', target)
            self.Layers[lid] = {key: layer.get(key, {}).get('value') for key in ('bypassed', 'solo', 'ignorecolumntrigger')}
            self.Layers[lid]['opacity'] = layer.get('video', {}).get('opacity', {}).get('value')
            self._walk(layer, '/composition/layers/' + lid)
            self._extractDashboard(target, layer.get('dashboard', {}))
            for ci, clip in enumerate(layer.get('clips', []), 1):
                state = clip.get('connected', {}).get('value')
                speed = ((clip.get('transport') or {}).get('controls') or {}).get('speed')
                if speed:
                    self._walk(speed, '/composition/layers/%s/clips/%d/transport/position/behaviour/speed' % (lid, ci))
                self.Clips[(lid, ci)] = {'connected': state in ('Connected', 'Connected & previewing'),
                    'present': state is not None and state != 'Empty', 'state': state,
                    'name': clip.get('name', {}).get('value', ''), 'id': clip.get('id'),
                    'speed':speed.get('value') if speed else None}
        for path, (value, until) in list(self.Pending.items()):
            if time.monotonic() >= until:
                self.Pending.pop(path, None)
            else:
                self._applyOptimistic(path, value)

    def _extractDashboard(self, target, dashboard):
        for i in range(1, 9):
            link = dashboard.get('Link %d' % i)
            if link:
                self.DashboardLinks[(target, i)] = normalized(link)
                self.DashboardLinkNames[(target, i)] = link.get('view', {}).get('alternative_name', '')

    def DashboardLinkValue(self, target, index):
        return self.DashboardLinks.get((target, index))

    def DashboardLinkName(self, target, index):
        return self.DashboardLinkNames.get((target, index))

    def Value(self, path):
        return self.Parameters.get(path)

    def ActiveClip(self, target):
        lid = self.ownerComp.Surface.LayerFor(target)
        return next((ci for (layer, ci), clip in self.Clips.items() if layer == lid and clip.get('connected')), None)

    def NativeValue(self, path, value):
        p = self.ParameterMeta.get(path, {})
        return p.get('min', 0) + value * (p.get('max', 1)-p.get('min', 0))

    def Optimistic(self, path, value):
        self.Pending[path] = (value, time.monotonic() + 0.5)
        self._applyOptimistic(path, value)

    def _applyOptimistic(self, path, value):
        self.Parameters[path] = value
        clip = re.fullmatch(r'/composition/layers/(\d+)/clips/(\d+)/connect', path)
        column = re.fullmatch(r'/composition/columns/(\d+)/connect', path)
        clear = re.fullmatch(r'/composition/layers/(\d+)/clear', path)
        if clip or column or clear or path == '/composition/disconnectall':
            layer = clip[1] if clip else clear[1] if clear else None
            index = int(clip[2] if clip else column[1]) if clip or column else None
            for (lid, ci), entry in self.Clips.items():
                if layer and lid != layer:
                    continue
                if column and (self.Layers.get(lid, {}).get('ignorecolumntrigger') or not self.Clips.get((lid, index), {}).get('present')):
                    continue
                entry['connected'] = bool(index == ci and entry['present'])
        link = re.fullmatch(r'/composition(?:/layers/(\d+))?/dashboard/link(\d+)', path)
        if link:
            target = 'COMPOSITION' if link[1] is None else next((t for t in self.ownerComp.Surface.Targets() if self.ownerComp.Surface.LayerFor(t) == link[1]), None)
            if target:
                self.DashboardLinks[(target, int(link[2]))] = value

    def _applyParameterUpdate(self, msg):
        pid = str(msg.get('id', msg.get('parameter', ''))).rsplit('/', 1)[-1]
        entry = self.ParameterIds.get(pid)
        if entry:
            path, parameter = entry
            parameter['value'] = msg.get('value')
            self._applyOptimistic(path, normalized(parameter))
        registry = self.ownerComp.FxRegistry
        if registry:
            for effect in registry.Registry.values():
                if str(effect.get('opacity_id')) == pid:
                    value = normalized(msg)
                    if msg.get('type') == 'parameter_get' and effect.get('_pending_until', 0) > time.time() and value != effect['opacity_value']:
                        continue
                    effect['opacity_value'] = value
                    effect['_padOn'] = effect['opacity_value'] > 0.002
                elif str(effect.get('bypassed_id')) == pid:
                    value = bool(msg.get('value'))
                    if msg.get('type') == 'parameter_get' and effect.get('_pending_until', 0) > time.time() and value != effect['bypassed_value']:
                        continue
                    effect['bypassed_value'] = value

    def CurrentOpacity(self, target, slot):
        registry = self.ownerComp.FxRegistry
        entry = registry.Registry.get('%s:%d' % (target, slot)) if registry else None
        return entry.get('opacity_value') if entry else None

    def LayerIdsOK(self):
        return bool(self.Composition and len(self.Bindings) == 7 and not self.BindingError)

    def Fresh(self):
        return bool(self.LastReceived and time.monotonic() - self.LastReceived < 10.0)

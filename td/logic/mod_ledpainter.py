"""Shared live descriptors for MIDI LEDs, the LCD and browser overlays."""
import re


def _color(target):
    return 'L' + target[5:] if target.startswith('LAYER') else 'COMP'


def Describe(ext, kind, number):
    s, state = ext.Surface, ext.ResolumeState
    row = s.Resolve(kind, number, s.ActiveModifier(), s.GridMode)
    if row is None:
        return None
    target = s.FocusTarget if row['target'] == 'FOCUS' else row['target']
    action = row['action']
    data = {'kind': kind, 'number': number, 'id': row['id'], 'action': action, 'target': target,
            'slot': s.Slot(row), 'available': s.Available(row), 'label': action.replace('_', ' '),
            'palette': 'OFF', 'blink': False, 'active': False, 'value': None, 'path': ''}
    try:
        data['path'] = s.ResolveTemplate(row['control_path'], target, row['slot'], ext.FxRegistry)
    except ValueError:
        pass
    if action == 'reserved':
        data['label'] = ''
        return data
    if action.startswith('clip_') and action in ('clip_connect', 'clip_select'):
        clip = state.Clips.get((s.LayerFor(target), data['slot']), {}) if state else {}
        data.update(label=clip.get('name') or '%s %d' % (_color(target), data['slot']), active=bool(clip.get('connected')))
        data['palette'] = _color(target) + '_FULL' if data['available'] else 'OFF'
        data['blink'] = data['active']
    elif action == 'column_connect':
        clips = [v for (lid, ci), v in state.Clips.items() if ci == data['slot'] and v.get('present')] if state else []
        playing = sum(bool(c.get('connected')) for c in clips)
        data.update(label='Column %d' % data['slot'], active=playing > 0,
                    palette='SCENE_FULL' if playing else 'SCENE_DIM' if clips else 'OFF')
    elif action in ('fx_opacity_toggle', 'fx_bypass_toggle', 'fx_capture_on_value'):
        entry = ext.FxRegistry.Registry.get('%s:%d' % (target, data['slot'])) if ext.FxRegistry else None
        if entry:
            value = entry.get('opacity_value', 0.0)
            data.update(label=entry['label'], value=value, bypassed=bool(entry.get('bypassed_value')), active=value > 0.002)
            data['palette'] = 'FX_BYPASSED' if data['bypassed'] else 'FX_ON' if value >= 0.98 else 'FX_MID' if value > 0.002 else 'FX_OFF'
    elif action == 'param_relative':
        data['value'] = s.ParameterValue(row) if data['available'] else None
        link = re.search(r'dashboard/link(\d+)$', data['path'])
        data['label'] = (state.DashboardLinkName(target, int(link[1])) or 'Link ' + link[1]) if link else 'Speed' if data['path'].endswith('/speed') else 'Opacity' if 'opacity' in data['path'] else 'Tempo' if 'tempo' in data['path'] else 'Transition' if 'transition' in data['path'] else 'Master'
        data['displayValue'] = '--' if data['value'] is None else '%.2fx' % state.NativeValue(data['path'],data['value']) if data['label']=='Speed' else '%d%%' % round(data['value']*100)
    elif action == 'speed_reset':
        data.update(label='Reset ' + _color(target) + ' speed to 1x', value=state.Value(data['path']))
        data['displayValue'] = '%.2fx' % state.NativeValue(data['path'],data['value']) if data['value'] is not None else '--'
        data['palette'] = _color(target) + '_DIM' if data['available'] else 'OFF'
    elif action in ('layer_focus', 'comp_focus'):
        data.update(label=state.TargetNames.get(target, target), active=s.FocusTarget == target)
        data['palette'] = _color(target) + ('_FULL' if data['active'] else '_DIM')
        path = '/composition' + ('/layers/' + s.LayerFor(target) if target != 'COMPOSITION' else '') + '/bypassed'
        if state.Value(path):
            data['palette'] = 'WARN'
    elif action in ('layer_clear', 'comp_disconnect_all', 'layer_solo_toggle', 'tempo_resync'):
        data['label'] = 'Clear ' + _color(target) if action == 'layer_clear' else 'Disconnect all' if action == 'comp_disconnect_all' else 'Solo ' + _color(target) if action == 'layer_solo_toggle' else 'Tempo resync'
        data['active'] = bool(state.Value(data['path'])) if action == 'layer_solo_toggle' else False
        data['palette'] = 'SOLO' if data['active'] else _color(target) + '_DIM'
    elif action in ('clip_bank_select', 'fx_page_select', 'deck_select'):
        data['label'] = ('Bank ' if action == 'clip_bank_select' else 'FX page ' if action == 'fx_page_select' else 'Deck ') + str(data['slot'])
        data['active'] = data['slot'] == (s.Bank if action == 'clip_bank_select' else s.FxPage if action == 'fx_page_select' else -1)
        if action == 'deck_select' and data['available']:
            deck = state.Composition['decks'][data['slot'] - 1]
            data['active'] = bool(deck.get('selected', {}).get('value'))
            data['label'] = deck.get('name', {}).get('value', data['label'])
        data['palette'] = ('DECK_' if action == 'deck_select' else 'BANK_') + ('FULL' if data['active'] else 'DIM') if data['available'] else 'OFF'
    else:
        active = {'modifier_shift': 'SHIFT' in s.Modifiers, 'modifier_select': 'SELECT' in s.Modifiers,
                  'grid_mode_toggle': s.GridMode == 'FX', 'encoder_page_toggle': s.EncoderPage == 'MACRO',
                  'fx_page_prev': s.FxPage > 1, 'fx_page_next': s.FxPage < s.FxPageCount(),
                  'clip_bank_prev': s.Bank > 1, 'clip_bank_next': s.Bank < s.BankCount()}
        data['active'] = active.get(action, False)
        data['palette'] = 'WHITE_FULL' if data['active'] else 'WHITE_DIM'
        if action == 'surface_resync':
            data.update(label='Syncing' if state.Syncing else 'Resync failed' if state.SyncError else 'Resync state', active=state.Syncing)
            data['palette'] = 'WARN' if state.SyncError else 'WHITE_FULL' if state.Syncing else 'WHITE_DIM'
        elif action == 'surface_hard_reset':
            data.update(label='Hard reset: rebind + rebuild', active=True)
            data['palette'] = 'WHITE_FULL'
        elif action == 'comp_bypass_toggle':
            target = s.HeldFocusTarget or 'COMPOSITION'
            path = '/composition' + ('/layers/' + s.LayerFor(target) if target != 'COMPOSITION' else '') + '/bypassed'
            data.update(target=target, path=path, label='Mute ' + _color(target), active=bool(state.Value(path)))
            data['palette'] = 'WARN' if data['active'] else 'COMP_DIM'
        elif number in (29, 61, 85, 86, 89):
            data['palette'] = 'COMP_DIM'
    return data


def Paint(ext):
    if not ext.Surface or not ext.PushIO or not ext.ResolumeState:
        return {}
    controls = {(k[0], k[1]) for k in ext.Surface._index}
    out = {}
    for kind, number in controls:
        if kind not in ('note','cc') or (kind == 'cc' and number in (14,15,79,*range(71,79))):
            continue
        data = Describe(ext, kind, number)
        if not data:
            continue
        index = ext.PushIO.PaletteIndex(data['palette'])
        out[(kind, number)] = (0,index) if data['blink'] else index
    return out


def Snapshot(ext):
    s, state = ext.Surface, ext.ResolumeState
    palette = s.ownerComp.op('config/map_palette')
    colors = {palette[r,'name'].val: [int(palette[r,c].val) for c in ('r','g','b')] for r in range(1,palette.numRows)}
    targets = []
    start = (s.Bank-1)*8+1
    for target in s.Targets():
        lid = s.LayerFor(target)
        clips = [dict(c,index=ci) for (layer,ci),c in state.Clips.items() if layer == lid]
        effects = [dict(e) for e in ext.FxRegistry.Registry.values() if e['target'] == target] if ext.FxRegistry else []
        prefix = '/composition' + ('/layers/' + lid if lid else '')
        targets.append({'target':target,'short':_color(target),'name':state.TargetNames.get(target,target),
                        'layerIndex':int(lid) if lid else None,'color':colors.get(_color(target)+'_FULL',[255,255,255]),
                        'opacity':state.Value(prefix+'/video/opacity'), 'bypassed':bool(state.Value(prefix+'/bypassed')),
                        'solo':bool(state.Value(prefix+'/solo')), 'playing':[c for c in clips if c['connected']],
                        'loaded':sum(c['present'] for c in clips),'visibleLoaded':sum(c['present'] for c in clips if start<=c['index']<start+8),
                        'effects':sorted(effects,key=lambda e:e['slot'])})
    decks = (state.Composition or {}).get('decks', [])
    deck = next((d.get('name',{}).get('value','') for d in decks if d.get('selected',{}).get('value')), '')
    return {'armed':ext.Armed,'syncing':state.Syncing,'syncError':state.SyncError,'health':dict(ext.Health),'gridMode':s.GridMode,'bank':s.Bank,'bankCount':s.BankCount(),
            'clipRange':[start,start+7],'fxPage':s.FxPage,'fxPageCount':s.FxPageCount(),'encoderPage':s.EncoderPage,
            'focus':s.FocusTarget,'modifiers':sorted(s.Modifiers),'bindingError':state.BindingError,
            'bindingNotice':state.Notice(),'palette':colors,
            'targets':targets,'deck':deck,'deckCount':len(decks),'bpm':(state.Composition or {}).get('tempocontroller',{}).get('tempo',{}).get('value',0),
            'master':state.Value('/composition/master'),'composition':(state.Composition or {}).get('name',{}).get('value',''),
            'pads':[Describe(ext,'note',36+(7-r)*8+c) for r in range(8) for c in range(8)],
            'encoders':[Describe(ext,'cc',cc) for cc in range(71,79)],
            'upper':[Describe(ext,'cc',cc) for cc in range(102,110)],
            'lower':[Describe(ext,'cc',cc) for cc in range(20,28)],
            'right':[Describe(ext,'cc',cc) for cc in range(36,44)],
            'buttons':[Describe(ext,'cc',cc) for cc in sorted({k[1] for k in s._index if k[0]=='cc'})
                       if cc not in (*range(20,28),*range(36,44),*range(71,79),*range(102,110),14,15,79)]}

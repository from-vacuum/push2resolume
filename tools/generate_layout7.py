#!/usr/bin/env python3
"""Generate repeated layout mappings; retain the rig's unrelated controls."""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config'


def read(name):
    with (CONFIG / name).open(newline='') as stream:
        return list(csv.DictReader(stream))


def write(name, rows):
    with (CONFIG / name).open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def generate():
    old = read('map_controls.csv')
    fields = list(old[0])
    rows = []
    def add(id, zone, number, action, target='', path='', slot='', modifier='', mode='ANY',
            transport='internal', value='1', vtype='int', palette='', kind='cc', notes=''):
        row = dict.fromkeys(fields, '')
        row.update(id=id, zone=zone, in_type=kind, in_number=str(number), in_channel='1',
                   modifier=modifier, grid_mode=mode, action=action, target=target, slot=str(slot),
                   transport=transport, control_path=path, value_type=vtype, value=value,
                   led_palette=palette, notes=notes)
        rows.append(row)
    targets = ['LAYER%d' % i for i in range(1, 8)] + ['COMPOSITION']
    for r in range(1, 9):
        for c in range(1, 9):
            note = 36 + (8-r)*8+c-1
            slot = 'bank*8+%d' % c
            if r < 8:
                target = 'LAYER%d' % (8-r)
                prefix = '/composition/layers/{L%d}/clips/{%s}' % (8-r, slot)
                for mod, action in (('', 'clip_connect'), ('SELECT', 'clip_select')):
                    add('PAD_S%d_T%d_%s' % (r,c,action.upper()), 'GRID_CLIP', note, action, target,
                        prefix + ('/connect' if not mod else '/select'), slot, mod, 'SESSION', 'osc',
                        palette='OFF|L%d_DIM|L%d_FULL' % (8-r,8-r), kind='note')
            else:
                add('PAD_S8_T%d_COLUMN' % c, 'GRID_COLUMN', note, 'column_connect', 'COMPOSITION',
                    '/composition/columns/{%s}/connect' % slot, slot, mode='SESSION', transport='osc',
                    palette='OFF|SCENE_DIM|SCENE_FULL', kind='note')
            target, slot = targets[c-1], 'fx_page*8+%d' % r
            for mod, action, field in (('', 'fx_opacity_toggle', 'opacity_id'), ('SHIFT', 'fx_bypass_toggle', 'bypassed_id'), ('SELECT', 'fx_capture_on_value', 'on_value')):
                capture = mod == 'SELECT'
                path = 'fx[%s:%s].%s' % (target,slot,field)
                add('PAD_S%d_T%d_%s' % (r,c,action.upper()), 'GRID_FX', note, action, target,
                    path if capture else '/parameter/by-id/{'+path+'}', slot, mod, 'FX',
                    'internal' if capture else 'ws', 'current opacity' if capture else '0|1' if mod else '0.0<->on_value',
                    'bool_as_int' if mod == 'SHIFT' else 'float', 'OFF|FX_OFF|FX_MID|FX_ON|FX_BYPASSED', 'note',
                    'Paged slot; immediate opacity toggle, Shift bypass, Select capture current opacity.')
    for i, target in enumerate(targets, 1):
        prefix = '/composition' + ('/layers/{L%d}' % i if i < 8 else '')
        color = 'L%d' % i if i < 8 else 'COMP'
        add('LOWER_%d' % i, 'LOWER_ROW',19+i,'layer_focus' if i < 8 else 'comp_focus',target,prefix+'/select',transport='osc',palette=color+'_DIM|'+color+'_FULL')
        speed_path = prefix + ('/clips/{ACTIVE_CLIP}/transport/position/behaviour/speed' if i < 8 else '/speed')
        add('LOWER_%d_SHIFT' % i,'LOWER_ROW',19+i,'speed_reset',target,speed_path,modifier='SHIFT',transport='internal',value='1.0',vtype='float',palette=color+'_DIM|'+color+'_FULL',notes='Native WebSocket reset by parameter ID; read back actual speed, preserve focus.')
        add('UPPER_%d' % i,'UPPER_ROW',101+i,'layer_clear' if i < 8 else 'comp_disconnect_all',target,prefix+'/clear' if i<8 else '/composition/disconnectall',transport='osc',palette=color+'_DIM|'+color+'_FULL')
        add('UPPER_%d_SHIFT' % i,'UPPER_ROW',101+i,'layer_solo_toggle' if i<8 else 'tempo_resync',target,prefix+'/solo' if i<8 else '/composition/tempocontroller/resync',modifier='SHIFT',transport='osc',value='0|1' if i<8 else '1',palette='OFF|SOLO')
        for mod, suffix in (('', '/video/opacity'), ('SHIFT','/speed')):
            if mod and i < 8:
                suffix = '/clips/{ACTIVE_CLIP}/transport/position/behaviour/speed'
            add('ENC_%d_SESSION%s' % (i,'_SHIFT' if mod else ''),'ENCODER',70+i,'param_relative',target,prefix+suffix,modifier=mod,mode='SESSION',transport='osc',value='0.0-1.0',vtype='float')
        add('ENC_%d_FX' % i,'ENCODER',70+i,'param_relative','FOCUS','/composition{FOCUS}/dashboard/link%d' % i,mode='FX',transport='osc',value='0.0-1.0',vtype='float')
        add('RIGHT_%d' % i,'RIGHT_COL',35+i,'clip_bank_select','SURFACE','surface.bank','bank_group+%d' % i,mode='SESSION',palette='BANK_DIM|BANK_FULL')
        add('RIGHT_%d_FX' % i,'RIGHT_COL',35+i,'fx_page_select' if i<=2 else 'reserved','SURFACE','surface.fx_page',i,mode='FX',palette='BANK_DIM|BANK_FULL' if i<=2 else 'OFF')
        add('RIGHT_%d_DECK' % i,'RIGHT_COL',35+i,'deck_select','COMPOSITION','/composition/decks/%d/select' % i,i,'SHIFT','ANY','osc',palette='DECK_DIM|DECK_FULL')
    retained = [r for r in old if r['zone'] in ('GLOBAL','ENCODER_TOUCH','TOUCHSTRIP') or r['id'] in ('ENC_TEMPO','ENC_SWING','ENC_MASTER')]
    for row in retained:
        if row['action'] in ('clip_bank_prev','clip_bank_next','fx_page_prev','fx_page_next'):
            continue
        if row['id'] == 'MIX':
            row.update(action='encoder_page_toggle',transport='internal',target='SURFACE',control_path='surface.encoder_page',grid_mode='SESSION',led_palette='WHITE_DIM|WHITE_FULL',notes='Toggle Session encoder page: Opacity / Macro.')
        if row['id'] in ('DEVICE', 'DEVICE_PARAMBANK'):
            row.update(action='surface_resync',transport='internal',target='SURFACE',control_path='',notes='Device: read authoritative Resolume state and repaint Push; preserve view and bindings.',led_palette='WHITE_DIM|WHITE_FULL')
        if row['id'] == 'ENC_SWING':
            row['control_path'] = '/composition/layers/{LAST_LAYER}/transition/duration'
        if row['id'] == 'MUTE':
            row['notes'] = 'CC60: Composition blackout. Hold a lower target button to bypass that target.'
        rows.append(row)
    for cc, direction in ((44,'prev'),(45,'next')):
        for mode, action in (('SESSION','clip_bank_'+direction),('FX','fx_page_'+direction)):
            add(('LEFT' if cc==44 else 'RIGHT')+'_'+mode,'GLOBAL',cc,action,'SURFACE',mode=mode,palette='WHITE_DIM|WHITE_FULL')
    write('map_controls.csv', rows)
    cfg = read('cfg_general.csv')
    changes = {'layer_ids':('1,2,3,4,5,6,7','Seven 1-based Resolume layer indices; Composition is separate.'),
               'clips_per_bank':('8','One row per layer, eight clips per bank.'),
               'bank_count':('16','Baseline banks of eight; expands for longer decks.'),
               'fx_slots_per_target':('16','Logical slots per target; eight targets, two pages of eight.')}
    for row in cfg:
        if row['key'] in changes:
            row['value'], row['notes'] = changes[row['key']]
    if not any(r['key']=='fx_visible_slots' for r in cfg):
        cfg.append(dict(key='fx_visible_slots',value='8',notes='Visible FX slots per target on each page.'))
    write('cfg_general.csv',cfg)
    palette = [r for r in read('map_palette.csv') if not r['name'].startswith(('L4_','L5_','L6_','L7_'))]
    for layer, rgb in enumerate(((80,230,65),(255,215,30),(90,115,255),(255,70,65)),4):
        for level, scale, white in (('DIM',0.16,18),('MID',0.47,55),('FULL',1.0,127)):
            palette.append(dict(palette_index=str(43+(layer-4)*3+('DIM','MID','FULL').index(level)),name='L%d_%s'%(layer,level),
                                r=str(round(rgb[0]*scale)),g=str(round(rgb[1]*scale)),b=str(round(rgb[2]*scale)),w=str(white),purpose='Layer %d %s'%(layer,level.lower())))
    write('map_palette.csv',palette)
    print('Generated',len(rows),'controls and',len(palette),'palette entries')


if __name__ == '__main__':
    generate()

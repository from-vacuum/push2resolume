#!/usr/bin/env python3
"""Validate the Push 2 -> TouchDesigner -> Resolume mapping tables.

Run after ANY edit to config/*.csv:   python3 verify.py

Note on FX: there is deliberately NO check that effect names are unique or
declared anywhere. Effects are discovered at runtime and driven by Resolume
parameter id, so duplicates (goo, goo2, goo3) and renames are non-events.
"""
import csv, collections, re, sys, os, runpy

expression = runpy.run_path(os.path.join(os.path.dirname(__file__), 'td/logic/mod_surface.py'))['_expression']

CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config')

# Ableton Push 2 ground truth, from doc/Push2-map.json in Ableton/push-interface
PADS      = set(range(36, 100))
ENC_TOUCH = set(range(0, 11))
RGB_CC    = {29, 60, 61, 85, 86, 89} | set(range(20, 28)) | set(range(36, 44)) | set(range(102, 110))
WHITE_CC  = {3, 9, 28, 30, 31, 35, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58,
             59, 62, 63, 87, 88, 90, 110, 111, 112, 113, 116, 117, 118, 119}
ENC_CC    = {14, 15, 71, 72, 73, 74, 75, 76, 77, 78, 79}
VALID_CC  = RGB_CC | WHITE_CC | ENC_CC

TRANSPORTS = {'osc', 'ws', 'internal', 'context', ''}
GRID_MODES = {'ANY', 'SESSION', 'FX'}

fails = []
def check(name, bad, show=8):
    if bad:
        fails.append(name)
        print(f'FAIL  {name}')
        for b in list(bad)[:show]:
            print(f'        {b}')
        if len(bad) > show:
            print(f'        ... and {len(bad)-show} more')
    else:
        print(f'ok    {name}')

rows = list(csv.DictReader(open(os.path.join(CFG, 'map_controls.csv'))))
pal  = list(csv.DictReader(open(os.path.join(CFG, 'map_palette.csv'))))
cfg  = {r['key']: r['value'] for r in csv.DictReader(open(os.path.join(CFG, 'cfg_general.csv')))}
pins = list(csv.DictReader(open(os.path.join(CFG, 'fx_pins.example.csv'))))
palnames = {r['name'] for r in pal}
print(f'\nmap_controls.csv: {len(rows)} rows\n')

# 1 -- one action per (input, modifier, mode)
c = collections.Counter((r['in_type'], r['in_number'], r['modifier'], r['grid_mode']) for r in rows)
check('no duplicate (type, number, modifier, mode)', [k for k, v in c.items() if v > 1])

# 2 -- a mode-agnostic mapping must not also be claimed by a specific grid mode
byctl = collections.defaultdict(set)
for r in rows:
    byctl[(r['in_type'], r['in_number'], r['modifier'])].add(r['grid_mode'])
check('no ANY-mode vs grid-mode clash',
      [(k, sorted(v)) for k, v in byctl.items() if 'ANY' in v and len(v) > 1])

# 3 -- every control number exists on the hardware
bad = []
for r in rows:
    n = int(r['in_number'])
    if r['in_type'] == 'note' and n not in PADS and n not in ENC_TOUCH: bad.append((r['id'], 'note', n))
    if r['in_type'] == 'cc'   and n not in VALID_CC:                    bad.append((r['id'], 'cc', n))
check('all control numbers exist in Push2-map.json', bad)

# 4 -- vocabularies closed
check('grid_mode vocabulary', sorted({r['grid_mode'] for r in rows} - GRID_MODES))
check('transport vocabulary', sorted({r['transport'] for r in rows} - TRANSPORTS))

# 5 -- palette names defined, white-only buttons never given an RGB colour
bad = []
for r in rows:
    if not r['led_palette']: continue
    n = int(r['in_number'])
    for p in r['led_palette'].split('|'):
        if p not in palnames:
            bad.append((r['id'], 'undefined palette name', p)); continue
        if r['in_type'] == 'cc':
            if n in WHITE_CC and p not in ('OFF', 'WHITE_DIM', 'WHITE_FULL'):
                bad.append((r['id'], f'CC{n} white-only, given RGB palette', p))
            if n in RGB_CC and p in ('WHITE_DIM', 'WHITE_FULL'):
                bad.append((r['id'], f'CC{n} RGB, given white palette', p))
check('palette assignments match RGB/white capability', bad)

# 6 -- each grid mode covers all 64 pads exactly once
bad = []
for mode in ('SESSION', 'FX'):
    ns = [int(r['in_number']) for r in rows
          if r['grid_mode'] == mode and r['in_type'] == 'note' and r['modifier'] == '']
    if set(ns) != PADS or len(ns) != 64:
        bad.append((mode, f'{len(ns)} pads, {len(set(ns))} unique, complete={set(ns)==PADS}'))
check('SESSION and FX each cover pads 36-99 exactly once', bad)

# 7 -- OSC address shape and no stray whitespace (a real cause of dead controls)
oscpat = re.compile(r'^/(composition|smptecontroller|application|audiodevicemanager)(/[A-Za-z0-9{}*+\-_]+)*$')
check('OSC paths well formed',
      sorted({r['control_path'] for r in rows
              if r['transport'] == 'osc' and not oscpat.match(r['control_path'].replace('{FOCUS}', '/layers/1'))}))
wspat = re.compile(r'^/parameter/by-id/\{[^}]+\}$')
check('WS paths are parameter-by-id templates',
      sorted({r['control_path'] for r in rows
              if r['transport'] == 'ws' and not wspat.match(r['control_path'])}))
check('no whitespace-padded control paths',
      [r['id'] for r in rows if r['control_path'] != r['control_path'].strip()])

# 8 -- typing. Resolume remaps a float across a parameter's whole native range,
#      so a float 1.0 on an int param means MAXIMUM, not one.
ALLOWED_FLOAT_TRIGGERS = {'/composition/tempocontroller/tempomultiplytwo',
                          '/composition/tempocontroller/tempodividetwo'}
check('OSC triggers/toggles typed int',
      [(r['id'], r['value_type']) for r in rows
       if r['transport'] == 'osc' and r['value'] in ('1', '0|1') and r['value_type'] != 'int'])
check('float-typed OSC triggers are only the two known Resolume type bugs',
      [(r['id'], r['control_path']) for r in rows
       if r['transport'] == 'osc' and r['value_type'] == 'float' and r['value'] == '1.0'
       and r['action'] != 'speed_reset'
       and r['control_path'] not in ALLOWED_FLOAT_TRIGGERS])
check('speed reset uses native API reset dispatch',
      [(r['id'], r['control_path']) for r in rows if r['action'] == 'speed_reset'
       and (r['transport'] != 'internal' or not r['control_path'].endswith('/speed'))])
check('WS booleans marked bool_as_int',
      [(r['id'], r['value_type']) for r in rows
       if r['transport'] == 'ws' and r['value'] == '0|1' and r['value_type'] != 'bool_as_int'])

# 9 -- every FX pad slot is reachable and within the configured budget
fxslots = cfg.get('fx_slots_per_target', '16')
pages = int(fxslots) // int(cfg['fx_visible_slots'])
bad = [(r['id'], r['slot']) for r in rows if r['zone'] == 'GRID_FX'
       for page in range(pages) if not 1 <= expression(r['slot'], {'fx_page': page}) <= int(fxslots)]
check(f'FX pad slots within 1-{fxslots}', bad)
fxpairs = {(r['target'], expression(r['slot'], {'fx_page': page})) for r in rows
           if r['zone'] == 'GRID_FX' and r['modifier'] == '' for page in range(pages)}
check('FX pages expose 8 targets x 16 unique slots',
      [] if len(fxpairs) == 8 * int(fxslots) else [f'{len(fxpairs)} pairs, expected {8*int(fxslots)}'])

# 10 -- palette table integrity
bad = [(r['name'], k, r[k]) for r in pal for k in ('r', 'g', 'b', 'w')
       if not (r[k].isdigit() and 0 <= int(r[k]) <= 255)]
bad += [(r['name'], 'index', r['palette_index']) for r in pal
        if not (r['palette_index'].isdigit() and 0 <= int(r['palette_index']) <= 127)]
bad += [('duplicate index', k) for k, v in collections.Counter(r['palette_index'] for r in pal).items() if v > 1]
check('palette values in range, indices unique', bad)

# 11 -- pin file: keys unique, slots in range, on_value normalised.
#       Duplicate effect NAMES are expected and legal; duplicate pin KEYS are not.
check('pin keys unique', [k for k, v in collections.Counter(p['pin_key'] for p in pins).items() if v > 1])
check('pin (target, slot) unique',
      [k for k, v in collections.Counter((p['target'], p['slot']) for p in pins).items() if v > 1])
check('pin key format target|name|ordinal',
      [p['pin_key'] for p in pins if not re.match(r'^[A-Z0-9]+\|[^|]+\|\d+$', p['pin_key'])])
check('pin key target matches target column',
      [(p['pin_key'], p['target']) for p in pins if p['pin_key'].split('|')[0] != p['target']])
check('pin on_value in 0.0-1.0',
      [(p['pin_key'], p['on_value']) for p in pins if not 0.0 <= float(p['on_value']) <= 1.0])

# 12 -- config sanity
bad = []
if int(cfg['tick_hz']) > 30: bad.append(('tick_hz', cfg['tick_hz'], 'Resolume lags above ~30 Hz per stream'))
if cfg['fx_transport'] not in ('ws_param_id', 'osc_name_guess', 'off'): bad.append(('fx_transport', cfg['fx_transport']))
if cfg['state_source'] not in ('websocket', 'rest_poll', 'none'):       bad.append(('state_source', cfg['state_source']))
if cfg['fx_transport'] == 'ws_param_id' and cfg['state_source'] == 'none':
    bad.append(('fx_transport needs a webserver connection', 'state_source=none'))
if int(cfg['fx_visible_slots']) * 8 != 64: bad.append(('fx_visible_slots x 8 must fill the 64-pad grid', cfg['fx_visible_slots']))
if len(set(cfg['layer_ids'].split(','))) != 7: bad.append(('seven distinct layer indices required', cfg['layer_ids']))
check('config values coherent', bad)

print()
for z, n in collections.Counter(r['zone'] for r in rows).most_common(): print(f'  {z:16s} {n}')
print()
for t, n in collections.Counter(r['transport'] for r in rows).most_common():
    print(f'  transport {t or "(none)":10s} {n}')
print()
if fails:
    print(f'{len(fails)} CHECK(S) FAILED: ' + ', '.join(fails)); sys.exit(1)
print('ALL CHECKS PASSED')

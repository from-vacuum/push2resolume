"""Apply only speed-reset sources/rows, preserving concurrent MIDI changes."""
import csv
import argparse
import json
from pathlib import Path
from envoy_call import call

ROOT = Path(__file__).resolve().parents[1]


def deploy(before_path):
    before = json.loads((ROOT/before_path).read_text())['result']['sources']
    sources = {path:(ROOT/'td'/(path+'.py')).read_text() for path in before}
    with (ROOT/'config/map_controls.csv').open(newline='') as stream:
        rows = [r for r in csv.DictReader(stream) if r['action']=='speed_reset']
    code = 'BEFORE='+repr(before)+'\nSOURCES='+repr(sources)+'\nROWS='+repr(rows)+'\n'
    code += '''
import sys
root=opex('/project1/PUSH_RESOLUME')
for path,source in SOURCES.items():
    assert root.op(path).text in (BEFORE[path],source), 'Concurrent source edit: '+path
table=root.op('config/map_controls')
columns=[table[0,c].val for c in range(table.numCols)]
def signature(row):
    return tuple(row[k] for k in ('in_type','in_number','modifier','grid_mode'))
existing={signature({c:table[r,c].val for c in columns}):r for r in range(1,table.numRows)}
for row in ROWS:
    index=existing.get(signature(row))
    assert index is None or table[index,'action'].val=='speed_reset', 'Shift mapping already assigned'
for path,source in SOURCES.items():
    if root.op(path).text != source:
        root.op(path).text=source
for row in ROWS:
    index=existing.get(signature(row))
    if index is None:
        table.appendRow([row.get(c,'') for c in columns])
    else:
        for c in columns:
            table[index,c]=row.get(c,'')
old=root.Surface
surface=root.op('logic/mod_surface').module.Surface(root)
for key,value in old.__dict__.items():
    if key not in ('_cfg','_index') and not callable(value):
        setattr(surface,key,value)
root.extensions[0].Surface=surface
for name,path in (('ResolumeOut','logic/mod_resolume_out'),('ResolumeState','logic/mod_resolume_state')):
    if path in SOURCES:
        old=getattr(root,name)
        helper=getattr(root.op(path).module,name)(root)
        helper.__dict__.update({k:v for k,v in old.__dict__.items() if not callable(v)})
        setattr(root.extensions[0],name,helper)
runtime=sys.modules.get('_push2_runtime')
if runtime and str(root.id) in runtime.__dict__:
    runtime.__dict__[str(root.id)]['surface']=surface
    runtime.__dict__[str(root.id)]['state']=root.ResolumeState
root.PushIO.InvalidateLeds()
root.FullRedraw()
result={'mapped':len(ROWS),'controls':table.numRows-1,'mode':surface.GridMode,'focus':surface.FocusTarget}
'''
    print(json.dumps(call('execute_python', {'code':code}),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--before',default='checkpoints/speed-reset-before.json')
    deploy(parser.parse_args().before)

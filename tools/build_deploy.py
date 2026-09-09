#!/usr/bin/env python3
"""Build an atomic Envoy source/config update without file IO on TD's thread."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    sources = {str(p.relative_to(ROOT / 'td')).removesuffix('.py'): p.read_text()
               for p in (ROOT / 'td').rglob('*.py')}
    tables = {}
    for name in ('map_controls', 'map_palette', 'cfg_general'):
        with (ROOT / 'config' / (name + '.csv')).open(newline='') as stream:
            tables['config/' + name] = list(csv.reader(stream))
    code = '''def deploy():
    root = opex('/project1/PUSH_RESOLUME')
    root.ResolumeOut.ClearPending() if hasattr(root.ResolumeOut, 'ClearPending') else None
    for path, source in SOURCES.items():
        if root.op(path).text != source:
            root.op(path).text = source
    for path, rows in TABLES.items():
        table = root.op(path)
        table.clear()
        for row in rows:
            table.appendRow(row)
    run("args[0].extensions[0]._postInit()", root, delayFrames=10)
    run("args[0].Surface.LoadCfg(); args[0].Surface.BuildIndex(); args[0].PushIO.WritePalette(); args[0].PushIO.ReapplyPalette(); args[0].PushIO._ledCache.clear()", root, delayFrames=15)
    return {'project': project.name, 'source_count': len(SOURCES), 'status': 'applied; initialization settles over 15 frames'}
result = deploy()
'''
    code = 'SOURCES = ' + repr(sources) + '\nTABLES = ' + repr(tables) + '\n' + code
    path = ROOT / 'checkpoints' / 'layout7-deploy.json'
    path.write_text(json.dumps({'code': code}))
    path.with_name('layout7-deploy-batch.json').write_text(json.dumps({'operations':[
        {'tool':'execute_python','params':{'code':code}},
        {'tool':'get_op_errors','params':{'op_path':'/project1/PUSH_RESOLUME','recurse':True}}]}))
    print(path)


if __name__ == '__main__':
    build()

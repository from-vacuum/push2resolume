"""Scoped startup/Refresh deployment; refuses to overwrite changed live sources."""
import json
from pathlib import Path

from envoy_call import call

ROOT = Path(__file__).resolve().parents[1]


def main():
    before = json.loads((ROOT / 'checkpoints/startup-before.json').read_text())['result']['sources']
    paths = ('display/mod_display', 'logic/exec_boot', 'logic/ext_PushResolume')
    sources = {path: (ROOT / 'td' / (path + '.py')).read_text() for path in paths}
    callback = (ROOT / 'td/logic/parexec_refresh.py').read_text()
    code = 'BEFORE=' + repr(before) + '\nSOURCES=' + repr(sources) + '\nCALLBACK=' + repr(callback) + '\n'
    code += '''
root=opex('/project1/PUSH_RESOLUME')
for path, source in SOURCES.items():
    assert root.op(path).text in (BEFORE[path], source), 'Concurrent source edit: '+path
callback=opex(root.path+'/logic/parexec_refresh')
assert not callback.par.active.eval() or callback.text == CALLBACK, 'Refresh callback already changed'
display=root.ext.PushResolume.Display
root.op('display/mod_display').text=SOURCES['display/mod_display']
# Upgrade the existing helper too: outstanding callbacks must honor StopHelper.
display.__class__=root.op('display/mod_display').module.Display
display._stopping=False
display._connectGeneration=0
for path in ('logic/exec_boot','logic/ext_PushResolume'):
    root.op(path).text=SOURCES[path]
callback.text=CALLBACK
callback.par.op=root
callback.par.pars='Refresh'
callback.par.valuechange=0
callback.par.onpulse=1
callback.par.builtin=0
callback.par.active=1
root.initializeExtensions()
result={'sources':list(SOURCES),'callback':callback.path,'refresh':root.par.Refresh.name}
'''
    print(json.dumps(call('execute_python', {'code': code}), indent=2))


if __name__ == '__main__':
    main()

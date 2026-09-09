"""Install bounded, temporary main-thread timing hooks through Envoy."""
from envoy_call import call

CODE = '''
import time,json
root = opex('/project1/PUSH_RESOLUME')
trace = []
root.Surface.LatencyTrace = trace
def wrap(obj, name, label, describe):
    original = getattr(obj, name)
    def traced(*args, **kwargs):
        start = time.perf_counter()
        details = describe(args)
        try:
            return original(*args, **kwargs)
        finally:
            if details is not None:
                trace.append(dict(event=label, at=start, ms=(time.perf_counter()-start)*1000, details=details))
            del trace[:-160]
    setattr(obj, name, traced)
wrap(root.Surface, 'OnReceiveMIDI', 'midi', lambda a: [a[0],a[1],a[3],root.Surface.GridMode,sorted(root.Surface.Modifiers)])
wrap(root.ResolumeOut, '_sendWS', 'ws_send', lambda a: list(a))
wrap(root.ResolumeState, '_applyParameterUpdate', 'ws_ack', lambda a: a[0])
def feedback(number, expected):
    row=root.Surface.Resolve('note',number,'','FX')
    key='%s:%d' % (row['target'],root.Surface.Slot(row))
    entry=root.FxRegistry.Registry.get(key,{})
    snapshot=json.loads(root.Display._textSignature or '{}')
    lcd=next((e.get('opacity_value') for t in snapshot.get('targets',[]) for e in t['effects'] if e['target']==row['target'] and e['slot']==root.Surface.Slot(row)),None)
    trace.append(dict(event='feedback',at=time.perf_counter(),details=dict(number=number,expected=expected,state=entry.get('opacity_value'),led=root.PushIO._ledCache.get(('note',number)),lcd_submitted=lcd)))
    del trace[:-160]
original_input=root.Surface.OnReceiveMIDI
def input_with_feedback(*args,**kwargs):
    row=original_input(*args,**kwargs)
    if row and args[3] and row['action']=='fx_opacity_toggle':
        entry=root.FxRegistry.Registry.get('%s:%d'%(row['target'],root.Surface.Slot(row)),{})
        expected=entry.get('opacity_value')
        run('args[0](args[1],args[2])',feedback,args[1],expected,delayFrames=4)
        run('args[0](args[1],args[2])',feedback,args[1],expected,delayFrames=12)
    return row
root.Surface.OnReceiveMIDI=input_with_feedback
root.Surface.TraceStarted = time.perf_counter()
result = {'trace':'installed; no parameter writes'}
'''

if __name__ == '__main__':
    print(call('execute_python', {'code': CODE}))

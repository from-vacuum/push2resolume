import csv
import json
from pathlib import Path
from unittest.mock import patch
import runpy
import tempfile
import time
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Table:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.text = ''
        self.messages = []
    @property
    def numRows(self): return len(self.rows)
    @property
    def numCols(self): return len(self.rows[0]) if self.rows else 0
    def __getitem__(self, pair):
        row, col = pair
        if isinstance(col, str): col = self.rows[0].index(col)
        return types.SimpleNamespace(val=str(self.rows[row][col]))
    def clear(self): self.rows.clear()
    def appendRow(self, row): self.rows.append(row)
    def sendOSC(self, path, values, **kwargs): self.messages.append((path,values))
    def sendText(self, text): self.messages.append(json.loads(text))


class Owner:
    def __init__(self):
        self.nodes = {}
        for name in ('cfg_general','map_controls','map_palette'):
            with (ROOT/'config'/(name+'.csv')).open(newline='') as f:
                self.nodes['config/'+name] = Table(list(csv.reader(f)))
        for path in ('config/fx_registry','logic/dryrun_log','net/ws1','net/oscout1'):
            self.nodes[path] = Table()
        self.storage = {}
        self.Armed = True
        self.ResolumeState = self.FxRegistry = self.ResolumeOut = None
        self.Health = {}
        self.ownerComp = self
    def op(self,path): return self.nodes.get(path)
    def fetch(self,key,default=None,search=False): return self.storage.get(key,default)
    def store(self,key,value): self.storage[key] = value


def parameter(value,id,min=0,max=1):
    return dict(value=value,id=id,valuetype='ParamRange',min=min,max=max)


def composition():
    layers = []
    for i in range(1,8):
        effects = [dict(id=i*100+j,name='Effect%d'%j,display_name='Effect %d'%j,
                        params={'Opacity':parameter(0.0,i*1000+j)},bypassed={'value':False,'id':i*10000+j}) for j in range(1,17)]
        layers.append(dict(id=i,name={'value':'Layer %d'%i},bypassed={'value':False},solo={'value':False},
                           video={'opacity':parameter(i/10,i),'effects':effects},
                           dashboard={'Link %d'%j:parameter(i/10,i*100+j) for j in range(1,9)},
                           clips=[dict(id=i*1000+j,name={'value':'Clip %d'%j},connected={'value':'Connected' if j==1 else 'Disconnected'},transport={'controls':{'speed':parameter(1,i*100000+j,max=10)}}) for j in range(1,129)]))
    return dict(id=99,name={'value':'Fixture'},layers=layers,columns=[{}]*128,decks=[{'selected':{'value':True},'name':{'value':'Deck'}}]*15,
                video={'opacity':parameter(1,999),'effects':layers[0]['video']['effects']},
                dashboard={'Link %d'%j:parameter(0.9,900+j) for j in range(1,9)},master=parameter(1,888))


def make_owner(folder):
    owner = Owner()
    surface = runpy.run_path(str(ROOT/'td/logic/mod_surface.py'),init_globals={'run':lambda *a,**kw:None})
    state = runpy.run_path(str(ROOT/'td/logic/mod_resolume_state.py'))
    out = runpy.run_path(str(ROOT/'td/logic/mod_resolume_out.py'))
    fx = runpy.run_path(str(ROOT/'td/logic/mod_fxregistry.py'), init_globals={'project':types.SimpleNamespace(folder=folder),'debug':lambda *args:None})
    Path(folder,'config').mkdir(exist_ok=True)
    owner.Surface = surface['Surface'](owner)
    owner.ResolumeOut = out['ResolumeOut'](owner)
    owner.ResolumeState = state['ResolumeState'](owner)
    owner.FxRegistry = fx['FxRegistry'](owner)
    owner.ResolumeState.OnMessage(json.dumps(composition()),owner)
    return owner


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.o = make_owner(self.tmp.name)
        self.s = self.o.Surface

    def press(self, cc, value=127):
        return self.s.OnReceiveMIDI('cc',cc,1,value,self.o)

    def test_all_clip_banks_and_layers(self):
        seen = set()
        for bank in range(1,17):
            self.s.SetBank(bank)
            for note in range(44,100):
                row = self.s.Resolve('note',note,'','SESSION')
                path = self.s.ResolveTemplate(row['control_path'],row['target'],row['slot'])
                expected_layer = (note-36)//8
                expected_clip = (bank-1)*8+(note-36)%8+1
                self.assertEqual(path,f'/composition/layers/{expected_layer}/clips/{expected_clip}/connect')
                seen.add((expected_layer,expected_clip))
        self.assertEqual(len(seen),7*128)

    def test_fx_pages_all_targets_and_capture(self):
        seen=set()
        for page in (1,2):
            self.s.FxPage=page
            for note in range(36,100):
                row=self.s.Resolve('note',note,'','FX')
                slot=self.s.Slot(row)
                path=self.s.ResolveTemplate(row['control_path'],row['target'],row['slot'],self.o.FxRegistry)
                self.assertRegex(path,r'^/parameter/by-id/\d+$')
                seen.add((row['target'],slot))
        self.assertEqual(len(seen),128)
        self.s.GridMode='FX'; self.s.Modifiers={'SELECT'}
        self.o.FxRegistry.Registry['LAYER1:9']['opacity_value']=0.65
        self.s.OnReceiveMIDI('note',92,1,127,self.o)
        self.assertEqual(self.o.FxRegistry.Registry['LAYER1:9']['on_value'],0.65)

    def test_context_fine_and_macro(self):
        self.s.GridMode='FX';self.s.FocusTarget='LAYER7'
        self.press(71,1)
        self.assertAlmostEqual(self.o.ResolumeOut._oscPending['/composition/layers/7/dashboard/link1'][0],0.705)
        self.s.FocusTarget='LAYER2';self.s.Modifiers={'SELECT'}
        self.press(71,1)
        self.assertAlmostEqual(self.o.ResolumeOut._oscPending['/composition/layers/2/dashboard/link1'][0],0.201)
        self.s.GridMode='SESSION';self.s.EncoderPage='MACRO';self.s.Modifiers={'SHIFT'}
        self.press(78,1)
        self.assertIn('/composition/dashboard/link2',self.o.ResolumeOut._oscPending)

    def test_press_release_and_hold_mute(self):
        self.press(26);self.o.ResolumeOut.ClearPending()
        self.press(60)
        self.assertEqual(self.o.ResolumeOut._oscPending['/composition/layers/7/bypassed'][0],1)
        self.o.ResolumeOut.ClearPending();self.press(60,0)
        self.assertFalse(self.o.ResolumeOut._oscPending)
        self.press(26,0);self.assertIsNone(self.s.HeldFocusTarget)
        self.press(60);self.assertIn('/composition/bypassed',self.o.ResolumeOut._oscPending)
        self.o.ResolumeOut.ClearPending();self.press(102,0)
        self.assertFalse(self.o.ResolumeOut._oscPending)

    def test_dryrun_and_unarmed_fx_never_send(self):
        self.s.GridMode='FX'
        self.s._cfg['dry_run']='1'
        table=self.o.nodes['config/cfg_general']
        for row in table.rows:
            if row[0]=='dry_run':row[1]='1'
        self.s.OnReceiveMIDI('note',92,1,127,self.o)
        self.assertFalse(self.o.ResolumeOut._wsPending)
        self.assertIn('FX_',self.o.nodes['logic/dryrun_log'].text)
        self.assertFalse(self.o.FxRegistry.Registry['LAYER1:1']['_padOn'])
        self.o.Armed=False;self.o.nodes['logic/dryrun_log'].text=''
        self.s.OnReceiveMIDI('note',92,1,127,self.o)
        self.assertEqual(self.o.nodes['logic/dryrun_log'].text,'')

    def test_configured_indices_and_identity(self):
        self.s._cfg['layer_ids']='7,6,5,4,3,2,1'
        self.o.ResolumeState.Rebind()
        self.o.ResolumeState.OnMessage(json.dumps(composition()),self.o)
        self.assertAlmostEqual(self.o.ResolumeState.DashboardLinkValue('LAYER1',1),0.7)
        self.s._cfg['layer_ids']='1,2,3,4,5,6,99'
        self.o.ResolumeState.OnMessage(json.dumps(composition()),self.o)
        self.assertFalse(self.o.ResolumeState.LayerIdsOK())

    def test_identity_change_disarms_and_clears_in_strict_mode(self):
        self.s._cfg['layer_binding_mode']='strict'
        c=composition();c['layers'][2]['id']=999
        self.o.ResolumeState.OnMessage(json.dumps(c),self.o)
        self.assertFalse(self.o.ResolumeState.LayerIdsOK())
        self.assertIn('identities',self.o.ResolumeState.BindingError)
        self.assertFalse(self.o.ResolumeState.Notice())

    def test_identity_change_adopts_live_layers_by_default(self):
        state=self.o.ResolumeState
        state.Optimistic('/composition/layers/1/video/opacity',0.99)
        self.s.EncoderValues['stale']=0.99
        self.s.EncoderWritten['stale']=time.monotonic()
        self.o.ResolumeOut.SendWSById(1001,1.0)
        c=composition();c['layers'][2]['id']=999
        state.OnMessage(json.dumps(c),self.o)
        self.assertTrue(state.LayerIdsOK())
        self.assertFalse(state.BindingError)
        self.assertEqual(state.Bindings['3'],999)
        self.assertEqual(self.o.storage['layout7_bindings']['3'],999)
        self.assertIn('identities',state.Notice())
        self.assertFalse(self.s.EncoderValues or self.s.EncoderWritten or state.Pending)
        self.assertFalse(self.o.ResolumeOut._wsPending or self.o.ResolumeOut._oscPending)
        self.assertAlmostEqual(state.Value('/composition/layers/1/video/opacity'),0.1)

    def test_bindings_from_another_composition_are_adopted_even_when_strict(self):
        # A .toe carrying bindings from another machine's composition: the saved
        # layer ids describe layers that are not on screen at all.
        state=self.o.ResolumeState
        self.s._cfg['layer_binding_mode']='strict'
        self.o.storage['layout7_bindings']={str(i):10_000+i for i in range(1,8)}
        self.o.storage['layout7_composition']='MacShow'
        state.Bindings=dict(self.o.storage['layout7_bindings'])
        state.BoundComposition='MacShow'
        state.OnMessage(json.dumps(composition()),self.o)
        self.assertTrue(state.LayerIdsOK())
        self.assertFalse(state.BindingError)
        self.assertEqual(state.BoundComposition,'Fixture')
        self.assertEqual(state.Bindings,{str(i):i for i in range(1,8)})
        self.assertEqual(self.o.storage['layout7_composition'],'Fixture')
        self.assertIn('Fixture',state.Notice())

    def test_legacy_bindings_without_provenance_are_adopted_when_strict(self):
        state=self.o.ResolumeState
        self.s._cfg['layer_binding_mode']='strict'
        self.o.storage.pop('layout7_composition',None)
        state.Bindings={str(i):10_000+i for i in range(1,8)}
        state.BoundComposition=''
        state.OnMessage(json.dumps(composition()),self.o)
        self.assertTrue(state.LayerIdsOK())
        self.assertFalse(state.BindingError)
        self.assertEqual(state.BoundComposition,'Fixture')

    def test_matching_identities_leave_no_notice_and_do_not_rewrite_storage(self):
        state=self.o.ResolumeState
        self.o.storage['layout7_composition']='sentinel-untouched'
        state.OnMessage(json.dumps(composition()),self.o)
        self.assertTrue(state.LayerIdsOK())
        self.assertFalse(state.Notice() or state.BindingError)
        self.assertEqual(self.o.storage['layout7_composition'],'sentinel-untouched')

    def test_notice_expires(self):
        state=self.o.ResolumeState
        c=composition();c['layers'][2]['id']=999
        state.OnMessage(json.dumps(c),self.o)
        self.assertTrue(state.Notice())
        state.BindingNoticeUntil=time.monotonic()-0.1
        self.assertFalse(state.Notice())

    def test_rebind_clears_provenance(self):
        state=self.o.ResolumeState
        self.assertEqual(state.BoundComposition,'Fixture')
        state.Rebind()
        self.assertFalse(state.Bindings or state.BoundComposition)
        self.assertFalse(self.o.storage['layout7_composition'])
        state.OnMessage(json.dumps(composition()),self.o)
        self.assertTrue(state.LayerIdsOK())
        self.assertFalse(state.Notice())

    def test_reset_ladder_stop_unmapped_device_tiers_escalate(self):
        calls=[]
        self.o.Resync=lambda: calls.append('soft')
        self.o.HardReset=lambda: calls.append('hard')
        self.assertEqual(self.press(29)['action'],'reserved')
        self.s.Modifiers={'SHIFT'}
        # Shift+Stop falls back to the unmodified reserved row rather than acting.
        self.assertEqual(self.press(29)['action'],'reserved')
        self.s.Modifiers=set()
        self.assertEqual(self.press(110)['action'],'surface_resync')
        self.s.Modifiers={'SHIFT'}
        self.assertEqual(self.press(110)['action'],'surface_hard_reset')
        self.assertEqual(calls,['soft','hard'])
        self.assertFalse(self.o.ResolumeOut._oscPending or self.o.ResolumeOut._wsPending)

    def test_hard_reset_drops_bindings_and_defers_refresh_pulse(self):
        deferred=[]
        cls=runpy.run_path(str(ROOT/'td/logic/ext_PushResolume.py'),
                           init_globals={'run':lambda *a,**kw:deferred.append((a,kw))})['PushResolumeExt']
        self.o.HardReset=types.MethodType(cls.HardReset,self.o)
        self.o.HardReset()
        state=self.o.ResolumeState
        self.assertFalse(state.Bindings or state.BoundComposition)
        self.assertFalse(self.o.storage['layout7_composition'])
        self.assertFalse(self.o.Armed)
        self.assertEqual(len(deferred),1)
        self.assertIn('par.Refresh.pulse()',deferred[0][0][0])
        self.assertEqual(deferred[0][1],{'delayFrames':1})

    def test_empty_clips_are_inert_and_state_replaced(self):
        c=composition();c['layers'][0]['clips']=[]
        self.o.ResolumeState.OnMessage(json.dumps(c),self.o)
        self.s.OnReceiveMIDI('note',44,1,127,self.o)
        self.assertFalse(self.o.ResolumeOut._oscPending)
        self.assertFalse(any(lid=='1' for lid,ci in self.o.ResolumeState.Clips))

    def test_pages_independent_and_deck_modifier(self):
        self.s.SetBank(9);self.press(43);self.assertEqual(self.s.Bank,16)
        self.press(51);self.press(37);self.assertEqual(self.s.FxPage,2)
        self.press(51);self.assertEqual(self.s.Bank,16)
        self.s.Modifiers={'SHIFT'}
        self.assertEqual(self.s.Resolve('cc',37,'SHIFT','FX')['action'],'deck_select')

    def test_queue_caps_and_feedback(self):
        for i in range(20):self.o.ResolumeOut.SendWSById(5000+i,0.5)
        self.assertEqual(self.o.ResolumeOut.FlushWS(16),16)
        self.assertEqual(len(self.o.ResolumeOut._wsQueue),4)
        c=composition();c['layers'][0]['video']['effects'][0]['params']['Opacity']['value']=0.6
        self.o.ResolumeState.OnMessage(json.dumps(c),self.o)
        self.assertAlmostEqual(self.o.ResolumeState.CurrentOpacity('LAYER1',1),0.6)

    def test_shared_snapshot(self):
        painter=runpy.run_path(str(ROOT/'td/logic/mod_ledpainter.py'))
        snapshot=painter['Snapshot'](self.o)
        self.assertEqual(len(snapshot['pads']),64)
        self.assertEqual(snapshot['targets'][6]['target'],'LAYER7')
        self.assertEqual(snapshot['lower'][7]['target'],'COMPOSITION')

    def test_deck_trigger_survives_queue_invalidation(self):
        self.s.Modifiers={'SHIFT'}
        self.press(37)
        self.assertIn('/composition/decks/2/select',self.o.ResolumeOut._oscPending)
        self.assertFalse(self.o.ResolumeState.Clips)

    def test_fx_confirmation_updates_live_opacity(self):
        self.o.ResolumeState.OnMessage(json.dumps(dict(type='parameter_get',id=1001,value=0.45,valuetype='ParamRange',min=0,max=1)),self.o)
        self.assertAlmostEqual(self.o.FxRegistry.Registry['LAYER1:1']['opacity_value'],0.45)

    def test_set_ack_cannot_roll_back_fx_feedback(self):
        painter=runpy.run_path(str(ROOT/'td/logic/mod_ledpainter.py'))
        self.s.GridMode='FX'
        for expected, stale in ((1.0,0.0),(0.0,1.0),(1.0,0.0)):
            self.s.OnReceiveMIDI('note',92,1,127,self.o)
            self.o.ResolumeState.OnMessage(json.dumps(dict(type='parameter_set',id=1001,value=stale,valuetype='ParamRange',min=0,max=1)),self.o)
            snapshot=painter['Snapshot'](self.o)
            self.assertEqual(snapshot['pads'][0]['value'],expected)
            self.assertEqual(snapshot['targets'][0]['effects'][0]['opacity_value'],expected)
            self.assertEqual(snapshot['pads'][0]['palette'],'FX_ON' if expected else 'FX_OFF')

    def test_readback_is_delayed_bounded_and_cleared_by_resync(self):
        out=self.o.ResolumeOut
        with patch('time.monotonic',return_value=10):
            out.SendWSById(1001,1.0)
            out.SendWSById(1002,1.0)
            self.assertEqual(out.FlushWS(2),2)
            self.assertEqual(out.FlushWS(2),0)
        with patch('time.monotonic',return_value=10.1):
            self.assertEqual(out.FlushWS(1),1)
        self.assertEqual(self.o.nodes['net/ws1'].messages[-1]['action'],'get')
        self.assertEqual(len(out._wsReadbacks),1)
        out.ClearPending()
        self.assertFalse(out._wsReadbacks)

    def test_older_readback_cannot_undo_rapid_toggle(self):
        self.o.FxRegistry.TogglePad('LAYER1',1,self.o.ResolumeOut)
        self.o.ResolumeState.OnMessage(json.dumps(dict(type='parameter_get',id=1001,value=0.0,valuetype='ParamRange',min=0,max=1)),self.o)
        self.assertEqual(self.o.ResolumeState.CurrentOpacity('LAYER1',1),1.0)
        self.o.FxRegistry.Registry['LAYER1:1']['_pending_until']=0
        self.o.ResolumeState.OnMessage(json.dumps(dict(type='parameter_get',id=1001,value=0.0,valuetype='ParamRange',min=0,max=1)),self.o)
        self.assertEqual(self.o.ResolumeState.CurrentOpacity('LAYER1',1),0.0)

    def test_pins_persist_after_restart(self):
        slot=self.o.FxRegistry.Registry['LAYER7:9']['slot']
        self.o.FxRegistry.SetOnValue('LAYER7',slot,0.63)
        restored=make_owner(self.tmp.name)
        self.assertAlmostEqual(restored.FxRegistry.Registry['LAYER7:9']['on_value'],0.63)

    def test_off_capture_preserves_usable_on_value(self):
        self.o.FxRegistry.SetOnValue('LAYER1',4,0.63)
        self.o.FxRegistry.SetOnValue('LAYER1',4,0.0)
        self.assertAlmostEqual(self.o.FxRegistry.Registry['LAYER1:4']['on_value'],0.63)
        self.o.FxRegistry.TogglePad('LAYER1',4,self.o.ResolumeOut)
        self.assertAlmostEqual(self.o.ResolumeOut._wsPending['/parameter/by-id/1004'][0],0.63)

    def test_legacy_zero_on_values_are_repaired(self):
        self.o.FxRegistry.Pins['LAYER1|Effect4|1']['on_value']=0.0
        self.o.ResolumeState.OnMessage(json.dumps(composition()),self.o)
        self.assertEqual(self.o.FxRegistry.Registry['LAYER1:4']['on_value'],1.0)

    def test_speed_follows_active_clip(self):
        self.s.Modifiers={'SHIFT'}
        self.press(77,1)
        path='/composition/layers/7/clips/1/transport/position/behaviour/speed'
        self.assertAlmostEqual(self.o.ResolumeOut._oscPending[path][0],0.105)
        self.o.ResolumeState.Clips[('7',1)]['connected']=False
        self.o.ResolumeOut.ClearPending()
        self.press(77,1)
        self.assertFalse(self.o.ResolumeOut._oscPending)

    def test_shift_lower_resets_native_speed_in_both_modes(self):
        c=composition()
        c['speed']=parameter(3,777,max=10)
        c['layers'][6]['clips'][0]['transport']['controls']['speed']=parameter(4,700001,max=16)
        self.o.ResolumeState.OnMessage(json.dumps(c),self.o)
        for mode in ('SESSION','FX'):
            self.s.GridMode=mode
            self.s.EncoderPage='MACRO'
            self.s.FocusTarget='LAYER5'
            self.s.Modifiers={'SHIFT'}
            for cc in range(20,28):
                self.o.ResolumeOut.ClearPending()
                self.press(cc)
                target=self.s.Targets()[cc-20]
                path='/composition/speed' if cc==27 else f'/composition/layers/{cc-19}/clips/1/transport/position/behaviour/speed'
                pid=self.o.ResolumeState.ParameterMeta[path]['id']
                self.assertEqual(self.o.ResolumeOut._wsPending['/parameter/by-id/'+str(pid)],(None,'reset'))
                self.assertFalse(self.o.ResolumeOut._oscPending)
                self.assertNotIn(path,self.s.EncoderValues)
                self.assertEqual(self.s.FocusTarget,'LAYER5')
                if cc==26:self.assertEqual(self.o.ResolumeState.Clips[('7',1)]['speed'],4.0)
                self.o.ResolumeOut.ClearPending()
                self.press(cc,0)
                self.assertFalse(self.o.ResolumeOut._oscPending or self.o.ResolumeOut._wsPending)

    def test_speed_reset_is_inert_without_clip_and_guarded(self):
        self.s.Modifiers={'SHIFT'}
        self.o.ResolumeState.Clips[('1',1)]['connected']=False
        self.press(20)
        self.assertFalse(self.o.ResolumeOut._oscPending or self.o.ResolumeOut._wsPending)
        self.o.Armed=False
        self.press(21)
        self.assertFalse(self.o.ResolumeOut._oscPending or self.o.ResolumeOut._wsPending)
        self.o.Armed=True
        self.s._cfg['dry_run']='1'
        for row in self.o.nodes['config/cfg_general'].rows:
            if row[0]=='dry_run':row[1]='1'
        self.press(21)
        self.assertFalse(self.o.ResolumeOut._oscPending or self.o.ResolumeOut._wsPending or self.s.EncoderValues)

    def test_reset_uses_native_api_and_waits_for_actual_speed(self):
        c=composition()
        c['layers'][0]['clips'][0]['transport']['controls']['speed']=parameter(0.218291,100001,max=10)
        self.o.ResolumeState.OnMessage(json.dumps(c),self.o)
        self.s.Modifiers={'SHIFT'}
        path='/composition/layers/1/clips/1/transport/position/behaviour/speed'
        self.o.ResolumeOut._oscCache[path]=0.1
        self.s.EncoderValues[path]=0.1
        self.press(20)
        self.assertNotIn(path,self.o.ResolumeOut._oscCache)
        self.assertAlmostEqual(self.o.ResolumeState.Clips[('1',1)]['speed'],0.218291)
        self.o.ResolumeOut.FlushWS()
        self.assertEqual(self.o.nodes['net/ws1'].messages[-1],dict(action='reset',parameter='/parameter/by-id/100001'))
        self.assertNotIn(path,self.o.ResolumeState.Pending)
        self.o.ResolumeState.OnMessage(json.dumps(dict(type='parameter_get',id=100001,value=1.0,valuetype='ParamRange',min=0,max=10)),self.o)
        self.assertEqual(self.o.ResolumeState.Clips[('1',1)]['speed'],1.0)
        self.assertAlmostEqual(self.o.ResolumeState.Value(path),0.1)
        self.press(20)
        self.o.ResolumeOut.FlushWS()
        self.assertEqual(sum(m['action']=='reset' for m in self.o.nodes['net/ws1'].messages),2)

    def test_shift_changed_while_lower_held_clears_hold_on_release(self):
        self.press(20)
        self.assertEqual(self.s.HeldFocusTarget,'LAYER1')
        self.press(49)
        self.press(20,0)
        self.assertIsNone(self.s.HeldFocusTarget)

    def test_null_transport_does_not_interrupt_fx_discovery(self):
        c=composition()
        c['layers'][0]['clips'][1]['transport']=None
        self.o.FxRegistry.Registry.clear()
        self.o.ResolumeState.OnMessage(json.dumps(c),self.o)
        self.assertTrue(self.o.ResolumeState.LayerIdsOK())
        self.assertEqual(len(self.o.FxRegistry.Registry),128)

    def prepare_resync(self):
        cls = runpy.run_path(str(ROOT/'td/logic/ext_PushResolume.py'))['PushResolumeExt']
        for name in ('Resync','FinishResync','CheckHealth','FullRedraw'):
            setattr(self.o, name, types.MethodType(getattr(cls,name), self.o))
        push = runpy.run_path(str(ROOT/'td/logic/mod_pushio.py'))['PushIO']
        self.o.PushIO = push(self.o)
        self.o.PushIO.Bound = self.o.PushIO.PushMode = True
        self.o.Health.update(push_bound=True, push_mode=True)
        self.o.Display = types.SimpleNamespace(_textSignature='stale', mode='text', Health=lambda:True)
        painter = runpy.run_path(str(ROOT/'td/logic/mod_ledpainter.py'))
        self.o.nodes['logic/mod_ledpainter'] = types.SimpleNamespace(module=types.SimpleNamespace(**painter))
        web = Table()
        def request(*args, **kwargs):
            web.messages.append((args, kwargs))
            return len(web.messages)
        web.request = request
        self.o.nodes['net/web1'] = web
        return self.o.ResolumeState, web

    def test_resync_replaces_stale_state_and_preserves_context(self):
        state, web = self.prepare_resync()
        self.s.Bank, self.s.FxPage, self.s.GridMode = 9, 2, 'FX'
        self.s.FocusTarget, self.s.EncoderPage = 'LAYER7', 'MACRO'
        bindings = dict(state.Bindings)
        state.Optimistic('/composition/layers/1/video/opacity', 0.99)
        self.s.EncoderValues['stale'] = 0.99
        self.s.EncoderWritten['stale'] = time.monotonic()
        fx = self.o.FxRegistry.Registry['LAYER1:1']
        self.o.FxRegistry.SetOnValue('LAYER1', 1, 0.63)
        fx.update(opacity_value=1.0, _padOn=True, _pending_until=time.time()+100)
        self.o.ResolumeOut.SendWSById(1001, 1.0)
        self.o.PushIO.SetLed('note', 1, 99, blink_with=88)
        self.o.PushIO.SetLed('note', 2, 99)
        self.press(110)
        self.press(110,0)
        self.press(110)
        self.assertEqual(len(web.messages),1)
        self.assertFalse(self.o.Armed)
        self.assertTrue(state.Syncing)
        self.assertFalse(self.s.EncoderValues or self.s.EncoderWritten or state.Pending)
        self.assertFalse(self.o.ResolumeOut._wsPending or self.o.ResolumeOut._oscPending)
        c = composition()
        c['layers'][0]['clips'] = []
        c['layers'][0]['video']['effects'][0]['params']['Opacity']['value'] = 0.27
        state.OnResponse(json.dumps(c).encode(),1,self.o)
        self.assertFalse(state.Syncing or state.SyncError)
        self.assertTrue(self.o.Armed)
        self.assertAlmostEqual(state.Value('/composition/layers/1/video/opacity'),0.1)
        self.assertAlmostEqual(state.CurrentOpacity('LAYER1',1),0.27)
        self.assertAlmostEqual(self.o.FxRegistry.Registry['LAYER1:1']['on_value'],0.63)
        self.assertFalse(any(lid=='1' for lid,ci in state.Clips))
        self.assertEqual(state.Bindings,bindings)
        self.assertEqual((self.s.Bank,self.s.FxPage,self.s.GridMode,self.s.FocusTarget,self.s.EncoderPage),(9,2,'FX','LAYER7','MACRO'))
        self.assertIsNone(self.o.Display._textSignature)
        self.assertNotIn(('note',1),self.o.PushIO._blinkPads)
        self.assertNotEqual(self.o.PushIO._ledPending.get(('note',2)),99)
        self.assertTrue(self.o.PushIO._ledQueue)
        self.assertFalse(self.o.nodes['net/ws1'].messages or self.o.nodes['net/oscout1'].messages)

    def test_resync_ignores_older_rest_and_websocket_during_read(self):
        state, web = self.prepare_resync()
        state.Request(self.o)
        self.press(110)
        stale = composition()
        stale['layers'][0]['video']['opacity']['value'] = 0.99
        state.OnResponse(json.dumps(stale).encode(),1,self.o)
        state.OnMessage(json.dumps(stale),self.o)
        self.assertTrue(state.Syncing and state.PollPending)
        self.assertAlmostEqual(state.Value('/composition/layers/1/video/opacity'),0.1)
        state.OnResponse(json.dumps(composition()).encode(),2,self.o)
        state.OnResponse(json.dumps(stale).encode(),1,self.o)
        self.assertAlmostEqual(state.Value('/composition/layers/1/video/opacity'),0.1)
        self.assertFalse(state.Syncing)

    def test_resync_failure_can_retry(self):
        for payload, error in ((b'', 'Timeout'), (b'bad json',''), (b'\xff','')):
            state, web = self.prepare_resync()
            self.press(110)
            state.OnResponse(payload,1,self.o,error)
            self.assertFalse(state.Syncing or state.PollPending or self.o.Armed)
            self.assertTrue(state.SyncError)
            self.press(110)
            state.OnResponse(json.dumps(composition()).encode(),2,self.o)
            self.assertTrue(self.o.Armed)
            self.assertFalse(state.SyncError)

    def test_repaint_queues_playing_pads_immediately(self):
        state, web = self.prepare_resync()
        self.press(110)
        state.OnResponse(json.dumps(composition()).encode(),1,self.o)
        self.assertIn(('note',44),self.o.PushIO._ledPending)
        self.assertIn(('note',44),self.o.PushIO._blinkPads)


if __name__ == '__main__':unittest.main()

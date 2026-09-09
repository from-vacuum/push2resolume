const API = 'http://127.0.0.1:9871';
const $ = id => document.getElementById(id);
let state = null, pending = false, lastLcd = 0;
const controls = new Map();
const hardwareLabels={3:'Tap Tempo',29:'Stop',30:'Setup',31:'Layout',44:'Left',45:'Right',46:'Up',47:'Down',48:'Select',49:'Shift',51:'Session',58:'Scale',59:'User',60:'Mute',61:'Solo',62:'Page Left',63:'Page Right',85:'Play',86:'Record',110:'Device',112:'Mix'};
function el(tag, cls, text) { const n=document.createElement(tag); if(cls)n.className=cls; if(text!==undefined)n.textContent=text; return n; }
function key(d){return `${d.kind}:${d.number}`;}
function detail(d){
  if(!d)return;
  $('detailTitle').textContent=d.label || d.action;
  $('detailFields').replaceChildren();
  for(const [label,value] of Object.entries({Control:`${d.kind} ${d.number}`,Target:d.target,Slot:d.slot,Action:d.action,Path:d.path,Value:d.value,Available:d.available})){
    if(value===null||value==='')continue;
    $('detailFields').append(el('dt','',label),el('dd',label==='Path'?'code':'',String(value)));
  }
  $('detail').showModal();
}
function button(d,label,cls=''){
  const b=el('button',cls,label); b.type='button'; b.title=d.label || d.action;
  b.onclick=()=>detail(controls.get(key(d)) || d); return b;
}
function color(d){return `rgb(${(state.palette[d.palette] || [45,50,55]).join(',')})`;}
function renderButtons(id,items){
  const fragment=document.createDocumentFragment();
  for(const d of items){
    if(!d)continue;
    let label=d.label;
    if(id.endsWith('Rail'))label=hardwareLabels[d.number] || label;
    if(id==='right')label=d.available?String(d.slot):'-';
    if(id==='lower')label=d.target==='COMPOSITION'?'COMP':`L${d.target.slice(5)}`;
    const b=button(d,label);b.classList.toggle('active',d.active);b.style.setProperty('--accent',color(d));
    fragment.append(b);
  }
  $(id).replaceChildren(fragment);
}
function render(s){
  state=s;controls.clear();
  for(const d of [...s.pads,...s.encoders,...s.upper,...s.lower,...s.right,...(s.buttons||[])])if(d)controls.set(key(d),d);
  $('composition').textContent=s.composition;
  $('connection').textContent=s.syncing?'Syncing':s.syncError?'Resync failed':s.armed?'Connected':'Not armed';$('connectionDot').classList.toggle('on',s.armed);
  $('mode').textContent=s.gridMode;$('page').textContent=s.gridMode==='FX'?`FX page ${s.fxPage}/${s.fxPageCount} · Slots ${(s.fxPage-1)*8+1}–${s.fxPage*8}`:`Bank ${s.bank}/${s.bankCount} · Clips ${s.clipRange.join('–')} · ${s.encoderPage}`;
  const focus=s.targets.find(t=>t.target===s.focus);$('focus').textContent=`Focus: ${focus.short} ${focus.name}`;
  $('tempo').textContent=`${Number(s.bpm).toFixed(1)} BPM`;$('deck').textContent=s.deck;
  renderButtons('upper',s.upper);renderButtons('lower',s.lower);renderButtons('right',s.right);
  renderButtons('leftRail',(s.buttons||[]).filter(d=>d&&[51,112,110,49,48,44,45,46,47,62,63].includes(d.number)));
  renderButtons('rightRail',(s.buttons||[]).filter(d=>d&&[60,61,85,86,29,3,31,58,59,30].includes(d.number)));
  const encoders=document.createDocumentFragment();
  s.encoders.forEach(d=>{const b=button(d,'','encoder');b.append(el('span','dial',d.displayValue || `${Math.round((d.value||0)*100)}%`),el('span','label',d.label));encoders.append(b);});
  $('encoders').replaceChildren(encoders);
  if(!$('pads').children.length){for(let i=0;i<64;i++){const b=el('button','pad');b.type='button';b.append(el('span','name'),el('span','slot'),el('span','state'));b.onclick=()=>detail(state.pads[i]);$('pads').append(b);}}
  s.pads.forEach((d,i)=>{
    const b=$('pads').children[i];b.title=`${d.label} | ${d.target} | note ${d.number}`;
    b.classList.toggle('empty',!d.available);b.classList.toggle('playing',d.blink);b.style.background=d.available?color(d):'';
    const rgb=s.palette[d.palette] || [45,50,55];
    const luminance=rgb[0]*0.2126+rgb[1]*0.7152+rgb[2]*0.0722;
    b.style.color=d.available?(luminance>115?'#101518':'#f1f5f3'):'';
    b.children[0].textContent=d.available?d.label:'';
    b.children[1].textContent=s.gridMode==='FX'?`${d.target==='COMPOSITION'?'C':'L'+d.target.slice(5)} · ${d.slot}`:d.action==='column_connect'?`ALL · ${d.slot}`:`L${d.target.slice(5)} · ${d.slot}`;
    b.children[2].textContent=d.bypassed?'BYPASS':d.value!==null?`${Math.round(d.value*100)}%`:d.active?'PLAY':'';
  });
  $('tracknames').replaceChildren(...(s.gridMode==='FX'?s.targets.map(t=>`${t.short} ${t.name}`):Array.from({length:8},(_,i)=>`Column ${s.clipRange[0]+i}`)).map(t=>el('span','',t)));
  $('targets').replaceChildren(...s.targets.map(t=>{
    const row=el('div','targetrow');row.style.setProperty('--accent',`rgb(${t.color.join(',')})`);
    const active=t.playing.map(c=>`${c.index} ${c.name}`).join(', ');
    row.append(el('span','',`${t.short} ${t.name}`),el('span',active?'':'dim',active||'—'),el('span','',t.bypassed?'Bypass':`${Math.round((t.opacity||0)*100)}%`),el('span','',t.loaded),el('span','',t.effects.length));return row;
  }));
  $('metrics').replaceChildren(...Object.entries(s.health).map(([k,v])=>el('span',v?'ok':'',`${k.replaceAll('_',' ')} ${v?'●':'○'}`)));
  $('error').textContent=s.syncError || s.bindingError;
}
async function poll(){
  if(pending)return;pending=true;
  try{
    const response=await fetch(`${API}/state`,{cache:'no-store',signal:AbortSignal.timeout(2500)});
    if(!response.ok)throw new Error(`TD ${response.status}`);
    const s=await response.json();if(s.error)throw new Error(s.error);render(s);
    if(Date.now()-lastLcd>500){$('lcd').src=`${API}/lcd.png?t=${Date.now()}`;lastLcd=Date.now();}
  }catch(e){$('connection').textContent='Disconnected';$('connectionDot').classList.remove('on');$('error').textContent=e.message;}
  finally{pending=false;}
}
$('close').onclick=()=>$('detail').close();$('refresh').onclick=poll;
$('detail').onclick=e=>{if(e.target===$('detail'))$('detail').close();};
poll();setInterval(poll,300);

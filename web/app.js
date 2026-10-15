'use strict';
const $ = id => document.getElementById(id);
const E = (tag, cls='', value='') => { const e=document.createElement(tag); if(cls)e.className=cls; e.textContent=value; return e; };
const safeImage = url => typeof url === 'string' && /^https:\/\//i.test(url);
let inventory={inventory:[],bags:[],sets:[],total_pieces:0,different_parts:0,total_bags:0};
let activeSet='', openedSet='', setView='picking', currentDetail=null;
let selectedCandidate=null, videoStream=null, busy=false, photoUrl=null;
let pendingPreview=null, pendingSignature=null, revision=0, previewTimer=null;
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));

function notice(text,error=false){const el=$('global-message');el.textContent=text;el.className='message '+(error?'error':'info');window.scrollTo({top:0,behavior:'smooth'});}
function clearNotice(){$('global-message').classList.add('hidden');}
async function request(path, body, raw=false){const response=await fetch(path,{method:'POST',headers:{'Content-Type':raw?'image/jpeg':'application/json'},body:raw?body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw Error(data.error||`HTTP ${response.status}`);return data;}
async function get(path){const r=await fetch(path,{cache:'no-store'});const d=await r.json();if(!r.ok)throw Error(d.error||`HTTP ${r.status}`);return d;}
function setTab(tab){document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('active',p.id==='panel-'+tab));clearNotice();}
document.querySelectorAll('.nav').forEach(b=>b.addEventListener('click',()=>setTab(b.dataset.tab)));
function sectionMessage(parent, cls, text){parent.append(E('p',cls,text));}
function appendImage(container,url,alt){if(safeImage(url)){const img=E('img');img.src=url;img.alt=alt;img.loading='lazy';img.referrerPolicy='no-referrer';img.onerror=()=>{img.remove();container.append(E('span','no-image','No image'));};container.append(img);}else container.append(E('span','no-image','No image'));}
function labelQuantity(q){return `${q} piece${q===1?'':'s'}`;}

async function refresh(){
  inventory=await get('/api/summary');
  $('stat-pieces').textContent=inventory.total_pieces.toLocaleString('en-GB');
  $('stat-types').textContent=inventory.different_parts.toLocaleString('en-GB');
  $('stat-bags').textContent=inventory.total_bags.toLocaleString('en-GB');
  renderInventory();renderBags();renderSets();
  if(openedSet){try{currentDetail=await get('/api/set?set_num='+encodeURIComponent(openedSet));renderSetDetail(currentDetail);}catch(err){openedSet='';$('set-detail').classList.add('hidden');}}
  const select=$('active-set');const previous=activeSet;select.replaceChildren();
  const none=E('option','','No active set — sort loose pieces');none.value='';select.append(none);
  for(const set of inventory.sets){const opt=E('option','',`${set.set_num} · ${set.name} (${set.collected}/${set.required})`);opt.value=set.set_num;select.append(opt);}
  activeSet=inventory.sets.some(s=>s.set_num===previous)?previous:'';select.value=activeSet;
}
$('active-set').addEventListener('change',()=>{activeSet=$('active-set').value;calculateSoon();});
function piece(){return {part_id:$('part-id').value.trim(),description:$('description').value.trim(),colour:$('colour').value.trim(),quantity:Number($('quantity').value),active_set:activeSet,api_category:selectedCandidate?.category||''};}
function signature(){return JSON.stringify(piece());}
function valid(){return ['part-id','description','colour','quantity'].every(id=>$(id).validity.valid&&String($(id).value).trim());}
function invalidate(){revision++;if(previewTimer!==null)clearTimeout(previewTimer);previewTimer=null;pendingPreview=null;pendingSignature=null;$('allocation-panel').classList.add('hidden');$('save-button').disabled=true;$('saved-panel').classList.add('hidden');}
function showAllocation(plan){
  const target=$('allocation-panel');target.replaceChildren();
  if(plan.set_quantity){target.append(E('h3','',`Prioritised for set ${plan.set_num}`));for(const a of plan.set_allocations){const row=E('div','allocation-row');row.append(E('strong','',`Set Bag ${a.bag_number}${a.new_bag?' (new)':''}`),E('strong','',labelQuantity(a.quantity)));target.append(row);}}
  if(plan.loose_quantity){target.append(E('h3','',plan.already_known?'Existing loose part':'Loose inventory · '+plan.category));for(const a of plan.loose_allocations){const row=E('div','allocation-row');row.append(E('strong','',`Bag ${a.bag_number}${a.new_bag?' (new)':''}`),E('strong','',labelQuantity(a.quantity)));target.append(row);}}
  target.append(E('p','hint','Preview only. No CSV changes until Confirm & save.'));target.classList.remove('hidden');
}
async function calculate(){if(busy||!valid())return;const sig=signature(),rev=revision;$('preview-status').textContent='Calculating bag placement…';try{const plan=await request('/api/preview',piece());if(busy||rev!==revision||sig!==signature())return;pendingPreview=plan;pendingSignature=sig;showAllocation(plan);$('preview-status').textContent='Confirm the part and its destination.';$('save-button').disabled=false;}catch(err){if(!busy&&rev===revision){$('preview-status').textContent=err.message;$('save-button').disabled=true;}}}
function calculateSoon(){invalidate();if(busy)return;if(!valid()){$('preview-status').textContent='Complete or correct all fields to assign a bag.';return;}previewTimer=setTimeout(()=>{previewTimer=null;calculate();},250);}
['part-id','description','colour','quantity'].forEach(id=>$(id).addEventListener('input',calculateSoon));
function candidates(items,colours){
  const list=$('candidate-list');list.replaceChildren();
  for(const row of items){const b=E('button','candidate');b.type='button';b.dataset.id=row.id;appendImage(b,row.img_url,'');const text=E('span');text.append(E('strong','',row.name),E('small','',`Part ${row.id}${row.category?' · '+row.category:''}`));b.append(text);if(typeof row.score==='number')b.append(E('span','score',`${Math.round(row.score*100)}%`));b.addEventListener('click',()=>selectCandidate(row));list.append(b);}
  const colourOptions=$('colour-options'),known=new Set(Array.from(colourOptions.options).map(o=>o.value.toLowerCase()));
  for(const c of colours){if(!known.has(c.name.toLowerCase())){const opt=E('option');opt.value=c.name;colourOptions.append(opt);known.add(c.name.toLowerCase());}}
  $('colour').value=colours[0]?.name||'';
  $('colour-hint').textContent=colours.length?`Predicted: ${colours[0].name}. Check carefully — colour matching controls set assignment.`:'Colour was not returned. Enter the correct colour manually.';
  $('candidates').classList.toggle('hidden',!items.length);
  if(items.length)selectCandidate(items[0]);else calculateSoon();
}
function selectCandidate(item){selectedCandidate=item;$('part-id').value=item.id;$('description').value=item.name;document.querySelectorAll('.candidate').forEach(b=>b.classList.toggle('selected',b.dataset.id===item.id));calculateSoon();}
function clearScan(){invalidate();$('piece-form').reset();selectedCandidate=null;$('candidates').classList.add('hidden');$('preview-status').textContent='Analysing scan…';clearNotice();}
async function cameraOn(){if(videoStream?.getVideoTracks().some(t=>t.readyState==='live'))return; if(!navigator.mediaDevices?.getUserMedia)throw Error('Webcam access requires opening the app at http://localhost:8765 on this computer.');videoStream=await navigator.mediaDevices.getUserMedia({video:{width:{ideal:1280},height:{ideal:720}},audio:false});const vid=$('camera-video');vid.srcObject=videoStream;$('webcam-section').classList.remove('hidden');$('photo-placeholder').classList.add('hidden');$('stop-webcam').classList.remove('hidden');await vid.play();if(!vid.videoWidth){await Promise.race([new Promise(resolve=>vid.addEventListener('loadedmetadata',resolve,{once:true})),sleep(7000)]);}if(!vid.videoWidth)throw Error('Webcam has not produced a video frame.');}
function cameraOff(){if(videoStream)videoStream.getTracks().forEach(t=>t.stop());videoStream=null;$('camera-video').srcObject=null;$('webcam-section').classList.add('hidden');$('countdown-overlay').classList.add('hidden');$('photo-placeholder').classList.remove('hidden');$('stop-webcam').classList.add('hidden');}
$('stop-webcam').addEventListener('click',()=>{if(!busy){cameraOff();$('webcam-toggle').textContent='Open webcam & scan · 2 sec';$('scan-progress').textContent='Camera is off. Start a new scan whenever ready.';}});
async function capture(){const vid=$('camera-video');const canvas=document.createElement('canvas');const scale=Math.min(1,1400/Math.max(vid.videoWidth,vid.videoHeight));canvas.width=Math.round(scale*vid.videoWidth);canvas.height=Math.round(scale*vid.videoHeight);canvas.getContext('2d').drawImage(vid,0,0,canvas.width,canvas.height);const result=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',.85));if(!result)throw Error('Could not capture an image.');return result;}
function displayPhoto(blob){if(photoUrl)URL.revokeObjectURL(photoUrl);photoUrl=URL.createObjectURL(blob);$('photo-preview').src=photoUrl;$('capture-row').classList.remove('hidden');}
$('webcam-toggle').addEventListener('click',async()=>{
  if(busy)return;busy=true;$('webcam-toggle').disabled=true;clearScan();
  try{
    $('webcam-toggle').textContent='Opening webcam…';await cameraOn();
    for(let n=2;n>=1;n--){$('countdown-overlay').classList.remove('hidden');$('countdown-number').textContent=String(n);$('webcam-toggle').textContent=`Capturing in ${n}…`;$('scan-progress').textContent=`Hold your piece steady: ${n}…`;await sleep(1000);}
    const image=await capture();$('countdown-overlay').classList.add('hidden');displayPhoto(image);$('webcam-toggle').textContent='Recognising…';$('scan-progress').textContent='Sending image to Brickognize…';
    const found=await request('/api/recognise',image,true);candidates(found.items||[],found.colours||[]);
    $('scan-progress').textContent=found.items?.length?'Recognition complete. Review and confirm.':'No match found. Correct the details or scan again.';
  }catch(err){$('scan-progress').textContent='Scan failed — no changes saved.';notice(err.message,true);if(!videoStream)cameraOff();}
  finally{busy=false;$('webcam-toggle').disabled=false;$('webcam-toggle').textContent=videoStream?'Scan next brick · 2 sec':'Open webcam & scan · 2 sec';if(valid())calculateSoon();}
});
$('piece-form').addEventListener('submit',async event=>{
  event.preventDefault();if(busy||!pendingPreview||pendingSignature!==signature()||!$('piece-form').reportValidity())return;
  const confirmed=piece();busy=true;$('save-button').disabled=true;$('webcam-toggle').disabled=true;clearNotice();
  try{const saved=await request('/api/add',confirmed);await refresh();invalidate();const panel=$('saved-panel');panel.replaceChildren();panel.append(E('h3','','Saved to CSV'));
    for(const a of saved.result.set_allocations)panel.append(E('p','',`Move ${labelQuantity(a.quantity)} to Set Bag ${a.bag_number} (${saved.result.set_num}).`));
    for(const a of saved.result.loose_allocations)panel.append(E('p','',`Move ${labelQuantity(a.quantity)} to Bag ${a.bag_number}.`));
    panel.append(E('p','saved-next','Camera is still on. Place another piece and press Scan next brick.'));panel.classList.remove('hidden');$('preview-status').textContent='Saved. Ready for the next scan.';$('scan-progress').textContent='Saved successfully.';
  }catch(err){notice('Save failed: '+err.message,true);$('preview-status').textContent='Verify your inventory before retrying a failed save.';}
  finally{busy=false;$('webcam-toggle').disabled=false;}
});

function renderInventory(){const body=$('inventory-rows');body.replaceChildren();const filter=$('inventory-filter').value.toLowerCase().trim();const rows=inventory.inventory.filter(r=>Object.values(r).some(v=>String(v).toLowerCase().includes(filter)));
  if(!rows.length){const tr=E('tr'),td=E('td','empty','No matching loose pieces.');td.colSpan=7;tr.append(td);body.append(tr);return;}
  rows.forEach(r=>{const tr=E('tr');for(const col of ['bag_number','part_id','description','colour','category','quantity'])tr.append(E('td',col==='quantity'?'qty':'',String(r[col])));const td=E('td'),edit=E('button','mini-button','Edit');edit.type='button';edit.addEventListener('click',()=>editQuantity(r));td.append(edit);tr.append(td);body.append(tr);});
}
$('inventory-filter').addEventListener('input',renderInventory);
async function editQuantity(row){const value=prompt(`New quantity for ${row.part_id} (${row.colour}) in Bag ${row.bag_number}. Enter 0 to delete:`,String(row.quantity));if(value===null)return;if(!/^\d+$/.test(value.trim())||Number(value)>100)return notice('Enter 0–100.',true);if(Number(value)===0&&!confirm('Remove this entry?'))return;try{await request('/api/adjust',{bag_number:row.bag_number,part_id:row.part_id,colour:row.colour,quantity:Number(value)});await refresh();}catch(err){notice(err.message,true);}}
function renderBags(){const box=$('bag-list');box.replaceChildren();if(!inventory.bags.length){sectionMessage(box,'empty','No bags yet.');return;}
  for(const b of inventory.bags){const card=E('article','bag-card');card.append(E('div','bag-title',`Bag ${b.bag_number}`),E('div','bag-category',b.category));const progress=E('div','progress'),fill=E('div',b.quantity===100?'full-bar':'');fill.style.width=`${b.quantity}%`;progress.append(fill);card.append(progress);const caption=E('div','bag-caption');caption.append(E('strong','',`${b.quantity}/100 pieces`),E('span','',b.remaining?`${b.remaining} spaces left`:'FULL'));card.append(caption);box.append(card);}
}

function renderSets(){const list=$('set-list');list.replaceChildren();if(!inventory.sets.length){sectionMessage(list,'hint','No tracked sets. Enter a set number above to import its parts list.');return;}
  for(const set of inventory.sets){const b=E('button','set-tile'+(openedSet===set.set_num?' selected':''));b.type='button';appendImage(b,set.image_url,`Set ${set.set_num}`);const info=E('div','tile-body');info.append(E('strong','',set.name),E('small','',`${set.set_num} · ${set.collected}/${set.required} collected (${set.percent}%)`));const progress=E('div','progress'),fill=E('div');fill.style.width=Math.min(100,set.percent)+'%';progress.append(fill);info.append(progress);b.append(info);b.addEventListener('click',()=>openSet(set.set_num));list.append(b);}
}
$('add-set-form').addEventListener('submit',async event=>{event.preventDefault();const num=$('new-set-num').value.trim(),button=$('import-button');button.disabled=true;button.textContent='Importing catalogue…';try{const result=await request('/api/import-set',{set_num:num});$('new-set-num').value='';await refresh();await openSet(result.set_num);notice(`Added ${result.name}: ${result.required} pieces (${result.types} part/colour combinations).`);}catch(err){notice('Could not import set: '+err.message,true);}finally{button.disabled=false;button.textContent='Add set from Rebrickable';}});
async function openSet(num){openedSet=num;try{currentDetail=await get('/api/set?set_num='+encodeURIComponent(num));renderSets();renderSetDetail(currentDetail);$('set-detail').classList.remove('hidden');}catch(err){notice('Could not load set: '+err.message,true);}}
function renderSetDetail(detail){const parent=$('set-detail');parent.replaceChildren();const set=detail.set;
  const hero=E('div','set-hero'),thumb=E('div');appendImage(thumb,set.image_url,`LEGO ${set.set_num}`);const info=E('div');info.append(E('h2','',set.name),E('p','',`Set ${set.set_num} · ${detail.total_collected} of ${detail.total_required} collected`));hero.append(thumb,info);parent.append(hero);
  const stats=E('div','set-totals');for(const [number,label] of [[detail.total_collected,'Collected'],[detail.total_required-detail.total_collected,'Still needed'],[detail.can_collect_now,'Available loose'],[detail.set_bags.length,'Set bags']]){const box=E('div','mini-stat');box.append(E('strong','',String(number)),E('span','',label));stats.append(box);}parent.append(stats);
  const progress=E('div','big-progress'),fill=E('div');fill.style.width=detail.total_required?Math.min(100,100*detail.total_collected/detail.total_required)+'%':'100%';progress.append(fill);parent.append(progress);
  const scanButton=E('button','btn secondary','Make this my active scanning set');scanButton.type='button';scanButton.addEventListener('click',()=>{activeSet=set.set_num;$('active-set').value=activeSet;calculateSoon();setTab('scan');});parent.append(scanButton);
  const tabs=E('div','set-tabs');for(const [tab,label] of [['picking','Pick from loose bags'],['missing','Full parts checklist']]){const b=E('button',setView===tab?'active':'',label);b.type='button';b.addEventListener('click',()=>{setView=tab;renderSetDetail(currentDetail);});tabs.append(b);}parent.append(tabs);
  if(setView==='missing')renderChecklist(parent,detail);else renderPicking(parent,detail);
}
function renderChecklist(parent,detail){const grid=E('div','missing-grid');for(const p of detail.parts){const entry=E('div','missing-entry'),thumbnail=E('div');if(Number(p.required)>0 && Number(p.collected)>=Number(p.required)){entry.style.backgroundColor='#e3f6e9';entry.style.borderColor='#91cda4';}appendImage(thumbnail,p.image_url,p.description);const text=E('div');text.append(E('strong','',p.description),E('span','',`Part ${p.part_id} · ${p.colour}`),E('div','',`${p.collected}/${p.required} collected · ${p.available_loose} loose`));entry.append(thumbnail,text);grid.append(entry);}parent.append(grid);}
function renderPicking(parent,detail){parent.append(E('h3','', 'Collect from your loose bags'));sectionMessage(parent,'hint','Click each image to mark a proposed quantity. Use + or − to adjust. When finished with a bag, confirm it to move the staged pieces into numbered set bags.');
  const available=detail.picking;if(!available.length){sectionMessage(parent,'hint',detail.total_collected>=detail.total_required?'All required parts collected.':'No matching pieces currently remain in loose bags.');return;}
  for(const bag of available){const card=E('section','bag-pick-card'+(bag.done?' complete':'')),heading=E('div','bag-pick-head'),title=E('div');title.append(E('h3','',`Bag ${bag.bag_number}`),E('small','',bag.done?'Marked finished':'Select pieces you physically removed'));heading.append(title);const status=E('strong','',bag.done?'✓ Completed':'');heading.append(status);card.append(heading);
    const grid=E('div','pick-grid');for(const item of bag.items)grid.append(pickCard(bag,item));card.append(grid);
    const action=E('button','btn '+(bag.done?'secondary':'primary')+' finish-button',bag.done?'Reopen this bag':'Confirm finished with Bag '+bag.bag_number);action.type='button';action.addEventListener('click',async()=>{if(!bag.done && !confirm(`Finish Bag ${bag.bag_number}? All selected pieces will be deducted from Bag ${bag.bag_number} and added to this set's bags.`))return;action.disabled=true;try{const result=await request(bag.done?'/api/reopen-bag':'/api/finish-bag',{set_num:detail.set.set_num,bag_number:bag.bag_number});await refresh();await openSet(detail.set.set_num);if(!bag.done){const desc=result.moved.flatMap(r=>r.destinations.map(a=>`${r.quantity} × ${r.part_id} → Set Bag ${a.bag_number}`));notice(desc.length?`Bag ${bag.bag_number} complete. Moved: ${desc.join('; ')}`:`Bag ${bag.bag_number} marked complete (no pieces transferred).`);}}catch(err){notice(err.message,true);action.disabled=false;}});card.append(action);parent.append(card);}
}
function pickCard(bag,item){const el=E('div','pick-item'+(item.staged?' marked':''));const photo=E('button','pick-image');photo.type='button';photo.title='Click to mark or unmark these pieces';appendImage(photo,item.image_url,item.description);if(item.staged)photo.append(E('span','check-indicator','✓'));
  photo.addEventListener('click',()=>stageChange(bag,item,item.staged?0:Math.max(1,Math.min(item.suggested,item.needed))));photo.disabled=bag.done;el.append(photo);
  el.append(E('div','pick-name',item.description),E('div','pick-meta',`${item.part_id} · ${item.colour}`),E('div','pick-meta',`In bag: ${item.available} · still needed: ${item.needed}`));
  const controls=E('div','pick-controls'),minus=E('button','','−'),plus=E('button','','+');minus.type='button';plus.type='button';minus.disabled=bag.done;plus.disabled=bag.done;
  const current=E('strong','',`${item.staged} picked`);minus.addEventListener('click',()=>stageChange(bag,item,Math.max(0,item.staged-1)));plus.addEventListener('click',()=>stageChange(bag,item,Math.min(item.available,item.staged+1)));controls.append(minus,current,plus);el.append(controls);
  el.append(E('div','picked-label',item.staged?'Selected · pending bag confirmation':'Not yet selected'));return el;
}
async function stageChange(bag,item,quantity){if(bag.done)return;try{await request('/api/stage-pick',{set_num:item.set_num,bag_number:bag.bag_number,part_id:item.part_id,colour:item.colour,quantity});await openSet(item.set_num);}catch(err){notice(err.message,true);}}
async function updateSettings(){try{const s=await get('/api/settings');$('settings-status').textContent=s.rebrickable_connected?'API key saved on this computer. You can import sets.':'No Rebrickable API key saved yet.';}catch(err){$('settings-status').textContent='Could not read settings: '+err.message;}}
$('settings-form').addEventListener('submit',async event=>{event.preventDefault();try{await request('/api/settings',{api_key:$('api-key').value.trim()});$('api-key').value='';await updateSettings();notice('Rebrickable API key saved locally.');}catch(err){notice(err.message,true);}});
window.addEventListener('beforeunload',()=>{cameraOff();if(photoUrl)URL.revokeObjectURL(photoUrl);});
refresh().then(updateSettings).catch(err=>notice('Startup failed: '+err.message,true));
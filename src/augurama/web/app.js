const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = { models: [], assets: [], refs: new Map(), contract: null, private: null, job: null, dirty: false, signup: false, timer: null, originalRequest: '', parentId: null };
const lines = (id) => $(id).value.split('\n').map(x=>x.trim()).filter(Boolean);
const dateText = (value) => new Date(value * 1000).toLocaleString(undefined, {dateStyle:'medium',timeStyle:'short'});
const csrf = () => document.cookie.split('; ').find(x=>x.startsWith('dd_csrf='))?.split('=').slice(1).join('=') || '';
async function api(path, options={}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrf());
  const response = await fetch(path, {...options, headers, credentials:'same-origin', redirect:'error'});
  let data; try { data = await response.json(); } catch { throw new Error(`Server returned HTTP ${response.status}. No generation retry was made.`); }
  if (!response.ok) {
    const error = data.error || {};
    const details = error.details?.map(x=>`${x.path}: ${x.message}`).join(' · ');
    const e = new Error(details || error.message || `Request failed (${response.status})`); e.code = error.code; throw e;
  }
  return data;
}
function alertError(message, id='plan-error') { $(id).textContent = message; if(id==='global-error') $(id).hidden = !message; }
function busy(button, on, label) { button.disabled = on; if (on) { button.dataset.label=button.textContent; button.textContent=label; } else button.textContent=button.dataset.label || button.textContent; }
function markDirty() {
  state.dirty = Boolean(state.contract);
  if (state.contract && !state.job) {
    const approve = $('approve-generation'); if (approve) approve.disabled = true;
    $('review-chip').textContent='DIRECTION CHANGED';
    const msg=$('contract-dirty'); if(msg)msg.hidden=false;
  }
}
function selectModel() {
  const m=state.models.find(m=>m.profile===$('model').value); if(!m)return;
  $('duration').max=m.maximum_duration;
  const current=$('resolution').value;
  $('resolution').innerHTML=m.resolutions.map(r=>`<option${r===current?' selected':''}>${r}</option>`).join('');
  // Do not silently reduce duration or resolution; validation asks the user to choose.
}
function addShot(shot) {
  const el=document.createElement('div');el.className='shot';
  const last=$('shots').lastElementChild;
  const start=shot?.start ?? (last ? Number(last.querySelector('[data-field=end]').value) : 0);
  const end=shot?.end ?? Number($('duration').value);
  el.innerHTML=`<div class="shot-head"><span>AUTHORED BEAT</span><button type="button" data-remove-shot class="ghost small" aria-label="Remove timed shot">Remove</button></div><div class="time-fields"><div class="field"><label>Start (s)<input type="number" data-field="start" min="0" max="30" step="0.1" value="${esc(start)}" required></label></div><div class="field"><label>End (s)<input type="number" data-field="end" min="0.1" max="30" step="0.1" value="${esc(end)}" required></label></div></div><div class="field"><label>Action<textarea data-field="action" rows="2" maxlength="900" required minlength="3">${esc(shot?.action||'')}</textarea></label></div><div class="field"><label>Camera<input data-field="camera" maxlength="400" value="${esc(shot?.camera||'')}"></label></div><div class="field"><label>Sound<input data-field="sound" maxlength="300" value="${esc(shot?.sound||'')}"></label></div>`;
  el.querySelector('[data-remove-shot]').addEventListener('click',()=>{el.remove();markDirty();});
  $('shots').append(el);
}
function readPlan() {
  const direction=$('direction').value.trim();
  return {title:$('title').value.trim(),original_request:state.originalRequest||direction,direction,model_profile:$('model').value,recipe:$('recipe').value,operation:$('operation').value,duration_seconds:Number($('duration').value),aspect_ratio:$('ratio').value,resolution:$('resolution').value,shots:[...$('shots').children].map(el=>Object.fromEntries(['start','end','action','camera','sound'].map(k=>[k,['start','end'].includes(k)?Number(el.querySelector(`[data-field=${k}]`).value):el.querySelector(`[data-field=${k}]`).value]))),references:[...state.refs].filter(([,v])=>v.role).map(([asset_id,v])=>({asset_id,...v})),audio:$('audio-enabled').checked?{enabled:true,dialogue:lines('dialogue'),ambience:$('ambience').value.trim(),music:$('music').value.trim()}:{enabled:false,dialogue:[],ambience:'',music:''},preserve:lines('preserve'),avoid:lines('avoid'),parent_generation_id:state.parentId,seed:$('seed').value===''?null:Number($('seed').value),watermark:$('watermark').checked};
}
function loadPlan(p) {
  state.originalRequest=p.original_request;state.parentId=p.parent_generation_id;
  for(const [id,key] of Object.entries({title:'title',direction:'direction',model:'model_profile',recipe:'recipe',operation:'operation',duration:'duration_seconds',ratio:'aspect_ratio'})) $(id).value=p[key];
  selectModel();$('resolution').value=p.resolution;$('seed').value=p.seed??'';$('watermark').checked=p.watermark;
  $('audio-enabled').checked=p.audio.enabled;$('dialogue').value=p.audio.dialogue.join('\n');$('ambience').value=p.audio.ambience;$('music').value=p.audio.music;
  $('preserve').value=p.preserve.join('\n');$('avoid').value=p.avoid.join('\n');$('shots').replaceChildren();p.shots.forEach(addShot);
  state.refs=new Map(p.references.map(({asset_id,...ref})=>[asset_id,ref]));renderAssets();state.dirty=false;
}
function renderAssets() {
  const roles=['identity','environment','style','object','motion','camera','audio','first_frame','last_frame'];
  $('asset-list').innerHTML=state.assets.map(a=>{
    const ref=state.refs.get(a.id)||{role:'',direction:''};
    const preview=a.kind==='image'&&!a.provider_uri?`<img src="${esc(a.preview_url)}" alt="${esc(a.name)}">`:'<div class="ref-fallback" style="width:52px;height:62px">'+esc(a.kind)+'</div>';
    return `<div class="reference-card" data-asset="${esc(a.id)}">${preview}<div class="file-info"><div class="file-name">${esc(a.name)}</div><div class="two"><label class="sr-only" for="role-${a.id}">Role for ${esc(a.name)}</label><select id="role-${a.id}" data-role><option value="">Not used</option>${roles.filter(r=>a.kind==='audio'?r==='audio':r!=='audio').map(r=>`<option value="${r}"${ref.role===r?' selected':''}>${r.replaceAll('_',' ')}</option>`).join('')}</select><button type="button" data-delete-asset class="ghost small" aria-label="Delete ${esc(a.name)}">Delete</button></div><label class="sr-only" for="direction-${a.id}">Reference direction for ${esc(a.name)}</label><input id="direction-${a.id}" data-ref-direction maxlength="400" placeholder="What to preserve or use" value="${esc(ref.direction)}"><p class="hint">${esc(a.likeness)} · ${a.duration?esc(a.duration.toFixed(2))+' s · ':''}${Math.ceil(a.bytes/1024)} KB</p></div></div>`;
  }).join('') || '<p class="hint">Your private reference library is empty.</p>';
  $('ref-count').textContent=[...state.refs.values()].filter(v=>v.role).length;
}
async function loadAssets() { state.assets=(await api('/api/assets')).assets;renderAssets(); }
function stopPoll(){if(state.timer)clearTimeout(state.timer);state.timer=null;}
function schedulePoll(){stopPoll();if(state.job && ['submitting','queued','running','cancel_outcome_unknown'].includes(state.job.status) && !document.hidden)state.timer=setTimeout(refreshJob,5000);}
async function refreshJob(){if(!state.job)return;try{state.job=await api('/api/generations/'+state.job.generation_id);renderJob();await loadHistory();}catch(e){alertError(e.message,'review-error');}schedulePoll();}
function renderContract(data,privateData) {
  stopPoll();state.contract=data;state.private=privateData;state.job=null;state.dirty=false;
  const p=data.plan;const seconds=p.duration_seconds;
  $('review-chip').textContent=data.expired?'APPROVAL EXPIRED':'CONTRACT FROZEN';
  $('review-body').innerHTML=`<div class="meta-grid"><div><small>Model</small><strong>${esc(p.model_profile.replace('seedance-','Seedance '))}</strong></div><div><small>Duration</small><strong>${seconds} seconds</strong></div><div><small>Format</small><strong>${esc(p.aspect_ratio)} · ${esc(p.resolution)}</strong></div><div><small>Sound</small><strong>${p.audio.enabled?'Native audio':'Silent'}</strong></div></div><div class="panel-body"><p class="eyebrow">EXACTLY THIS TAKE</p><h2 class="contract-title">${esc(p.title)}</h2><div id="contract-dirty" class="status-banner" hidden>You changed the direction. Prepare a new contract before generating.</div>${data.expired?'<p class="notice">This approval expired. Prepare a new contract; no settings will be changed silently.</p>':''}<div class="reference-strip">${data.reference_map.map(r=>{const a=(privateData.preview_assets||[]).find(a=>a.id===r.asset_id);return `<figure class="ref-preview" style="margin:0">${a?.kind==='image'?`<img src="${esc(a.preview_url)}" alt="${esc(r.name)}">`:`<div class="ref-fallback">${esc(r.kind)}</div>`}<figcaption>${esc(r.token)}<br>${esc(r.role.replaceAll('_',' '))}</figcaption></figure>`;}).join('')}</div>${p.shots.length?`<div class="timeline" aria-label="Shot timeline">${p.shots.map(s=>`<span class="beat" style="flex:${s.end-s.start}" title="${esc(s.action)}">${s.start}–${s.end}s</span>`).join('')}</div>`:''}<label for="contract-prompt">Compiled production direction · ${data.compiled_prompt.length} characters</label><pre class="prompt" id="contract-prompt" tabindex="0">${esc(data.compiled_prompt)}</pre><p class="hint mono">${esc(data.model_id)}<br>Recipe ${esc(data.recipe_version)} · Model card ${esc(data.model_revision)}<br>Contract ${esc(data.fingerprint.slice(0,20))}…</p><hr class="divider"><div class="bar"><div><p class="eyebrow">APPROXIMATE API USAGE</p><div class="cost">$${data.estimate.approximate_usd.toFixed(2)} <small>USD / one take</small></div></div><span class="chip">NOT DREAMINA CREDITS</span></div><p class="hint">${esc(data.estimate.notice)}</p><p class="hint">Approval expires ${esc(dateText(data.expires_at))}.</p><label class="check"><input id="approve-rights" type="checkbox"><span>I have permission to use the selected media, likenesses, voices and other content.</span></label><label class="check"><input id="approve-billing" type="checkbox"><span>I approve this exact contract and the provider’s API charges. The estimate is not a billing cap.</span></label><p id="review-error" class="error-text" role="alert"></p><button id="approve-generation" class="primary full" disabled>Approve & generate one take ↗</button><div class="spacer"></div><div class="actions"><a href="/api/contracts/${esc(data.contract_id)}/export" class="small">Export contract</a><button id="copy-prompt" class="ghost small">Copy direction</button><button id="revise-contract" class="ghost small">Revise</button></div></div>`;
  const sync=()=>{$('approve-generation').disabled=data.expired||Boolean(data.generation_id)||state.dirty||!$('approve-rights').checked||!$('approve-billing').checked;};
  $('approve-rights').addEventListener('change',sync);$('approve-billing').addEventListener('change',sync);
  $('approve-generation').addEventListener('click',async()=>{
    if(state.dirty)return;
    const button=$('approve-generation');busy(button,true,'Submitting exactly one take…');
    try {state.job=await api('/api/generations',{method:'POST',body:JSON.stringify({contract_id:data.contract_id,fingerprint:data.fingerprint,approval_token:privateData.approval_token,rights_confirmed:true,accept_provider_billing:true})});renderJob();await loadHistory();schedulePoll();}
    catch(e){alertError(e.message,'review-error');busy(button,false);}
  });
  $('copy-prompt').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(data.compiled_prompt);$('copy-prompt').textContent='Copied';}catch{alertError('Select and copy the direction text above.','review-error');}});
  $('revise-contract').addEventListener('click',async()=>{try{await api('/api/contracts/'+data.contract_id,{method:'DELETE'});state.contract.expired=true;markDirty();$('direction').focus();}catch(e){alertError(e.message,'review-error');}});
}
function renderJob(){
  const job=state.job;const result=job.result||{};const active=['submitting','queued','running'].includes(job.status);const unknown=['submission_unknown','cancel_outcome_unknown'].includes(job.status);
  $('review-chip').textContent=job.status.toUpperCase().replaceAll('_',' ');
  $('review-body').innerHTML=`<div class="panel-body"><p class="eyebrow">YOUR APPROVED TAKE</p><h2 class="contract-title">${esc(job.title)}</h2><div class="job-status" role="status">${active?'<span class="spinner" aria-hidden="true"></span>':''}<strong>${esc(job.status.replaceAll('_',' '))}</strong><span class="muted">${esc(dateText(job.created_at))}</span></div>${result.video_url?`<div class="player"><video controls playsinline preload="metadata" src="${esc(result.video_url)}" aria-label="Generated video"></video></div>`:`<div class="status-still"><div><h3>${unknown?'Do not submit again.':active?'The provider is making your take.':job.status==='succeeded'?'Rendered. Saving your media…':'This take needs attention.'}</h3><p>${unknown?'The submission or cancellation outcome needs reconciliation in the provider console.':active?'You can leave this page. The running service will continue checking this task ID. No new generations are started.':'Check the status and recovery information below.'}</p></div></div>`}${result.error?`<p class="notice">${esc(result.error)}</p>`:''}${result.archive_error?`<p class="notice">${esc(result.archive_error)} Provider URLs expire; check the original task promptly.</p>`:''}${result.poll_error?`<p class="notice">${esc(result.poll_error)}</p>`:''}${result.usage?.completion_tokens!=null?`<p class="small muted">${result.usage.completion_tokens.toLocaleString()} completion tokens · $${(result.list_rate_usage_usd||0).toFixed(4)} at the recorded list rate.<br>${esc(result.usage_notice)}</p>`:''}<p class="hint mono">Generation ${esc(job.generation_id)}<br>Provider task ${esc(job.provider_task_id||'not confirmed')}</p><p id="review-error" class="error-text" role="alert"></p><div class="actions"><button id="refresh-job">Check status</button>${result.video_url?`<a class="small" href="${esc(result.video_url)}" target="_blank" rel="noopener noreferrer">Open saved video</a>`:''}${result.last_frame_url?`<a class="small" href="${esc(result.last_frame_url)}" target="_blank" rel="noopener noreferrer">Last frame</a>`:''}<button id="review-original" class="ghost">Original contract</button><button id="new-variation" class="ghost">Prepare a variation</button></div>${job.status==='queued'?'<details><summary>Cancel queued task</summary><p class="hint">The provider only allows cancelling queued tasks. If it finishes between the status check and cancellation, its provider record may be deleted. No refund is assumed.</p><label class="check"><input id="cancel-ack" type="checkbox"><span>I understand this race and authorize the possible deletion of the provider’s completed-task record.</span></label><button id="cancel-job" class="danger" disabled>Request cancellation</button></details>':''}</div>`;
  $('refresh-job').addEventListener('click',refreshJob);
  $('review-original').addEventListener('click',()=>openContract(job.contract_id,false));
  $('new-variation').addEventListener('click',async()=>{try{const data=await api('/api/contracts/'+job.contract_id);loadPlan(data.contract.plan);state.parentId=job.generation_id;state.contract=null;state.private=null;state.job=null;stopPoll();$('direction').focus();$('review-chip').textContent='VARIATION NOT SUBMITTED';$('review-body').innerHTML='<div class="empty-stage"><div><h2>A fresh take. A fresh approval.</h2><p>Revise the direction, then prepare a new contract. Nothing is generated automatically.</p></div></div>';}catch(e){alertError(e.message,'review-error');}});
  if($('cancel-ack')){$('cancel-ack').addEventListener('change',()=>{$('cancel-job').disabled=!$('cancel-ack').checked;});$('cancel-job').addEventListener('click',async()=>{busy($('cancel-job'),true,'Requesting…');try{state.job=await api(`/api/generations/${job.generation_id}/cancel`,{method:'POST',body:JSON.stringify({accept_completed_record_deletion:true})});renderJob();}catch(e){alertError(e.message,'review-error');busy($('cancel-job'),false);}});}
}
async function openContract(id,showJob=true){try{const r=await api('/api/contracts/'+id);loadPlan(r.contract.plan);renderContract(r.contract,r.private);if(r.contract.generation_id&&showJob){state.job=await api('/api/generations/'+r.contract.generation_id);renderJob();schedulePoll();}}catch(e){alertError(e.message);}}
async function loadHistory(){const {generations}=await api('/api/generations');$('history').innerHTML=generations.map(g=>`<button class="history-item" data-job="${esc(g.generation_id)}"><span><strong>${esc(g.title)}</strong><small>${esc(dateText(g.created_at))}</small></span><span class="chip">${esc(g.status.replaceAll('_',' '))}</span></button>`).join('')||'<p class="muted small">No generations yet. Nothing has been spent.</p>';}
function showAccount(show){$('account-view').hidden=!show;$('director-view').hidden=show;if(show)$('provider-key').focus();}
async function loadDesk(){
  const account=await api('/api/account');$('auth').hidden=true;$('desk').hidden=false;$('account-toggle').hidden=false;$('logout').hidden=false;
  $('connection-notice').hidden=account.provider_key_configured;$('connection-notice').textContent='Planning is available. Add your own Fal.ai or ModelArk API key in Account before you approve a generation.';
  $('key-status').textContent=account.provider_key_configured?'Encrypted key configured. Model entitlement has not been verified.':'No API key configured (Fal.ai or ModelArk).';
  await loadAssets();await loadHistory();
  const params=new URLSearchParams(location.search);const returnTo=params.get('return_to');
  if(returnTo&&returnTo.startsWith('/oauth/authorize?')){location.assign(returnTo);return;}
  if(params.get('contract'))await openContract(params.get('contract'));
  else if(params.get('generation')){state.job=await api('/api/generations/'+params.get('generation'));renderJob();schedulePoll();}
  if(location.hash==='#account')showAccount(true);
}
$('signup-toggle').addEventListener('click',()=>{state.signup=!state.signup;$('invite-field').hidden=!state.signup;$('invitation').required=state.signup;$('password').autocomplete=state.signup?'new-password':'current-password';$('auth-submit').textContent=state.signup?'Create private account':'Sign in';$('signup-toggle').textContent=state.signup?'Back to sign in':'I have an invitation';alertError('','auth-error');});
$('login-form').addEventListener('submit',async(event)=>{event.preventDefault();const button=$('auth-submit');busy(button,true,'Connecting…');alertError('','auth-error');try{const login={username:$('username').value,password:$('password').value};if(state.signup)await api('/api/signup',{method:'POST',body:JSON.stringify({...login,invitation:$('invitation').value})});await api('/api/login',{method:'POST',body:JSON.stringify(login)});$('password').value='';$('invitation').value='';await loadDesk();}catch(e){alertError(e.message,'auth-error');}finally{busy(button,false);}});
$('logout').addEventListener('click',async()=>{try{await api('/api/logout',{method:'POST'});location.assign('/');}catch(e){alertError(e.message,'global-error');}});
$('account-toggle').addEventListener('click',()=>showAccount($('account-view').hidden));$('back-to-desk').addEventListener('click',()=>showAccount(false));
$('key-form').addEventListener('submit',async event=>{event.preventDefault();try{await api('/api/account/provider-key',{method:'POST',body:JSON.stringify({key:$('provider-key').value})});$('provider-key').value='';$('key-status').textContent='Key encrypted and saved. Access is not yet verified.';$('connection-notice').hidden=true;}catch(e){$('key-status').textContent=e.message;}});
$('remove-key').addEventListener('click',async()=>{try{await api('/api/account/provider-key',{method:'POST',body:JSON.stringify({key:''})});$('key-status').textContent='Key removed. Status checks need the original provider account to be reconnected.';$('connection-notice').hidden=false;}catch(e){$('key-status').textContent=e.message;}});
$('model').addEventListener('change',selectModel);$('add-shot').addEventListener('click',()=>{if($('shots').children.length<12){addShot();markDirty();}});
$('plan-form').addEventListener('input',markDirty);$('plan-form').addEventListener('change',markDirty);
$('plan-form').addEventListener('submit',async event=>{event.preventDefault();alertError('');const button=$('prepare-button');busy(button,true,'Validating direction…');try{if(state.contract&&!state.job)await api('/api/contracts/'+state.contract.contract_id,{method:'DELETE'});const data=await api('/api/contracts',{method:'POST',body:JSON.stringify({plan:readPlan()})});state.originalRequest=data.contract.plan.original_request;renderContract(data.contract,data.private);if(innerWidth<760)$('review-panel').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});}catch(e){alertError(e.message);}finally{busy(button,false);}});
$('asset-list').addEventListener('change',event=>{const card=event.target.closest('[data-asset]');if(!card)return;state.refs.set(card.dataset.asset,{role:card.querySelector('[data-role]').value,direction:card.querySelector('[data-ref-direction]').value});$('ref-count').textContent=[...state.refs.values()].filter(x=>x.role).length;markDirty();});
$('asset-list').addEventListener('input',event=>{const card=event.target.closest('[data-asset]');if(card)state.refs.set(card.dataset.asset,{role:card.querySelector('[data-role]').value,direction:card.querySelector('[data-ref-direction]').value});});
$('asset-list').addEventListener('click',async event=>{if(!event.target.closest('[data-delete-asset]'))return;const id=event.target.closest('[data-asset]').dataset.asset;try{await api('/api/assets/'+id,{method:'DELETE'});state.refs.delete(id);await loadAssets();markDirty();}catch(e){alertError(e.message);}});
$('upload-button').addEventListener('click',async()=>{const file=$('upload-file').files[0];if(!file||!$('upload-rights').checked){alertError('Choose a reference and confirm permission before importing.');return;}const button=$('upload-button');busy(button,true,'Inspecting reference…');try{const form=new FormData();form.append('file',file);form.append('likeness',$('likeness').value);form.append('rights_confirmed','true');await api('/api/assets/upload',{method:'POST',body:form});$('upload-file').value='';$('upload-rights').checked=false;await loadAssets();alertError('');}catch(e){alertError(e.message);}finally{busy(button,false);}});
$('provider-asset-button').addEventListener('click',async()=>{if(!$('provider-asset-rights').checked){alertError('Confirm provider asset authorization first.');return;}try{await api('/api/assets/provider',{method:'POST',body:JSON.stringify({uri:$('provider-asset').value,name:$('provider-asset-name').value,kind:'image',rights_confirmed:true})});await loadAssets();$('provider-asset').value='';alertError('');}catch(e){alertError(e.message);}});
$('refresh-history').addEventListener('click',()=>loadHistory().catch(e=>alertError(e.message)));
$('history').addEventListener('click',async event=>{const button=event.target.closest('[data-job]');if(!button)return;try{state.job=await api('/api/generations/'+button.dataset.job);renderJob();schedulePoll();}catch(e){alertError(e.message);}});
document.addEventListener('visibilitychange',()=>document.hidden?stopPoll():schedulePoll());
try{const data=await api('/api/public');state.models=data.capabilities.model_registry.models;$('model').innerHTML=state.models.map(m=>`<option value="${esc(m.profile)}">${esc(m.label)}</option>`).join('');$('model').value='seedance-2.0';selectModel();$('mcp-url').textContent=location.origin+'/mcp';try{await loadDesk();}catch(e){if(e.code==='LOGIN_REQUIRED')$('auth').hidden=false;else throw e;}}catch(e){alertError(e.message,'global-error');}

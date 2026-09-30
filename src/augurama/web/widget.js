(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pending=new Map(); let sequence=0,hostOrigin=null,connected=false,current=null,privateData={},generation=null,timer=null;
  function rpc(method,params={}){
    return new Promise((resolve,reject)=>{
      const id='dd-'+(++sequence);const timeout=setTimeout(()=>{pending.delete(id);reject(new Error('The host did not respond. Open the secure review link rather than resubmitting.'));},60000);
      pending.set(id,{resolve,reject,timeout});
      window.parent.postMessage({jsonrpc:'2.0',id,method,params},hostOrigin&&hostOrigin!=='null'?hostOrigin:'*');
    });
  }
  function notify(method,params={}){window.parent.postMessage({jsonrpc:'2.0',method,params},hostOrigin&&hostOrigin!=='null'?hostOrigin:'*');}
  function error(e){$('widget-error').textContent=e.message||String(e);}
  function validUrl(url){try{const u=new URL(url);return ['http:','https:'].includes(u.protocol)&&!u.username&&!u.password;}catch{return false;}}
  async function openLink(url){if(!validUrl(url))throw new Error('Invalid link.');await rpc('ui/open-link',{url});}
  async function call(name,args){
    const result=await rpc('tools/call',{name,arguments:args});
    if(result.isError)throw new Error(result.structuredContent?.error?.message||result.content?.find(c=>c.type==='text')?.text||'The operation failed.');
    return result;
  }
  function stop(){if(timer)clearTimeout(timer);timer=null;}
  function poll(){stop();if(generation&&['queued','running','submitting','cancel_outcome_unknown'].includes(generation.status)&&!document.hidden)timer=setTimeout(async()=>{try{accept(await call('dreamina_get_generation',{generation_id:generation.generation_id}));}catch(e){error(e);poll();}},5000);}
  function renderContract(){
    const c=current,p=c.plan;generation=null;stop();
    $('widget-status').textContent=c.expired?'EXPIRED':'FROZEN CONTRACT';
    $('widget-main').innerHTML=`<h1>${esc(p.title)}</h1><section class="panel"><div class="meta-grid"><div><small>Model</small><strong>${esc(p.model_profile)}</strong></div><div><small>Time</small><strong>${p.duration_seconds}s</strong></div><div><small>Format</small><strong>${esc(p.aspect_ratio)} · ${esc(p.resolution)}</strong></div><div><small>Audio</small><strong>${p.audio.enabled?'Native':'Silent'}</strong></div></div><div class="panel-body"><div class="reference-strip">${c.reference_map.map(r=>{const a=(privateData.preview_assets||[]).find(a=>a.id===r.asset_id);return `<div class="ref-preview">${a?.kind==='image'&&validUrl(a.preview_url)?`<img alt="${esc(r.name)}" src="${esc(a.preview_url)}">`:`<div class="ref-fallback">${esc(r.kind)}</div>`}<figcaption>${esc(r.token)} · ${esc(r.role)}</figcaption></div>`;}).join('')}</div><details open><summary>Exact production direction</summary><pre class="prompt" tabindex="0">${esc(c.compiled_prompt)}</pre></details><p class="hint mono">${esc(c.model_id)}<br>Contract ${esc(c.fingerprint.slice(0,20))}… · Recipe ${esc(c.recipe_version)}</p><hr class="divider"><p class="eyebrow">APPROXIMATE API USAGE</p><div class="cost">$${c.estimate.approximate_usd.toFixed(2)} <small>USD · one take</small></div><p class="hint">${esc(c.estimate.notice)}</p><p class="hint">Expires ${esc(new Date(c.expires_at*1000).toLocaleString())}</p>${c.generation_id?'<p class="notice">This contract already has a generation. It cannot create a second task.</p>':''}<label class="check"><input id="widget-rights" type="checkbox"><span>I have the rights and permission for all selected content and likenesses.</span></label><label class="check"><input id="widget-billing" type="checkbox"><span>I approve this exact contract and the provider charges. This estimate is not a billing cap.</span></label><button id="widget-generate" class="primary full" disabled>Approve & generate one take</button><div class="spacer"></div><button id="widget-open" class="ghost full">Open secure production desk ↗</button></div></section>`;
    const consent=()=>{$('widget-generate').disabled=c.expired||Boolean(c.generation_id)||!privateData.approval_token||!$('widget-rights').checked||!$('widget-billing').checked;};
    $('widget-rights').addEventListener('change',consent);$('widget-billing').addEventListener('change',consent);
    $('widget-generate').addEventListener('click',async()=>{
      const b=$('widget-generate');b.disabled=true;b.textContent='Submitting exactly one take…';$('widget-error').textContent='';
      try{accept(await call('dreamina_submit_generation',{contract_id:c.contract_id,fingerprint:c.fingerprint,approval_token:privateData.approval_token,rights_confirmed:true,accept_provider_billing:true}));}
      catch(e){error(e);b.textContent='Approve & generate one take';consent();}
    });
    $('widget-open').addEventListener('click',()=>openLink(c.review_url).catch(error));
    if(!privateData.approval_token)error(new Error('This host did not deliver the private approval capability. Use the secure production desk; approval cannot be inferred from chat.'));
  }
  function renderGeneration(){
    const g=generation,r=g.result||{};const active=['queued','running','submitting'].includes(g.status);
    $('widget-status').textContent=g.status.toUpperCase().replaceAll('_',' ');
    $('widget-main').innerHTML=`<h1>${esc(g.title)}</h1><section class="panel"><div class="panel-body"><div class="job-status" role="status">${active?'<span class="spinner" aria-hidden="true"></span>':''}${esc(g.status.replaceAll('_',' '))}</div>${r.video_url&&validUrl(r.video_url)?`<div class="player"><video controls playsinline preload="metadata" src="${esc(r.video_url)}" aria-label="Generated video"></video></div>`:`<div class="status-still"><div><h3>${g.status==='submission_unknown'?'Do not resubmit.':active?'Your approved take is in production.':g.status==='succeeded'?'Rendered. Saving the output…':'Review this take’s status.'}</h3><p>Only the existing task is checked. No automatic regeneration.</p></div></div>`}${r.error?`<p class="notice">${esc(r.error)}</p>`:''}${r.archive_error?`<p class="notice">${esc(r.archive_error)}</p>`:''}<p class="hint mono">${esc(g.provider_task_id||'Provider task ID not confirmed')}</p><div class="actions"><button id="widget-check">Check status</button><button id="widget-open-job" class="ghost">Open production desk ↗</button></div><p class="hint">To revise or extend, ask for a new contract. Every new take needs new approval.</p></div></section>`;
    $('widget-check').addEventListener('click',async()=>{try{accept(await call('dreamina_get_generation',{generation_id:g.generation_id}));}catch(e){error(e);}});
    $('widget-open-job').addEventListener('click',()=>openLink(g.review_url).catch(error));
    poll();
  }
  function accept(result){
    if(result?.isError){error(new Error(result.structuredContent?.error?.message||'The tool returned an error.'));return;}
    const data=result?.structuredContent;
    if(!data)return;
    $('widget-error').textContent='';
    if(data.plan&&data.fingerprint){current=data;privateData=result._meta||{};renderContract();}
    else if(data.generation_id&&data.status){generation=data;renderGeneration();}
  }
  window.addEventListener('message',event=>{
    if(event.source!==window.parent)return;
    const msg=event.data;if(!msg||msg.jsonrpc!=='2.0')return;
    // Pin the first authenticated-by-parent handshake response. Never accept sibling-window messages.
    if(hostOrigin!==null&&event.origin!==hostOrigin)return;
    const waiter=pending.get(msg.id);
    if(waiter){if(hostOrigin===null)hostOrigin=event.origin;clearTimeout(waiter.timeout);pending.delete(msg.id);msg.error?waiter.reject(new Error(msg.error.message||'Host request failed.')):waiter.resolve(msg.result);return;}
    if(!connected)return;
    if(msg.method==='ui/notifications/tool-result')accept(msg.params);
    else if(msg.method==='ui/notifications/host-context-changed'){
      const theme=msg.params?.theme;if(theme==='light'||theme==='dark')document.documentElement.dataset.hostTheme=theme;
    }else if(msg.method==='ui/resource-teardown'&&msg.id!==undefined){stop();window.parent.postMessage({jsonrpc:'2.0',id:msg.id,result:{}},hostOrigin&&hostOrigin!=='null'?hostOrigin:'*');}
  });
  document.addEventListener('visibilitychange',()=>document.hidden?stop():poll());
  new ResizeObserver(()=>{if(connected)notify('ui/notifications/size-changed',{height:document.documentElement.scrollHeight});}).observe(document.body);
  if(window.parent===window){$('widget-status').textContent='HOST REQUIRED';error(new Error('Open this review card from an MCP Apps-compatible host, or use the production desk.'));return;}
  rpc('ui/initialize',{appInfo:{name:'Dreamina Director',version:'0.1.0-rc.1'},appCapabilities:{},protocolVersion:'2026-01-26'}).then(result=>{
    if(result.protocolVersion!=='2026-01-26')throw new Error('Host selected an unsupported MCP Apps protocol. Use the secure review link.');
    connected=true;notify('ui/notifications/initialized');$('widget-status').textContent='READY FOR CONTRACT';
  }).catch(error);
})();

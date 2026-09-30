"""Real Chromium DOM/interaction tests, with offline network fulfillment.

This environment blocks browser URL navigation by administrator policy. We do not
change that policy. Inline the production assets into about:blank and bridge fetch
through FastAPI's actual TestClient. Browser origin/cookie/TLS behavior is therefore
NOT validated here; those HTTP/security properties are covered separately.
"""
from __future__ import annotations
import base64
import json
import os
from pathlib import Path
import shutil

import pytest
from playwright.sync_api import sync_playwright,expect

from augurama.app import WEB
from augurama.auth import Principal,SCOPES
from augurama.models import GenerationPlan

EVIDENCE=Path(os.environ.get('DD_EVIDENCE_DIR',str(Path(__file__).parents[1]/'artifacts'/'browser')))

@pytest.fixture
def browser():
    binary=os.environ.get('DD_TEST_CHROMIUM') or shutil.which('chromium')
    with sync_playwright() as p:
        b=p.chromium.launch(executable_path=binary,headless=True,args=['--no-sandbox'] if os.geteuid()==0 else [])
        yield b
        b.close()


def data_media(client,value):
    if isinstance(value,dict):return {k:data_media(client,v) for k,v in value.items()}
    if isinstance(value,list):return [data_media(client,v) for v in value]
    if isinstance(value,str) and value.startswith('http://127.0.0.1:8765/media/'):
        from urllib.parse import urlsplit
        u=urlsplit(value);r=client.get(u.path+'?'+u.query)
        assert r.status_code==200
        return 'data:'+r.headers['content-type']+';base64,'+base64.b64encode(r.content).decode()
    return value


def attach_offline_app(page,client,engine):
    def bridge(request):
        path=request['url']
        if not path.startswith('/api/'):
            raise AssertionError('Unapproved browser API path: '+path)
        headers={**request.get('headers',{}),'Origin':engine.settings.base_url}
        kwargs={}
        if request.get('form'):
            fields=request['form'];files=[];data={}
            for field in fields:
                if 'base64' in field:files.append((field['name'],(field['filename'],base64.b64decode(field['base64']),field['mime'])))
                else:data[field['name']]=field['value']
            kwargs.update(files=files,data=data)
        elif request.get('body') is not None:
            kwargs['content']=request['body']
        response=client.request(request.get('method','GET'),path,headers=headers,**kwargs)
        try:body=json.dumps(data_media(client,response.json()))
        except ValueError:body=response.text
        return {'status':response.status_code,'body':body,'headers':{'Content-Type':response.headers.get('content-type','application/json')},'cookies':'; '.join(f'{k}={v}' for k,v in client.cookies.items())}
    page.expose_function('__directorOfflineRequest',bridge)
    bootstrap="""let offlineCookies='';Object.defineProperty(document,'cookie',{get:()=>offlineCookies,set:v=>{offlineCookies=v}});window.fetch=async(url,options={})=>{const req={url:String(url),method:options.method||'GET',headers:Object.fromEntries(new Headers(options.headers||{}))};if(options.body instanceof FormData){req.form=[];for(const [name,v] of options.body){if(v instanceof File){const bytes=new Uint8Array(await v.arrayBuffer());let raw='';for(const x of bytes)raw+=String.fromCharCode(x);req.form.push({name,filename:v.name,mime:v.type,base64:btoa(raw)})}else req.form.push({name,value:v})}}else if(options.body!=null)req.body=options.body;const r=await window.__directorOfflineRequest(req);offlineCookies=r.cookies;return new Response(r.body,{status:r.status,headers:r.headers})};"""
    html=(WEB/'index.html').read_text()
    css=(WEB/'style.css').read_text();js=(WEB/'app.js').read_text()
    mark='data:image/svg+xml;base64,'+base64.b64encode((WEB/'mark.svg').read_bytes()).decode()
    html=html.replace('<link rel="stylesheet" href="/static/style.css">','<style>'+css+'</style>').replace('/static/mark.svg',mark)
    html=html.replace('<script type="module" src="/static/app.js"></script>','<script>'+bootstrap+'</script><script type="module">'+js+'</script>')
    page.set_content(html,wait_until='load')


@pytest.mark.browser
def test_desktop_mobile_keyboard_and_playable_output(browser,client,engine,uid,plan):
    page=browser.new_page(viewport={'width':1440,'height':1100},device_scale_factor=1)
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    attach_offline_app(page,client,engine)
    page.get_by_label('Account name',exact=True).fill('director-tester')
    page.get_by_label('Password',exact=True).fill('a sufficiently long test password')
    page.get_by_role('button',name='Sign in',exact=True).click()
    expect(page.locator('#desk')).to_be_visible()
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(EVIDENCE/'desktop-desk.png'),full_page=True)
    page.get_by_label('Project title').fill('The paper moon')
    page.get_by_label('What should happen?').fill('An entirely synthetic corgi discovers a paper moon in a miniature studio. Warm edge light traces its silhouette. The camera makes one slow, unbroken push-in as the moon turns. End with the corgi looking up, perfectly still. No dialogue or music; only a tiny creak from the paper scenery.')
    page.get_by_label('Direction recipe').select_option('continuous')
    page.get_by_label('Duration (seconds)').fill('4')
    page.get_by_role('button',name='Prepare generation contract').click()
    expect(page.locator('#approve-generation')).to_be_visible()
    assert not engine.test_transport.calls
    expect(page.locator('#approve-generation')).to_be_disabled()
    page.screenshot(path=str(EVIDENCE/'desktop-contract.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844});page.emulate_media(reduced_motion='reduce')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(EVIDENCE/'mobile-contract.png'),full_page=True)
    page.locator('#approve-rights').focus();page.keyboard.press('Space')
    page.keyboard.press('Tab');expect(page.locator('#approve-billing')).to_be_focused();page.keyboard.press('Space')
    page.keyboard.press('Tab');expect(page.locator('#approve-generation')).to_be_focused()
    expect(page.locator('#approve-generation')).to_be_enabled();page.keyboard.press('Enter')
    expect(page.locator('#refresh-job')).to_be_visible()
    page.locator('#refresh-job').click()
    video=page.locator('.player video');expect(video).to_be_visible()
    video.evaluate('(v)=>v.play()')
    page.wait_for_function('document.querySelector("video")?.readyState >= 2')
    assert video.evaluate('(v)=>v.duration')==pytest.approx(4,abs=.05)
    assert video.evaluate('(v)=>v.error') is None
    page.screenshot(path=str(EVIDENCE/'mobile-result-test-fixture.png'),full_page=True)
    page.set_viewport_size({'width':1440,'height':1100})
    page.screenshot(path=str(EVIDENCE/'desktop-result-test-fixture.png'),full_page=True)
    assert len([c for c in engine.test_transport.calls if c[0]=='POST'])==1
    assert errors==[]
    page.close()


@pytest.mark.browser
def test_embedded_mcp_apps_review_and_approval(browser,client,engine,uid,plan):
    page=browser.new_page(viewport={'width':1080,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    who=Principal(uid,'director-tester',SCOPES)
    mcp=client.app.state.mcp
    result=mcp.tool(who,'augurama_prepare_generation',{'plan':plan.model_dump()})
    page.expose_function('__offlineTool',lambda p:mcp.tool(who,p['name'],p.get('arguments',{})))
    payload=base64.b64encode(json.dumps({'html':mcp.resource()['text'],'initial':result}).encode()).decode()
    page.set_content('''<!doctype html><html><head><style>body{background:#0f130f;font:14px system-ui;color:#d8ff7d;padding:20px}iframe{width:100%;height:1450px;border:1px solid #343e33;border-radius:18px}main{max-width:880px;margin:auto}</style></head><body><main><p>Offline MCP Apps host harness · no native host or provider claim</p><iframe id="app" title="Video review"></iframe></main><script>const p=JSON.parse(atob("'''+payload+'''"));const f=document.querySelector('iframe');f.srcdoc=p.html;function send(m){f.contentWindow.postMessage(m,'*')}window.addEventListener('message',async e=>{if(e.source!==f.contentWindow)return;const m=e.data;if(!m||m.jsonrpc!=='2.0')return;if(m.method==='ui/initialize'){window.__initialize=m.params;send({jsonrpc:'2.0',id:m.id,result:{protocolVersion:'2026-01-26',hostInfo:{name:'Offline harness',version:'1'},hostCapabilities:{serverTools:{},openLinks:{}},hostContext:{theme:'dark'}}})}else if(m.method==='ui/notifications/initialized'){send({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:p.initial})}else if(m.method==='tools/call'){send({jsonrpc:'2.0',id:m.id,result:await window.__offlineTool(m.params)})}else if(m.method==='ui/open-link'){window.__link=m.params.url;send({jsonrpc:'2.0',id:m.id,result:{}})}else if(m.method==='ui/notifications/size-changed'){f.style.height=(m.params.height+20)+'px'}})</script></body></html>''')
    frame=page.frame_locator('#app')
    expect(frame.locator('#widget-status')).to_have_text('FROZEN CONTRACT')
    assert page.evaluate('window.__initialize.protocolVersion')=='2026-01-26'
    expect(frame.locator('#widget-generate')).to_be_disabled()
    page.screenshot(path=str(EVIDENCE/'mcp-apps-contract-offline-harness.png'),full_page=True)
    frame.locator('#widget-open').click()
    page.wait_for_function("prefix => window.__link?.startsWith(prefix) === true",arg=engine.settings.base_url+'/?contract=')
    assert page.evaluate('window.__link').startswith(engine.settings.base_url+'/?contract=')
    frame.locator('#widget-rights').check();frame.locator('#widget-billing').check();frame.locator('#widget-generate').click()
    expect(frame.locator('#widget-status')).to_have_text('QUEUED')
    assert len([c for c in engine.test_transport.calls if c[0]=='POST'])==1
    assert errors==[]
    page.close()

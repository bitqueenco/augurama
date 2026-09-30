"""Local-only browser acceptance fixture. Not a production mode or provider fallback."""
import argparse
import json
from pathlib import Path
import tempfile

import httpx
from fastapi import Request
from fastapi.responses import HTMLResponse
import uvicorn

from conftest import FixtureFetcher,FixtureTransport,oauth_access
from augurama.app import create_app
from augurama.config import Settings
from augurama.models import GenerationPlan
from augurama.provider import BytePlus
from augurama.service import Director
from augurama.mcp import UI_URI

parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=18765);args=parser.parse_args()
settings=Settings(data_dir=Path(tempfile.mkdtemp(prefix='director-browser-')),base_url=f'http://127.0.0.1:{args.port}',environment='test',encryption_key=b'b'*32)
fixture=FixtureTransport()
d=Director(settings,provider=BytePlus(settings.provider_base_url,httpx.MockTransport(fixture)),fetcher=FixtureFetcher())
uid=d.auth.create_user('browser-reviewer','browser-only-test-password',d.auth.invite('Browser acceptance only'))
d.auth.save_provider_key(uid,'test-only-key-not-a-provider-credential')
app=create_app(settings,d)
tokens,_=oauth_access(d,uid);principal=d.auth.bearer(tokens['access_token'])

@app.get('/test-host')
def test_host():
    initial=app.state.mcp.tool(principal,'augurama_prepare_generation',{'plan':GenerationPlan(title='The paper moon',original_request='An entirely synthetic corgi discovers a paper moon.',direction='An entirely synthetic corgi pauses beneath a floating paper moon. Soft studio lighting, a slow forward camera move, and a held final frame.',duration_seconds=4,recipe='continuous').model_dump()})
    resource=app.state.mcp.resource()['text']
    payload=json.dumps({'html':resource,'initial':initial}).replace('<','\\u003c')
    # Deliberately minimal reference host, clearly NOT ChatGPT or Antigravity.
    return HTMLResponse('''<!doctype html><html><head><meta charset="utf-8"><title>MCP Apps browser harness — not a native host</title><style>body{background:#0C100D;color:#d8ff7d;font:14px system-ui;margin:22px}iframe{border:1px solid #343e33;border-radius:18px;width:100%;height:1250px;background:#101311}h1{font-size:16px;font-weight:500}main{max-width:920px;margin:auto}</style></head><body><main><h1>Protocol test host · synthetic provider · no AI generation or charges</h1><iframe id="app" title="Dreamina Director MCP Apps review"></iframe></main><script>const payload='''+payload+''';const f=document.getElementById('app');f.srcdoc=payload.html;function send(msg){f.contentWindow.postMessage(msg,'*');}window.addEventListener('message',async e=>{if(e.source!==f.contentWindow)return;const m=e.data;if(!m||m.jsonrpc!=='2.0')return;if(m.method==='ui/initialize'){send({jsonrpc:'2.0',id:m.id,result:{protocolVersion:'2026-01-26',hostInfo:{name:'Director test harness',version:'1.0'},hostCapabilities:{serverTools:{},openLinks:{}},hostContext:{theme:'dark',displayMode:'inline'}}});}else if(m.method==='ui/notifications/initialized'){send({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:payload.initial});}else if(m.method==='tools/call'){const r=await fetch('/test-tool',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(m.params)});send({jsonrpc:'2.0',id:m.id,result:await r.json()});}else if(m.method==='ui/open-link'){window.__openedLink=m.params.url;send({jsonrpc:'2.0',id:m.id,result:{}});}else if(m.method==='ui/notifications/size-changed'){f.style.height=Math.max(300,m.params.height+20)+'px';}});</script></body></html>''')

@app.post('/test-tool')
async def test_tool(request:Request):
    p=await request.json()
    return app.state.mcp.tool(principal,p['name'],p.get('arguments',{}))

@app.get('/test-counts')
def test_counts():
    return {'paid_posts_simulated':len([x for x in fixture.calls if x[0]=='POST']),'jobs':len(d.db.all('SELECT id FROM jobs'))}

@app.middleware('http')
async def harness_csp(request,call_next):
    response=await call_next(request)
    if request.url.path=='/test-host':
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-src 'self'; img-src 'self'; media-src 'self'; connect-src 'self'"
    return response

if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=args.port,log_level='warning',access_log=False)

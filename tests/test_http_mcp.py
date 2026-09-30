from __future__ import annotations
import json
from urllib.parse import parse_qs,urlsplit

import pytest
from jsonschema import Draft202012Validator

from conftest import FIXTURES,oauth_access
from augurama.mcp import UI_URI,tool_descriptors


def auth_headers(engine,uid):
    token,_=oauth_access(engine,uid)
    return {'Authorization':'Bearer '+token['access_token']}


def login(client,engine):
    headers={'Origin':engine.settings.base_url}
    result=client.post('/api/login',json={'username':'director-tester','password':'a sufficiently long test password'},headers=headers)
    assert result.status_code==200
    return {**headers,'X-CSRF-Token':result.json()['csrf_token']}


def legacy(client,headers,method,params=None,rid=1):
    return client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':rid,'method':method,'params':params or {}})


def modern(client,headers,method,params=None):
    params=params or {}
    params['_meta']={'io.modelcontextprotocol/protocolVersion':'2026-07-28','io.modelcontextprotocol/clientCapabilities':{}}
    headers={**headers,'MCP-Protocol-Version':'2026-07-28','Mcp-Method':method}
    if method=='tools/call':headers['Mcp-Name']=params.get('name','')
    return legacy(client,headers,method,params)


def test_unauthenticated_mcp_discovers_oauth(client,engine):
    response=client.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/list'})
    assert response.status_code==401
    assert '/.well-known/oauth-protected-resource' in response.headers['www-authenticate']
    assert client.get('/.well-known/oauth-protected-resource').json()['resource']==engine.settings.resource
    server=client.get('/.well-known/oauth-authorization-server').json()
    assert server['code_challenge_methods_supported']==['S256']
    assert server['authorization_response_iss_parameter_supported'] is True


def test_legacy_and_modern_protocols(client,engine,uid):
    headers=auth_headers(engine,uid)
    r=legacy(client,headers,'initialize',{'protocolVersion':'2025-11-25','clientInfo':{'name':'test','version':'1'},'capabilities':{}})
    assert r.status_code==200 and r.json()['result']['protocolVersion']=='2025-11-25'
    r=modern(client,headers,'server/discover')
    assert r.status_code==200
    assert r.json()['result']['supportedVersions'][0]=='2026-07-28'
    assert r.json()['result']['resultType']=='complete'
    assert r.json()['result']['_meta']['io.modelcontextprotocol/serverInfo']['name']=='augurama'
    assert client.get('/mcp').status_code==405
    assert 'mcp-session-id' not in r.headers


def test_modern_version_and_headers_checked(client,engine,uid):
    headers=auth_headers(engine,uid)
    r=legacy(client,{**headers,'MCP-Protocol-Version':'2099-01-01'},'tools/list')
    assert r.status_code==400 and r.json()['error']['code']==-32022
    r=legacy(client,{**headers,'MCP-Protocol-Version':'2026-07-28'},'tools/list')
    assert r.status_code==400
    r=legacy(client,{**headers,'MCP-Protocol-Version':'2026-07-28','Mcp-Method':'wrong'},'tools/list',{'_meta':{'io.modelcontextprotocol/protocolVersion':'2026-07-28','io.modelcontextprotocol/clientCapabilities':{}}})
    assert r.status_code==400


def test_tool_schemas_visibility_and_file_inputs(client,engine,uid):
    headers=auth_headers(engine,uid)
    result=modern(client,headers,'tools/list').json()['result']
    tools={t['name']:t for t in result['tools']}
    assert len(tools)==12
    for tool in tools.values():Draft202012Validator.check_schema(tool['inputSchema'])
    assert tools['augurama_submit_generation']['_meta']['ui']['visibility']==['app']
    assert tools['augurama_cancel_generation']['annotations']['destructiveHint'] is True
    file=tools['augurama_import_reference']['inputSchema']['properties']['file']
    assert file['required']==['download_url','file_id']
    assert set(file['properties'])=={'download_url','file_id','mime_type','file_name'}
    assert tools['augurama_import_reference']['_meta']['openai/fileParams']==['file']


def test_mcp_plan_private_approval_and_submit(client,engine,uid,plan):
    headers=auth_headers(engine,uid)
    result=modern(client,headers,'tools/call',{'name':'augurama_prepare_generation','arguments':{'plan':plan.model_dump()}}).json()['result']
    c=result['structuredContent']
    assert 'approval_token' not in json.dumps(c) and 'approval_token' not in result['content'][0]['text']
    token=result['_meta']['approval_token']
    response=modern(client,headers,'tools/call',{'name':'augurama_submit_generation','arguments':{'contract_id':c['contract_id'],'fingerprint':c['fingerprint'],'approval_token':token,'accept_provider_billing':True,'rights_confirmed':True}}).json()['result']
    assert response['isError'] is False and response['structuredContent']['status']=='queued'
    assert len(engine.test_transport.calls)==1


def test_mcp_widget_resource_is_self_contained(client,engine,uid):
    result=legacy(client,auth_headers(engine,uid),'resources/read',{'uri':UI_URI}).json()['result']['contents'][0]
    assert result['mimeType']=='text/html;profile=mcp-app'
    assert 'ui/initialize' in result['text']
    assert '/*__SCRIPT__*/' not in result['text'] and '/*__STYLES__*/' not in result['text']
    assert result['_meta']['ui']['csp']['connectDomains']==[]


def test_mcp_malformed_and_tool_errors_are_distinct(client,engine,uid):
    headers=auth_headers(engine,uid)
    result=legacy(client,headers,'tools/call',{'name':'augurama_prepare_generation','arguments':{'plan':{'direction':'not a complete plan'}}}).json()['result']
    assert result['isError'] is True
    missing=legacy(client,headers,'tools/call',{'name':'invented'}).json()
    assert missing['error']['code']==-32602
    r=client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','method':'tools/call','params':{'name':'augurama_get_capabilities'}})
    assert r.status_code==400
    r=client.post('/mcp',headers={**headers,'Content-Type':'application/json'},content='{')
    assert r.json()['error']['code']==-32700



def test_http_csrf_and_account_key_handling(client,engine,uid):
    assert client.post('/api/login',json={'username':'x','password':'x'}).status_code==403
    headers=login(client,engine)
    assert client.get('/api/account').json()['provider_key_configured'] is True
    assert client.post('/api/account/provider-key',json={'key':'another-test-key-not-live'},headers={'Origin':engine.settings.base_url}).status_code==403
    r=client.post('/api/account/provider-key',json={'key':'another-test-key-not-live'},headers=headers)
    assert r.status_code==200 and 'another-test-key-not-live' not in r.text
    assert client.post('/api/logout',headers=headers).status_code==200
    assert client.get('/api/account').status_code==401


def test_upload_review_export_and_signed_media(client,engine,uid,plan):
    headers=login(client,engine)
    result=client.post('/api/assets/upload',headers=headers,files={'file':('studio.png',(FIXTURES/'provider-test-frame.png').read_bytes(),'image/png')},data={'rights_confirmed':'true','likeness':'none'})
    assert result.status_code==200
    aid=result.json()['asset']['id']
    assets=client.get('/api/assets').json()['assets']
    url=assets[0]['preview_url'];path=urlsplit(url).path+'?'+urlsplit(url).query
    assert client.get(path).status_code==200
    assert client.get(path.replace('signature=','signature=bad')).status_code==403
    p={**plan.model_dump(),'references':[{'asset_id':aid,'role':'environment','direction':'Lighting'}]}
    r=client.post('/api/contracts',json={'plan':p},headers=headers)
    assert r.status_code==200
    cid=r.json()['contract']['contract_id']
    assert client.delete('/api/assets/'+aid,headers=headers).status_code==409
    exported=client.get('/api/contracts/'+cid+'/export')
    assert exported.status_code==200 and 'approval_token' not in exported.text
    assert client.delete('/api/contracts/'+cid,headers=headers).status_code==200
    assert client.delete('/api/assets/'+aid,headers=headers).status_code==200


def test_security_headers_and_no_wide_cors(client):
    r=client.get('/')
    assert r.status_code==200 and 'frame-ancestors' in r.headers['content-security-policy']
    assert r.headers['referrer-policy']=='no-referrer'
    assert r.headers['x-content-type-options']=='nosniff'
    assert 'access-control-allow-origin' not in r.headers
    assert client.get('/static/../config.py').status_code==404


def test_http_oauth_authorize_and_consent(client,engine,uid):
    headers=login(client,engine)
    c=client.post('/oauth/register',json={'redirect_uris':['https://antigravity.google/oauth-callback'],'client_name':'Antigravity test'})
    assert c.status_code==201
    import hashlib,base64,re
    verifier='a'*50;challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    params={'client_id':c.json()['client_id'],'redirect_uri':'https://antigravity.google/oauth-callback','response_type':'code','code_challenge_method':'S256','code_challenge':challenge,'resource':engine.settings.resource,'state':'keep-me'}
    r=client.get('/oauth/authorize',params=params)
    assert r.status_code==200 and 'Antigravity test' in r.text
    rid=re.search('name="request_id" value="([^"]+)"',r.text).group(1)
    consent=client.post('/oauth/consent',headers={'Origin':engine.settings.base_url},data={'request_id':rid,'csrf':headers['X-CSRF-Token'],'allow':'yes'},follow_redirects=False)
    assert consent.status_code==303
    code=parse_qs(urlsplit(consent.headers['location']).query)['code'][0]
    token=client.post('/oauth/token',data={'grant_type':'authorization_code','client_id':c.json()['client_id'],'redirect_uri':params['redirect_uri'],'resource':engine.settings.resource,'code':code,'code_verifier':verifier})
    assert token.status_code==200 and token.json()['token_type']=='Bearer'


def test_domain_challenge_returns_exact_token_only(engine):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from augurama.app import create_app
    settings=replace(engine.settings,openai_challenge_token='operator-provided-challenge')
    with TestClient(create_app(settings,engine)) as c:
        response=c.get('/.well-known/openai-apps-challenge')
        assert response.text=='operator-provided-challenge'
        assert response.headers['content-type'].startswith('text/plain')


def test_production_requires_approved_policies_and_serves_them(engine,tmp_path):
    from dataclasses import replace
    import pytest
    from fastapi.testclient import TestClient
    from augurama.app import create_app
    settings=replace(engine.settings,environment='production',base_url='https://director.company.example',public_contact='support@company.example',legal_approved=True,widget_origin='https://widget.company.example')
    with pytest.raises(ValueError,match='approved privacy'):create_app(settings,engine)
    policies=tmp_path/'policies';policies.mkdir()
    (policies/'privacy.html').write_text('<p>Operator-approved privacy content.</p>')
    (policies/'terms.html').write_text('<p>Operator-approved terms content.</p>')
    # Do not start the production monitor in this policy-routing test.
    c=TestClient(create_app(settings,engine),base_url=settings.base_url)
    assert 'Operator-approved privacy' in c.get('/privacy').text
    assert 'Operator-approved terms' in c.get('/terms').text

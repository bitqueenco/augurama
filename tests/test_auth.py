from __future__ import annotations
import base64
import hashlib
from urllib.parse import parse_qs,urlsplit
import pytest

from augurama.errors import DirectorError
from augurama.security import random_token
from conftest import oauth_access


def test_password_and_provider_key_are_not_plaintext(engine,uid):
    row=engine.db.one('SELECT * FROM users WHERE id=?',(uid,))
    assert row['password_hash'].startswith('$argon2')
    assert 'test-only-key' not in row['provider_key']
    assert engine.auth.provider_key(uid)=='test-only-key-never-a-live-credential'
    assert 'test-only-key' not in str(engine.db.all('SELECT * FROM audit'))


def test_login_csrf_and_logout(engine,uid):
    token,csrf=engine.auth.login('director-tester','a sufficiently long test password')
    assert engine.auth.session(token,csrf,True).user_id==uid
    with pytest.raises(DirectorError):engine.auth.session(token,'wrong-csrf',True)
    engine.auth.logout(token)
    with pytest.raises(DirectorError):engine.auth.session(token)


def test_invitation_is_one_use(engine):
    invitation=engine.auth.invite('private')
    engine.auth.create_user('first-account','long unique test password',invitation)
    with pytest.raises(DirectorError):engine.auth.create_user('second-account','long unique test password',invitation)


@pytest.mark.parametrize('uri',[
 'https://evil.example/callback','http://evil.example/callback','https://chatgpt.com.evil.example/connector_platform_oauth_redirect',
 'https://chatgpt.com/connector_platform_oauth_redirect#fragment','https://x@chatgpt.com/connector_platform_oauth_redirect',
 'http://169.254.169.254/callback','http://localhost:1234/callback',
 'javascript:alert(1)','https://chatgpt.com/connector_platform_oauth_redirect?next=https://evil.example',
])
def test_untrusted_oauth_redirects_rejected(engine,uri):
    with pytest.raises(DirectorError):engine.auth.register_client({'redirect_uris':[uri],'application_type':'native'})


def test_native_loopback_exact_redirect_supported(engine):
    result=engine.auth.register_client({'redirect_uris':['http://127.0.0.1:41829/callback'],'application_type':'native'})
    assert result['redirect_uris']==['http://127.0.0.1:41829/callback']
    with pytest.raises(DirectorError):engine.auth.register_client({'redirect_uris':['http://127.0.0.1:41829/callback'],'application_type':'web'})


def test_oauth_full_code_flow_scope_and_audience(engine,uid):
    tokens,_=oauth_access(engine,uid,'director:read')
    who=engine.auth.bearer(tokens['access_token'])
    assert who.user_id==uid
    with pytest.raises(DirectorError):who.require('director:write')
    assert 'test-only-key' not in tokens['access_token']


def test_authorization_code_is_consumed(engine,uid):
    tokens,params=oauth_access(engine,uid)
    with pytest.raises(DirectorError,match='invalid or expired'):engine.auth.token(params)


def test_pkce_verifier_and_resource_are_enforced(engine,uid):
    a=engine.auth;c=a.register_client({'redirect_uris':['https://antigravity.google/oauth-callback']})
    verifier=random_token()+'suffix';challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    p={'client_id':c['client_id'],'redirect_uri':c['redirect_uris'][0],'response_type':'code','resource':engine.settings.resource,'code_challenge_method':'S256','code_challenge':challenge,'state':'a-state'}
    rid,_=a.authorization_request(p);redirect=a.consent(uid,rid,True);query=parse_qs(urlsplit(redirect).query)
    assert query['iss']==[engine.settings.base_url] and query['state']==['a-state']
    code=query['code'][0];request={'grant_type':'authorization_code','client_id':c['client_id'],'redirect_uri':p['redirect_uri'],'resource':p['resource'],'code':code,'code_verifier':'wrong'*10}
    with pytest.raises(DirectorError):a.token(request)
    with pytest.raises(DirectorError):a.token({**request,'code_verifier':verifier,'resource':'https://other.example/mcp'})
    assert a.token({**request,'code_verifier':verifier})['access_token']


def test_refresh_rotation_replay_revokes_entire_family(engine,uid):
    tokens,params=oauth_access(engine,uid)
    request={'grant_type':'refresh_token','refresh_token':tokens['refresh_token'],'client_id':params['client_id'],'resource':engine.settings.resource}
    refreshed=engine.auth.token(request)
    assert engine.auth.bearer(refreshed['access_token']).user_id==uid
    with pytest.raises(DirectorError,match='reuse'):engine.auth.token(request)
    with pytest.raises(DirectorError):engine.auth.bearer(tokens['access_token'])
    with pytest.raises(DirectorError):engine.auth.bearer(refreshed['access_token'])


def test_revocation_invalidates_access(engine,uid):
    tokens,params=oauth_access(engine,uid)
    engine.auth.revoke(tokens['refresh_token'],params['client_id'])
    with pytest.raises(DirectorError):engine.auth.bearer(tokens['access_token'])


def test_password_reset_revokes_web_and_oauth(engine,uid):
    tokens,_=oauth_access(engine,uid)
    session,csrf=engine.auth.login('director-tester','a sufficiently long test password')
    engine.auth.reset_password('director-tester','another sufficiently long password')
    with pytest.raises(DirectorError):engine.auth.bearer(tokens['access_token'])
    with pytest.raises(DirectorError):engine.auth.session(session,csrf,True)


def test_read_token_cannot_expand_scope_with_refresh(engine,uid):
    tokens,params=oauth_access(engine,uid,'director:read')
    with pytest.raises(DirectorError):engine.auth.token({'grant_type':'refresh_token','refresh_token':tokens['refresh_token'],'client_id':params['client_id'],'resource':engine.settings.resource,'scope':'director:read director:write'})

from __future__ import annotations
import base64
from pathlib import Path
import hashlib
import json
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from augurama.app import create_app
from augurama.config import Settings
from augurama.models import GenerationPlan, SubmitInput
from augurama.provider import BytePlus
from augurama.service import Director
from augurama.security import random_token

FIXTURES=Path(__file__).parent/'fixtures'

class FixtureTransport:
    """Local simulation of documented wire responses; never included in plugin distributions."""
    def __init__(self):
        self.calls=[]; self.tasks={}; self.error=None; self.poll_status='succeeded'; self.lock=threading.Lock(); self.delay=0
    def __call__(self,request):
        with self.lock:
            self.calls.append((request.method,request.url.path,dict(request.headers),json.loads(request.content) if request.content else None))
        if self.delay and request.method=='POST':time.sleep(self.delay)
        if self.error:
            if isinstance(self.error,Exception):raise self.error
            return httpx.Response(self.error,json={'error':{'message':'Sensitive provider details must NOT be forwarded SECRET'}})
        if request.method=='POST':
            task='cgt-test-'+str(len(self.tasks)+1)
            self.tasks[task]={'id':task,'model':json.loads(request.content)['model']}
            return httpx.Response(200,json={'id':task})
        task=request.url.path.rsplit('/',1)[-1]
        if task not in self.tasks:return httpx.Response(404,json={'error':{}})
        if request.method=='DELETE':self.tasks[task]['cancelled']=True;return httpx.Response(200,json={})
        status='cancelled' if self.tasks[task].get('cancelled') else self.poll_status
        result={**self.tasks[task],'status':status}
        if status=='succeeded':result.update(content={'video_url':'https://media.provider-test.example/video.mp4','last_frame_url':'https://media.provider-test.example/frame.png'},usage={'completion_tokens':86400})
        return httpx.Response(200,json=result)

class FixtureFetcher:
    def __init__(self):self.calls=[];self.error=None
    def download(self,url,limit):
        self.calls.append(url)
        if self.error:raise self.error
        path=FIXTURES/('provider-test-frame.png' if url.endswith('png') else 'provider-test-video.mp4')
        data=path.read_bytes()
        assert len(data)<=limit
        return data,'image/png' if url.endswith('png') else 'video/mp4'

@pytest.fixture
def engine(tmp_path):
    transport=FixtureTransport();fetcher=FixtureFetcher()
    settings=Settings(data_dir=tmp_path,environment='test',encryption_key=b'x'*32)
    service=Director(settings,provider=BytePlus(settings.provider_base_url,httpx.MockTransport(transport)),fetcher=fetcher)
    service.test_transport=transport;service.test_fetcher=fetcher
    yield service
    service.provider.close()

@pytest.fixture
def uid(engine):
    user=engine.auth.create_user('director-tester','a sufficiently long test password',engine.auth.invite('test'))
    engine.auth.save_provider_key(user,'test-only-key-never-a-live-credential')
    return user

@pytest.fixture
def other_uid(engine):
    return engine.auth.create_user('other-tester','a sufficiently long test password',engine.auth.invite('test'))

@pytest.fixture
def plan():
    return GenerationPlan(title='One small adventure',original_request='A synthetic corgi discovers a paper moon.',direction='A synthetic corgi discovers a paper moon in a miniature studio. Slow camera push-in; the moon gently rotates. End on a still, curious gaze.',duration_seconds=4,recipe='continuous')

@pytest.fixture
def approval(engine,uid,plan):
    public,private=engine.prepare(uid,plan)
    return SubmitInput(contract_id=public['contract_id'],fingerprint=public['fingerprint'],approval_token=private['approval_token'],rights_confirmed=True,accept_provider_billing=True)

@pytest.fixture
def client(engine):
    with TestClient(create_app(engine.settings,engine)) as client:
        yield client

def oauth_access(engine,uid,scope='director:read director:write'):
    auth=engine.auth
    client=auth.register_client({'redirect_uris':['https://chatgpt.com/connector_platform_oauth_redirect'],'client_name':'Test host','token_endpoint_auth_method':'none'})
    verifier=random_token()+'test'
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    params={'client_id':client['client_id'],'redirect_uri':client['redirect_uris'][0],'response_type':'code','code_challenge_method':'S256','code_challenge':challenge,'resource':engine.settings.resource,'scope':scope,'state':'test-state'}
    rid,_=auth.authorization_request(params)
    from urllib.parse import parse_qs,urlsplit
    code=parse_qs(urlsplit(auth.consent(uid,rid,True)).query)['code'][0]
    token_params={'grant_type':'authorization_code','client_id':client['client_id'],'redirect_uri':params['redirect_uri'],'code_verifier':verifier,'code':code,'resource':engine.settings.resource}
    return auth.token(token_params),token_params

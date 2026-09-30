"""Actual loopback TCP + installed CLI startup, without a provider credential."""
from __future__ import annotations
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import httpx


def test_installed_cli_serves_real_http_and_prepares_without_provider(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    env={**os.environ,'DD_DATA_DIR':str(tmp_path),'DD_ENV':'development','DD_BASE_URL':base}
    env.pop('DD_ENCRYPTION_KEY',None)
    invitation=subprocess.run([sys.executable,'-m','augurama.cli','invite','--label','TCP test'],env=env,capture_output=True,text=True,check=True).stdout.strip()
    proc=subprocess.Popen([sys.executable,'-m','augurama.cli','serve','--port',str(port)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        with httpx.Client(base_url=base,headers={'Origin':base},trust_env=False,timeout=2) as c:
            for _ in range(100):
                try:
                    if c.get('/healthz').status_code==200:break
                except httpx.ConnectError:pass
                time.sleep(.05)
            else:raise AssertionError('CLI server failed to start')
            assert c.get('/healthz').json()['provider_status']=='not_checked'
            assert 'The story stays' in c.get('/').text
            assert c.post('/api/signup',json={'username':'tcp-tester','password':'long test password for real TCP','invitation':invitation}).status_code==200
            login=c.post('/api/login',json={'username':'tcp-tester','password':'long test password for real TCP'});assert login.status_code==200
            assert 'HttpOnly' in login.headers['set-cookie']
            c.headers['X-CSRF-Token']=login.json()['csrf_token']
            account=c.get('/api/account').json();assert account['provider_key_configured'] is False
            r=c.post('/api/contracts',json={'plan':{'title':'No charges','original_request':'A paper moon turns slowly.','direction':'A paper moon turns slowly in a miniature studio.','duration_seconds':4}})
            assert r.status_code==200
            result=r.json();f=result['contract'];private=result['private']
            blocked=c.post('/api/generations',json={'contract_id':f['contract_id'],'fingerprint':f['fingerprint'],'approval_token':private['approval_token'],'rights_confirmed':True,'accept_provider_billing':True})
            assert blocked.status_code==409
            assert c.get('/api/generations').json()['generations']==[]
            assert c.get('/.well-known/oauth-authorization-server').json()['issuer']==base
    finally:
        proc.terminate()
        try:proc.wait(timeout=10)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()

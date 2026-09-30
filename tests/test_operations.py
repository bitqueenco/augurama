from __future__ import annotations
import base64
import json
from pathlib import Path
import time
from dataclasses import replace

import pytest

from augurama.cli import main
from augurama.config import Settings
from augurama.errors import DirectorError
from augurama.operations import backup, restore, maintain, delete_account, service_lock, doctor
from augurama.service import Director
from conftest import FIXTURES


def test_duplicate_after_credential_removal_is_still_idempotent(engine,uid,approval):
    first=engine.submit(uid,approval)
    engine.auth.save_provider_key(uid,None)
    assert engine.submit(uid,approval)['generation_id']==first['generation_id']
    assert len(engine.test_transport.calls)==1


def test_default_profile_is_deterministic(engine):
    assert engine.registry.public()['models'][0]['profile']=='seedance-2.0'


def test_restart_retains_accounts_contracts_and_never_posts_again(engine,uid,approval):
    job=engine.submit(uid,approval)
    restarted=Director(engine.settings,provider=engine.provider,fetcher=engine.test_fetcher)
    assert restarted.auth.provider_key(uid).startswith('test-only-key-')
    assert restarted.submit(uid,approval)['generation_id']==job['generation_id']
    assert len(engine.test_transport.calls)==1


def test_backup_restore_retains_media_credentials_approval_and_jobs(engine,uid,approval,tmp_path):
    asset=engine.assets.ingest(uid,(FIXTURES/'provider-test-frame.png').read_bytes(),'moon.png','synthetic')
    job=engine.submit(uid,approval)
    dest=tmp_path.parent/(tmp_path.name+'-backup')
    assert backup(engine,dest)['files']==2  # database + media; key supplied externally in this test
    target=tmp_path.parent/(tmp_path.name+'-restored')
    key=base64.urlsafe_b64encode(engine.settings.encryption_key).decode()
    assert restore(dest,target,key)['files']==2
    recovered=Director(replace(engine.settings,data_dir=target),provider=engine.provider,fetcher=engine.test_fetcher)
    assert recovered.auth.provider_key(uid)==engine.auth.provider_key(uid)
    assert recovered.assets.path(recovered.assets.get(uid,asset['id'])).read_bytes()==(FIXTURES/'provider-test-frame.png').read_bytes()
    assert recovered.submit(uid,approval)['generation_id']==job['generation_id']
    assert len(engine.test_transport.calls)==1
    with pytest.raises(DirectorError,match='new directory'):restore(dest,target,key)


def test_backup_requires_stopped_service_and_never_overwrites(engine,tmp_path):
    target=tmp_path.parent/(tmp_path.name+'-blocked')
    with service_lock(engine.settings.data_dir):
        with pytest.raises(DirectorError,match='Stop'):backup(engine,target)
    assert not target.exists()
    target.mkdir()
    with pytest.raises(DirectorError,match='new backup'):backup(engine,target)


def test_restore_rejects_tamper_and_wrong_key(engine,tmp_path):
    source=tmp_path.parent/(tmp_path.name+'-backup');backup(engine,source)
    target=tmp_path.parent/(tmp_path.name+'-restore')
    with pytest.raises(DirectorError,match='original'):restore(source,target,base64.urlsafe_b64encode(b'z'*32).decode())
    (source/'director.sqlite3').write_bytes(b'tampered')
    with pytest.raises(DirectorError,match='changed'):restore(source,target,base64.urlsafe_b64encode(engine.settings.encryption_key).decode())
    assert not target.exists()


def test_restore_rejects_manifest_path_traversal(engine,tmp_path):
    source=tmp_path.parent/(tmp_path.name+'-backup');backup(engine,source)
    manifest=json.loads((source/'backup.json').read_text());manifest['files']['../outside']='bad';(source/'backup.json').write_text(json.dumps(manifest))
    with pytest.raises(DirectorError,match='invalid path'):restore(source,tmp_path.parent/(tmp_path.name+'-restore'))


def test_retention_removes_old_completed_records_but_pins_unknown_jobs(engine,uid,plan):
    asset=engine.assets.ingest(uid,(FIXTURES/'provider-test-frame.png').read_bytes(),'moon.png','synthetic')
    from augurama.models import GenerationPlan,SubmitInput
    p=GenerationPlan(**{**plan.model_dump(),'references':[{'asset_id':asset['id'],'role':'environment'}]})
    public,private=engine.prepare(uid,p)
    a=SubmitInput(contract_id=public['contract_id'],fingerprint=public['fingerprint'],approval_token=private['approval_token'],rights_confirmed=True,accept_provider_billing=True)
    engine.test_transport.error=503
    job=engine.submit(uid,a)
    old=time.time()-40*86400
    engine.db.execute('UPDATE assets SET created_at=?',(old,));engine.db.execute('UPDATE contracts SET created_at=?,expires_at=0',(old,));engine.db.execute('UPDATE jobs SET created_at=?',(old,))
    result=maintain(engine)
    assert result['assets']==0 and result['jobs']==0
    assert engine.assets.path(engine.assets.get(uid,asset['id'])).is_file()
    # Explicit operator disposition, not automatic retry or implicit refund.
    engine.db.execute("UPDATE jobs SET status='failed' WHERE id=?",(job['generation_id'],))
    result=maintain(engine)
    assert result['assets']==1 and result['jobs']==1 and result['contracts']==1


def test_delete_account_preserves_other_tenant_and_blocks_active(engine,uid,other_uid,approval):
    engine.submit(uid,approval)
    with pytest.raises(DirectorError,match='Resolve'):delete_account(engine,uid)
    engine.db.execute("UPDATE jobs SET status='failed' WHERE user_id=?",(uid,))
    assert delete_account(engine,uid)['deleted']
    assert engine.db.one('SELECT 1 FROM users WHERE id=?',(uid,)) is None
    assert engine.db.one('SELECT 1 FROM users WHERE id=?',(other_uid,)) is not None


def test_doctor_is_read_only_and_production_gate_fails(engine):
    assert doctor(engine)['local_configuration_ok']
    assert not doctor(engine,True)['local_configuration_ok']
    assert engine.test_transport.calls==[]


def test_operator_cli_invite_keygen_doctor_and_protected_delete(tmp_path,monkeypatch,capsys):
    monkeypatch.setenv('DD_DATA_DIR',str(tmp_path));monkeypatch.setenv('DD_ENV','development')
    monkeypatch.delenv('DD_ENCRYPTION_KEY',raising=False)
    assert main(['keygen'])==0
    key=capsys.readouterr().out.strip();assert len(base64.urlsafe_b64decode(key+'='))==32
    assert main(['invite','--label','Owner'])==0
    invite=capsys.readouterr().out.strip();assert len(invite)>=40
    assert main(['doctor'])==0
    assert json.loads(capsys.readouterr().out)['provider_api_called'] is False
    assert main(['doctor','--production'])==2
    capsys.readouterr()
    assert main(['serve','--host','0.0.0.0'])==2
    assert 'PUBLIC_DEVELOPMENT_BLOCKED' in capsys.readouterr().err


@pytest.mark.parametrize('bad',[None,3,{},[['authorization_code']],['refresh_token'],'authorization_code'])
def test_malformed_oauth_grants_fail_cleanly(engine,bad):
    with pytest.raises(DirectorError):engine.auth.register_client({'redirect_uris':['https://antigravity.google/oauth-callback'],'grant_types':bad})


def test_failed_file_cleanup_never_restores_deleted_account_or_metadata(engine,uid,monkeypatch):
    import os
    asset=engine.assets.ingest(uid,(FIXTURES/'provider-test-frame.png').read_bytes(),'moon.png','synthetic')
    path=engine.assets.path(asset)
    original=Path.unlink
    def denied(self,*a,**kw):
        if self==path:raise PermissionError('injected cleanup fault')
        return original(self,*a,**kw)
    monkeypatch.setattr(Path,'unlink',denied)
    result=delete_account(engine,uid)
    assert result['deleted'] and result['media_cleanup_pending']==1
    assert engine.db.one('SELECT 1 FROM users WHERE id=?',(uid,)) is None
    assert engine.db.one('SELECT 1 FROM assets WHERE id=?',(asset['id'],)) is None
    assert path.exists()
    monkeypatch.setattr(Path,'unlink',original)
    old=time.time()-7200;os.utime(path,(old,old))
    assert maintain(engine)['media_cleanup_pending']==0
    assert not path.exists()

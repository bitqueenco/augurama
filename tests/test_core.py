from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import io
import json
import time

import httpx
from PIL import Image
import pytest
from pydantic import ValidationError

from augurama.compiler import Registry
from augurama.db import dumps
from augurama.errors import DirectorError
from augurama.models import GenerationPlan,Reference,Shot,SubmitInput


def test_prepare_is_free_and_approval_is_private(engine,uid,plan):
    public,private=engine.prepare(uid,plan)
    assert not engine.test_transport.calls
    assert 'approval_token' not in dumps(public)
    assert len(private['approval_token'])>=32
    assert public['plan']['original_request']==plan.original_request
    assert public['plan']['direction']==plan.direction
    assert plan.direction in public['compiled_prompt']
    assert public['estimate']['approximate_usd']==pytest.approx(.6048)
    assert public['estimate']['not_a_quote_or_billing_cap'] is True


def test_duplicate_submit_is_one_paid_post(engine,uid,approval):
    a=engine.submit(uid,approval);b=engine.submit(uid,approval)
    assert a['generation_id']==b['generation_id']
    assert len([r for r in engine.test_transport.calls if r[0]=='POST'])==1
    body=engine.test_transport.calls[0][3]
    assert body['model']=='dreamina-seedance-2-0-260128'
    assert body['duration']==4 and body['generate_audio'] is True and body['return_last_frame'] is True
    assert body['ratio']=='9:16' and body['resolution']=='720p'
    assert body['content'][0]['type']=='text'
    assert 'approval_token' not in dumps(body)


def test_concurrent_submit_is_one_paid_post(engine,uid,approval):
    engine.test_transport.delay=.2
    with ThreadPoolExecutor(max_workers=8) as executor:
        jobs=list(executor.map(lambda _:engine.submit(uid,approval),range(8)))
    assert len({j['generation_id'] for j in jobs})==1
    assert len([r for r in engine.test_transport.calls if r[0]=='POST'])==1


def test_full_lifecycle_archives_real_playable_fixture(engine,uid,approval):
    job=engine.submit(uid,approval)
    result=engine.get(uid,job['generation_id'])
    assert result['status']=='succeeded'
    assert result['result']['archived'] is True
    assert result['result']['video_url'].startswith(engine.settings.base_url+'/media/')
    assert result['result']['last_frame_asset_id']
    assert result['result']['usage']['completion_tokens']==86400
    assert result['result']['list_rate_usage_usd']==pytest.approx(.6048)
    assert 'media.provider-test.example' not in dumps(result)
    assert len(engine.assets.list(uid))==2
    engine.get(uid,job['generation_id'])
    assert len(engine.assets.list(uid))==2


@pytest.mark.parametrize('status',[400,401,403,404,429])
def test_provider_rejections_are_recorded_no_retry(engine,uid,approval,status):
    engine.test_transport.error=status
    first=engine.submit(uid,approval);second=engine.submit(uid,approval)
    assert first['status']=='failed'
    assert second['generation_id']==first['generation_id']
    assert 'SECRET' not in dumps(first)
    assert len(engine.test_transport.calls)==1


@pytest.mark.parametrize('error',[500,503,408,409,httpx.ReadTimeout('provider request timed out')])
def test_uncertain_submission_never_retried(engine,uid,approval,error):
    engine.test_transport.error=error
    job=engine.submit(uid,approval)
    assert job['status']=='submission_unknown'
    assert engine.submit(uid,approval)['generation_id']==job['generation_id']
    assert engine.get(uid,job['generation_id'])['status']=='submission_unknown'
    assert len(engine.test_transport.calls)==1


def test_approval_fingerprint_and_nonce_required(engine,uid,approval):
    for change in ({'approval_token':'z'*43},{'fingerprint':'0'*64}):
        with pytest.raises(DirectorError,match='Approval does not match'):
            engine.submit(uid,approval.model_copy(update=change))
    assert not engine.test_transport.calls


def test_expired_and_invalidated_contracts_cannot_spend(engine,uid,approval):
    engine.invalidate(uid,approval.contract_id)
    with pytest.raises(DirectorError,match='expired'):
        engine.submit(uid,approval)
    assert not engine.test_transport.calls


def test_database_tampering_fails_closed(engine,uid,approval):
    row=engine.db.one('SELECT snapshot FROM contracts WHERE id=?',(approval.contract_id,))
    snapshot=json.loads(row['snapshot']);snapshot['plan']['duration_seconds']=30
    engine.db.execute('UPDATE contracts SET snapshot=? WHERE id=?',(dumps(snapshot),approval.contract_id))
    with pytest.raises(DirectorError,match='integrity'):
        engine.submit(uid,approval)
    assert not engine.test_transport.calls


def test_cross_tenant_access_denied(engine,uid,other_uid,approval):
    with pytest.raises(DirectorError,match='not found'):engine.review(other_uid,approval.contract_id)
    with pytest.raises(DirectorError,match='not found'):engine.submit(other_uid,approval)
    job=engine.submit(uid,approval)
    with pytest.raises(DirectorError,match='not found'):engine.get(other_uid,job['generation_id'])
    assert engine.list(other_uid)==[]


def test_model_and_recipe_are_frozen(engine,uid,approval):
    engine.registry.models['seedance-2.0']['model_id']='dreamina-seedance-upgraded-not-approved'
    engine.registry.recipes['continuous']['principles']=['A wholly different direction']
    job=engine.submit(uid,approval)
    body=engine.test_transport.calls[0][3]
    assert body['model']=='dreamina-seedance-2-0-260128'
    assert 'A wholly different direction' not in body['content'][0]['text']


def test_cancel_requires_ack_and_checks_provider_state(engine,uid,approval):
    job=engine.submit(uid,approval)
    with pytest.raises(DirectorError):engine.cancel(uid,job['generation_id'],False)
    with pytest.raises(DirectorError,match='Only queued'):engine.cancel(uid,job['generation_id'],True)
    engine.test_transport.poll_status='queued'
    cancelled=engine.cancel(uid,job['generation_id'],True)
    assert cancelled['status']=='cancelled'
    assert len([r for r in engine.test_transport.calls if r[0]=='DELETE'])==1


def test_reference_bindings_are_per_media_kind(engine,uid,plan):
    image=Image.new('RGB',(512,512),(20,40,60));buf=io.BytesIO();image.save(buf,format='PNG')
    a=engine.assets.ingest(uid,buf.getvalue(),'studio.png','none')
    from conftest import FIXTURES
    b=engine.assets.ingest(uid,(FIXTURES/'provider-test-video.mp4').read_bytes(),'motion.mp4','none')
    p=plan.model_copy(update={'references':[Reference(asset_id=b['id'],role='motion'),Reference(asset_id=a['id'],role='environment')]})
    public,_=engine.prepare(uid,p)
    assert [r['token'] for r in public['reference_map']]==['[Video 1]','[Image 1]']
    assert public['estimate']['input_video_seconds']==4
    assert public['estimate']['usd_per_million_tokens']==4.3


def test_real_face_declarations_require_provider_authorization(engine,uid,plan):
    buf=io.BytesIO();Image.new('RGB',(512,512)).save(buf,format='PNG')
    a=engine.assets.ingest(uid,buf.getvalue(),'a-person.png','real_person')
    with pytest.raises(DirectorError,match='real-person'):
        engine.prepare(uid,plan.model_copy(update={'references':[Reference(asset_id=a['id'],role='identity')]}))
    assert not engine.test_transport.calls


def test_authorized_provider_image_asset_preserves_uri(engine,uid,plan):
    a=engine.assets.register_provider_asset(uid,'asset://provider-approved-character-1','Authorized person','image')
    public,private=engine.prepare(uid,plan.model_copy(update={'references':[Reference(asset_id=a['id'],role='identity')]}))
    engine.submit(uid,SubmitInput(contract_id=public['contract_id'],fingerprint=public['fingerprint'],approval_token=private['approval_token'],rights_confirmed=True,accept_provider_billing=True))
    ref=engine.test_transport.calls[0][3]['content'][1]
    assert ref=={'type':'image_url','image_url':{'url':a['provider_uri']},'role':'reference_image'}


def test_model_review_expiration_blocks_new_work(plan):
    with pytest.raises(DirectorError,match='current provider review'):Registry().compile(plan,[],date(2027,1,1))


@pytest.mark.parametrize('changes',[
 {'duration_seconds':16}, {'resolution':'4k'}, {'model_profile':'seedance-does-not-exist'},
 {'audio':{'enabled':False,'dialogue':[],'ambience':'','music':''},'shots':[{'start':0,'end':4,'action':'Camera moves','sound':'Footsteps'}]},
])
def test_unsupported_contracts_are_not_silently_fixed(engine,uid,plan,changes):
    p=GenerationPlan.model_validate({**plan.model_dump(),**changes})
    with pytest.raises(DirectorError):engine.prepare(uid,p)
    assert not engine.test_transport.calls


@pytest.mark.parametrize('shots',[[{'start':1,'end':4,'action':'A slow move'}],[{'start':0,'end':2,'action':'A slow move'},{'start':1,'end':4,'action':'Then a cut'}],[{'start':0,'end':3,'action':'A slow move'}]])
def test_timeline_must_cover_exact_duration(plan,shots):
    with pytest.raises(ValidationError):GenerationPlan.model_validate({**plan.model_dump(),'recipe':'narrative','shots':shots})


def test_seed_and_legacy_flags_rejected(plan):
    with pytest.raises(ValidationError):GenerationPlan.model_validate({**plan.model_dump(),'direction':'Please generate --duration 99'})
    with pytest.raises(ValidationError):GenerationPlan.model_validate({**plan.model_dump(),'seed':-5})

#!/usr/bin/env python3
"""Operator-run live smoke check. Default is preparation only, with no paid render.

--render requires an interactive, exact-contract confirmation. No POST is retried.
Secrets, cookies, approval tokens and signed media URLs never enter the report.
"""
from __future__ import annotations
import argparse
import getpass
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

import httpx
from package_releases import source_digest, origin


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--origin',required=True);p.add_argument('--username',required=True);p.add_argument('--render',action='store_true');p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    base=origin(args.origin,True)
    if args.out.exists():p.error('Use a new report path; existing evidence is never overwritten.')
    report={'source_digest':source_digest(),'origin':base,'observed_at':time.time(),'transport':'actual HTTPS service','provider_render_requested':args.render,'byteplus_live_render_passed':False,'semantic_quality_review':'not_run','native_host_validation':'not_run'}
    client=httpx.Client(base_url=base,timeout=60,follow_redirects=False,trust_env=False,headers={'Origin':base})
    def call(method,path,**kwargs):
        response=client.request(method,path,**kwargs)
        if response.status_code>=400:
            raise RuntimeError(f'Service returned HTTP {response.status_code} for {path.split("?")[0]}. No automatic retry was attempted.')
        return response.json()
    try:
        health=call('GET','/healthz');report['service_version']=health['version']
        password=getpass.getpass('Director account password (not your API key): ')
        login=call('POST','/api/login',json={'username':args.username,'password':password});password=''
        client.headers['X-CSRF-Token']=login['csrf_token']
        plan={'title':'Live acceptance · paper moon','original_request':'An entirely synthetic corgi discovers a paper moon in a miniature studio. Four seconds, vertical, no dialogue.','direction':'An entirely synthetic corgi discovers a paper moon in a miniature studio. One slow, unbroken push-in. The moon rotates gently. End on a curious still gaze. No lettering or logos.','model_profile':'seedance-2.0','recipe':'continuous','operation':'generate','duration_seconds':4,'aspect_ratio':'9:16','resolution':'720p','audio':{'enabled':True,'dialogue':[],'ambience':'A soft paper creak.','music':'No music.'},'references':[],'shots':[],'preserve':['One synthetic corgi; one paper moon; one continuous shot.'],'avoid':['Extra animals','Text','Speech'],'watermark':True}
        prepared=call('POST','/api/contracts',json={'plan':plan})
        contract,private=prepared['contract'],prepared['private']
        report.update(contract_id=contract['contract_id'],fingerprint=contract['fingerprint'],estimate=contract['estimate'],preparation_passed=True)
        print(json.dumps(contract,indent=2))
        if not args.render:
            print('Preparation verified. No generation was requested. Use --render only when you authorize a real provider charge.')
            return 0
        if not sys.stdin.isatty():raise RuntimeError('Live rendering requires a person at an interactive terminal.')
        phrase='GENERATE '+contract['fingerprint']
        print('\nThis uses your BytePlus API account and may incur charges even if the result is unsatisfactory. The estimate is not a billing cap.\nConfirm you have rights to the selected synthetic scene and approve precisely this one contract.\nType: '+phrase)
        if input('Approval: ').strip()!=phrase:raise RuntimeError('Approval was not granted; no generation was submitted.')
        job=call('POST','/api/generations',json={'contract_id':contract['contract_id'],'fingerprint':contract['fingerprint'],'approval_token':private['approval_token'],'rights_confirmed':True,'accept_provider_billing':True})
        private.clear()
        report.update(generation_id=job['generation_id'],provider_task_id=job['provider_task_id'],status=job['status'])
        deadline=time.monotonic()+900
        while job['status'] in ('queued','running','submitting') and time.monotonic()<deadline:
            time.sleep(5)
            job=call('GET','/api/generations/'+job['generation_id'])
        # One extra read can finish archival without issuing another paid request.
        if job['status']=='succeeded' and not job['result'].get('video_url'):
            job=call('GET','/api/generations/'+job['generation_id'])
        report.update(status=job['status'],provider_task_id=job['provider_task_id'])
        url=job['result'].get('video_url')
        if job['status']!='succeeded' or not url:raise RuntimeError('Live output not confirmed and archived. Preserve the generation ID; do not resubmit automatically.')
        if urlsplit(url).netloc!=urlsplit(base).netloc or urlsplit(url).scheme!='https':raise RuntimeError('Unexpected media origin.')
        with tempfile.NamedTemporaryFile(suffix='.mp4') as f:
            sha=hashlib.sha256();size=0
            with client.stream('GET',url) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    size+=len(chunk)
                    if size>200*1024*1024:raise RuntimeError('Output exceeded the verification size limit.')
                    sha.update(chunk);f.write(chunk)
            f.flush()
            probe=subprocess.run(['ffprobe','-v','error','-protocol_whitelist','file','-show_entries','format=duration:stream=codec_type,width,height,r_frame_rate','-of','json',f.name],capture_output=True,timeout=15,check=True)
            metadata=json.loads(probe.stdout)
            video=next(s for s in metadata['streams'] if s.get('codec_type')=='video')
            duration=float(metadata['format']['duration'])
            if not 3.8<=duration<=4.2 or abs(video['width']/video['height']-9/16)>.02:raise RuntimeError('Actual video duration or aspect ratio did not match the frozen contract.')
            report.update(byteplus_live_render_passed=True,media_sha256=sha.hexdigest(),media_bytes=size,video=video,duration_seconds=duration,usage=job['result'].get('usage'))
        print('Actual provider task, archival, duration and aspect ratio verified. Human visual/semantic review and native-host tests are still required.')
        return 0
    except Exception as exc:
        # HTTP exception strings can contain signed URLs; do not print them.
        report['failure']=str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__
        print('CHECK_INCOMPLETE: '+report['failure'],file=sys.stderr)
        return 2
    finally:
        client.close();args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':raise SystemExit(main())

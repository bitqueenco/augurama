#!/usr/bin/env python3
"""Create thin, host-native archives. Private source and secrets are never allowlisted.

Local defaults are genuine local connections, not fictional production URLs.
--origin produces hosted staging packages. --public additionally requires owner
acceptance evidence tied to the exact current source digest.
"""
from __future__ import annotations
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlsplit
import zipfile

ROOT=Path(__file__).resolve().parents[1]
VERSION='1.0.0'
PUBLIC_GATES=('publishing_identity_verified','brand_and_provider_terms_reviewed','domain_and_https_verified','privacy_and_terms_approved','byteplus_live_render_passed','chatgpt_native_passed','codex_native_passed','antigravity_native_passed','reviewer_account_ready','walkthrough_recorded','security_review_completed')


def source_digest(root: Path=ROOT) -> str:
    h=hashlib.sha256()
    paths=list((root/'src').rglob('*'))+list((root/'releases').rglob('*'))
    paths += [root/'pyproject.toml', root/'requirements.lock']
    paths += list((root/'scripts').glob('*.py'))
    for p in sorted(paths):
        if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':
            h.update(p.relative_to(root).as_posix().encode()+b'\0'+p.read_bytes()+b'\0')
    return h.hexdigest()


def origin(value: str, public: bool) -> str:
    value=value.rstrip('/')
    u=urlsplit(value)
    if u.scheme not in ('http','https') or not u.hostname or u.path or u.query or u.fragment or u.username or u.password:
        raise ValueError('Use a clean HTTP(S) origin without a path, query or credentials.')
    if public:
        if u.scheme!='https' or u.port not in (None,443) or u.hostname in ('localhost','example.com','example.org','example.net') or u.hostname.endswith(('.localhost','.local','.example','.invalid','.test')):
            raise ValueError('Hosted packages require an actual owned public HTTPS origin, not a local/example/test domain.')
        try:ipaddress.ip_address(u.hostname)
        except ValueError:pass
        else:raise ValueError('Use an owned DNS hostname for production and OAuth, not an IP literal.')
    return value


def validate_package(directory: Path, host: str) -> dict:
    manifest=json.loads((directory/'plugin.json').read_text())
    assert manifest['name'] in ('augurama', 'dreamina-director')
    if host=='openai':
        assert manifest['$schema']=='https://agent-plugins.org/schemas/1.0.0/plugin.schema.json'
        assert manifest['version']==VERSION
        interface=manifest['extensions']['com.openai']['interface']
        assert interface['developerName']=='Corgi-Verse Software'
        for field in ('composerIcon','logo'):
            assert interface[field].startswith('./assets/') and (directory/interface[field][2:]).is_file()
        config=json.loads((directory/'mcp.json').read_text())
        assert config['$schema']=='https://agent-plugins.org/schemas/1.0.0/mcp.schema.json'
        server_key = 'augurama' if 'augurama' in config['mcpServers'] else 'dreamina-director'
        server=config['mcpServers'][server_key]
        assert set(server)=={'type','url'} and server['type']=='streamable-http'
        endpoint=server['url']
    else:
        # Google's inline manifest schema has $schema in its example but not
        # among its allowed data properties. Validate data fields separately.
        assert {'$schema','name','description'}.issubset(set(manifest))
        assert manifest['$schema']=='https://antigravity.google/schemas/v1/plugin.json'
        config=json.loads((directory/'mcp_config.json').read_text())
        server_key = 'augurama' if 'augurama' in config['mcpServers'] else 'dreamina-director'
        server=config['mcpServers'][server_key]
        assert set(server)=={'serverUrl'}
        endpoint=server['serverUrl']
    assert endpoint.endswith('/mcp')
    origin(endpoint[:-4],False)
    for skill in ('direct-video','product-trailer'):
        text=(directory/'skills'/skill/'SKILL.md').read_text()
        assert text.startswith('---\nname: '+skill+'\n') and 'description:' in text
    assert (directory/'LICENSE.txt').is_file()
    forbidden={'src','data','recipes','tests','.git','.director','.augurama','node_modules','__pycache__'}
    for p in directory.rglob('*'):
        assert not p.is_symlink(), 'Symlinks may not enter release packages.'
        assert not set(p.relative_to(directory).parts)&forbidden
        assert p.name not in ('.env','encryption.key') and p.suffix not in ('.py','.sqlite3','.db','.pem','.key','.pyc')
    return {'host':host,'endpoint':endpoint,'local_shape_check':'passed','vendor_native_validation':'not_run'}


def build(output: Path, base: str, *, public=False, evidence: Path|None=None) -> dict:
    hosted=base!='http://127.0.0.1:8765'
    base=origin(base,hosted or public)
    digest=source_digest()
    proofs={}
    if public:
        if evidence is None:raise ValueError('--public requires --evidence with actual native/provider acceptance results.')
        proofs=json.loads(evidence.read_text())
        missing=[k for k in PUBLIC_GATES if proofs.get(k) is not True]
        if proofs.get('source_digest')!=digest:missing.append('source_digest_matches_current_code')
        if proofs.get('origin')!=base:missing.append('origin_matches_tested_deployment')
        if missing:raise ValueError('Public package gates not satisfied: '+', '.join(missing))
    output=output.expanduser().resolve()
    if output==ROOT or ROOT in output.parents and output.name not in ('dist','artifacts'):
        raise ValueError('Use an external/new output directory or the repository dist/artifacts directory.')
    output.mkdir(parents=True,exist_ok=True)
    results=[]
    for host in ('openai','antigravity'):
        stage=output/(host+'-package')
        if stage.exists():shutil.rmtree(stage)
        shutil.copytree(ROOT/'releases'/host,stage)
        path=stage/('mcp.json' if host=='openai' else 'mcp_config.json')
        config=json.loads(path.read_text())
        server_key = 'augurama' if 'augurama' in config['mcpServers'] else 'dreamina-director'
        config['mcpServers'][server_key]['url' if host=='openai' else 'serverUrl']=base+'/mcp'
        path.write_text(json.dumps(config,indent=2)+'\n')
        if host=='openai':
            path=stage/'plugin.json';manifest=json.loads(path.read_text());interface=manifest['extensions']['com.openai']['interface']
            for field,suffix in (('websiteURL',''),('privacyPolicyURL','/privacy'),('termsOfServiceURL','/terms')):interface[field]=base+suffix
            path.write_text(json.dumps(manifest,indent=2)+'\n')
        info={'release':VERSION,'publisher':'Corgi-Verse Software','configuration':'public-submission-candidate' if public else 'hosted-staging' if hosted else 'local-development','backend_origin':base,'source_digest':digest,'native_host_verified':public,'provider_render_verified':public,'marketplace_registered':False,'contains_private_recipe_source':False,'notice':'Package validation is not platform registration, domain verification, or native/provider acceptance.'}
        (stage/'release-info.json').write_text(json.dumps(info,indent=2)+'\n')
        # Make the connection state visible even when distributing only an extracted folder.
        (stage/'CONNECTION.md').write_text(f'# This package\n\nMode: **{info["configuration"]}**\n\nMCP: `{base}/mcp`\n\n'+('Localhost is not eligible for ChatGPT web or public submission.\n' if not hosted else 'An actual deployed service must answer this endpoint; packaging does not deploy it.\n'))
        checked=validate_package(stage,host)
        archive=output/f'augurama-{host}-{VERSION}.zip'
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
            for p in sorted(stage.rglob('*')):
                if p.is_file():
                    # Portable manifest is at ZIP root, not hidden in another folder.
                    entry=zipfile.ZipInfo(p.relative_to(stage).as_posix(),date_time=(2026,9,29,0,0,0))
                    entry.compress_type=zipfile.ZIP_DEFLATED;entry.external_attr=0o100644<<16
                    z.writestr(entry,p.read_bytes())
        results.append({**checked,'archive':archive.name,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'bytes':archive.stat().st_size})
    report={'release':VERSION,'source_digest':digest,'origin':base,'public_acceptance_evidence_supplied':public,'packages':results}
    (output/'release-manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    return report



def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=ROOT/'dist');p.add_argument('--origin',default='http://127.0.0.1:8765');p.add_argument('--public',action='store_true');p.add_argument('--evidence',type=Path)
    args=p.parse_args(argv)
    try:print(json.dumps(build(args.out,args.origin,public=args.public,evidence=args.evidence),indent=2));return 0
    except (ValueError,AssertionError,OSError,KeyError) as exc:print('RELEASE_BLOCKED: '+str(exc),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())

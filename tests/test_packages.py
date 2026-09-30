from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import zipfile
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('packager',ROOT/'scripts/package_releases.py');packager=importlib.util.module_from_spec(spec);spec.loader.exec_module(packager)

@pytest.mark.parametrize('host',['openai','antigravity'])
def test_host_package_has_correct_distinct_structure(host):
    assert packager.validate_package(ROOT/'releases'/host,host)['local_shape_check']=='passed'


def test_archives_are_reproducible_thin_and_root_installable(tmp_path):
    first=packager.build(tmp_path/'first','http://127.0.0.1:8765')
    second=packager.build(tmp_path/'second','http://127.0.0.1:8765')
    for a,b in zip(first['packages'],second['packages']):
        assert a['sha256']==b['sha256']
        with zipfile.ZipFile(tmp_path/'first'/a['archive']) as z:
            names=z.namelist();assert 'plugin.json' in names
            assert not any('/recipes/' in p or '/src/' in p or p.endswith('.py') for p in names)
            assert json.loads(z.read('release-info.json'))['provider_render_verified'] is False


def test_hosted_package_rebinds_all_public_links(tmp_path):
    result=packager.build(tmp_path/'staging','https://director.corgiverse-owned-domain.net')
    manifest=json.loads((tmp_path/'staging/openai-package/plugin.json').read_text())
    assert manifest['extensions']['com.openai']['interface']['privacyPolicyURL']=='https://director.corgiverse-owned-domain.net/privacy'
    assert result['public_acceptance_evidence_supplied'] is False


@pytest.mark.parametrize('url',['http://real.company.org','https://127.0.0.1','https://localhost','https://fake.example','https://example.com','https://name:password@company.org','https://company.org/path'])
def test_public_origin_rejects_fictional_or_unsafe_targets(url):
    with pytest.raises(ValueError):packager.origin(url,True)


def test_public_archives_require_actual_acceptance_evidence(tmp_path):
    with pytest.raises(ValueError,match='requires'):packager.build(tmp_path/'public','https://director.company.org',public=True)
    evidence=tmp_path/'evidence.json';evidence.write_text(json.dumps({'source_digest':packager.source_digest(),'origin':'https://director.company.org'}))
    with pytest.raises(ValueError,match='gates not satisfied'):packager.build(tmp_path/'public','https://director.company.org',public=True,evidence=evidence)


def test_openai_review_case_metadata_is_complete_but_not_falsely_attested():
    manifest=json.loads((ROOT/'releases/openai/plugin.json').read_text())
    review=manifest['extensions']['com.openai']['review']
    cases=review['test_cases']
    assert len(cases['positive'])==5 and len(cases['negative'])==3
    for case in cases['positive']:
        assert all(case.get(k) for k in ('description','prompt','tools_triggered','expected_behavior'))
    assert 'demo_recording_url' not in review
    assert 'test_credentials' not in review
    gates=json.loads((ROOT/'docs/review/release-gates.json').read_text())
    assert all(gates[k] is False for k in packager.PUBLIC_GATES)


def test_exported_contract_schema_and_example_match_runtime():
    from augurama.models import GenerationPlan
    assert json.loads((ROOT/'contracts/generation-plan.schema.json').read_text())==GenerationPlan.model_json_schema()
    data=json.loads((ROOT/'examples/paper-moon.plan.json').read_text())
    assert set(data)=={'plan'}
    assert GenerationPlan.model_validate(data['plan']).duration_seconds==4

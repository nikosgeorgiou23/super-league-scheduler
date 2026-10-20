"""Independent KPI arithmetic and round-trip export checks."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import pytest
from super_league_scheduler.validate import compute_kpis, validate_schedule, read_schedule, validate_export
from conftest import record


def test_kpi_arithmetic(inputs,scenario):
    scenario=copy.deepcopy(scenario)
    for tid in scenario['attractiveness']:
        scenario['attractiveness'][tid]=[.5]*26
    ms=[record(inputs,1,'volos','ofi','S7'),record(inputs,2,'volos','ofi','S2')]
    k=compute_kpis(ms,inputs[1],scenario,3)
    assert k['total']==1.5
    assert k['range']==1
    assert k['Z']==-1.5
    assert k['scaled_objective']==-15000
    assert k['standard_deviation']==pytest.approx((1.25/26-(1.5/26)**2)**.5)

def test_rounding_is_per_match_and_lambda_once(inputs,scenario):
    ms=[record(inputs,1,'volos','ofi','S7'),record(inputs,2,'volos','ofi','S2')]
    k=compute_kpis(ms,inputs[1],scenario,.125)
    integers=[0]*26
    for m in ms:
        r=m['round']-1
        v=next(s['value'] for s in inputs[1] if s['id']==m['slot'])
        integers[r]+=round((scenario['attractiveness'][m['home']][r]+scenario['attractiveness'][m['away']][r])*v*10000)
    assert k['scaled_objective']==8*sum(integers)-(max(integers)-min(integers))
    assert k['objective_divisor']==80000

def test_forged_totals(inputs,scenario):
    ms=[record(inputs,1,'volos','ofi')]
    k=compute_kpis(ms,inputs[1],scenario)
    k['Z']+=1
    assert not validate_schedule(ms,*inputs,scenario,declared_kpis=k)['checks']['kpis']['passed']

@pytest.mark.parametrize('ext',['json','csv'])
def test_historical_exports_still_checked(inputs,scenario,ext):
    ms=read_schedule(f'examples/current/schedule.{ext}')
    report=validate_schedule(ms,*inputs,scenario)
    assert not report['valid']
    assert not report['checks']['big_opponent_streaks']['passed']
    assert len(ms)==182

def test_missing_file_cli(tmp_path):
    result=subprocess.run([sys.executable,'-m','super_league_scheduler.validate',str(tmp_path/'missing.csv'),
                           '--output-dir',str(tmp_path/'check')],capture_output=True,text=True)
    assert result.returncode==1
    assert not json.loads((tmp_path/'check/validation.json').read_text())['valid']

def test_validator_does_not_import_solver():
    code='import sys; import super_league_scheduler.validate; assert not any(k.startswith("ortools") or k.endswith(".model") for k in sys.modules)'
    subprocess.run([sys.executable,'-c',code],check=True)

@pytest.mark.parametrize('flag',['--many','--seed'])
def test_legacy_cli_retains_optimization(tmp_path,monkeypatch,flag):
    import super_league_scheduler.solve as module
    seen={}
    def fake(*args,**kwargs):
        seen.update(kwargs)
        return dict(status='UNKNOWN',validated=False)
    monkeypatch.setattr(module,'solve',fake)
    argv=['solve','--output-dir',str(tmp_path)] + ([flag] if flag=='--many' else [flag,'42'])
    monkeypatch.setattr(sys,'argv',argv)
    assert module.main()==3
    assert seen['mode']=='optimization'

@pytest.mark.parametrize('ext',['json','csv'])
def test_historical_optimized_exports_rejected(inputs,ext):
    scenario=json.loads(Path('examples/optimized/scenario.json').read_text())
    report=validate_schedule(read_schedule(f'examples/optimized/schedule.{ext}'),*inputs,scenario)
    assert not report['valid']
    assert not report['checks']['streaks']['passed']
    with pytest.raises(ValueError,match='snapshot'):
        validate_export(f'examples/optimized/schedule.{ext}')

def test_corrupted_saved_kpis(tmp_path,inputs):
    import shutil
    shutil.copytree('examples/optimized',tmp_path/'run')
    manifest=tmp_path/'run/run.json'
    snapshot=json.loads(manifest.read_text(encoding='utf-8'))
    snapshot['rules']=inputs[2]
    manifest.write_text(json.dumps(snapshot),encoding='utf-8')
    p=tmp_path/'run/status.json'
    s=json.loads(p.read_text())
    s['kpis']['Z']+=1
    p.write_text(json.dumps(s))
    for ext in ['json','csv']:
        report=validate_export(tmp_path/f'run/schedule.{ext}')
        assert not report['valid']
        assert not report['checks']['kpis']['passed']

def test_deleted_match(inputs):
    from super_league_scheduler.data import prepare_scenario
    ms=read_schedule('examples/optimized/schedule.json')
    scenario=json.loads(Path('examples/optimized/scenario.json').read_text())
    ms.pop()
    report=validate_schedule(ms,*inputs,scenario)
    for key in ['structure','participation','pairings','slots']:
        assert not report['checks'][key]['passed']

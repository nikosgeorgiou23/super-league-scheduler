"""Regression checks proving obsolete restrictions are absent."""
import pytest
from super_league_scheduler.validate import validate_schedule
from conftest import record

@pytest.mark.parametrize('r',[1,2,3])
@pytest.mark.parametrize('s',[f'S{i}' for i in range(1,8)])
def test_top_strength_pairs_allowed_all_slots_and_opening_rounds(inputs,scenario,r,s):
    ms=[record(inputs,r,'aek','paok',s)]
    report=validate_schedule(ms,*inputs,scenario)
    assert set(report['checks']).isdisjoint({'derbies','derby_slots','saturday_big','rematches'})
    assert report['checks']['metadata']['passed']

def test_three_derbies_remain_allowed_with_home_streak_check(inputs,scenario):
    ms=[record(inputs,1,h,a,f'S{i+1}') for i,(h,a) in enumerate([
        ('panathinaikos','olympiacos'),('aek','paok'),('aris','iraklis')])]
    ms += [record(inputs,r,'volos',a) for r,a in zip([12,13,14],['ofi','kifisia','kalamata'])]
    report=validate_schedule(ms,*inputs,scenario)
    for key in ('transition','mirror','metadata'):
        assert report['checks'][key]['passed']

    assert not report['checks']['streaks']['passed']

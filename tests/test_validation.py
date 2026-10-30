"""Record-level rule tests, independent of model variables."""
import pytest
from super_league_scheduler.validate import validate_schedule, mirror_summary
from conftest import record


def check(inputs, scenario, records, key):
    return validate_schedule(records, *inputs, scenario)['checks'][key]['passed']

@pytest.mark.parametrize('start', [1,12,13,24])
@pytest.mark.parametrize('target', ['volos','paok'])
@pytest.mark.parametrize('third', ['aek','ofi'])
def test_strength_ranking_does_not_restrict_opponent_windows(inputs, scenario, start, target, third):
    records=[record(inputs,start+i,*( (target,a) if i%2==0 else (a,target)))
             for i,a in enumerate(['panathinaikos','olympiacos',third])]
    report=validate_schedule(records,*inputs,scenario)
    assert 'big_opponent_streaks' not in report['checks']
    assert report['checks']['streaks']['passed']

@pytest.mark.parametrize('first', [10,11,12,13])
@pytest.mark.parametrize('second', [14,15,16,17])
def test_all_boundary_combinations(inputs, scenario, first, second):
    records=[record(inputs,first,'volos','ofi'),record(inputs,second,'ofi','volos')]
    assert check(inputs,scenario,records,'transition') == ((first, second) != (13, 14))

@pytest.mark.parametrize('hosts', [('panathinaikos','aek'),('paok','aris')])
@pytest.mark.parametrize('s,ok', [('S3',False),('S4',True)])
def test_geography(inputs,scenario,hosts,s,ok):
    records=[record(inputs,3,hosts[0],'volos'),record(inputs,3,hosts[1],'ofi',s)]
    assert check(inputs,scenario,records,'geography') == ok

def test_exempt_hosts(inputs,scenario):
    records=[record(inputs,3,'panathinaikos','paok'),record(inputs,3,'atromitos','aek','S3'),record(inputs,3,'kifisia','aris','S1')]
    assert check(inputs,scenario,records,'geography')

def test_venues_pairings_and_malformed(inputs,scenario):
    ms=[record(inputs,3,'volos','ofi'),record(inputs,16,'volos','ofi')]
    assert not check(inputs,scenario,ms,'venues')
    ms[1]['round']=12
    assert not check(inputs,scenario,ms,'pairings')
    assert not validate_schedule([None,{'round':True,'home':[]}],*inputs,scenario)['valid']
    assert not check(inputs,scenario,[ms[0],ms[0]],'participation')

def test_forged_day(inputs,scenario):
    ms=[record(inputs,3,'aek','volos'),record(inputs,3,'panathinaikos','ofi','S3')]
    ms[1]['day']='sunday'
    assert not check(inputs,scenario,ms,'geography')
    assert not check(inputs,scenario,ms,'metadata')

def test_mirror_ignores_slots_and_requires_all_rounds(inputs,scenario):
    ids=[t['id'] for t in inputs[0]]
    ms=[]
    for r in range(1,14):
        for i in range(7):
            h,a=ids[2*i:2*i+2]
            ms += [record(inputs,r,h,a,f'S{i+1}'),record(inputs,r+13,a,h,f'S{7-i}')]
    assert check(inputs,scenario,ms,'mirror')
    assert mirror_summary(ms)['rounds']==list(range(1,14))
    ms[-1]['home'],ms[-1]['away']=ms[-1]['away'],ms[-1]['home']
    assert check(inputs,scenario,ms,'mirror')
    assert len(mirror_summary(ms)['rounds'])==12

@pytest.mark.parametrize('start',[1,12,13,24])
@pytest.mark.parametrize('home',[True,False])
@pytest.mark.parametrize('pattern,ok',[( [True,True,True],False),([True,True,False],True),([True,False,True],True),([False,True,True],True)])
def test_home_away_limit(inputs,scenario,start,home,pattern,ok):
    records=[]
    for i,(a,same) in enumerate(zip(['ofi','kifisia','kalamata'],pattern)):
        h,away=('volos',a) if same==home else (a,'volos')
        records.append(record(inputs,start+i,h,away))
    assert check(inputs,scenario,records,'streaks')==ok


def monday_round(inputs):
    return [record(inputs,1,h,a,s) for h,a,s in [
        ('aek','volos','S1'),('panathinaikos','ofi','S4'),('olympiacos','kalamata','S8'),
        ('atromitos','paok','S2'),('kifisia','aris','S3'),('levadiakos','iraklis','S5'),
        ('asteras_tripolis','panetolikos','S7')]]


def test_monday_allows_three_protected_hosts_and_one_unused_slot(inputs,scenario):
    ms=monday_round(inputs)
    # Repeat the round only to inspect slot/geography/metadata families;
    # this fixture deliberately makes no claim about season pairings.
    report=validate_schedule([dict(m,round=r) for r in range(1,27) for m in ms],*inputs,scenario)
    for key in ['slots','geography','metadata']:
        assert report['checks'][key]['passed']
    assert len({m['slot'] for m in ms})==7
    assert 'S6' not in {m['slot'] for m in ms}
    from super_league_scheduler.validate import compute_kpis
    expected=sum((scenario['attractiveness'][m['home']][0]+scenario['attractiveness'][m['away']][0])
                 *next(s['value'] for s in inputs[1] if s['id']==m['slot']) for m in ms)
    assert compute_kpis(ms,inputs[1],scenario)['round_values'][0]==pytest.approx(expected)


def test_duplicate_monday_slot_rejected(inputs,scenario):
    ms=monday_round(inputs)
    ms[0]['slot']='S8'
    assert not check(inputs,scenario,ms,'slots')
    assert not check(inputs,scenario,ms,'geography')

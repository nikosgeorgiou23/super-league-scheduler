import copy
import math
import random
import pytest
from super_league_scheduler.data import ratings, prepare_scenario


def test_formulas_and_absence(inputs,scenario):
    values,top_four=ratings(inputs[0],scenario['source'],scenario['rating_config'])
    assert values['iraklis']['H']==pytest.approx(-100/13)
    h=.2*100*10/13+.3*100*12/13+.5*100*10/13
    assert values['panathinaikos']['H']==pytest.approx(h)
    assert values['panathinaikos']['F']==pytest.approx(.3*h+7.5*math.log2(126.35))
    assert set(top_four)=={'aek','paok','olympiacos','panathinaikos'}
    assert scenario['top_four_by_strength']==top_four
    assert 'big_four' not in scenario

def test_equal_and_alternate_top_four_by_strength(inputs,scenario):
    source=copy.deepcopy(scenario['source'])
    for row in source['teams'].values():
        row.update(positions=[15]*3,market_value_million_eur=16)
    values,top_four=ratings(inputs[0],source,scenario['rating_config'])
    assert all(v['mu']==.55 for v in values.values())
    assert top_four==sorted(source['teams'])[:4]
    for tid in ['volos','ofi','kifisia','kalamata']:
        source['teams'][tid]['market_value_million_eur']=10000
    _,top_four=ratings(inputs[0],source,scenario['rating_config'])
    assert set(top_four)=={'volos','ofi','kifisia','kalamata'}

@pytest.mark.parametrize('value',[0,-1,float('inf'),float('nan'),True])
def test_bad_market(inputs,scenario,value):
    source=copy.deepcopy(scenario['source'])
    source['teams']['volos']['market_value_million_eur']=value
    with pytest.raises(ValueError): ratings(inputs[0],source,scenario['rating_config'])

def test_local_rng_and_reuse(inputs,scenario):
    state=random.getstate()
    a=prepare_scenario(inputs[0],scenario['source'],scenario['rating_config'],20261019)
    assert random.getstate()==state
    assert a==scenario
    assert sum(map(len,a['attractiveness'].values()))==364
    assert prepare_scenario(inputs[0],a['source'],a['rating_config'],999,reuse=a)==a
    b=copy.deepcopy(a)
    b['attractiveness']['volos'][0]=20
    with pytest.raises(ValueError): prepare_scenario(inputs[0],a['source'],a['rating_config'],reuse=b)

def test_complete_tiebreak_order(inputs,scenario):
    source=copy.deepcopy(scenario['source'])
    for row in source['teams'].values():
        row.update(positions=[15]*3,market_value_million_eur=1)
    source['teams']['volos']['market_value_million_eur']=3
    source['teams']['ofi']['market_value_million_eur']=2
    source['teams']['iraklis']['positions'][-1]=1
    cfg=dict(history_weights=[.2,.3,.5],history_factor=0,market_factor=0)
    _,top_four=ratings(inputs[0],source,cfg)
    assert top_four==['volos','ofi','iraklis','aek']


def test_historical_ranking_metadata_is_migrated(inputs,scenario):
    legacy=copy.deepcopy(scenario)
    legacy['big_four']=legacy.pop('top_four_by_strength')
    restored=prepare_scenario(inputs[0],legacy['source'],legacy['rating_config'],reuse=legacy)
    assert restored==scenario and 'big_four' not in restored


@pytest.mark.parametrize('legacy',[False,True])
def test_forged_strength_ranking_is_rejected(inputs,scenario,legacy):
    altered=copy.deepcopy(scenario)
    key='top_four_by_strength'
    if legacy:altered['big_four']=altered.pop(key);key='big_four'
    altered[key]=list(reversed(altered[key]))
    with pytest.raises(ValueError,match='strength ranking'):
        prepare_scenario(inputs[0],altered['source'],altered['rating_config'],reuse=altered)

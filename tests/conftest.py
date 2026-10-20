import json
from pathlib import Path
import pytest
from super_league_scheduler.data import load_inputs, prepare_scenario

@pytest.fixture(scope='session')
def inputs():
    return load_inputs('data')

@pytest.fixture(scope='session')
def scenario(inputs):
    return prepare_scenario(inputs[0], json.loads(Path('data/strength.json').read_text()),
                            json.loads(Path('data/rating_config.json').read_text()), 20261019)

def record(inputs, r, h, a, s='S2'):
    teams, slots, _ = inputs
    t = {t['id']: t for t in teams}
    slot = next(slot for slot in slots if slot['id'] == s)
    return dict(round=r, home=h, away=a, home_name=t[h]['name'], away_name=t[a]['name'],
                venue=h, slot=s, **{k: slot[k] for k in ('day','start_earliest','start_latest')})

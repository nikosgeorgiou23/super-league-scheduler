"""Boundary tests use records, never solver variables or solver assertions."""
import pytest
from super_league_scheduler.data import load_inputs
from super_league_scheduler.validate import validate_schedule


@pytest.fixture
def inputs():
    return load_inputs('data')


def record(inputs, r, h, a, s='S2'):
    teams, slots, _ = inputs
    from super_league_scheduler.data import derby_kind
    t = {t['id']: t for t in teams}
    slot = next(slot for slot in slots if slot['id'] == s)
    return dict(round=r, home=h, away=a, home_name=t[h]['name'], away_name=t[a]['name'],
                venue=h, slot=s, day=slot['day'], start_earliest=slot['start_earliest'],
                start_latest=slot['start_latest'], derby=derby_kind(t[h], t[a]))


def passed(inputs, records, check):
    return validate_schedule(records, *inputs)['checks'][check]['passed']


@pytest.mark.parametrize('r,ok', [(1, False), (2, False), (3, True)])
@pytest.mark.parametrize('h,a', [('panathinaikos', 'paok'), ('aris', 'iraklis'), ('aris', 'aek')])
def test_opening_derbies(inputs, r, ok, h, a):
    assert passed(inputs, [record(inputs, r, h, a)], 'derbies') == ok


def test_derby_limit(inputs):
    records = [record(inputs, 3, h, a) for h, a in
               [('panathinaikos', 'olympiacos'), ('aek', 'paok'), ('aris', 'iraklis')]]
    assert passed(inputs, records[:2], 'derbies')
    assert not passed(inputs, records, 'derbies')


@pytest.mark.parametrize('hosts', [('panathinaikos', 'aek'), ('paok', 'aris')])
@pytest.mark.parametrize('s,ok', [('S3', False), ('S4', True)])
def test_geography_per_day(inputs, hosts, s, ok):
    records = [record(inputs, 3, hosts[0], 'volos'), record(inputs, 3, hosts[1], 'ofi', s)]
    assert passed(inputs, records, 'geography') == ok


def test_exempt_hosts_and_away_teams(inputs):
    records = [record(inputs, 3, 'panathinaikos', 'paok'),
               record(inputs, 3, 'atromitos', 'aek', 'S3'),
               record(inputs, 3, 'kifisia', 'aris', 'S1')]
    assert passed(inputs, records, 'geography')


@pytest.mark.parametrize('start', [12, 13])
@pytest.mark.parametrize('home', [True, False])
def test_streak_across_halves(inputs, start, home):
    records = [record(inputs, r, 'volos', a) if home else record(inputs, r, a, 'volos')
               for r, a in zip(range(start, start + 3), ['ofi', 'kifisia', 'kalamata'])]
    assert not passed(inputs, records, 'streaks')
    records[-1]['home'], records[-1]['away'] = records[-1]['away'], records[-1]['home']
    assert passed(inputs, records, 'streaks')


@pytest.mark.parametrize('difference,ok', [(2, False), (3, True)])
def test_rematch_boundary(inputs, difference, ok):
    records = [record(inputs, 13, 'volos', 'ofi'), record(inputs, 13 + difference, 'ofi', 'volos')]
    assert passed(inputs, records, 'rematches') == ok


def test_same_venue_and_wrong_half(inputs):
    records = [record(inputs, 3, 'volos', 'ofi'), record(inputs, 16, 'volos', 'ofi')]
    assert not passed(inputs, records, 'venues')
    records[1]['round'] = 12
    assert not passed(inputs, records, 'pairings')


@pytest.mark.parametrize('h,a', [('panathinaikos', 'volos'), ('volos', 'paok')])
@pytest.mark.parametrize('s,ok', [('S1', False), ('S5', False), ('S4', True)])
def test_big_slots_both_venues(inputs, h, a, s, ok):
    assert passed(inputs, [record(inputs, 3, h, a, s)], 'slots') is False  # incomplete rounds
    errors = validate_schedule([record(inputs, 3, h, a, s)], *inputs)['checks']['slots']['errors']
    assert any('big team' in e for e in errors) == (not ok)


def test_malformed_and_duplicate(inputs):
    assert not validate_schedule([None, {'round': True, 'home': []}], *inputs)['valid']
    m = record(inputs, 3, 'volos', 'ofi')
    assert not passed(inputs, [m, m], 'participation')
    m['day'] = 'monday'
    assert not passed(inputs, [m], 'metadata')


def test_balander_derby_requires_s3(inputs):
    m = record(inputs, 3, 'aris', 'iraklis', 'S1')
    errors = validate_schedule([m], *inputs)['checks']['slots']['errors']
    assert not any('big team' in e for e in errors)
    assert not passed(inputs, [m], 'derby_slots')

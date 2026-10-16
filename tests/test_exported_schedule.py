"""Regression checks on a complete, independently checked CP-SAT solution."""
import json
from pathlib import Path
import pytest
from super_league_scheduler.data import load_inputs
from super_league_scheduler.validate import read_schedule, validate_schedule


@pytest.fixture
def schedule():
    return read_schedule(Path('examples/verified/schedule.json'))


@pytest.mark.parametrize('extension', ['json', 'csv'])
def test_legacy_export_rejected_by_new_rules(extension):
    matches = read_schedule(Path(f'examples/verified/schedule.{extension}'))
    report = validate_schedule(matches, *load_inputs('data'))
    assert not report['valid']
    assert not report['checks']['slots']['passed']
    assert not report['checks']['derby_slots']['passed']
    assert len(matches) == 182
    assert matches == sorted(matches, key=lambda m: (m['round'], m['slot']))


def test_deleted_match(schedule):
    schedule.pop()
    report = validate_schedule(schedule, *load_inputs('data'))
    for key in ('structure', 'participation', 'pairings', 'slots'):
        assert not report['checks'][key]['passed']


def test_forged_derby_label_cannot_bypass_rules(schedule):
    derby = next(m for m in schedule if m['derby'])
    derby['round'] = 1
    derby['derby'] = None
    report = validate_schedule(schedule, *load_inputs('data'))
    assert not report['checks']['derbies']['passed']
    assert not report['checks']['metadata']['passed']


def test_forged_day_cannot_bypass_geography(schedule):
    # Force two protected Athens hosts into Saturday slots, then falsify a day.
    teams, slots, rules = load_inputs('data')
    athens = {t['id'] for t in teams if t['home_conflict_group'] == 'athens'}
    for r in range(1, 27):
        hosts = [m for m in schedule if m['round'] == r and m['home'] in athens]
        if len(hosts) == 2:
            hosts[0]['slot'], hosts[1]['slot'] = 'S2', 'S3'
            hosts[1]['day'] = 'sunday'
            break
    else:
        pytest.fail('Expected a round with two Athens hosts')
    report = validate_schedule(schedule, teams, slots, rules)
    assert not report['checks']['geography']['passed']
    assert not report['checks']['metadata']['passed']

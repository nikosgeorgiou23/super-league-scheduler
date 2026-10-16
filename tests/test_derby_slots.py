"""Regression cases for restored derby windows and Saturday participation."""
import pytest
from ortools.sat.python import cp_model
from super_league_scheduler.data import load_inputs
from super_league_scheduler.model import build_model, _add_derby_slots
from super_league_scheduler.validate import validate_schedule


@pytest.fixture(scope='module')
def inputs():
    return load_inputs('data')


def record(inputs, h, a, slot_id):
    teams, slots, _ = inputs
    team = {t['id']: t for t in teams}
    slot = next(s for s in slots if s['id'] == slot_id)
    from super_league_scheduler.data import derby_kind
    return dict(round=3, home=h, away=a, slot=slot_id, venue=h,
                home_name=team[h]['name'], away_name=team[a]['name'],
                derby=derby_kind(team[h], team[a]),
                **{k: slot[k] for k in ('day', 'start_earliest', 'start_latest')})


CASES = [
    ([('aris', 'iraklis', 'S3')], True),
    ([('aris', 'iraklis', 'S1')], False),
    ([('aris', 'panathinaikos', 'S7')], True),
    ([('aris', 'panathinaikos', 'S6')], False),
    ([('aek', 'paok', 'S7')], True),
    ([('aek', 'paok', 'S3')], False),
    ([('aris', 'panathinaikos', 'S6'), ('iraklis', 'olympiacos', 'S7')], True),
    ([('aris', 'panathinaikos', 'S7'), ('iraklis', 'olympiacos', 'S6')], True),
    ([('aris', 'panathinaikos', 'S3'), ('iraklis', 'olympiacos', 'S7')], False),
    ([('panathinaikos', 'olympiacos', 'S6'), ('paok', 'aek', 'S7')], True),
    ([('panathinaikos', 'olympiacos', 'S7'), ('paok', 'aek', 'S6')], True),
    ([('panathinaikos', 'olympiacos', 'S4'), ('paok', 'aek', 'S7')], False),
    ([('aris', 'iraklis', 'S3'), ('paok', 'aek', 'S7')], True),
    ([('aris', 'iraklis', 'S6'), ('paok', 'aek', 'S7')], False),
    ([('aris', 'panathinaikos', 'S6'), ('paok', 'aek', 'S7')], True),
    ([('aris', 'panathinaikos', 'S7'), ('paok', 'aek', 'S6')], False),
]


@pytest.mark.parametrize('matches,ok', CASES)
def test_independent_validator_derby_cases(inputs, matches, ok):
    report = validate_schedule([record(inputs, *m) for m in matches], *inputs)
    # Partial schedules are deliberately not claimed to be valid overall.
    assert report['checks']['derby_slots']['passed'] == ok


@pytest.mark.parametrize('matches,ok', CASES)
def test_model_derby_cases(inputs, matches, ok):
    teams, slots, _ = inputs
    ids = {t['id']: i for i, t in enumerate(teams)}
    chosen = {(ids[h], ids[a]): s for h, a, s in matches}
    model = cp_model.CpModel()
    x, y = {}, {}
    for h in range(len(teams)):
        for a in range(len(teams)):
            if h == a:
                continue
            x[2, h, a] = model.new_bool_var(f'x_{h}_{a}')
            model.add(x[2, h, a] == int((h, a) in chosen))
            for s, slot in enumerate(slots):
                var = model.new_bool_var(f'y_{h}_{a}_{s}')
                y[2, h, a, s] = var
                model.add(var == int(chosen.get((h, a)) == slot['id']))
    _add_derby_slots(model, 2, x, y, teams, slots)
    solver = cp_model.CpSolver()
    assert (solver.solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)) == ok


def test_s2_still_available_to_other_teams(inputs):
    report = validate_schedule([record(inputs, 'volos', 'ofi', 'S2')], *inputs)
    assert not any('big team' in e for e in report['checks']['slots']['errors'])


def test_s2_forbidden_to_big_teams_both_venues(inputs):
    for h, a in [('aek', 'volos'), ('volos', 'aek')]:
        report = validate_schedule([record(inputs, h, a, 'S2')], *inputs)
        assert any('big team' in e for e in report['checks']['slots']['errors'])


def test_saturday_counts_teams_not_matches(inputs):
    report = validate_schedule(
        [record(inputs, 'panathinaikos', 'olympiacos', 'S3')], *inputs)
    assert not report['checks']['saturday_big']['passed']


def test_two_separate_big_teams_saturday(inputs):
    report = validate_schedule([
        record(inputs, 'aek', 'volos', 'S2'),
        record(inputs, 'paok', 'ofi', 'S3')], *inputs)
    assert not report['checks']['saturday_big']['passed']


def test_single_balander_derby_cannot_fit_full_round(inputs):
    model, variables = build_model(*inputs)
    teams = inputs[0]
    ids = {t['id']: i for i, t in enumerate(teams)}
    # A sole Aris-Iraklis derby consumes S3. Four separate big-team
    # matches cannot fit the remaining three eligible Sunday slots.
    model.add(variables[2, ids['aris'], ids['iraklis'], 2] == 1)
    for (r, h, a, s), var in variables.items():
        if r == 2 and teams[h]['category'] == teams[a]['category'] == 'big':
            model.add(var == 0)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    solver.parameters.num_search_workers = 8
    assert solver.solve(model) == cp_model.INFEASIBLE

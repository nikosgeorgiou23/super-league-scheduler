import json
from pathlib import Path
import pytest
from ortools.sat.python import cp_model
from super_league_scheduler.data import load_inputs
from super_league_scheduler.model import build_model
from super_league_scheduler.solve import solve
from super_league_scheduler.solve import exclude_similar_schedule


@pytest.mark.parametrize('candidate, allowed', [
    ((0, 0, 1, 1), False),  # Changing only the slot is the same pairing.
    ((0, 1, 0, 0), False),  # Reversing home/away is also the same pairing.
    ((1, 0, 1, 0), True),   # Moving the pairing to another round is different.
])
def test_schedule_diversity_ignores_slots_and_venues(candidate, allowed):
    model = cp_model.CpModel()
    previous = (0, 0, 1, 0)
    variables = {key: model.new_bool_var(str(key)) for key in (previous, candidate)}
    model.add_exactly_one(list(variables.values()))
    exclude_similar_schedule(model, variables, lambda var: var is variables[previous], 1)
    model.add(variables[candidate] == 1)
    status = cp_model.CpSolver().solve(model)
    assert status == (cp_model.OPTIMAL if allowed else cp_model.INFEASIBLE)


@pytest.fixture(scope='module')
def built():
    return build_model(*load_inputs('data'))


def test_model_is_valid_and_has_no_objective(built):
    model, _ = built
    assert model.validate() == ''
    assert not model.has_objective()


@pytest.mark.parametrize('start', [0, 11, 12, 23])
@pytest.mark.parametrize('target', ['volos', 'paok'])
def test_model_forbids_three_big_opponents(built, start, target):
    original, variables = built
    model = original.clone()
    teams, _, _ = load_inputs('data')
    ids = {t['id']: i for i, t in enumerate(teams)}
    for i, opponent in enumerate(['panathinaikos', 'olympiacos', 'aek']):
        h, a = (ids[target], ids[opponent]) if i % 2 == 0 else (ids[opponent], ids[target])
        model.add(sum(var for (r, hh, aa, s), var in variables.items()
                      if r == start + i and hh == h and aa == a) == 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    assert solver.solve(model) == cp_model.INFEASIBLE


@pytest.mark.parametrize('r', [0, 1])
def test_model_forbids_opening_derby(built, r):
    original, variables = built
    model = original.clone()
    model.add(variables[r, 0, 1, 2] == 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    assert solver.solve(model) == cp_model.INFEASIBLE


def test_model_forbids_cross_half_home_streak(built):
    original, variables = built
    model = original.clone()
    for r, opponent in zip((11, 12, 13), (6, 7, 8)):
        model.add(variables[r, 0, opponent, 2] == 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    assert solver.solve(model) == cp_model.INFEASIBLE


def test_timeout_is_unknown_and_does_not_export(tmp_path):
    result = solve('data', tmp_path, time_limit=0.000001, seed=42)
    assert result['status'] == 'UNKNOWN'
    assert not result['validated']
    assert not (tmp_path / 'schedule.json').exists()
    assert json.loads((tmp_path / 'status.json').read_text())['status'] == 'UNKNOWN'


def test_reject_stale_output(tmp_path):
    (tmp_path / 'schedule.json').write_text('[]')
    with pytest.raises(ValueError, match='fresh'):
        solve('data', tmp_path)


def test_conflicting_input_is_rejected(tmp_path):
    for path in Path('data').glob('*.json'):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    rules = json.loads((tmp_path / 'rules.json').read_text())
    rules['mirror_required'] = True
    (tmp_path / 'rules.json').write_text(json.dumps(rules))
    with pytest.raises(ValueError, match='conflicts with README'):
        load_inputs(tmp_path)

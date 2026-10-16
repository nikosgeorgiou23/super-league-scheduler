import json
from pathlib import Path
import pytest
from ortools.sat.python import cp_model
from super_league_scheduler.data import load_inputs
from super_league_scheduler.model import build_model
from super_league_scheduler.solve import solve


@pytest.fixture(scope='module')
def built():
    return build_model(*load_inputs('data'))


def test_model_is_valid_and_has_no_objective(built):
    model, _ = built
    assert model.validate() == ''
    assert not model.has_objective()


@pytest.mark.parametrize('r', [0, 1])
def test_model_forbids_opening_derby(built, r):
    original, variables = built
    model = original.clone()
    model.add(variables[r, 0, 1, 1] == 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    assert solver.solve(model) == cp_model.INFEASIBLE


def test_model_forbids_cross_half_home_streak(built):
    original, variables = built
    model = original.clone()
    for r, opponent in zip((11, 12, 13), (6, 7, 8)):
        model.add(variables[r, 0, opponent, 1] == 1)
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

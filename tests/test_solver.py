import json
from pathlib import Path
import pytest
from ortools.sat.python import cp_model
from super_league_scheduler.model import build_model, add_value_objective, objective_units
from super_league_scheduler.solve import solve, solve_many

@pytest.fixture(scope='module')
def built(inputs,scenario):
    return build_model(*inputs,scenario)

def test_model_valid_and_optimization(built,inputs,scenario):
    assert built[0].validate()==''
    assert built[0].has_objective()
    m,_=build_model(*inputs,scenario,mode='feasibility')
    assert not m.has_objective()

def force_match(model,variables,teams,r,h,a):
    ids={t['id']:i for i,t in enumerate(teams)}
    model.add(sum(variables[r,ids[h],ids[a],s] for s in range(7))==1)

@pytest.mark.parametrize('start',[0,11,12,23])
@pytest.mark.parametrize('target',['volos','paok'])
def test_model_big_windows(built,inputs,start,target):
    original,vs=built
    m=original.clone()
    for i,a in enumerate(['panathinaikos','olympiacos','aek']):
        force_match(m,vs,inputs[0],start+i,target,a)
    solver=cp_model.CpSolver()
    solver.parameters.max_time_in_seconds=30
    assert solver.solve(m)==cp_model.INFEASIBLE

@pytest.mark.parametrize('first,second',[(12,13)])
def test_model_transition(built,inputs,first,second):
    m=built[0].clone()
    force_match(m,built[1],inputs[0],first,'volos','ofi')
    force_match(m,built[1],inputs[0],second,'ofi','volos')
    s=cp_model.CpSolver()
    s.parameters.max_time_in_seconds=30
    assert s.solve(m)==cp_model.INFEASIBLE

@pytest.mark.parametrize('balance,expected,choice',[(0,32,20),(3,16,10),(.5,56,20)])
def test_known_optimum(balance,expected,choice):
    m=cp_model.CpModel()
    flag=m.new_bool_var('choice')
    a=m.new_int_var(10,20,'a')
    b=m.new_int_var(12,12,'b')
    m.add(a==10+10*flag)
    add_value_objective(m,[a,b],20,balance)
    s=cp_model.CpSolver()
    assert s.solve(m)==cp_model.OPTIMAL
    assert s.objective_value==expected
    assert s.value(a)==choice

@pytest.mark.parametrize('balance',[-1,float('inf'),1e30,.12345678901234567])
def test_overflow_and_bad_lambda(balance):
    with pytest.raises(ValueError): objective_units(balance)

def test_timeout_and_stale(tmp_path):
    result=solve('data',tmp_path,time_limit=.000001,seed=42)
    assert result['status']=='UNKNOWN'
    assert not result['validated']
    assert not (tmp_path/'schedule.json').exists()
    assert json.loads((tmp_path/'status.json').read_text())['status']=='UNKNOWN'
    with pytest.raises(ValueError,match='fresh'): solve('data',tmp_path)

def test_solver_configuration_does_not_change_data(tmp_path):
    a,b=tmp_path/'a',tmp_path/'b'
    solve('data',a,.000001,1,data_seed=123,workers=1,balance=0)
    solve_many('data',b,.000001,99,data_seed=123,workers=2,balance=3)
    assert (a/'scenario.json').read_bytes()==(b/'scenario.json').read_bytes()
    assert not json.loads((b/'solver_parameters.json').read_text())['stop_after_first_solution']

def test_conflicting_input(tmp_path):
    for p in Path('data').glob('*.json'): (tmp_path/p.name).write_bytes(p.read_bytes())
    path=tmp_path/'rules.json'
    rules=json.loads(path.read_text())
    rules['max_consecutive_home']=3
    path.write_text(json.dumps(rules))
    from super_league_scheduler.data import load_inputs
    with pytest.raises(ValueError,match='conflict'): load_inputs(tmp_path)

@pytest.mark.parametrize('different_round',[None,0,12])
def test_model_full_mirror_equivalence(different_round):
    from super_league_scheduler.model import forbid_full_mirror
    m=cp_model.CpModel()
    comparisons=[]
    for r in range(13):
        a,b=m.new_bool_var(f'a{r}'),m.new_bool_var(f'b{r}')
        m.add(a==1)
        m.add(b==int(r!=different_round))
        comparisons.append((a,b))
    forbid_full_mirror(m,comparisons)
    status=cp_model.CpSolver().solve(m)
    assert status==(cp_model.INFEASIBLE if different_round is None else cp_model.OPTIMAL)

@pytest.mark.parametrize('name',['UNKNOWN','INFEASIBLE','MODEL_INVALID'])
def test_unsuccessful_statuses_do_not_export(tmp_path,monkeypatch,name):
    from types import SimpleNamespace
    import super_league_scheduler.solve as module
    class FakeSolver:
        parameters=SimpleNamespace()
        wall_time=0
        def solve(self,model,callback): return getattr(cp_model,name)
        def status_name(self,status): return name
        def response_stats(self): return 'controlled no-solution response'
    monkeypatch.setattr(module.cp_model,'CpSolver',FakeSolver)
    result=module.solve('data',tmp_path,time_limit=1)
    assert result['status']==name
    assert not result['validated']
    assert not any((tmp_path/f'schedule.{ext}').exists() for ext in ['json','csv'])
    from super_league_scheduler.validate import validate_export
    assert validate_export(tmp_path/'schedule.json')['error']==f'No solution: {name}'

def test_full_model_rejects_historical_home_streaks(built,inputs):
    from super_league_scheduler.validate import read_schedule, validate_schedule
    ms=read_schedule('examples/optimized/schedule.json')
    scenario=json.loads(Path('examples/optimized/scenario.json').read_text())
    # Move the third round's Big 4 meeting into the opening round. This
    # retains historical home streak violations, which both checks must reject.
    for fixture in ms:
        fixture['round']={1:3,3:1}.get(fixture['round'],fixture['round'])
    assert not validate_schedule(ms,*inputs,scenario)['checks']['streaks']['passed']
    big=set(scenario['big_four'])
    assert any(m['round']<=2 and {m['home'],m['away']}<=big for m in ms)
    assert any(m['slot'] in ['S1','S2','S5'] and {m['home'],m['away']}&big for m in ms)
    assert any(all(any(m['round']==r+i and m['home']==t['id'] for m in ms) for i in range(3))
               for r in range(1,25) for t in inputs[0])
    m=built[0].clone()
    for fixture in ms:
        force_match(m,built[1],inputs[0],fixture['round']-1,fixture['home'],fixture['away'])
        ids={t['id']:i for i,t in enumerate(inputs[0])}
        m.add(built[1][fixture['round']-1,ids[fixture['home']],ids[fixture['away']],int(fixture['slot'][1:])-1]==1)
    solver=cp_model.CpSolver()
    solver.parameters.max_time_in_seconds=30
    assert solver.solve(m)==cp_model.INFEASIBLE

@pytest.mark.parametrize('start',[0,11,12,23])
@pytest.mark.parametrize('home',[True,False])
def test_model_forbids_three_same_venues(built,inputs,start,home):
    model=built[0].clone()
    for i,a in enumerate(['ofi','kifisia','kalamata']):
        h,away=('volos',a) if home else (a,'volos')
        force_match(model,built[1],inputs[0],start+i,h,away)
    solver=cp_model.CpSolver()
    solver.parameters.max_time_in_seconds=30
    assert solver.solve(model)==cp_model.INFEASIBLE

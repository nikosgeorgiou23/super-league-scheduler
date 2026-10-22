"""Deterministic ALNS logic plus real CP-SAT repair/validation checks."""
import csv
from copy import deepcopy
import json
import math
import random
from pathlib import Path
from types import SimpleNamespace
import pytest
from ortools.sat.python import cp_model
from super_league_scheduler.alns import (
    ALNSConfig, AdaptiveWeights, CPSatRepair, Evaluation, Neighborhood, OPERATORS,
    RepairResult, SearchState, assignment_keys, assignments, build_repair, destroy,
    evaluate, reference_loss, sa_accept, search, temperature_at, unchanged_outside)
from super_league_scheduler.model import build_model
from super_league_scheduler.solve import extract_matches
from super_league_scheduler.validate import read_schedule, validate_export


@pytest.fixture
def initial():
    return read_schedule('examples/current-rules/schedule.json')


def test_three_operators_and_fixed_seed(initial,inputs):
    ids=[t['id'] for t in inputs[0]]
    for op in OPERATORS:
        first,second=random.Random(5),random.Random(5)
        halves,sizes=set(),set()
        for _ in range(100):
            n=destroy(op,initial,list(range(26)),ids,first)
            assert n==destroy(op,initial,list(range(26)),ids,second)
            if op=='random_teams':
                assert len(set(n.teams))==2
                assert sum(n.contains(m) for m in initial)==50
                assert not n.rounds
            else:
                assert len(set(n.rounds))==len(n.rounds) in (2,3,4)
                half=n.rounds[0]//13
                halves.add(half);sizes.add(len(n.rounds))
                assert all(r//13==half for r in n.rounds)
                if op=='worst_value_rounds':
                    assert set(n.rounds)<=set(range(13*half,13*half+5))
        if op!='random_teams': assert halves=={0,1} and sizes=={2,3,4}


def test_worst_value_pool_is_configurable(initial,inputs):
    ids=[t['id'] for t in inputs[0]]
    values=list(reversed(range(26)))
    n=destroy('worst_value_rounds',initial,values,ids,random.Random(10),worst_pool=7)
    half=n.rounds[0]//13
    assert set(n.rounds)<=set(range(13*half+6,13*half+13))


def test_local_no_good_freezes_complement_and_does_not_accumulate():
    teams=[{'id':'a'},{'id':'b'}];slots=[{'id':'S1'},{'id':'S2'}]
    base=cp_model.CpModel()
    variables={(r,0,1,s):base.new_bool_var(f'y{r}{s}') for r in range(3) for s in range(2)}
    for r in range(3): base.add_exactly_one(variables[r,0,1,s] for s in range(2))
    initial=[dict(round=r+1,home='a',away='b',slot='S1') for r in range(3)]
    base.maximize(-sum(v for (r,h,a,s),v in variables.items() if s==1))
    n=Neighborhood('random_rounds',rounds=(1,))
    repaired,free=build_repair(base,variables,initial,teams,slots,n)
    assert free==1
    solver=cp_model.CpSolver()
    assert solver.solve(repaired)==cp_model.OPTIMAL
    assert solver.value(variables[1,0,1,1])==1  # A worse solution is allowed.
    assert solver.objective_value==-1
    assert solver.value(variables[0,0,1,0])==solver.value(variables[2,0,1,0])==1
    identical=repaired.clone()
    identical.add(variables[1,0,1,0]==1)
    assert solver.solve(identical)==cp_model.INFEASIBLE
    assert solver.solve(base)==cp_model.OPTIMAL
    assert solver.objective_value==0  # The temporary no-good never reached base.
    assert len(base.proto.constraints)==3


def test_team_operator_fixes_inactive_nonteam_choices_too():
    teams=[{'id':t} for t in 'abcd'];slots=[{'id':'S1'},{'id':'S2'}]
    base=cp_model.CpModel()
    keys=[(0,0,1,0),(0,0,1,1),(0,2,3,0),(1,2,3,0),(0,1,0,1)]
    vs={key:base.new_bool_var(str(key)) for key in keys}
    base.add_exactly_one([vs[keys[0]],vs[keys[1]],vs[keys[4]]])
    matches=[dict(round=1,home='a',away='b',slot='S1'),dict(round=1,home='c',away='d',slot='S1')]
    repaired,free=build_repair(base,vs,matches,teams,slots,Neighborhood('random_teams',teams=('a','b')))
    assert free==1
    solver=cp_model.CpSolver()
    assert solver.solve(repaired)==cp_model.OPTIMAL
    assert solver.value(vs[(0,2,3,0)])==1 and solver.value(vs[(1,2,3,0)])==0
    for forbidden,value in [((0,2,3,0),0),((1,2,3,0),1)]:
        wrong=repaired.clone();wrong.add(vs[forbidden]==value)
        assert solver.solve(wrong)==cp_model.INFEASIBLE
    reverse=repaired.clone();reverse.add(vs[(0,1,0,1)]==1)
    assert solver.solve(reverse)==cp_model.OPTIMAL  # Selected-team venue is free.


@pytest.mark.parametrize('operator',OPERATORS)
def test_real_repair_preserves_every_rule_and_neighborhood(initial,inputs,scenario,operator):
    teams,slots,rules=inputs
    base,vs=build_model(*inputs,scenario)
    ids={t['id']:i for i,t in enumerate(teams)}
    # Controlled instance: fix the real season's pairings/venues globally;
    # repair still chooses slots and must satisfy all original constraints.
    for m in initial:
        base.add(sum(vs[m['round']-1,ids[m['home']],ids[m['away']],s] for s in range(len(slots)))==1)
    n=destroy(operator,initial,evaluate(initial,*inputs,scenario,10000).kpis['round_values'],
              list(ids),random.Random(2))
    repaired,free=build_repair(base,vs,initial,teams,slots,n)
    assert free==(50 if operator=='random_teams' else 7*len(n.rounds))
    solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=10
    solver.parameters.num_search_workers=1
    assert solver.solve(repaired) in (cp_model.OPTIMAL,cp_model.FEASIBLE)
    candidate=extract_matches(solver.value,vs,teams,slots)
    assert assignments(candidate)!=assignments(initial)
    assert unchanged_outside(initial,candidate,n)
    assert evaluate(candidate,*inputs,scenario,10000).score==round(solver.objective_value)


class FixedRandom:
    def random(self): return 0


def toy(score,tag):
    return [dict(round=1,home='a',away='b',slot=tag,score=score)]


def toy_evaluate(matches):
    value=matches[0]['score']
    return Evaluation(value,dict(Z=value/1000,round_values=list(range(26))))


def test_sa_best_is_independent_and_never_falls():
    initial=toy(1000,'a');state=SearchState.initial(initial,toy_evaluate(initial))
    assert state.current is not state.best and state.current[0] is not state.best[0]
    rng=FixedRandom()
    result=state.consider(toy(900,'b'),toy_evaluate(toy(900,'b')),1000,rng)
    assert result['note']=='SA ACCEPTED (worse)' and result['reward']==1
    assert state.current_eval.score==900 and state.best_eval.score==1000
    result=state.consider(toy(950,'c'),toy_evaluate(toy(950,'c')),1000,rng)
    assert result['note']=='IMPROVED CURRENT' and result['reward']==3
    result=state.consider(toy(950,'d'),toy_evaluate(toy(950,'d')),1000,rng)
    assert result['note']=='ACCEPTED EQUAL' and result['reward']==1
    result=state.consider(toy(1100,'e'),toy_evaluate(toy(1100,'e')),1000,rng)
    assert result['note']=='NEW BEST' and result['reward']==5
    state.current[0]['slot']='mutated'
    assert state.best[0]['slot']=='e' and initial[0]['slot']=='a'
    assert sa_accept(-100,1000,SimpleNamespace(random=lambda:1))[0] is False
    assert sa_accept(-100,1000,SimpleNamespace(random=lambda:pytest.fail('No draw during calibration')),True)==(False,0,None)


def test_time_geometric_cooling_and_reference_loss():
    loss=100
    start,end=temperature_at(loss,0,225),temperature_at(loss,225,225)
    assert math.exp(-loss/start)==pytest.approx(.5)
    assert math.exp(-loss/end)==pytest.approx(.01)
    assert temperature_at(loss,112.5,225)==pytest.approx(math.sqrt(start*end))
    assert reference_loss([2,8,4],1000,10000)==(4,False)
    assert reference_loss([],1000,10000)==(10,True)
    assert reference_loss([],0,10000)==(10,True)


def test_adaptive_segment_reward_floor_and_unused_operator():
    w=AdaptiveWeights()
    for i in range(20): assert w.record(OPERATORS[0],5)==(i==19)
    assert w.weights=={OPERATORS[0]:1.8,OPERATORS[1]:1,OPERATORS[2]:1}
    assert sum(w.uses.values())==sum(w.rewards.values())==w.count==0
    for _ in range(30*20): w.record(OPERATORS[0],0)
    assert w.weights[OPERATORS[0]]==.1
    assert w.weights[OPERATORS[1]]==w.weights[OPERATORS[2]]==1
    assert sum(w.probabilities().values())==pytest.approx(1)


class Clock:
    def __init__(self,value=1000): self.value=value
    def __call__(self): return self.value


class ScriptedRandom(FixedRandom):
    def __init__(self,seed): pass
    def choices(self,seq,weights,k): return [seq[0]]
    def randrange(self,n): return 0
    def choice(self,seq): return seq[0]
    def sample(self,seq,k): return list(seq)[:k]


def test_scripted_calibration_sa_live_and_deadline(monkeypatch,capsys):
    monkeypatch.setattr('super_league_scheduler.alns.random.Random',ScriptedRandom)
    clock=Clock();initial=toy(1000,'initial');values=iter([1100,900,1000,1050,1050,1200])
    starts=[];deadlines=[]
    def repair(current,n,deadline,limit,iteration):
        starts.append(clock());deadlines.append(deadline);clock.value+=1
        return RepairResult('FEASIBLE',toy(next(values),str(iteration)),1,1,1,7)
    best,current,report,history=search(initial,toy_evaluate(initial),list('abcdefghijklmn'),toy_evaluate,
        repair,ALNSConfig(seconds=6,calibration_seconds=2),1000,clock)
    assert report['iterations']==6 and report['accepted_worse']==1
    assert report['calibration']['duration']==2 and report['calibration']['reference_loss_scaled']==200
    assert not report['calibration']['fallback_used']
    assert [h['note'] for h in history]==['NEW BEST','REJECTED','SA ACCEPTED (worse)','IMPROVED CURRENT','ACCEPTED EQUAL','NEW BEST']
    assert [h['current_scaled_objective'] for h in history]==[1100,1100,1000,1050,1050,1200]
    assert [h['best_scaled_objective'] for h in history]==[1100,1100,1100,1100,1100,1200]
    assert best[0]['score']==1200 and current[0]['score']==1200
    assert deadlines[:2]==[1002,1002] and deadlines[2:]==[1006]*4
    assert all(t<1006 for t in starts) and report['wall_time']==6
    live=capsys.readouterr().out
    for note in ['INITIAL','CALIBRATION: NEW BEST','SA ACCEPTED (worse)','IMPROVED CURRENT','ACCEPTED EQUAL']:
        assert note in live
    assert '1000.0000' not in live  # Human objective units, not scaled integers.


@pytest.mark.parametrize('statuses',[['UNKNOWN','INFEASIBLE'],['FEASIBLE','FEASIBLE']])
def test_failed_or_identical_repairs_keep_current(statuses):
    clock=Clock();initial=toy(1000,'initial')
    def repair(current,n,deadline,limit,iteration):
        clock.value+=1
        return RepairResult(statuses[iteration-1],deepcopy(current) if statuses[0]=='FEASIBLE' else None)
    best,current,report,history=search(initial,toy_evaluate(initial),list('abcdefghijklmn'),toy_evaluate,
        repair,ALNSConfig(seconds=2,calibration_seconds=0),1000,clock)
    assert current==best==initial
    if statuses[0]=='UNKNOWN': assert [h['note'] for h in history]==['REPAIR UNKNOWN','REPAIR INFEASIBLE']
    else: assert all(h['note']=='REPAIR IDENTICAL' for h in history)
    assert all(not h['accepted'] and h['reward']==0 for h in history)


def test_backend_caps_solver_time_after_construction(monkeypatch):
    import super_league_scheduler.alns as module
    clock=Clock(0);seen={}
    def build(*a):
        clock.value+=.4
        return cp_model.CpModel(),50
    class FakeSolver:
        def __init__(self): self.parameters=SimpleNamespace();self.wall_time=.5
        def solve(self,m): seen['limit']=self.parameters.max_time_in_seconds;clock.value+=.5;return cp_model.UNKNOWN
        def status_name(self,s): return 'UNKNOWN'
    monkeypatch.setattr(module,'build_repair',build)
    monkeypatch.setattr(module.cp_model,'CpSolver',FakeSolver)
    backend=CPSatRepair(None,{},[],[],None,1,42,clock=clock)
    result=backend([],Neighborhood('random_teams',teams=('a','b')),1,5,1)
    assert seen['limit']==pytest.approx(.6) and result.status=='UNKNOWN'
    assert backend([],Neighborhood('random_teams'),clock(),5,2).status=='NOT_RUN_BUDGET'


@pytest.mark.parametrize('kwargs',[{'seconds':0},{'seconds':float('inf')},{'worst_pool':3},{'seed':-1},{'calibration_seconds':16},{'random_teams_seconds':0}])
def test_config_rejects_invalid_options(kwargs):
    with pytest.raises(ValueError): ALNSConfig(**kwargs).validate()


def test_separate_budget_and_real_exports(tmp_path,monkeypatch,initial):
    import super_league_scheduler.solve as module
    import super_league_scheduler.alns as alns
    clock=Clock(0);real_evaluate=alns.evaluate;real_search=alns.search
    checked=[]
    def checked_evaluate(*a):
        checked.append(clock());clock.value+=20
        return real_evaluate(*a)
    def search_wrapper(*a,**kw):
        assert clock()==420 and checked==[400]
        return real_search(*a,**kw,clock=clock)
    class FakeSolver:
        def __init__(self): self.parameters=SimpleNamespace();self.wall_time=400;self.best_objective_bound=3000000
        def value(self,var): return 0
        def solve(self,m,callback):
            clock.value=400
            callback.history.append(dict(seconds=400,scaled_objective=0,scaled_bound=3000000))
            return cp_model.FEASIBLE
        def status_name(self,s): return 'FEASIBLE'
        def response_stats(self): return 'initial full model'
    class FakeRepair:
        def __init__(self,*a,**k): pass
        def __call__(self,current,n,deadline,limit,iteration):
            assert clock()<deadline
            duration=min(limit,deadline-clock());clock.value+=duration
            return RepairResult('UNKNOWN',duration=duration,solver_seconds=duration,solver_limit=duration)
    monkeypatch.setattr(module.time,'monotonic',clock)
    monkeypatch.setattr(module,'build_model',lambda *a:(cp_model.CpModel(),{}))
    monkeypatch.setattr(module.cp_model,'CpSolver',FakeSolver)
    monkeypatch.setattr(module,'extract_matches',lambda *a:deepcopy(initial))
    monkeypatch.setattr(alns,'evaluate',checked_evaluate)
    monkeypatch.setattr(alns,'search',search_wrapper)
    monkeypatch.setattr(alns,'CPSatRepair',FakeRepair)
    result=module.solve('data',tmp_path,time_limit=500,data_seed=20261019,alns_config=ALNSConfig())
    assert result['validated'] and result['alns']['wall_time']==240
    assert result['alns']['calibration']['duration']==15
    assert result['total_time']==660  # 400 search + 20 validation + full 240 ALNS.
    assert result['scaled_bound']==3000000
    assert result['first_solution_time']==400
    for ext in ['json','csv']: assert validate_export(tmp_path/f'schedule.{ext}')['valid']
    trace=json.loads((tmp_path/'alns_history.json').read_text())
    with (tmp_path/'alns_history.csv').open(newline='',encoding='utf-8') as stream:
        rows=list(csv.DictReader(stream))
    assert len(rows)==len(trace)==result['alns']['iterations']
    assert (tmp_path/'initial_schedule.json').exists() and (tmp_path/'initial_schedule.csv').exists()
    assert (tmp_path/'current_schedule.json').exists()
    parameters=json.loads((tmp_path/'solver_parameters.json').read_text())
    assert parameters['stop_after_first_solution']


def test_no_initial_solution_never_starts_alns(tmp_path,monkeypatch):
    import super_league_scheduler.solve as module
    class FakeSolver:
        parameters=SimpleNamespace();wall_time=0
        def solve(self,m,callback): return cp_model.UNKNOWN
        def status_name(self,s): return 'UNKNOWN'
        def response_stats(self): return 'timeout'
    monkeypatch.setattr(module.cp_model,'CpSolver',FakeSolver)
    monkeypatch.setattr('super_league_scheduler.alns.search',lambda *a,**k:pytest.fail('No incumbent'))
    result=module.solve('data',tmp_path,time_limit=1,alns_config=ALNSConfig())
    assert result['status']=='UNKNOWN' and not result['validated']
    assert not (tmp_path/'schedule.json').exists() and not (tmp_path/'alns_summary.json').exists()


@pytest.mark.parametrize('balance,mode',[(0,'optimization'),(7,'optimization'),(3,'feasibility')])
def test_alns_requires_lambda_three(tmp_path,balance,mode):
    from super_league_scheduler.solve import solve
    with pytest.raises(ValueError,match='lambda 3'):
        solve('data',tmp_path,balance=balance,mode=mode,alns_config=ALNSConfig())


def test_search_returns_best_even_when_last_current_is_worse(monkeypatch):
    monkeypatch.setattr('super_league_scheduler.alns.random.Random',ScriptedRandom)
    clock=Clock();initial=toy(1000,'initial')
    def repair(current,n,deadline,limit,iteration):
        clock.value+=1
        return RepairResult('FEASIBLE',toy(900,'worse'))
    best,current,report,history=search(initial,toy_evaluate(initial),list('abcdefghijklmn'),toy_evaluate,
        repair,ALNSConfig(seconds=1,calibration_seconds=0),1000,clock)
    assert best==initial and current[0]['score']==900
    assert report['best_scaled_objective']==1000 and report['current_scaled_objective']==900
    assert report['accepted_worse']==1 and history[0]['note']=='SA ACCEPTED (worse)'
    current[0]['slot']='mutated'
    assert best[0]['slot']=='initial'


@pytest.mark.parametrize('outside',[False,True])
def test_invalid_candidate_never_accepted_or_used_for_calibration(monkeypatch,outside):
    monkeypatch.setattr('super_league_scheduler.alns.random.Random',ScriptedRandom)
    clock=Clock();initial=toy(1000,'initial');checks=[]
    def repair(current,n,deadline,limit,iteration):
        clock.value+=1
        candidate=toy(900,'candidate')
        if outside: candidate[0]['round']=3
        return RepairResult('FEASIBLE',candidate)
    def invalid(candidate):
        checks.append(candidate)
        raise ValueError('mandatory constraint violation')
    best,current,report,history=search(initial,toy_evaluate(initial),list('abcdefghijklmn'),invalid,
        repair,ALNSConfig(seconds=1,calibration_seconds=1),1000,clock)
    assert best==current==initial
    assert history[0]['note']=='REPAIR INVALID CANDIDATE' and not history[0]['accepted']
    assert report['calibration']['fallback_used'] and report['calibration']['loss_samples_scaled']==[]
    assert bool(checks)==(not outside)

"""Focused verification requested for the historical sigmoid integration.

Uses unittest from the standard library; does not restore the deleted old suite.
"""
import contextlib
import csv
import io
import json
import math
from pathlib import Path
import shutil
import tempfile
import unittest

from ortools.sat.python import cp_model
from super_league_scheduler.data import load_inputs, prepare_scenario
from super_league_scheduler.slot_values import (
    SIGMOID_SLOPE, load_historical_scores, sigmoid_weights, valuation_report)
from super_league_scheduler.model import build_model
from super_league_scheduler.alns import evaluate, build_repair, Neighborhood
from super_league_scheduler.solve import solve, extract_matches
from super_league_scheduler.validate import read_schedule, validate_schedule, compute_kpis

ROOT=Path(__file__).resolve().parents[1]


class SlotValues(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.teams, cls.slots, cls.rules=load_inputs(ROOT/'data')
        cls.history=load_historical_scores(ROOT/'data/historical_slot_scores.csv')
        old=json.loads((ROOT/'examples/current-rules/scenario.json').read_text(encoding='utf-8'))
        cls.scenario=prepare_scenario(cls.teams,old['source'],old['rating_config'],reuse=old)
        cls.matches=read_schedule(ROOT/'examples/current-rules/schedule.json')
        cls.model,cls.variables=build_model(cls.teams,cls.slots,cls.rules,cls.scenario,balance=5)

    def test_reference_formula(self):
        scores=[122.29,110.87,94.70,92.93,87.08,85.10,82.55,80.38]
        expected=[.7961,.6502,.3938,.3667,.2836,.2582,.2278,.2039]
        center,weights=sigmoid_weights(scores)
        self.assertAlmostEqual(center,101.335,places=12)
        self.assertEqual(SIGMOID_SLOPE,.065)
        for score,weight,approx in zip(scores,weights,expected):
            self.assertAlmostEqual(weight,1/(1+math.exp(-.065*(score-center))),places=15)
            self.assertAlmostEqual(weight,approx,delta=.0001)

    def test_monotonicity_dynamic_center_equal_scores_and_range(self):
        center,weights=sigmoid_weights([120,80,90,110])
        self.assertEqual(center,100)
        self.assertTrue(all(0<v<1 for v in weights))
        ordered=sorted(zip([120,80,90,110],weights))
        self.assertTrue(all(a[1]<b[1] for a,b in zip(ordered,ordered[1:])))
        self.assertEqual(sigmoid_weights([92,92]),(92,[.5,.5]))
        for bad in ([],[math.nan],[math.inf],[True],[-1e10,1e10]):
            with self.subTest(scores=bad),self.assertRaises(ValueError):sigmoid_weights(bad)

    def test_explicit_mapping_and_no_hardcoded_values(self):
        raw=json.loads((ROOT/'data/slots.json').read_text())
        self.assertTrue(all('value' not in s for s in raw['slots']))
        self.assertEqual([s['id'] for s in self.slots],[f'S{i}' for i in range(1,9)])
        self.assertEqual([(s['day'],s['start_earliest'],s['start_latest']) for s in self.slots],
                         [('saturday','16:00','17:00'),('saturday','18:00','19:00'),
                          ('saturday','20:00','21:00'),('sunday','16:00','17:00'),
                          ('sunday','17:00','18:00'),('sunday','18:00','19:00'),
                          ('sunday','20:00','21:00'),('monday','18:00','19:00')])
        center,weights=sigmoid_weights(h['score'] for h in self.history)
        by_id={h['id']:w for h,w in zip(self.history,weights)}
        for slot in self.slots:
            self.assertEqual(slot['value'],by_id[slot['historical_slot']])
            self.assertEqual(slot['normalization_center'],center)
            self.assertNotEqual(slot['value'],round(slot['value'],4))
        self.assertEqual(self.slots[3]['value'],self.slots[4]['value'])
        self.assertAlmostEqual(center,101.33337713274888)

    def test_changed_history_recomputes_weights_and_missing_data_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'data';shutil.copytree(ROOT/'data',root)
            path=root/'historical_slot_scores.csv'
            with path.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
            fields=list(rows[0])
            def save():
                with path.open('w',encoding='utf-8',newline='') as f:
                    writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
            rows[0]['mean_strength']='130.0123456789';save()
            new_slots=load_inputs(root)[1]
            self.assertNotEqual(new_slots[6]['value'],self.slots[6]['value'])
            self.assertEqual(new_slots[6]['historical_score'],130.0123456789)
            rows[0]['match_count']='0';save()
            with self.assertRaisesRegex(ValueError,'No historical observations'):load_inputs(root)
            rows[0]['match_count']='74';save()
            config=json.loads((root/'slots.json').read_text())
            config['slots'][0]['historical_slot']='nonexistent'
            (root/'slots.json').write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError,'Missing historical'):load_inputs(root)
            config['slots'][0]['historical_slot']='saturday_1600_1800'
            config['slots'][0]['value']=.4
            (root/'slots.json').write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError,'Hardcoded'):load_inputs(root)
            path.unlink()
            with self.assertRaises(FileNotFoundError):load_inputs(root)

    def test_hard_constraints_unchanged_by_revaluation(self):
        alternate=[dict(s,value=.5) for s in self.slots]
        other,_=build_model(self.teams,alternate,self.rules,self.scenario,balance=5)
        # Ignore only the 26 equations defining U_r; compare every other row.
        def hard_rows(model):
            indices={i for i,v in enumerate(model.proto.variables) if v.name.startswith('U_') and v.name[2:].isdigit()}
            skipped=[c for c in model.proto.constraints if c.has_linear() and set(c.linear.vars)&indices]
            self.assertEqual(len(skipped),26)
            return [str(c) for c in model.proto.constraints if not (c.has_linear() and set(c.linear.vars)&indices)]
        self.assertEqual(hard_rows(self.model),hard_rows(other))
        self.assertEqual(str(self.model.proto.objective),str(other.proto.objective))

    def test_real_model_alns_and_validator_agree_on_objective(self):
        self.assertTrue(validate_schedule(self.matches,self.teams,self.slots,self.rules,self.scenario,5)['valid'])
        model=self.model.clone()
        tids={t['id']:i for i,t in enumerate(self.teams)};sids={s['id']:i for i,s in enumerate(self.slots)}
        for m in self.matches:
            model.add(self.variables[m['round']-1,tids[m['home']],tids[m['away']],sids[m['slot']]]==1)
        solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=5;solver.parameters.num_search_workers=1
        self.assertEqual(solver.solve(model),cp_model.OPTIMAL)
        kpis=compute_kpis(self.matches,self.slots,self.scenario,5)
        alns=evaluate(self.matches,self.teams,self.slots,self.rules,self.scenario,10000,5)
        self.assertEqual(solver.objective_value,kpis['scaled_objective'])
        self.assertEqual(alns.score,kpis['scaled_objective'])
        self.assertEqual(alns.kpis,kpis)
        for r in range(26):
            total=sum(round((self.scenario['attractiveness'][m['home']][r]+
                             self.scenario['attractiveness'][m['away']][r])*
                            next(s['value'] for s in self.slots if s['id']==m['slot'])*10000)
                      for m in self.matches if m['round']==r+1)
            self.assertEqual(kpis['scaled_round_values'][r],total)

    def test_actual_repair_preserves_rules_and_uses_new_objective(self):
        # Fix pairings/venues to test real slot repair without an extended search.
        base=self.model.clone();tids={t['id']:i for i,t in enumerate(self.teams)}
        for m in self.matches:
            base.add(sum(self.variables[m['round']-1,tids[m['home']],tids[m['away']],s]
                         for s in range(8))==1)
        repair,_=build_repair(base,self.variables,self.matches,self.teams,self.slots,
                              Neighborhood('random_rounds',rounds=(0,1)))
        solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=5;solver.parameters.num_search_workers=1
        self.assertIn(solver.solve(repair),(cp_model.OPTIMAL,cp_model.FEASIBLE))
        candidate=extract_matches(solver.value,self.variables,self.teams,self.slots)
        check=validate_schedule(candidate,self.teams,self.slots,self.rules,self.scenario,5)
        self.assertTrue(check['valid'],check['checks'])
        self.assertEqual(solver.objective_value,check['kpis']['scaled_objective'])

    def test_result_reporting_snapshots_normalized_inputs(self):
        with tempfile.TemporaryDirectory() as temporary,contextlib.redirect_stdout(io.StringIO()) as output:
            destination=Path(temporary)/'run'
            solve(ROOT/'data',destination,time_limit=.000001,balance=5)
            report=json.loads((destination/'slot_values.json').read_text())
            run=json.loads((destination/'run.json').read_text(encoding='utf-8'))
            self.assertEqual(report,valuation_report(self.slots))
            self.assertEqual(run['slots'],self.slots)
            self.assertEqual(run['configuration']['slot_valuation']['center'],report['center'])
            self.assertIn('historical window',output.getvalue())
            self.assertIn('observations N_s',output.getvalue())


if __name__=='__main__':unittest.main()

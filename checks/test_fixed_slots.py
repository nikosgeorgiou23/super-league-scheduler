"""Focused checks for restored fixed slots and their optimization integration."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from ortools.sat.python import cp_model
from super_league_scheduler.data import load_inputs, prepare_scenario
from super_league_scheduler.model import build_model
from super_league_scheduler.alns import evaluate, build_repair, Neighborhood
from super_league_scheduler.solve import solve, extract_matches
from super_league_scheduler.validate import read_schedule, validate_schedule, compute_kpis

ROOT=Path(__file__).resolve().parents[1]


class FixedSlots(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.teams,cls.slots,cls.rules=load_inputs(ROOT/'data')
        old=json.loads((ROOT/'examples/current-rules/scenario.json').read_text(encoding='utf-8'))
        cls.scenario=prepare_scenario(cls.teams,old['source'],old['rating_config'],reuse=old)
        cls.matches=read_schedule(ROOT/'examples/current-rules/schedule.json')
        cls.model,cls.variables=build_model(cls.teams,cls.slots,cls.rules,cls.scenario,balance=7)

    def test_original_slots_and_values_are_restored(self):
        self.assertEqual([s['id'] for s in self.slots],[f'S{i}' for i in range(1,9)])
        self.assertEqual([s['value'] for s in self.slots],[.4,.5,.8,.7,.6,.9,1.,.3])
        self.assertEqual([(s['day'],s['start_earliest'],s['start_latest']) for s in self.slots],
            [('saturday','16:00','17:00'),('saturday','18:00','19:00'),('saturday','20:00','21:00'),
             ('sunday','16:00','17:00'),('sunday','17:00','18:00'),('sunday','18:00','19:00'),
             ('sunday','20:00','21:00'),('monday','18:00','19:00')])
        self.assertTrue(all(set(s)=={'id','day','start_earliest','start_latest','value'} for s in self.slots))
        self.assertFalse((ROOT/'src/super_league_scheduler/slot_values.py').exists())
        self.assertFalse((ROOT/'data/historical_slot_scores.csv').exists())

    def test_invalid_fixed_weight_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            target=Path(temporary)/'data';shutil.copytree(ROOT/'data',target)
            path=target/'slots.json';original=json.loads(path.read_text())
            for value in [0,-.1,1.1,float('nan')]:
                config=json.loads(json.dumps(original));config['slots'][0]['value']=value
                path.write_text(json.dumps(config))
                with self.subTest(value=value),self.assertRaises(ValueError):load_inputs(target)

    def test_cp_sat_alns_and_validator_agree(self):
        checked=validate_schedule(self.matches,self.teams,self.slots,self.rules,self.scenario,7)
        self.assertTrue(checked['valid'])
        model=self.model.clone();teams={t['id']:i for i,t in enumerate(self.teams)}
        slots={s['id']:i for i,s in enumerate(self.slots)}
        for m in self.matches:
            model.add(self.variables[m['round']-1,teams[m['home']],teams[m['away']],slots[m['slot']]]==1)
        solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=5;solver.parameters.num_search_workers=1
        self.assertEqual(solver.solve(model),cp_model.OPTIMAL)
        kpis=compute_kpis(self.matches,self.slots,self.scenario,7)
        self.assertEqual(solver.objective_value,kpis['scaled_objective'])
        self.assertEqual(evaluate(self.matches,self.teams,self.slots,self.rules,self.scenario,10000,7).kpis,kpis)
        records=extract_matches(solver.value,self.variables,self.teams,self.slots)
        self.assertEqual(records,self.matches)

    def test_real_repair_still_preserves_rules(self):
        model=self.model.clone();teams={t['id']:i for i,t in enumerate(self.teams)}
        for m in self.matches:
            model.add(sum(self.variables[m['round']-1,teams[m['home']],teams[m['away']],s] for s in range(8))==1)
        repair,_=build_repair(model,self.variables,self.matches,self.teams,self.slots,
                             Neighborhood('random_rounds',rounds=(0,1)))
        solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=5;solver.parameters.num_search_workers=1
        self.assertIn(solver.solve(repair),(cp_model.FEASIBLE,cp_model.OPTIMAL))
        candidate=extract_matches(solver.value,self.variables,self.teams,self.slots)
        report=validate_schedule(candidate,self.teams,self.slots,self.rules,self.scenario,7)
        self.assertTrue(report['valid'])
        self.assertEqual(solver.objective_value,report['kpis']['scaled_objective'])

    def test_output_reports_fixed_values_without_historical_metadata(self):
        with tempfile.TemporaryDirectory() as temporary,contextlib.redirect_stdout(io.StringIO()) as output:
            destination=Path(temporary)/'run'
            solve(ROOT/'data',destination,time_limit=.000001,balance=7)
            report=json.loads((destination/'slot_values.json').read_text())
            run=json.loads((destination/'run.json').read_text(encoding='utf-8'))
            self.assertEqual(report,dict(method='fixed',slots=self.slots))
            self.assertEqual(run['configuration']['slot_valuation'],dict(method='fixed'))
            self.assertEqual(run['slots'],self.slots)
            self.assertIn('fixed values from data/slots.json',output.getvalue())
            self.assertNotIn('sigmoid',output.getvalue().lower())


if __name__=='__main__':unittest.main()

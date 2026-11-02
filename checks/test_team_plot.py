"""Verify startup reporting, plotted scenario data and CLI phase settings."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from super_league_scheduler.data import load_inputs, prepare_scenario
from super_league_scheduler import solve as runner

ROOT=Path(__file__).resolve().parents[1]


class TeamPlot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.teams, _, _=load_inputs(ROOT/'data')
        cls.scenario=prepare_scenario(cls.teams,
            json.loads((ROOT/'data/strength.json').read_text(encoding='utf-8')),
            json.loads((ROOT/'data/rating_config.json').read_text(encoding='utf-8')),20261019)

    def test_plot_uses_all_14_original_26_point_series_and_closes(self):
        from matplotlib.axes import Axes
        import matplotlib.pyplot as plt
        from super_league_scheduler.plot import plot_team_values
        original=Axes.plot;seen=[];before=plt.get_fignums()
        def record(ax,x,y,**kwargs):
            seen.append((list(x),list(y),kwargs['label']))
            return original(ax,x,y,**kwargs)
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'teams.png'
            with patch.object(Axes,'plot',record),patch('super_league_scheduler.plot._open_chart') as opener:
                self.assertEqual(plot_team_values(self.teams,self.scenario,path,show=True),path.resolve())
            self.assertTrue(path.read_bytes().startswith(b'\x89PNG'))
            opener.assert_called_once_with(path.resolve())
        self.assertEqual(len(seen),14)
        for (x,y,label),team in zip(seen,self.teams):
            self.assertEqual(x,list(range(1,27)))
            self.assertEqual(y,self.scenario['attractiveness'][team['id']])
            self.assertEqual(label,team['name'])
        self.assertEqual(plt.get_fignums(),before)

    def test_graph_and_values_precede_model_construction(self):
        events=[]
        def chart(teams,scenario,path,show):
            self.assertTrue(show)
            self.assertEqual(scenario,self.scenario)
            self.assertTrue((path.parent/'scenario.json').exists())
            events.append('chart');return path
        def stop(*args):
            events.append('model');raise RuntimeError('test stops before optimization')
        with tempfile.TemporaryDirectory() as temporary,contextlib.redirect_stdout(io.StringIO()) as output:
            with patch('super_league_scheduler.plot.plot_team_values',side_effect=chart),patch.object(runner,'build_model',side_effect=stop):
                with self.assertRaisesRegex(RuntimeError,'test stops'):
                    runner.solve(ROOT/'data',Path(temporary)/'run',data_seed=20261019,show_team_chart=True)
            self.assertIn('TEAM ATTRACTIVENESS',output.getvalue())
            self.assertIn('weight V_s',output.getvalue())
            self.assertTrue(all(t['name'] in output.getvalue() for t in self.teams))
        self.assertEqual(events,['chart','model'])

    def test_cli_selects_180_seconds_alns_lambda7_and_team_chart(self):
        captured={}
        def fake(*args,**kwargs):
            captured.update(kwargs)
            return dict(status='UNKNOWN',validated=False)
        args=['solve','--lambda','7','--alns','--alns-time','180',
              '--alns-seed','42','--show-team-chart','--data-seed','20261019']
        with patch('sys.argv',args),patch.object(runner,'solve',side_effect=fake),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(),3)
        self.assertEqual(captured['balance'],7)
        self.assertEqual(captured['alns_config'].seconds,180)
        self.assertEqual(captured['alns_config'].seed,42)
        self.assertEqual(captured['data_seed'],20261019)
        self.assertTrue(captured['show_team_chart'])


if __name__=='__main__':unittest.main()

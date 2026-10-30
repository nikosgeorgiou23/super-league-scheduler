"""Chart export and desktop opening without opening windows during tests."""
import os
import pytest


def test_chart_saved_and_opened(tmp_path,monkeypatch):
    pytest.importorskip('matplotlib')
    from super_league_scheduler.plot import plot_round_values
    opened=[]
    if os.name=='nt':
        monkeypatch.setattr(os,'startfile',lambda path: opened.append(path))
    else:
        monkeypatch.setattr('webbrowser.open',lambda path: opened.append(path))
    path=plot_round_values([float(i)/5 for i in range(1,27)],tmp_path/'chart.png',show=True)
    assert path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
    assert len(opened)==1


@pytest.mark.parametrize('values',[[],[1]*25,[float('nan')]*26,[-1]*26])
def test_invalid_chart_values(tmp_path,values):
    from super_league_scheduler.plot import plot_round_values
    with pytest.raises(ValueError):
        plot_round_values(values,tmp_path/'invalid.png')


@pytest.mark.parametrize('alns',[False,True])
def test_cli_prints_solution_then_opens_chart(tmp_path,monkeypatch,capsys,alns):
    pytest.importorskip('matplotlib')
    import sys
    import super_league_scheduler.solve as module
    events=[]
    values=[float(i) for i in range(1,27)]
    def fake_solve(*a,**k):
        assert k['balance']==7
        result=dict(status='FEASIBLE',validated=True,kpis={'round_values':values})
        if alns:
            assert k['alns_config'].seconds==240
            result.update(relative_gap=.1,alns=dict(iterations=1,accepted_worse=0,
                initial_real_Z=100,best_real_Z=101,best_scaled_objective=1010000,
                objective_divisor=10000,operator_statistics={},weights={}))
        return result
    monkeypatch.setattr(module,'solve',fake_solve)
    monkeypatch.setattr(module,'read_schedule',lambda p: [])
    monkeypatch.setattr(module,'print_schedule',lambda ms: events.append('print'))
    def fake_chart(actual,path,show=False):
        assert actual==values and show
        events.append('chart')
        return path
    monkeypatch.setattr('super_league_scheduler.plot.plot_round_values',fake_chart)
    monkeypatch.setattr(sys,'argv',['solve','--output-dir',str(tmp_path),'--lambda','7','--show-chart']+
                        (['--alns','--alns-time','240'] if alns else []))
    assert module.main()==0
    assert events==['print','chart']
    if alns:
        output=capsys.readouterr().out
        assert 'BEST ALNS SCHEDULE' in output and 'lambda=7' in output
        assert 'best Z=101.000000' in output and 'rounded objective=101.000000' in output
        assert 'global integer-objective gap=10.00%' in output


def test_cli_unknown_explains_missing_chart(tmp_path,monkeypatch,capsys):
    import sys
    import super_league_scheduler.solve as module
    monkeypatch.setattr(module,'solve',lambda *a,**k: dict(status='UNKNOWN',validated=False))
    monkeypatch.setattr(sys,'argv',['solve','--output-dir',str(tmp_path)])
    assert module.main()==3
    assert 'No schedule found. Status: UNKNOWN. No chart generated.' in capsys.readouterr().out

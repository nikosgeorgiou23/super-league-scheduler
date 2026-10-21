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


def test_cli_prints_solution_then_opens_chart(tmp_path,monkeypatch):
    pytest.importorskip('matplotlib')
    import sys
    import super_league_scheduler.solve as module
    events=[]
    values=[float(i) for i in range(1,27)]
    monkeypatch.setattr(module,'solve',lambda *a,**k: dict(status='FEASIBLE',validated=True,kpis={'round_values':values}))
    monkeypatch.setattr(module,'read_schedule',lambda p: [])
    monkeypatch.setattr(module,'print_schedule',lambda ms: events.append('print'))
    def fake_chart(actual,path,show=False):
        assert actual==values and show
        events.append('chart')
        return path
    monkeypatch.setattr('super_league_scheduler.plot.plot_round_values',fake_chart)
    monkeypatch.setattr(sys,'argv',['solve','--output-dir',str(tmp_path),'--show-chart'])
    assert module.main()==0
    assert events==['print','chart']


def test_cli_unknown_explains_missing_chart(tmp_path,monkeypatch,capsys):
    import sys
    import super_league_scheduler.solve as module
    monkeypatch.setattr(module,'solve',lambda *a,**k: dict(status='UNKNOWN',validated=False))
    monkeypatch.setattr(sys,'argv',['solve','--output-dir',str(tmp_path)])
    assert module.main()==3
    assert 'No schedule found. Status: UNKNOWN. No chart generated.' in capsys.readouterr().out

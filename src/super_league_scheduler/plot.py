"""Save the 26 round values and optionally open the image on the desktop."""
import math
import os
from pathlib import Path
import webbrowser
from .data import ATTRACTIVENESS_DELTA


def _open_chart(path):
    """Launch the viewer without blocking the optimization or requiring a close."""
    try:
        if os.name == 'nt':
            os.startfile(str(path))
        elif not webbrowser.open(path.as_uri()):
            print(f'Chart saved; open it manually: {path}', flush=True)
    except OSError as exc:
        print(f'Chart saved at {path}; automatic opening failed: {exc}', flush=True)


def plot_team_values(teams, scenario, path, show=False):
    """Plot the 14 pre-drawn attractiveness trajectories, before scheduling."""
    ids = [team['id'] for team in teams]
    if len(ids) != 14 or len(set(ids)) != 14 or set(scenario['attractiveness']) != set(ids):
        raise ValueError('Expected attractiveness for exactly 14 unique teams')
    for tid in ids:
        values = scenario['attractiveness'][tid]
        if len(values) != 26 or any(not math.isfinite(v) or v < 0 for v in values):
            raise ValueError('Expected 26 finite nonnegative attractiveness values per team')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    path = Path(path).resolve()
    fig, ax = plt.subplots(figsize=(17, 8), layout='constrained')
    try:
        palette = plt.get_cmap('tab20')
        colors = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 1, 5, 9, 13]
        for index, team in enumerate(teams):
            ax.plot(range(1, 27), scenario['attractiveness'][team['id']],
                    label=team['name'], color=palette(colors[index]), linewidth=1.5,
                    marker='o', markersize=3, linestyle='-' if index < 10 else '--')
        ax.set(xticks=range(1, 27), xlim=(1, 26), ylim=(0, 1.05),
               xlabel='Αγωνιστική', ylabel='Ελκυστικότητα ομάδας aᵢ,ᵣ',
               title=f"Ελκυστικότητα των 14 ομάδων ανά αγωνιστική\n"
                     f"aᵢ,ᵣ ~ Uniform[μᵢ − δ, μᵢ + δ] · δ={ATTRACTIVENESS_DELTA:g} · data seed={scenario['data_seed']}")
        ax.grid(alpha=.25)
        ax.legend(loc='center left', bbox_to_anchor=(1.01, .5), frameon=False)
        fig.savefig(path, dpi=180)
    finally:
        plt.close(fig)
    if show:
        _open_chart(path)
    return path


def plot_round_values(values, path, show=False):
    if len(values) != 26 or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError('Expected 26 nonnegative finite round values')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    path = Path(path).resolve()
    fig, ax = plt.subplots(figsize=(16, 6), layout='constrained')
    try:
        bars = ax.bar(range(1, 27), values, color='#2563eb')
        ax.bar_label(bars, fmt='%.2f', padding=3, fontsize=8)
        ax.set(xticks=range(1, 27), xlabel='Round', ylabel='TV value U_r',
               title='TV value per round', ylim=(0, max(1, max(values) * 1.15)))
        ax.axhline(sum(values) / 26, color='#ea580c', linestyle='--', label='Mean')
        ax.legend()
        fig.savefig(path, dpi=180)
    finally:
        plt.close(fig)
    if show:
        _open_chart(path)
    return path

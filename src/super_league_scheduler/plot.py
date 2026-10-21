"""Save the 26 round values and optionally open the image on the desktop."""
import math
import os
from pathlib import Path
import webbrowser


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
        if os.name == 'nt':
            os.startfile(str(path))
        else:
            webbrowser.open(path.as_uri())
    return path

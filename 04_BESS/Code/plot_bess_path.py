"""
plot_bess_path.py -- Figure 6 of the thesis: battery spreads along the price path of the IRR model.

Spread = discharge price - charge cost (Output/bess_dispatch_summary.csv, mean of the weather years),
scaled with the spread factors of the IRR model, at the five anchors and linear in between.
Output: Figures/bess_spreads_path.pdf and .png.

Run:  python plot_bess_path.py
"""
import os
import sys

import pandas as pd

CODE = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(CODE)   # topic folder: Data/, Output/, Figures/
sys.path.insert(0, os.path.join(HERE, '..'))
import thesis_style as ts  # noqa: E402

SPREAD_FACTOR = {'grey': 1.2694, 'green': 1.2413}   # Inputs_BESS D49, D46 of the IRR Excel; change both together
ANCHORS = [(2025, 'S1', 15.94), (2030, 'S2', 27.5), (2037, 'S3', 35), (2045, 'S4', 45), (2054, 'S4', 50)]   # Inputs_Price rows 17 to 21 (year, scenario, penetration) = 03_Sensitivity/thresholds.ANCHOR_PATH
REF_YEAR = 2037   # end label: change of the spread from this anchor
# grey BESS solid in grey, green BESS dashed in HSG green; value labels above (grey) / below (green)
STYLE = {'grey': ('#666666', '-', +1), 'green': (ts.HSG_DARK, (0, (5, 2)), -1)}


def spreads():
    s = pd.read_csv(os.path.join(HERE, 'Output', 'bess_dispatch_summary.csv'))
    out = {}
    for mode in STYLE:
        y = []
        for _, sc, pen in ANCHORS:
            t = s[(s.scenario_key == sc) & (s.penetration_pct == pen)].iloc[0]
            y.append((t[f'bess_{mode}_discharge_price'] - t[f'bess_{mode}_charge_cost']) * SPREAD_FACTOR[mode])
        out[mode] = y
    return out


def plot(values):
    fig, ax = ts.figure(ts.FULL_WIDTH, 8.5)
    # x = PV penetration (PV fed in / total load, mean of the weather years) at each anchor
    r = pd.read_csv(os.path.join(HERE, '..', '02_Main_Model', 'Output', 'v6_results_long.csv'))
    r = r[r.flex_factor == 1.0]
    x = [r[(r.scenario_key == sc) & (r.penetration_pct == pen)].pv_share_load_pct.mean() for _, sc, pen in ANCHORS]
    print('x (PV penetration %)', [round(a, 1) for a in x])
    ax.set(xlim=(13, 45), ylim=(60, 150), xlabel='PV penetration (% of total load)', ylabel='Spread, scaled to observed level (EUR/MWh)')
    ax.set_xticks(x, [f'{a:.0f}' for a in x])
    for pen in x:
        ax.axvline(pen, color=ts.GRID, lw=0.6, zorder=0.4)     # anchor years

    ref = [year for year, _, _ in ANCHORS].index(REF_YEAR)
    for mode, (color, ls, side) in STYLE.items():
        y = values[mode]
        ax.plot(x, y, color=color, lw=1.6, ls=ls, marker='o', ms=ts.MS + 1, mec='white', mew=0.8, zorder=3)
        # value labels: grey above, green below its line; a label leans away from a neighbouring segment
        # that runs through its side (and the last one leans left, away from the end label)
        for i, (xi, yi) in enumerate(zip(x, y)):
            into = lambda j: 0 <= j < len(y) and (y[j] - yi) * side > 0   # noqa: E731  neighbour j on the label side
            lean = -1 if (i == len(x) - 1 or (into(i + 1) and not into(i - 1))) else (+1 if into(i - 1) and not into(i + 1) else 0)
            ax.annotate(f'{yi:.0f}', (xi, yi), xytext=(3 * lean, 6 * side), textcoords='offset points',
                        ha={-1: 'right', 0: 'center', 1: 'left'}[lean], va='bottom' if side > 0 else 'top',
                        fontsize=ts.FS_LABEL, color=ts.INK)
        change = (y[-1] / y[ref] - 1) * 100
        ax.annotate(f'{mode.capitalize()} BESS\n{change:+.0f} % from {REF_YEAR}'.replace('-', '−'),
                    (x[-1], y[-1]), xytext=(8, 0), textcoords='offset points', ha='left', va='center',
                    fontsize=ts.FS_LABEL, color=color, annotation_clip=False)
        print(mode, [round(v, 1) for v in y], round(change, 1))

    # top axis: year and scenario of each anchor
    top = ax.secondary_xaxis('top')
    top.set_xticks(x, [f'{year}\n{sc}' for year, sc, _ in ANCHORS])
    top.tick_params(length=0, labelsize=ts.FS_TICK)
    top.spines['top'].set_visible(False)
    ts.save(fig, 'bess_spreads_path', os.path.join(HERE, 'Figures'), formats=('pdf', 'png'))
    return fig


if __name__ == '__main__':
    plot(spreads())

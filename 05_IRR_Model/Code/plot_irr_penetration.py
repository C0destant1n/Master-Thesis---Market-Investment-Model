"""
plot_irr_penetration.py -- Figure 4 of the thesis: equity IRR by PV penetration and scenario, (a) Utility, (b) Rooftop.

Reads Table 1 of the Sensitivity sheet and the hurdle rate from the IRR model (values as last saved in
Excel) and maps the penetration to PV fed in with the diagnostics of the main run.
Output: Figures/fig_irr_penetration.pdf and .png.

Run:  python plot_irr_penetration.py [path to the IRR Excel]
"""
import os
import sys

import numpy as np
import openpyxl
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.transforms import blended_transform_factory
from matplotlib.ticker import MultipleLocator, PercentFormatter

CODE = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(CODE)   # topic folder: Data/, Output/, Figures/
sys.path.insert(0, os.path.join(HERE, '..'))
import thesis_style as ts  # noqa: E402

sys.path.insert(0, CODE)
from irr_replica import XLSX  # noqa: E402  (location of the IRR model)
FIG_DIR = os.path.join(HERE, 'Figures')
DIAG = os.path.join(HERE, '..', '02_Main_Model', 'Output', 'v6_capture_price_matrix.xlsx')
SHARE_LABEL = 'PV penetration (% of total load)'
TABLE1 = {'Utility (ground mounted)': 'C', 'Rooftop': 'J'}   # corner column of Table 1 (penetration column)
ROW_SC, ROW_FIRST, ROW_LAST = 18, 19, 41                      # scenario index row, data rows
SC_KEY = {1: 'S1', 2: 'S2', 3: 'S3', 4: 'S4'}
IRR_LABEL = 'Equity IRR\n(nominal, after tax)'
XLIM, YLIM = (15, 50), (-0.20, 0.30)   # x from 15: Table 1 starts today (15.94 % penetration = 15.1 to 15.9 % share)


def load(path):
    """{segment: {scenario key: [(penetration %, IRR)]}} and the hurdle rate, from the saved Excel values."""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb['Sensitivity']
    data = {}
    for seg, col in TABLE1.items():
        c0 = openpyxl.utils.column_index_from_string(col)
        rows = list(ws.iter_rows(min_row=ROW_SC, max_row=ROW_LAST, min_col=c0, max_col=c0 + 4, values_only=True))
        idx = rows[0][1:]
        data[seg] = {}
        for j, sc in enumerate(idx):
            pts = [(r[0], r[1 + j]) for r in rows[1:]
                   if isinstance(r[0], (int, float)) and isinstance(r[1 + j], (int, float))]
            data[seg][SC_KEY[int(sc)]] = pts
    hurdle = next(r[3] for r in wb['Inputs_Finance'].iter_rows(max_col=4, values_only=True)
                  if isinstance(r[1], str) and r[1].startswith('Equity hurdle rate'))
    return data, hurdle


def to_share(data):
    """Penetration -> PV share of total load, per scenario (linear between grid points; Table 1 points lie on the grid)."""
    diag = pd.read_excel(DIAG, sheet_name='diagnostics')
    diag['sc'] = diag.scenario.map(ts.SCENARIO_BY_NAME)
    out = {}
    for seg, curves in data.items():
        out[seg] = {}
        for sc, pts in curves.items():
            d = diag[diag.sc == sc].sort_values('penetration_pct')
            pen, irr = zip(*pts)
            share = np.interp(pen, d.penetration_pct, d.pv_share_load_pct)
            out[seg][sc] = list(zip(share, irr))
    return out


def panel(ax, curves, hurdle, show_ylabel):
    ax.axhline(0, color=ts.BASELINE, lw=0.8, zorder=0.8)
    for sc in ts.SCENARIOS:
        pts = curves.get(sc)
        if pts:
            x, y = zip(*pts)
            ax.plot(x, y, color=ts.SCENARIOS[sc]['color'], lw=ts.LW, zorder=2)
    # hurdle in black, dashed, label right above the line
    ax.axhline(hurdle, color='black', lw=0.9, ls='--', zorder=1.5)
    tr = blended_transform_factory(ax.transAxes, ax.transData)
    ax.annotate(f'Hurdle rate {hurdle * 100:.2f} % (merchant)', (0.995, hurdle), xycoords=tr, xytext=(0, 1.5),
                textcoords='offset points', ha='right', va='bottom', fontsize=ts.FS_LABEL, color='black')
    ax.set(xlim=XLIM, ylim=YLIM, xlabel=SHARE_LABEL, ylabel=IRR_LABEL if show_ylabel else None)
    ax.xaxis.set_major_locator(MultipleLocator(10))
    ax.yaxis.set_major_locator(MultipleLocator(0.10))
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))


def plot(path=XLSX):
    data, hurdle = load(path)
    data = to_share(data)
    fig, axes = ts.figure(ts.FULL_WIDTH, 7.0, 1, 2, sharey=True)
    for ax, (seg, curves), letter in zip(axes, data.items(), 'ab'):
        panel(ax, curves, hurdle, show_ylabel=letter == 'a')
        ax.set_title(f'({letter}) {seg}', loc='left', fontsize=ts.FS_AXES, fontweight='bold', pad=12)   # more white between title and plot
    axes[1].tick_params(labelleft=True)
    keys = [k for k in ts.SCENARIOS if any(k in c for c in data.values())]
    handles = [Line2D([], [], color=ts.SCENARIOS[k]['color'], lw=ts.LW) for k in keys]
    fig.legend(handles, [ts.SCENARIOS[k]['label'] for k in keys], loc='outside lower center', ncol=len(keys),
               handlelength=2.0, columnspacing=1.5)
    ts.save(fig, 'fig_irr_penetration', FIG_DIR, formats=('pdf', 'png'))
    return fig


if __name__ == '__main__':
    plot(sys.argv[1] if len(sys.argv) > 1 else XLSX)

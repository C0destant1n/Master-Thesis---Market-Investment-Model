# -*- coding: utf-8 -*-
"""
plot_feasibility.py -- figures of the main run (Figure 3 of the thesis), from the saved results only.

Reads Output/v6_capture_price_matrix.xlsx (sheet diagnostics) and the observed 2025 point
(../01_Validation/Output/validation.xlsx) and plots capture rate and capture price against potential PV
penetration and PV penetration fed in, with the flexibility band per scenario.
Output: Figures/fig3_capture_price_rate.pdf/.png (2 x 2 panels) and the single panels as PNG.

Structure:  load_diag, curves > panels (panel_curve, panel_saturation, legend) > fig3, fig_single, plot_all

Run:  python plot_feasibility.py
"""

import os
import sys

import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

CODE = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(CODE)   # topic folder: Data/, Output/, Figures/
sys.path.insert(0, os.path.join(HERE, '..'))
import thesis_style as ts  # noqa: E402

BASE_YEAR = 2025   # = PyPSA_model_v6.CONFIG['base_year'] (prices in real EUR of this year)
OUT_DIR = os.path.join(HERE, 'Output')
FIG_DIR = os.path.join(HERE, 'Figures')
PRICE_LABEL = f'PV capture price\n(EUR/MWh, real {BASE_YEAR})'
RATE_LABEL = 'PV capture rate\n(capture price / baseload)'
SHARE_LABEL = 'PV penetration (% of total load)'
SHARE_YLABEL = 'PV penetration\n(% of total load)'
PEN, SHARE = 'penetration_pct', 'pv_share_load_pct'
# x range per axis: penetration over the whole grid (0-100 %); PV share from the points up to
# 60 % penetration (the overbuild points above are shown on the penetration axis only)
X_RANGE = {PEN: 100.0, SHARE: ts.PEN_MAX}


def load_diag():
    """Mean of the weather years per scenario and penetration, as written by PyPSA_model_v6.write_outputs."""
    diag = pd.read_excel(os.path.join(OUT_DIR, 'v6_capture_price_matrix.xlsx'), sheet_name='diagnostics')
    return diag.assign(sc=diag.scenario.map(ts.SCENARIO_BY_NAME))


def observed_base_year():
    """Observed market of BASE_YEAR (same system as S1) from the validation, or None."""
    f = os.path.join(HERE, '..', '01_Validation', 'Output', 'validation.xlsx')
    if not os.path.exists(f):
        return None
    obs = pd.read_excel(f, sheet_name='comparison', index_col=0)
    return obs.loc[BASE_YEAR] if BASE_YEAR in obs.index else None


def curves(diag):
    """(scenario key, data sorted by penetration) in scenario order."""
    for sc in ts.SCENARIOS:
        d = diag[diag.sc == sc].sort_values(PEN)
        if len(d):
            yield sc, d


def observed_point(ax, obs, x, y_col):
    if obs is not None:
        ox = obs.penetration_pct if x == PEN else obs.pv_share_load_pct_obs
        ax.plot([ox], [obs[y_col]], marker='D', ms=4, color='black', ls='none', zorder=5)


# ---------------------------------------------------------------------------
# Panels (drawn into a given axes; used by the 2 x 2 figure and the single figures)
# ---------------------------------------------------------------------------

def panel_curve(ax, diag, obs, x, value):
    """Capture rate or capture price vs penetration or PV share; band = flexibility effect."""
    xmax = X_RANGE[x]
    data = diag[diag.penetration_pct <= xmax + 1e-9] if x == SHARE else diag
    for sc, d in curves(data):
        c = ts.SCENARIOS[sc]['color']
        ax.fill_between(d[x], d[value], d[f'{value}_storage_bid'], color=c, alpha=ts.BAND_ALPHA, lw=0, zorder=1)
        ax.plot(d[x], d[f'{value}_storage_bid'], color=c, lw=0.5, ls=(0, (3, 2)), zorder=1.5)   # upper edge
    for sc, d in curves(data):
        ax.plot(d[x], d[value], color=ts.SCENARIOS[sc]['color'], lw=ts.LW, zorder=2)
    if value == 'capture_rate':
        ax.axhline(1.0, color=ts.BASELINE, lw=0.8, zorder=0.8)   # capture rate 1 = baseload
    ax.set(xlim=(0, xmax), xlabel=ts.PEN_LABEL if x == PEN else SHARE_LABEL,
           ylim=(0, 1.3) if value == 'capture_rate' else (0, 150),
           ylabel=RATE_LABEL if value == 'capture_rate' else PRICE_LABEL)
    observed_point(ax, obs, x, f'{value}_obs')


def panel_saturation(ax, diag, obs):
    """PV share fed in vs PV penetration over the whole grid (translation between the two axes)."""
    ax.plot([0, 100], [0, 100], color=ts.BASELINE, lw=0.8, zorder=0.8)
    ax.annotate('Equal values', (62, 62), xytext=(-4, 2), textcoords='offset points', ha='right',
                va='bottom', fontsize=ts.FS_LABEL, color=ts.REF_GREY)
    for sc, d in curves(diag):
        ax.plot(d[PEN], d[SHARE], color=ts.SCENARIOS[sc]['color'], lw=ts.LW, zorder=2)
    ax.set(xlim=(0, 100), ylim=(0, 70), xlabel=ts.PEN_LABEL, ylabel=SHARE_YLABEL)
    if obs is not None:
        ax.plot([obs.penetration_pct], [obs.pv_share_load_pct_obs], marker='D', ms=4, color='black', ls='none',
                zorder=5)


def legend(fig, diag, band=True, ncol=3):
    keys = [k for k in ts.SCENARIOS if k in set(diag.sc)]
    handles = [Line2D([], [], color=ts.SCENARIOS[k]['color'], lw=ts.LW) for k in keys]
    labels = [ts.SCENARIOS[k]['label'] for k in keys]
    if band:
        handles.append((Patch(color=ts.REF_GREY, alpha=0.35, lw=0),
                        Line2D([], [], color=ts.REF_GREY, lw=0.5, ls=(0, (3, 2)))))
        labels.append('Band: flexibility effect, dashed: storage sets the price')
    handles.append(Line2D([], [], marker='D', ms=4, color='black', ls='none'))
    labels.append(f'Observed market {BASE_YEAR}')
    fig.legend(handles, labels, loc='outside lower center', ncol=ncol, handlelength=2.0, columnspacing=1.5)


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def fig3(diag, obs):
    """Fig. 3, 2 x 2 (PDF + PNG): (a) capture rate vs penetration, (b) capture rate vs PV share,
    (c) saturation, (d) capture price vs PV share."""
    fig, ((a, b), (c, d)) = ts.figure(ts.FULL_WIDTH, 11.5, 2, 2)
    panel_curve(a, diag, obs, PEN, 'capture_rate')
    panel_curve(b, diag, obs, SHARE, 'capture_rate')
    panel_saturation(c, diag, obs)
    panel_curve(d, diag, obs, SHARE, 'capture_price')
    for ax, letter in zip((a, b, c, d), 'abcd'):
        ts.panel_letter(ax, letter)
    legend(fig, diag)
    ts.save(fig, 'fig3_capture_price_rate', FIG_DIR, formats=('pdf', 'png'))
    return fig


SINGLES = {   # file name: (x, value); value None = saturation
    'fig_capture_rate_penetration': (PEN, 'capture_rate'),
    'fig_capture_rate_share': (SHARE, 'capture_rate'),
    'fig_saturation': (PEN, None),
    'fig_capture_price_share': (SHARE, 'capture_price'),
    'fig_capture_price_penetration': (PEN, 'capture_price'),
}


def fig_single(diag, obs, name):
    """One panel at full width (PNG only)."""
    x, value = SINGLES[name]
    fig, ax = ts.figure(ts.FULL_WIDTH, 7.5)
    if value is None:
        panel_saturation(ax, diag, obs)
    else:
        panel_curve(ax, diag, obs, x, value)
    legend(fig, diag, band=value is not None)
    ts.save(fig, name, FIG_DIR, formats=('png',))
    return fig


def plot_all(diag=None, close=True):
    diag = load_diag() if diag is None else diag.assign(sc=diag.scenario.map(ts.SCENARIO_BY_NAME))
    obs = observed_base_year()
    figs = {'fig3_capture_price_rate': fig3(diag, obs)}
    figs.update({name: fig_single(diag, obs, name) for name in SINGLES})
    if close:
        for f in figs.values():
            ts.plt.close(f)
    return figs


if __name__ == '__main__':
    plot_all()

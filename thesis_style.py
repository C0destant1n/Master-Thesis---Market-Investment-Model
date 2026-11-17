# -*- coding: utf-8 -*-
"""
thesis_style.py -- one plotting style for every figure of the thesis (chapters 3 and 4).

Every plotting script imports colours, fonts, sizes and helpers from here; no script sets
its own colours or fonts. Plotting only: nothing here touches model or data.

    import thesis_style as ts
    fig, ax = ts.figure(ts.FULL_WIDTH, 7)
    ...
    ts.save(fig, 'fig3_capture_price_rate', folder)     # -> folder/fig3_capture_price_rate.pdf + .png
"""

import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
HSG_DARK = '#0B7A3A'    # result, central series
REF_GREY = '#898781'    # S1 status quo, references
GRID = '#D9D9D9'
INK = '#222222'         # text, observed market points
BASELINE = '#B5B3AE'    # reference lines (capture rate = 1, share = penetration, zero line)

# One source for all scripts: colour and label per scenario
# 'text' = colour of the direct label: same hue, darker where the line colour is too pale for 8 pt text
SCENARIOS = {
    'S1': {'color': REF_GREY,  'ls': '-', 'text': REF_GREY,  'label': 'S1 Status quo', 'name': 'Status quo (frozen)'},
    'S2': {'color': '#3D74B0', 'ls': '-', 'text': '#3D74B0', 'label': 'S2 NEP A',      'name': 'NEP 2037 A'},
    'S3': {'color': HSG_DARK,  'ls': '-', 'text': HSG_DARK,  'label': 'S3 NEP B',      'name': 'NEP 2037 B'},
    'S4': {'color': '#C8922A', 'ls': '-', 'text': '#A8771C', 'label': 'S4 NEP C',      'name': 'NEP 2037 C'},
}
# one hue per scenario: S1 grey (reference), S2 blue, S3 HSG green, S4 ochre
SCENARIO_BY_NAME = {v['name']: k for k, v in SCENARIOS.items()}   # 'NEP 2037 B' -> 'S3'

LW = 1.1            # line width of a scenario line (all scenarios the same; band edges 0.5)
MS = 3              # marker size (pt) at real model points
BAND_ALPHA = 0.16   # bands in the scenario colour (flexibility effect), light so overlaps stay visible

PEN_MAX = 60.0               # default end of the penetration axis, %
PEN_LABEL = 'Potential PV penetration (% of fixed load)'

# ---------------------------------------------------------------------------
# Fonts and sizes
# ---------------------------------------------------------------------------
CM = 1 / 2.54
FULL_WIDTH = 16.0    # cm
FS_AXES, FS_TICK, FS_LABEL = 9, 8, 8   # pt: axis labels, tick labels, direct labels

plt.rcParams.update({
    'font.family': 'serif',
    'font.serif': ['Times New Roman', 'Times', 'DejaVu Serif'],
    'mathtext.fontset': 'stix',
    'font.size': FS_LABEL,
    'axes.labelsize': FS_AXES,
    'axes.titlesize': FS_AXES,
    'xtick.labelsize': FS_TICK,
    'ytick.labelsize': FS_TICK,
    'legend.fontsize': FS_LABEL,
    'axes.linewidth': 0.6,
    'axes.edgecolor': INK,
    'axes.labelcolor': INK,
    'text.color': INK,
    'xtick.color': INK,
    'ytick.color': INK,
    'xtick.major.width': 0.6,
    'ytick.major.width': 0.6,
    'xtick.major.size': 3,
    'ytick.major.size': 3,
    'axes.spines.top': False,
    'axes.spines.right': False,
    'axes.grid': True,
    'axes.grid.axis': 'y',
    'axes.axisbelow': True,
    'grid.color': GRID,
    'grid.linewidth': 0.5,
    'lines.linewidth': LW,
    'lines.markersize': MS,
    'legend.frameon': False,
    'figure.constrained_layout.use': True,
    'figure.dpi': 100,
    'savefig.dpi': 300,
    'pdf.fonttype': 42,      # TrueType in the PDF: text stays text in Word
    'svg.fonttype': 'none',
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def figure(width_cm=FULL_WIDTH, height_cm=7.0, nrows=1, ncols=1, **kw):
    """New figure in thesis format (width 16 cm, height as needed, constrained layout)."""
    return plt.subplots(nrows, ncols, figsize=(width_cm * CM, height_cm * CM), layout='constrained', **kw)


def panel_letter(ax, letter):
    """(a), (b), ... bold, top left of the panel."""
    ax.set_title(f'({letter})', loc='left', fontsize=FS_AXES, fontweight='bold', pad=4)


def save(fig, name, folder, formats=('pdf', 'png')):
    """Save in folder: PDF (vector, for Word) and/or PNG 300 dpi; fixed size (no bbox_inches='tight')."""
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, name)
    for f in formats:
        fig.savefig(f'{out}.{f}', dpi=300 if f == 'png' else None)
    print(f'wrote {out}.' + ' / .'.join(formats))
    return out

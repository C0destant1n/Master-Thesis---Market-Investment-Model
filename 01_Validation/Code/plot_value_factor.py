"""
plot_value_factor.py -- Figure 2 of the thesis: PV value factor against PV penetration, model and observed, 2019-2025.

Reads Output/validation_YYYY.csv (validate.py), fits a line per series (2022 excluded) and writes
Figures/fig2_value_factor.png and .svg.

Run:  python plot_value_factor.py [folder with validation_YYYY.csv]
"""
import sys, os, glob
import numpy as np, pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

CODE = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(CODE)   # topic folder: Data/, Output/, Figures/
folder = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'Output')
v = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(os.path.join(folder, 'validation_20??.csv')))])
v = v[v.point == 'real']
m, o = (v[v.source == k].set_index('year').sort_index() for k in ('model', 'observed'))
year = list(m.index); inc = [0 if y == 2022 else 1 for y in year]
pen_m, pen_o = list(m.pv_share_load_pct), list(o.pv_share_load_pct)
vf_m, vf_o = list(m.capture_rate), list(o.capture_rate)
def fit(x, y):
    x = np.array([a for a, i in zip(x, inc) if i]); y = np.array([b for b, i in zip(y, inc) if i])
    k, d = np.polyfit(x, y, 1); return k, d, [x.min(), x.max()]
slope_m, dm, xm = fit(pen_m, vf_m); slope_o, do, xo = fit(pen_o, vf_o)
xl = [min(xm[0], xo[0]), max(xm[1], xo[1])]
fit_m = [slope_m * a + dm for a in xl]; fit_o = [slope_o * a + do for a in xl]
pen = pen_o

DARK, LIGHT, PALE, GRID = '#0B7A3A', '#7DC197', '#C9E4D3', '#D9D9D9'
plt.rcParams.update({'font.family': 'serif', 'font.serif': ['Times New Roman', 'Liberation Serif', 'DejaVu Serif'],
                     'font.size': 10, 'axes.linewidth': 0.8})
fig, ax = plt.subplots(figsize=(6.3, 3.3))              # 16 x 8.4 cm = full A4 text width, insert at 100% in Word
ax.grid(axis='y', color=GRID, lw=0.6); ax.set_axisbelow(True)
for s in ('top', 'right'): ax.spines[s].set_visible(False)
ax.plot(xl, fit_o, color=LIGHT, lw=1.6)
ax.plot(xl, fit_m, color=DARK, lw=1.6)
ax.scatter([p for p, i in zip(pen_o, inc) if i], [v for v, i in zip(vf_o, inc) if i], s=28, color=LIGHT, zorder=3)
ax.scatter([p for p, i in zip(pen_m, inc) if i], [v for v, i in zip(vf_m, inc) if i], s=28, color=DARK, zorder=4)
for p, v, i, y in zip(pen, vf_o, inc, year):
    if i == 0:                                           # crisis year: observed point only, pale
        ax.scatter([p], [v], s=28, color=PALE, zorder=2)
        ax.annotate(f'{y}, excluded', (p, v), xytext=(0, 9), textcoords='offset points', ha='center', fontsize=8.5, color='#666666')
lab = lambda s: f'−{abs(s):.3f} per pp'
ax.text(xl[1] + 0.3, fit_m[1] + 0.035, f'Model\n{lab(slope_m)}', fontsize=9, va='center', ha='left')
ax.text(xl[1] + 0.3, fit_o[1] + 0.005, f'Observed\n{lab(slope_o)}', fontsize=9, va='center', ha='left')
ax.set_xlim(8, 18.5); ax.set_xticks([8, 10, 12, 14, 16, 18])   # data span 8.5-16 %; room right for labels
ax.set_ylim(0.4, 1.0); ax.set_yticks([0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
ax.set_xlabel('PV penetration (% of total load)', fontsize=8.5)
ax.set_ylabel('PV value factor')
fig.tight_layout()
os.makedirs(os.path.join(HERE, 'Figures'), exist_ok=True)
out = os.path.join(HERE, 'Figures', 'fig2_value_factor')
fig.savefig(out + '.png', dpi=300); fig.savefig(out + '.svg')
print('written', out + '.png', 'slopes', round(slope_m, 4), round(slope_o, 4))

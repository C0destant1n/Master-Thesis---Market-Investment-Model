"""
bess_lever_hourly.py -- hourly prices of the break-even lever cases L1, N3 and N4 at the path anchors.

Solves each case once per anchor (weather year 2025) and saves the hourly price, storage-bid price and PV
output as input of bess_dispatch.py lever. Existing files are skipped.
Output: Output/hourly/<case>_<S>_pv<p>.parquet

Run:  python bess_lever_hourly.py      after ../../03_Sensitivity/Code/breakeven.py
"""
import os
import sys

import pandas as pd

CODE = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(CODE)   # topic folder: Data/, Output/, Figures/
sys.path.insert(0, os.path.join(HERE, '..', '03_Sensitivity', 'Code'))
import thresholds as t  # noqa: E402

s, v6 = t.s, t.v6
out = os.path.join(HERE, 'Output', 'hourly')
os.makedirs(out, exist_ok=True)
yi = v6.read_year_inputs([s.CONFIG['weather_year']])[s.CONFIG['weather_year']]
for name in ['bat_be', 'c3_be', 'c4_be']:   # L1 and N3 in Py_BESS_Lever; N4 kept for comparison
    case = next((c for c in t.CASES if c['name'] == name), None)
    if case is None:   # break-even not found in breakeven.py
        print(name, 'no break-even factor, skipped', flush=True)
        continue
    for sc, pi in t.ANCHORS:
        f = os.path.join(out, f'{name}_{sc}_pv{pi:g}.parquet')
        if os.path.exists(f):
            continue
        original = s.apply_case(case, sc)
        load = v6.build_load(yi, sc) * case.get('demand', 1.0)
        r = v6.run_point(sc, pi, yi, load, flex_factor=case.get('bat', 1.0),
                         keep_network=True, keep_price=True, save_hourly=False)
        n = r['network']
        _, _, p_sb = v6.hourly_price(n, yi['floor'])
        d = pd.DataFrame({'price': r['hourly_price'], 'price_sb': p_sb, 'pv': n.generators_t.p['DE0 Photovoltaics']})
        d.to_parquet(f)
        print(name, sc, pi, 'capture', (d.price * d.pv).sum() / d.pv.sum(), 'baseload', d.price.mean(), flush=True)
        v6.ASSUMPTIONS = original
        del r, n

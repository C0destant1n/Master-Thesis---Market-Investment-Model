# -*- coding: utf-8 -*-
"""
merchant_capture_price.py -- capture price of a new merchant PV plant from the hourly main run.

A new merchant plant gets no market premium and switches off at negative prices, so its revenue is
max(price, 0) x PV fed in. The script reads the hourly files of the main run (Output/hourly/) and writes
the mean over the weather years per scenario and penetration to Output/merchant_capture_price.csv
(column AB of Py_Main in the IRR model). No model run.

Run:  python merchant_capture_price.py
"""
import glob
import os
import re
import sys

import pandas as pd

CODE = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(CODE)   # topic folder: Data/, Output/, Figures/
sys.path.insert(0, CODE)
from PyPSA_model_v6 import SCENARIO_NAMES as NAMES  # noqa: E402  (same labels as Py_Main)
rows = []
for f in glob.glob(os.path.join(HERE, 'Output', 'hourly', '*_k1.csv.gz')):
    m = re.search(r'(S\d)_pv([\d.]+)_y(\d+)_k1', os.path.basename(f))
    d = pd.read_csv(f, usecols=['price', 'pv_fed'])
    w = d.pv_fed
    cp = (d.price * w).sum() / w.sum() if w.sum() > 0 else float('nan')
    cpm = (d.price.clip(lower=0) * w).sum() / w.sum() if w.sum() > 0 else float('nan')
    rows.append(dict(scenario_key=m.group(1), penetration_pct=float(m.group(2)), weather_year=int(m.group(3)),
                     capture_price=cp, capture_price_merchant=cpm))
r = pd.DataFrame(rows).groupby(['scenario_key', 'penetration_pct']).mean(numeric_only=True).reset_index()
main = pd.read_csv(os.path.join(HERE, 'Output', 'v6_results_long.csv'))
main = main.groupby(['scenario_key', 'penetration_pct']).capture_price.mean()
r['capture_price_merchant'] = r.apply(lambda x: main[(x.scenario_key, x.penetration_pct)]
                                      if pd.isna(x.capture_price_merchant) else x.capture_price_merchant, axis=1)
r['scenario'] = r.scenario_key.map(NAMES)
out = r[['penetration_pct', 'scenario', 'capture_price_merchant']].sort_values(['scenario', 'penetration_pct'])
out.round(4).to_csv(os.path.join(HERE, 'Output', 'merchant_capture_price.csv'), index=False)
print(out.round(2).head(8).to_string(index=False), '\nrows:', len(out))

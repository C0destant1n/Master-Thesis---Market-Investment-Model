"""
bess_dispatch.py -- revenue of a co-located battery (BESS) from hourly prices, aggregated for the IRR model.

Per 1 MWp PV the battery has RATIO MW, DURATION h and round-trip efficiency ETA, shares the grid connection
with the PV and makes at most one full cycle per day with perfect foresight: it charges in the cheapest and
discharges in the most expensive hours of each day. Green charges only from the own PV, grey also from the
grid. Output per scenario and penetration: full cycles, discharge price, charge cost and net margin per MWh
of battery capacity per year (real EUR 2025), mean over the weather years.

Structure:  fill, dispatch (daily optimisation) > run_model, run_observed, run_lever (the three modes)

Run:  python bess_dispatch.py            model prices of the main run -> Output/bess_dispatch_summary.csv
      python bess_dispatch.py observed   observed prices 2025         -> Output/bess_dispatch_observed_2025.csv
      python bess_dispatch.py lever      break-even cases L1 and N3   -> Output/bess_dispatch_lever.xlsx
"""
import glob
import json
import os
import re
import sys

import numpy as np
import pandas as pd

RATIO = 0.5       # MW BESS per MWp PV  (Excel Inputs_BESS D11; interviews E7, E17, E10)
DURATION = 2.0    # h                    (Excel Inputs_BESS D12)
ETA = 0.86        # round trip efficiency (Excel Inputs_BESS D14; Schmidt & Staffell 2023, Table 3.2)
CONNECTION = 1.0  # MW grid connection per MWp PV, shared by PV and BESS

CODE = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(CODE)   # topic folder: Data/, Output/, Figures/
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, 'Output')
MAIN = os.path.join(ROOT, '02_Main_Model', 'Output')            # main run: hourly files, v6_results_long.csv
SENS_HOURLY = os.path.join(ROOT, '03_Sensitivity', 'Output', 'hourly')   # base case + PV profile, weather year 2025
LEVER_HOURLY = os.path.join(OUT, 'hourly')                      # lever cases (bess_lever_hourly.py)
OBS = os.path.join(ROOT, '01_Validation', 'Output', 'validation_prices_2025.csv')
OBS_LABEL = 'Observed 2025 (SMARD)'
LEVER_LABELS = {'bat_be': 'L1 Batteries x {:.4g}', 'c3_be': 'N3 f = {:.4g} (without demand)'}   # rows of Py_BESS_Lever


def fill(price, cap, target, cheapest):
    """Fill `target` MWh per day (vector) from hours with per-hour caps, cheapest (or dearest) first.
    price, cap: arrays (days x hours). Returns (energy filled, money) per day."""
    order = np.argsort(price if cheapest else -price, axis=1, kind='stable')
    p = np.take_along_axis(price, order, axis=1)
    c = np.take_along_axis(cap, order, axis=1)
    before = np.cumsum(c, axis=1) - c
    take = np.clip(target[:, None] - before, 0.0, c)
    return take.sum(axis=1), (take * p).sum(axis=1)


def dispatch(price, pv, mode):
    """price, pv (per MWp): arrays days x 24. Returns dict of annual results per MWh of BESS energy."""
    P, E = RATIO, RATIO * DURATION
    days, H = price.shape
    ch_cap = np.minimum(P, pv) if mode == 'green' else np.full_like(price, P)
    ch_cost = np.maximum(price, 0.0) if mode == 'green' else price
    dis_cap = np.minimum(P, np.maximum(0.0, CONNECTION - pv))
    best = np.zeros(days); best_c = np.zeros(days); best_rev = np.zeros(days); best_cost = np.zeros(days)
    for s in range(1, H):
        # energy that can be stored before s and delivered from s on
        avail_c = ch_cap[:, :s].sum(axis=1)
        avail_d = dis_cap[:, s:].sum(axis=1)
        C = np.minimum(E, np.minimum(avail_c, avail_d / ETA))
        got_c, cost = fill(ch_cost[:, :s], ch_cap[:, :s], C, cheapest=True)
        got_d, rev = fill(price[:, s:], dis_cap[:, s:], C * ETA, cheapest=False)
        profit = rev - cost
        better = profit > best
        best = np.where(better, profit, best)
        best_c = np.where(better, got_c, best_c)
        best_rev = np.where(better, rev, best_rev)
        best_cost = np.where(better, cost, best_cost)
    charged, discharged = best_c.sum(), best_c.sum() * ETA
    return dict(cycles_per_year=charged / E,
                discharge_price=best_rev.sum() / discharged if discharged > 0 else np.nan,
                charge_cost=best_cost.sum() / charged if charged > 0 else np.nan,
                margin_per_mwh_discharged=best.sum() / discharged if discharged > 0 else np.nan,
                net_margin_per_mwh_cap=best.sum() / E)


def run_model():
    """Model prices of the main run, every scenario x penetration x weather year."""
    res = pd.read_csv(os.path.join(MAIN, 'v6_results_long.csv'))
    files = sorted(glob.glob(os.path.join(MAIN, 'hourly', '*.csv.gz')))
    rows = []
    for i, f in enumerate(files):
        m = re.match(r'(S\d)_pv([\d.]+)_y(\d{4})_k1\.csv\.gz$', os.path.basename(f))
        if not m:
            continue
        sc, pen, yr = m.group(1), float(m.group(2)), int(m.group(3))
        hit = res[(res.scenario_key == sc) & (np.isclose(res.penetration_pct, pen)) & (res.weather_year == yr)]
        if hit.empty or hit.pv_capacity_gw.iloc[0] <= 0:
            continue                       # 0 % penetration: no PV, no co-located BESS
        d = pd.read_csv(f, index_col=0, parse_dates=True)
        d = d[~((d.index.month == 2) & (d.index.day == 29))]       # 365 days
        n = len(d) // 24 * 24
        price = d['price'].to_numpy()[:n].reshape(-1, 24)
        pv = (d['pv_potential'].to_numpy()[:n] / (hit.pv_capacity_gw.iloc[0] * 1000.0)).reshape(-1, 24)
        row = dict(scenario_key=sc, scenario=hit.scenario.iloc[0], penetration_pct=pen, weather_year=yr)
        for mode in ('green', 'grey'):
            for k, v in dispatch(price, pv, mode).items():
                row[f'bess_{mode}_{k}'] = v
        rows.append(row)
        if i % 20 == 0:
            print(f'{i + 1}/{len(files)} {os.path.basename(f)}', flush=True)
    by_year = pd.DataFrame(rows).sort_values(['scenario_key', 'penetration_pct', 'weather_year'])
    by_year.to_csv(os.path.join(OUT, 'bess_dispatch_by_year.csv'), index=False)
    value_cols = [c for c in by_year.columns if c.startswith('bess_')]
    summ = by_year.groupby(['penetration_pct', 'scenario', 'scenario_key'], as_index=False)[value_cols].mean()
    summ.insert(3, 'weather_years', by_year.groupby(['penetration_pct', 'scenario', 'scenario_key']).size().values)
    summ['bess_ratio_mw_per_mwp'], summ['bess_duration_h'], summ['bess_eta'] = RATIO, DURATION, ETA
    summ.sort_values(['scenario', 'penetration_pct']).to_csv(os.path.join(OUT, 'bess_dispatch_summary.csv'), index=False)
    print('wrote', len(summ), 'rows ->', os.path.join(OUT, 'bess_dispatch_summary.csv'))


def run_observed():
    """Observed day-ahead prices 2025, PV profile of the main run (S1, today's penetration, weather year 2025)."""
    sys.path.insert(0, os.path.join(ROOT, '02_Main_Model', 'Code'))
    from PyPSA_model_v6 import CONFIG
    today = CONFIG['penetration_today']   # PV penetration 2025 (%), grid point of the main run
    p = pd.read_csv(OBS, index_col=0, parse_dates=True)['observed']
    h = pd.read_csv(os.path.join(MAIN, 'hourly', f'S1_pv{today:g}_y2025_k1.csv.gz'), index_col=0, parse_dates=True)
    res = pd.read_csv(os.path.join(MAIN, 'v6_results_long.csv'))
    cap = res[(res.scenario_key == 'S1') & np.isclose(res.penetration_pct, today) & (res.weather_year == 2025)].pv_capacity_gw.iloc[0]
    d = pd.DataFrame({'price': p}).join((h['pv_potential'] / (cap * 1000.0)).rename('pv'), how='inner')
    d = d[~((d.index.month == 2) & (d.index.day == 29))]
    n = len(d) // 24 * 24
    price = d['price'].to_numpy()[:n].reshape(-1, 24)
    pv = d['pv'].to_numpy()[:n].reshape(-1, 24)
    row = dict(penetration_pct=today, scenario=OBS_LABEL, scenario_key='OBS', weather_years=1)
    for mode in ('green', 'grey'):
        for k, v in dispatch(price, pv, mode).items():
            row[f'bess_{mode}_{k}'] = v
    row.update(bess_ratio_mw_per_mwp=RATIO, bess_duration_h=DURATION, bess_eta=ETA)
    # cross check: PV weighted observed price (should be close to the 2025 solar market value 45.08 EUR/MWh)
    cp = float((d['price'] * d['pv']).sum() / d['pv'].sum())
    pd.DataFrame([row]).to_csv(os.path.join(OUT, 'bess_dispatch_observed_2025.csv'), index=False)
    print('hours', len(d), '| observed baseload', round(d['price'].mean(), 2), '| PV weighted price', round(cp, 2))
    print({k: round(v, 1) for k, v in row.items() if k.startswith('bess_')})


def days_x_24(s):
    return s.to_numpy()[:len(s) // 24 * 24].reshape(-1, 24)


def lever_prices(case, sc, pen, rule):
    if case == 'base' and rule == 'storage bid':   # base storage-bid prices are in the main run files
        f = os.path.join(MAIN, 'hourly', f'{sc}_pv{pen:g}_y2025_k1.csv.gz')
        return pd.read_csv(f, index_col=0, parse_dates=True)['price_storage_bid']
    folder = SENS_HOURLY if case == 'base' else LEVER_HOURLY
    d = pd.read_parquet(os.path.join(folder, f'{case}_{sc}_pv{pen:g}.parquet'))
    return d['price_sb'] if rule == 'storage bid' else d['price']


def run_lever():
    """Break-even lever cases L1 and N3 at the path anchors (factors from ../03_Sensitivity/breakeven.py)."""
    sys.path.insert(0, os.path.join(ROOT, '03_Sensitivity', 'Code'))
    from thresholds import ANCHOR_PATH   # same anchors as the break-even run
    be = json.load(open(os.path.join(ROOT, '03_Sensitivity', 'Output', 'breakeven_factors.json')))
    cases = {'base': 'Base', **{k: v.format(be[k]['factor']) + f" ({be[k]['type']})" for k, v in LEVER_LABELS.items()
                                if be.get(k, {}).get('type') in ('break-even', 'plateau')}}   # case without a factor: left out
    pv = days_x_24(pd.read_parquet(os.path.join(SENS_HOURLY, 'pv_profile_2025.parquet'))['pv_mw_per_mw'])
    rows = []
    for rule in ('normal', 'storage bid'):
        for case, label in cases.items():
            for mode in ('grey', 'green'):
                row = dict(rule=rule, case=case, label=label, mode=mode)
                for k, (year, sc, pen) in enumerate(ANCHOR_PATH, 1):   # one column per anchor of the price path
                    p = days_x_24(lever_prices(case, sc, pen, rule))
                    row[f'A{k} {sc} {pen:g} %'] = dispatch(p, pv, mode)['net_margin_per_mwh_cap']
                rows.append(row)
    pd.DataFrame(rows).to_excel(os.path.join(OUT, 'bess_dispatch_lever.xlsx'), sheet_name='Py_BESS_Lever', index=False)
    print(pd.DataFrame(rows).round(0).to_string(index=False))


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'model'
    os.makedirs(OUT, exist_ok=True)
    {'model': run_model, 'observed': run_observed, 'lever': run_lever}[mode]()

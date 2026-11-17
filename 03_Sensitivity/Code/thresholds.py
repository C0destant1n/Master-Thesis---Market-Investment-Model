# -*- coding: utf-8 -*-
"""
thresholds.py -- price-path anchors, lever definitions and the lever cases at their multiplier.

Holds the five anchors of the price path of the IRR model (ANCHOR_PATH), the levers L1-L5 and the
combinations N1-N4 (BE_LEVERS), and solve(), which breakeven.py uses for every step. Run on its own after
breakeven.py, it writes the lever cases at their break-even or plateau multiplier.
Output: Output/thresholds.xlsx (sheet Py_Import_sens, same columns as sensitivities.xlsx),
checkpoint thresholds_long.csv.

Run:  python thresholds.py      after breakeven.py
"""

import gc
import json
import os
import sys
import time

import pandas as pd

import sensitivities as s

v6 = s.v6
# price path of the IRR model (Inputs_Price rows 17-21): operating year (COD 2025, 30 years: 2025-2054), scenario,
# PV penetration (% of the scenario's own fixed load; GW per %-pt: S1 5.4, S2 8.1, S3 9.4, S4 9.7):
#   2025 S1 15.94 % observed (~86 GW)
#   2030 S2 27.5 % (~222 GW; EEG 2023 §4 target 215 GW)
#   2037 S3 35 %   (~330 GW; NEP B 2037)
#   2045 S4 45 %   (~438 GW; NEP C 2045: 440 GW)
#   2054 S4 50 %   (~487 GW; no projection after 2045, further growth = cautious for the IRR)
# Between anchors the IRR model interpolates linearly.
# Change together with CONFIG['penetrations'] of sensitivities.py and ANCHORS of 04_BESS/plot_bess_path.py
ANCHOR_PATH = [(1, 'S1', 15.94), (6, 'S2', 27.5), (13, 'S3', 35.0), (21, 'S4', 45.0), (30, 'S4', 50.0)]
ANCHORS = list(dict.fromkeys((sc, pi) for _, sc, pi in ANCHOR_PATH))   # points to solve (no duplicates)
CHECKPOINT = os.path.join(s.CONFIG['out_dir'], 'thresholds_long.csv')


def combo(name, label, **levers):
    return dict(name=name, group='Threshold combinations', label=label, role='threshold', **levers)


def single(name, label, **levers):
    return dict(name=name, group='Threshold levers', label=label, role='threshold', **levers)


def breakeven(name, group, **levers):
    return dict(name=name, group=group, label='break-even', role='lever', **levers)


def same(f, *levers):
    """One factor f for all levers of a combination."""
    return {lever: f for lever in levers}


# lever combinations N1-N4 (names as in the IRR model and the thesis; case keys c1-c4 stay as Excel lookup keys)
N1 = ['bat', 'dsm']                              # N1 batteries + DSM
N2 = N1 + ['heat', 'elec', 'demand']             # N2 = N1 + heat + electrolysis + demand
N3 = N1 + ['heat', 'elec', 'co2']               # N3 = N1 + heat + electrolysis + CO2, no demand (no scarcity uplift)
N4 = N3 + ['demand']                           # N4 = N3 + demand
S23 = [sc for sc in s.CONFIG['scenarios'] if sc != 'S1']   # S1 has no DSM, power-to-heat or electrolysis
ALL = list(s.CONFIG['scenarios'])
# levers of breakeven.py = lever list of the IRR model (Dashboard, Sensitivity Table 4):
# name -> (group, levers moved by one factor f, scenarios); S1 has no DSM, PtH, electrolysis
BE_LEVERS = {'bat': ('L1 Batteries', ['bat'], ALL),
             'dsm': ('L2 DSM', ['dsm'], S23),
             'heat': ('L3a Sector coupling heat', ['heat'], S23),
             'elec': ('L3b Sector coupling electrolysis', ['elec'], S23),
             'demand': ('L4 Demand', ['demand'], ALL),
             'co2': ('L5 CO2 price', ['co2'], ALL),
             'c1': ('N1 Batteries + DSM', N1, ALL),
             'c2': ('N2 N1 + heat + electrolysis + demand', N2, ALL),
             'c3': ('N3 N1 + heat + electrolysis + CO2', N3, ALL),
             'c4': ('N4 N3 + demand', N4, ALL)}

# multiplier per lever (break-even or plateau), found by breakeven.py and saved in BE_FILE;
# the case <lever>_be uses that multiplier (left out before the file exists)
BE_FILE = os.path.join(s.CONFIG['out_dir'], 'breakeven_factors.json')
BE_FACTORS = json.load(open(BE_FILE)) if os.path.exists(BE_FILE) else {}
CASES = [dict(breakeven(f'{k}_be', g, **same(BE_FACTORS[f'{k}_be']['factor'], *lv)), scenarios=sc,
              label=BE_FACTORS[f'{k}_be']['type'])
         for k, (g, lv, sc) in BE_LEVERS.items()
         if BE_FACTORS.get(f'{k}_be', {}).get('type') in ('break-even', 'plateau')]


def solve(case, sc, pi, yi):
    """One solve of a case; returns its result row."""
    original = s.apply_case(case, sc)
    try:
        load = v6.build_load(yi, sc) * case.get('demand', 1.0)
        r = v6.run_point(sc, pi, yi, load, flex_factor=case.get('bat', 1.0),
                         keep_network=True, keep_price=True, save_hourly=False)
        n, w = r['network'], r['weights']
        _, _, price_sb = v6.hourly_price(n, yi['floor'])
        out = s.row(case, sc, pi, r['hourly_price'], price_sb, w, r, s.levels(case, sc, n, r))
        del r, n
        gc.collect()   # frees the solved network before the next run (limited RAM)
        return out
    finally:
        v6.ASSUMPTIONS = original


def run():
    yi = v6.read_year_inputs([s.CONFIG['weather_year']])[s.CONFIG['weather_year']]
    rows = pd.read_csv(CHECKPOINT).to_dict('records') if os.path.exists(CHECKPOINT) else []
    done = {(x['case'], x['scenario_key'], x['penetration_pct']) for x in rows}
    failed, start = [], time.time()
    for case in CASES:
        for sc, pi in [a for a in ANCHORS if a[0] in case.get('scenarios', s.CONFIG['scenarios'])]:
            if (case['name'], sc, pi) in done:
                continue
            t = time.time()
            print(f'{case["name"]}: {sc}, PV {pi} %', flush=True)
            try:
                rows.append(solve(case, sc, pi, yi))
            except Exception as e:   # not optimal or solver error: log it, go on with the next point
                print(f'FAILED {case["name"]} {sc} {pi}: {e}', flush=True)
                failed.append(dict(case=case['name'], scenario_key=sc, penetration_pct=pi, error=str(e)))
                continue
            pd.DataFrame(rows).to_csv(CHECKPOINT, index=False)
            print(f'  done in {time.time() - t:.0f} s', flush=True)
    print(f'\nrun time {(time.time() - start) / 3600:.1f} h, {len(failed)} failed point(s)')
    pd.DataFrame(failed, columns=['case', 'scenario_key', 'penetration_pct', 'error']).to_csv(
        os.path.join(s.CONFIG['out_dir'], 'thresholds_failed.csv'), index=False)
    return pd.DataFrame(rows)


def write_outputs(long):
    py_cols = ['case', 'group', 'label', 'scenario_key', 'scenario', 'penetration_pct', 'capture_price',
               'baseload_price', 'capture_rate', 'capture_price_storage_bid', 'capture_rate_storage_bid',
               'pv_share_load_pct', 'pv_gw', 'pv_twh', 'role']
    unit_cols = ['case', 'scenario_key', 'co2_price', 'gas_price', 'small_batteries_gw', 'small_batteries_gwh',
                 'large_batteries_gw', 'large_batteries_gwh', 'dsm_gw', 'pth_gw', 'pth_twh_max', 'electrolysis_gw',
                 'fixed_load_twh']
    base = pd.read_csv(s.CHECKPOINT).query("case == 'base'")
    units = pd.concat([base, long])[unit_cols].drop_duplicates(['case', 'scenario_key'])
    # absolute values per case and scenario (same at all penetrations of a scenario)
    cases = pd.DataFrame([{k: (str(v) if isinstance(v, (dict, list)) else v) for k, v in c.items()} for c in CASES])
    path = os.path.join(s.CONFIG['out_dir'], 'thresholds.xlsx')
    with pd.ExcelWriter(path) as writer:
        long[py_cols].round(4).to_excel(writer, sheet_name='Py_Import_sens', index=False)
        long.round(4).to_excel(writer, sheet_name='all', index=False)
        units.round(2).to_excel(writer, sheet_name='units', index=False)
        cases.to_excel(writer, sheet_name='cases', index=False)
    print(f'wrote {path}')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        yi = v6.read_year_inputs([s.CONFIG['weather_year']])[s.CONFIG['weather_year']]
        x = solve(CASES[0], 'S2', 27.5, yi)
        print({k: x[k] for k in ['case', 'scenario_key', 'penetration_pct', 'capture_price', 'baseload_price', 'co2_price']})
        sys.exit()
    write_outputs(run())

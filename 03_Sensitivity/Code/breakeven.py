# -*- coding: utf-8 -*-
"""
breakeven.py -- multiplier per lever at which the Utility equity IRR reaches the hurdle (12.25 %), or its plateau.

For each lever the factor climbs a ladder (x1.1 ... x20). Every step solves the path anchors
(thresholds.solve) and computes the equity IRR with the Python replica of the IRR model
(05_IRR_Model/Code/irr_replica.py). If the IRR crosses the hurdle, regula falsi between the last two steps
gives the break-even; if it stops rising (gain < PLATEAU_PP per step from x2 on), the lower step is the plateau.
Output: Output/breakeven_factors.json (multiplier per lever), breakeven_steps.csv (every step),
rows <lever>_be in thresholds_long.csv.

Structure:  load_replica, eirr > step (one ladder step) > find_multiplier (one lever) > main

Run:  python breakeven.py      after the main run, merchant_capture_price.py and sensitivities.py
"""

import json
import os
import sys
import time

import pandas as pd

import thresholds as t

s, v6 = t.s, t.v6
IRR_DIR = os.path.join(s.ROOT, '05_IRR_Model', 'Code')
sys.path.insert(0, IRR_DIR)
import irr_replica as R  # noqa: E402

XLSX = R.XLSX   # IRR model (COD 2025, 5-anchor path), inputs read only
FEAS = os.path.join(s.ROOT, '02_Main_Model', 'Output')
HURDLE, TOL = 0.1225, 0.0005          # accept 12.25 % <= IRR < 12.30 %
PLATEAU_PP = 0.10                     # IRR gain below 0.10 %-points per ladder step = plateau
PLATEAU_FROM = 2.0                    # plateau test from x2 on (the small first steps may start slowly)
LADDER = [1.1, 1.25, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 15.0, 20.0]
MAX_REFINE = 6
LONG = t.CHECKPOINT
STEPS = os.path.join(s.CONFIG['out_dir'], 'breakeven_steps.csv')


def rows():
    return pd.read_csv(LONG) if os.path.exists(LONG) else pd.DataFrame(columns=['case', 'scenario_key', 'penetration_pct'])


def save(new_rows):
    pd.concat([rows(), pd.DataFrame(new_rows)]).to_csv(LONG, index=False)


def load_replica():
    """Inputs of the IRR model, but anchors, Py_Main and Py_Sens base from the current Python run."""
    R.SCEN.update({i: name for i, name in enumerate(v6.SCENARIO_NAMES.values(), 1)})   # index as in Inputs_Price D30:D33
    R.load(XLSX)
    R.ANCH[:] = [(year, pi, v6.SCENARIO_NAMES[sc]) for year, sc, pi in t.ANCHOR_PATH]   # anchors of this run
    merchant = pd.read_csv(os.path.join(FEAS, 'merchant_capture_price.csv'))
    curt = pd.read_csv(os.path.join(FEAS, 'v6_results_long.csv'))
    curt = curt.groupby(['scenario', 'penetration_pct']).curtailment_pct.mean()
    R.MAIN.clear()
    for r in merchant.itertuples():
        R.MAIN[(r.scenario, float(r.penetration_pct))] = dict(cp=r.capture_price_merchant,
                                                              curt=curt[(r.scenario, r.penetration_pct)])
    base = pd.read_csv(s.CHECKPOINT).query("case == 'base'")
    R.SENS.clear()
    for r in base.itertuples():
        R.SENS[('base', r.scenario, float(r.penetration_pct))] = r.capture_price


def eirr(name):
    """Utility equity IRR of a case from the checkpoint."""
    d = rows()
    d = d[d.case == name]
    extra = {(name, sc, float(pi)): cp for sc, pi, cp in zip(d.scenario, d.penetration_pct, d.capture_price)}
    return R.model(name, extra)['eirr']


def step(key, levers, scenarios, f, yi, log):
    """Solves the anchors of lever key at factor f (skips points already saved); returns the equity IRR."""
    f = round(f, 4)
    case = dict(t.combo(f'{key}_f{f:.4f}', f'{key} f = {f:.4f}', **t.same(f, *levers)), scenarios=scenarios)
    for sc, pi in t.ANCHORS:
        d = rows()
        if sc not in scenarios or ((d.case == case['name']) & (d.scenario_key == sc) & (d.penetration_pct == pi)).any():
            continue
        tt = time.time()
        print(f'{case["name"]}: {sc}, PV {pi} %', flush=True)
        save([t.solve(case, sc, pi, yi)])
        print(f'  done in {time.time() - tt:.0f} s', flush=True)
    irr = eirr(case['name'])
    log.append(dict(lever=key, factor=f, equity_irr_pct=round(irr * 100, 3)))
    print(f'{key}: f = {f:.4f} -> equity IRR {irr * 100:.3f} %', flush=True)
    return f, irr, case['name']


def find_multiplier(key, yi, base_irr, log):
    """Ladder up to break-even or plateau; returns (type, factor, case name of that step)."""
    group, levers, scenarios = t.BE_LEVERS[key]
    prev_f, prev_irr, prev_name = 1.0, base_irr, 'base'
    for f in LADDER:
        f, irr, name = step(key, levers, scenarios, f, yi, log)
        if 0 <= irr - HURDLE < TOL:
            return 'break-even', f, name
        if irr >= HURDLE:   # crossed between prev_f and f: regula falsi
            lo, hi = (prev_f, prev_irr), (f, irr)
            for _ in range(MAX_REFINE):
                x = lo[0] + (HURDLE + TOL / 2 - lo[1]) * (hi[0] - lo[0]) / (hi[1] - lo[1])
                x, ix, nx = step(key, levers, scenarios, x, yi, log)
                if 0 <= ix - HURDLE < TOL:
                    return 'break-even', x, nx
                lo, hi = ((x, ix), hi) if ix < HURDLE else (lo, (x, ix))
            return 'break-even', hi[0], f'{key}_f{hi[0]:.4f}'   # closest step above the hurdle
        if prev_f >= PLATEAU_FROM and (irr - prev_irr) * 100 < PLATEAU_PP:
            return 'plateau', prev_f, prev_name
        prev_f, prev_irr, prev_name = f, irr, name
    return 'plateau', prev_f, prev_name   # top of the ladder, still growing


def main():
    load_replica()
    base_irr = R.model('base')['eirr']
    print(f'base case equity IRR {base_irr * 100:.3f} %', flush=True)
    yi = v6.read_year_inputs([s.CONFIG['weather_year']])[s.CONFIG['weather_year']]
    factors = json.load(open(t.BE_FILE)) if os.path.exists(t.BE_FILE) else {}
    log = pd.read_csv(STEPS).to_dict('records') if os.path.exists(STEPS) else []
    start = time.time()
    for key, (group, _, _) in t.BE_LEVERS.items():
        be_name = f'{key}_be'
        if be_name in factors:
            continue
        try:
            kind, f, name = find_multiplier(key, yi, base_irr, log)
        except Exception as e:   # solver error: log it, go on with the next lever
            print(f'FAILED {key}: {e}', flush=True)
            continue
        finally:
            pd.DataFrame(log).to_csv(STEPS, index=False)
        if name == 'base':
            print(f'{key}: no effect at the first step, nothing saved', flush=True)
            factors[be_name] = dict(type='no effect', factor=1.0, equity_irr_pct=round(base_irr * 100, 3))
        else:
            be = rows().query('case == @name').assign(case=be_name, group=group, label=kind, role='lever')
            save(be.to_dict('records'))
            factors[be_name] = dict(type=kind, factor=f, equity_irr_pct=round(eirr(be_name) * 100, 3))
        json.dump(factors, open(t.BE_FILE, 'w'), indent=1)
        print(f'{be_name}: {factors[be_name]}', flush=True)
    print(f'run time {(time.time() - start) / 3600:.1f} h', flush=True)


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""
sensitivities.py -- robustness cases of the market model at the anchors of the price path.

Each case changes one input or price rule against the base case (= main model): gas and hydrogen price,
electrolysis capacity, covered price, negative price floor, import capacity and ramp markup. Grid: path
scenarios x penetrations x weather year 2025; price-rule cases are evaluated on the base solves. The case
functions (apply_case, row) are also used by thresholds.py and breakeven.py.
Output: Output/sensitivities.xlsx (sheet Py_Import_sens), checkpoint sensitivities_long.csv.

Structure:
  CONFIG, CASES               grid and case definitions
  case_values, apply_case     temporary changes to the ASSUMPTIONS of the model
  run_grid                    solves with checkpoint
  check_base, write_outputs   check against the main run, Excel output

Run:  python sensitivities.py      (a restart skips finished points)
"""

import gc
import os
import sys
import time

import numpy as np
import pandas as pd

CODE = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(CODE)   # topic folder: Data/, Output/, Figures/
ROOT = os.path.join(HERE, '..')
sys.path.insert(0, os.path.join(ROOT, '02_Main_Model', 'Code'))
import PyPSA_model_v6 as v6  # noqa: E402

CONFIG = {
    'scenarios':         ['S1', 'S2', 'S3', 'S4'],   # scenarios on the price path of the IRR Excel (one per anchor, 03_Sensitivity/thresholds.py)
    'penetrations':      [15.94, 27.5, 35.0, 45.0, 50.0],   # % of fixed load, as main run; = path anchors (03_Sensitivity/thresholds.py)
    'weather_year':      2025,                    # weather spread in the main run is small (1-7 EUR)
    'report_pv':         [33.4, 37.2],            # capture rate table, interpolated between grid points
    'hourly_cases':      ['base'],  # hourly prices saved (BESS at the PV site, later)
    'out_dir':           os.path.join(HERE, 'Output'),
}
CHECKPOINT = os.path.join(CONFIG['out_dir'], 'sensitivities_long.csv')

# Cases: name, group (lever family), label, role (lever = what it takes, robustness = risk / model rule),
# what changes: co2 / gas = factor on the price, bat = factor on all batteries (home + large),
# dsm = factor on shiftable DSM, heat = factor on power-to-heat capacity and energy, elec = factor on
# electrolysis capacity, demand = factor on the fixed load, set = absolute values, rules = ex-post price rules
NEP = [sc for sc in v6.SCENARIO_NAMES if sc != 'S1']   # S1 has no DSM, power-to-heat or electrolysis
CASES = [
    dict(name='base',          group='base',             label='base', role='base'),
    dict(name='co2_x1.5',      group='CO2 price',        label='x 1.5', role='lever', co2=1.5),
    dict(name='co2_x2',        group='CO2 price',        label='x 2', role='lever', co2=2.0),
    # batteries only (home + large) x k, DSM unchanged: the value of storage alone
    dict(name='bat_k1.5',      group='Batteries',        label='x 1.5', role='lever', bat=1.5),
    dict(name='bat_k2',        group='Batteries',        label='x 2', role='lever', bat=2.0),
    # shiftable industrial demand x 2, batteries unchanged: the value of DSM alone (S1 has no DSM)
    dict(name='dsm_x2',        group='DSM',              label='x 2', role='lever', dsm=2.0, scenarios=NEP),
    # heat_x2 = additional electrified district heating that replaces gas boilers: new flexible demand up to
    # 2 x energy.PtH (capacity x 2 as well), bid stays at gas-boiler parity, fixed load unchanged so the
    # penetration axis stays the same (S1 has no power-to-heat)
    dict(name='heat_x2',       group='Sector coupling',  label='heat x 2', role='lever', heat=2.0, scenarios=NEP),
    # data centres and electrification: fixed load x 1.1 / x 1.2, same load shape; PV capacity per
    # penetration point rises with the load (penetration = potential PV / fixed load)
    dict(name='demand_x1.1',   group='Demand',           label='x 1.1', role='lever', demand=1.1),
    dict(name='demand_x1.2',   group='Demand',           label='x 1.2', role='lever', demand=1.2),
    # nested combinations, each adds levers to the previous one (S1: only the levers that exist there)
    dict(name='combo_bat_dsm', group='Combinations',     label='batteries + DSM', role='lever', bat=2.0, dsm=2.0,
         scenarios=NEP, same_as={'S1': 'bat_k2'}),
    dict(name='combo_flex',    group='Combinations',     label='+ heat + demand', role='lever', bat=2.0, dsm=2.0,
         heat=2.0, demand=1.2),
    dict(name='combo_all',     group='Combinations',     label='+ CO2 x 2', role='lever', bat=2.0, dsm=2.0,
         heat=2.0, demand=1.2, co2=2.0),
    # the two combinations above with electrolysis x 2 as an extra lever (S1 has no electrolysis: same system as without)
    dict(name='combo_flex_elec', group='Combinations', label='+ heat + elec + demand', role='lever', bat=2.0,
         dsm=2.0, heat=2.0, elec=2.0, demand=1.2, scenarios=NEP, same_as={'S1': 'combo_flex'}),
    dict(name='combo_all_elec', group='Combinations', label='+ CO2 x 2 (with elec)', role='lever', bat=2.0,
         dsm=2.0, heat=2.0, elec=2.0, demand=1.2, co2=2.0, scenarios=NEP, same_as={'S1': 'combo_all'}),
    dict(name='gas_low',       group='Gas + H2 price',   label='-30 %', role='robustness', gas=0.7),
    dict(name='gas_high',      group='Gas + H2 price',   label='+30 %', role='robustness', gas=1.3),
    # risk: only half the NEP electrolysis capacity is built, bid unchanged
    dict(name='elec_x0.5',     group='Electrolysis capacity', label='x 0.5', role='robustness', elec=0.5,
         scenarios=NEP),
    dict(name='covered_0',     group='Covered price',    label='0 EUR', role='robustness', rules=dict(covered_price=0.0)),
    dict(name='covered_20',    group='Covered price',    label='20 EUR', role='robustness', rules=dict(covered_price=20.0)),
    dict(name='floor_0',       group='Negative floor',   label='x 0', role='robustness', rules=dict(floor_factor=0.0)),
    dict(name='floor_x2',      group='Negative floor',   label='x 2', role='robustness', rules=dict(floor_factor=2.0)),
    dict(name='import_0',      group='Import',           label='0 GW', role='robustness', set={'cap.Import': 0.0}),
    dict(name='ramp_0',        group='Ramp markup',      label='0', role='robustness', rules=dict(ramp_markup=0.0)),
    dict(name='ramp_x2',       group='Ramp markup',      label='x 2', role='robustness', rules=dict(ramp_markup=0.05)),
]
# final run (2026-11-09): only base + robustness cases; the lever question is answered by breakeven.py
CASES = [c for c in CASES if c['role'] in ('base', 'robustness')]
# CO2 and gas move the bids that depend on them, so each scenario stays consistent (sources in
# v6.ASSUMPTIONS): power-to-heat bid = gas boiler = (gas + CO2 x 0.201) / 0.9; electrolysis bid = H2 x 0.7

# interaction check: combination vs product of its parts (capture rate ratios to base); nested
INTERACTIONS = {'combo_bat_dsm': ['bat_k2', 'dsm_x2'],
                'combo_flex':    ['combo_bat_dsm', 'heat_x2', 'demand_x1.2'],
                'combo_all':     ['combo_flex', 'co2_x2']}


# ---------------------------------------------------------------------------
# Case setup: temporary changes to v6.ASSUMPTIONS
# ---------------------------------------------------------------------------


def case_values(case, sc):
    """{parameter: new value} of a case for scenario sc."""
    par = lambda p: v6.par(sc, p)   # noqa: E731
    values = dict(case.get('set', {}))
    if 'co2' in case:
        co2 = par('co2_price') * case['co2']
        values['co2_price'] = co2
        if par('wtp.PtH') is not None:
            values['wtp.PtH'] = par('wtp.PtH') + (co2 - par('co2_price')) * 0.201 / 0.9
    if 'gas' in case:
        gas = par('fuel.Natural gas') * case['gas']
        values['fuel.Natural gas'] = gas
        if par('fuel.Hydrogen') is not None:
            values['fuel.Hydrogen'] = par('fuel.Hydrogen') * case['gas']
        if par('wtp.PtH') is not None:
            values['wtp.PtH'] = par('wtp.PtH') + (gas - par('fuel.Natural gas')) / 0.9
        if par('wtp.Electrolysis') is not None:
            values['wtp.Electrolysis'] = par('wtp.Electrolysis') * case['gas']
    if par('shift.DSM') is not None and ('bat' in case or 'dsm' in case):
        values['shift.DSM'] = par('shift.DSM') * case.get('dsm', 1.0) / case.get('bat', 1.0)
        # run_point scales batteries and DSM together by flex_factor = bat; dividing by bat keeps DSM at its own factor
    if 'heat' in case and par('flex.PtH') is not None:
        values['flex.PtH'] = par('flex.PtH') * case['heat']
        values['energy.PtH'] = par('energy.PtH') * case['heat']
    if 'elec' in case and par('flex.Electrolysis') is not None:
        values['flex.Electrolysis'] = par('flex.Electrolysis') * case['elec']
    return values


def apply_case(case, sc):
    """Writes the case changes for scenario sc into v6.ASSUMPTIONS; returns the original table."""
    original = v6.ASSUMPTIONS.copy()
    A = v6.ASSUMPTIONS
    for p, v in case_values(case, sc).items():
        hit = (A.scenario == sc) & (A.parameter == p)
        if hit.any():
            A.loc[hit, 'value'] = v
        else:
            A.loc[len(A)] = (sc, p, v, '', f'sensitivity {case["name"]}')
    return original


def levels(case, sc, n, r):
    """Absolute values of the run (case_levels sheet): what the case means in EUR, GW, GWh and TWh."""
    par = lambda p, d=0.0: v6.par(sc, p, d)   # noqa: E731
    k = case.get('bat', 1.0)
    use = lambda name: float(-n.generators_t.p.get(f'DE0 Flex {name}', pd.Series(0.0)).sum() / 1e6)   # noqa: E731
    return dict(co2_price=par('co2_price'), gas_price=par('fuel.Natural gas'),
                small_batteries_gw=par('cap.small-batteries') * k,
                small_batteries_gwh=par('cap.small-batteries') * k * par('hours.small-batteries'),
                large_batteries_gw=par('cap.large-batteries') * k,
                large_batteries_gwh=par('cap.large-batteries') * k * par('hours.large-batteries'),
                dsm_gw=r['dsm_gw'], pth_gw=par('flex.PtH'), pth_twh_max=par('energy.PtH'), pth_twh_used=use('PtH'),
                electrolysis_gw=par('flex.Electrolysis'), electrolysis_twh_used=use('Electrolysis'),
                fixed_load_twh=r['annual_load_twh'])


def row(case, sc, pi, price, price_sb, w, r, lev):
    """One result row: capture price / rate for the main price and the storage-bid price."""
    cp, cp_sb = (price * w).sum() / w.sum(), (price_sb * w).sum() / w.sum()
    return dict(case=case['name'], group=case['group'], label=case['label'], scenario_key=sc,
                scenario=v6.SCENARIO_NAMES[sc], penetration_pct=pi,
                capture_price=cp, baseload_price=price.mean(), capture_rate=cp / price.mean(),
                capture_price_storage_bid=cp_sb, capture_rate_storage_bid=cp_sb / price_sb.mean(),
                pv_share_load_pct=r['pv_share_load_pct'], pv_gw=r['pv_capacity_gw'], pv_twh=float(w.sum() / 1e6),
                role=case['role'], curtailment_pct=r['curtailment_pct'],
                hours_price_le_zero_pct=float(100 * (price <= 0).mean()),
                hours_import_pct=r['hours_import_pct'], hours_voll_pct=r['hours_voll_pct'], **lev)
    # pv_twh: PV fed in (after curtailment), TWh


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def run_grid():
    """Solves every case on the grid; price-rule cases are computed from the base solves.
    Every point is saved at once, so a restart skips the finished points."""
    yi = v6.read_year_inputs([CONFIG['weather_year']])[CONFIG['weather_year']]
    solved = [c for c in CASES if 'rules' not in c]
    ex_post = [c for c in CASES if 'rules' in c]
    rows = pd.read_csv(CHECKPOINT).to_dict('records') if os.path.exists(CHECKPOINT) else []
    done = {(x['case'], x['scenario_key'], round(x['penetration_pct'], 2)) for x in rows}
    hourly = os.path.join(CONFIG['out_dir'], 'hourly')
    os.makedirs(hourly, exist_ok=True)
    yi['pu'][['Photovoltaics']].rename(columns={'Photovoltaics': 'pv_mw_per_mw'}).to_parquet(
        os.path.join(hourly, f'pv_profile_{CONFIG["weather_year"]}.parquet'))
    # normalised PV profile (MW per MW installed) of the weather year
    total = sum(len(set(c.get('scenarios', CONFIG['scenarios'])) & set(CONFIG['scenarios']))
                for c in solved) * len(CONFIG['penetrations'])
    failed, i, start = [], 0, time.time()
    for case in solved:
        for sc in [s for s in case.get('scenarios', CONFIG['scenarios']) if s in CONFIG['scenarios']]:
            original = apply_case(case, sc)
            load = v6.build_load(yi, sc) * case.get('demand', 1.0)
            for pi in CONFIG['penetrations']:
                i += 1
                missing = [rc for rc in ex_post if (rc['name'], sc, pi) not in done] if case['name'] == 'base' else []
                rerun = (case['name'], sc, pi) in done   # base saved but ex-post cases missing: re-solve, add only those
                if rerun and not missing:
                    continue
                t = time.time()
                print(f'{case["name"]}: {sc}, PV {pi} %, {i}/{total}', flush=True)
                try:
                    r = v6.run_point(sc, pi, yi, load, flex_factor=case.get('bat', 1.0),
                                     keep_network=True, keep_price=True, save_hourly=False)
                except Exception as e:   # not optimal or solver error: log it, go on with the next point
                    print(f'FAILED {case["name"]} {sc} {pi}: {e}', flush=True)
                    failed.append(dict(case=case['name'], scenario_key=sc, penetration_pct=pi, error=str(e)))
                    continue
                n, w = r['network'], r['weights']
                _, _, price_sb = v6.hourly_price(n, yi['floor'])
                lev = levels(case, sc, n, r)
                if not rerun:
                    rows.append(row(case, sc, pi, r['hourly_price'], price_sb, w, r, lev))
                if case['name'] == 'base':
                    for rc in missing:
                        # price-rule variants: same dispatch, other ex-post rule
                        price, _, price_sb = v6.hourly_price(n, yi['floor'], rc['rules'])
                        rows.append(row(rc, sc, pi, price, price_sb, w, r, lev))
                if case['name'] in CONFIG['hourly_cases'] and not rerun:
                    r['hourly_price'].rename('price').to_frame().to_parquet(
                        os.path.join(hourly, f'{case["name"]}_{sc}_pv{pi:g}.parquet'))
                pd.DataFrame(rows).to_csv(CHECKPOINT, index=False)
                print(f'  done in {time.time() - t:.0f} s', flush=True)
                del r, n
                gc.collect()   # frees the solved network before the next run (limited RAM)
            v6.ASSUMPTIONS = original
    long = pd.DataFrame(rows)
    for case in CASES:
        for sc, source in case.get('same_as', {}).items():
            # same system as another case in this scenario (e.g. S1 has no DSM): copy instead of solving again
            copy = long[(long.case == source) & (long.scenario_key == sc)].assign(
                case=case['name'], group=case['group'], label=case['label'], role=case['role'])
            long = pd.concat([long[~((long.case == case['name']) & (long.scenario_key == sc))], copy])
    print(f'\nrun time {(time.time() - start) / 3600:.1f} h, {len(failed)} failed point(s)')
    pd.DataFrame(failed, columns=['case', 'scenario_key', 'penetration_pct', 'error']).to_csv(
        os.path.join(CONFIG['out_dir'], 'failed.csv'), index=False)
    return long.reset_index(drop=True), pd.DataFrame(failed)


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


def check_base(long):
    """Base case must reproduce the main run (same model, same points, weather year); limit 0.5 %."""
    f = os.path.join(ROOT, '02_Main_Model', 'Output', 'v6_results_long.csv')
    if not os.path.exists(f):
        return
    main = pd.read_csv(f)
    main = main[main.weather_year == CONFIG['weather_year']].assign(
        capture_rate=lambda d: d.capture_price / d.baseload_price)
    b = long[long.case == 'base'].merge(main[['scenario_key', 'penetration_pct', 'capture_price', 'capture_rate']],
                                        on=['scenario_key', 'penetration_pct'], suffixes=('', '_main'))
    for c in ['capture_price', 'capture_rate']:
        dev = 100 * (b[c] / b[f'{c}_main'] - 1).abs()
        print(f'base check {c}: max deviation from main run {dev.max():.3f} % ({len(b)} points)')
        for _, x in b[dev > 0.5].iterrows():
            print(f'  ABOVE 0.5 %: {x.scenario_key} PV {x.penetration_pct} %: {x[c]:.3f} vs {x[f"{c}_main"]:.3f}')


def interaction_check(long):
    """Capture rate of each combination vs the product of its parts, all as ratios to base.
    A part that does not exist in a scenario (e.g. DSM in S1) counts as ratio 1."""
    cr = long.set_index(['case', 'scenario_key', 'penetration_pct']).capture_rate
    out = []
    for combo, parts in INTERACTIONS.items():
        for sc, pi in long[long.case == combo][['scenario_key', 'penetration_pct']].itertuples(index=False):
            base = cr.get(('base', sc, pi), np.nan)
            product = np.prod([cr.get((p, sc, pi), base) / base for p in parts])
            out.append(dict(combo=combo, parts=' x '.join(parts), scenario_key=sc, penetration_pct=pi,
                            capture_rate_base=base, capture_rate_combo=cr[(combo, sc, pi)],
                            ratio_combo=cr[(combo, sc, pi)] / base, ratio_product_of_parts=product))
    out = pd.DataFrame(out)
    if len(out):
        out['difference_pct'] = 100 * (out.ratio_combo / out.ratio_product_of_parts - 1)
        # small difference -> multiplying the single-lever ratios in Excel is fine
    return out


def at_report_pv(long):
    """Capture rate at the report penetrations, linear between the two neighbouring grid points."""
    out = []
    for (case, sc), d in long.groupby(['case', 'scenario_key'], sort=False):
        d = d.sort_values('penetration_pct')
        out.append(dict(case=case, scenario_key=sc, **{f'capture_rate_at_{p:g}': np.interp(
            p, d.penetration_pct, d.capture_rate) for p in CONFIG['report_pv']}))
    return pd.DataFrame(out)


def write_outputs(long):
    order = {c['name']: i for i, c in enumerate(CASES)}
    long = long.sort_values(['case', 'scenario_key', 'penetration_pct'],
                            key=lambda s: s.map(order) if s.name == 'case' else s).reset_index(drop=True)
    base = long[long.case == 'base'].set_index(['scenario_key', 'penetration_pct'])
    idx = pd.MultiIndex.from_frame(long[['scenario_key', 'penetration_pct']])
    for c in ['capture_price', 'capture_rate', 'capture_price_storage_bid']:
        long[f'delta_{c}'] = long[c] - base[c].reindex(idx).to_numpy()
    long = long.round(4)
    os.makedirs(CONFIG['out_dir'], exist_ok=True)
    path = os.path.join(CONFIG['out_dir'], 'sensitivities.xlsx')
    py_cols = ['case', 'group', 'label', 'scenario_key', 'scenario', 'penetration_pct', 'capture_price',
               'baseload_price', 'capture_rate', 'capture_price_storage_bid', 'capture_rate_storage_bid',
               'pv_share_load_pct', 'pv_gw', 'pv_twh', 'role']
    level_cols = ['case', 'scenario_key', 'penetration_pct', 'co2_price', 'gas_price', 'small_batteries_gw',
                  'small_batteries_gwh', 'large_batteries_gw', 'large_batteries_gwh', 'dsm_gw', 'pth_gw',
                  'pth_twh_max', 'pth_twh_used', 'electrolysis_gw', 'electrolysis_twh_used', 'fixed_load_twh']
    cases = pd.DataFrame([{k: (str(v) if isinstance(v, (dict, list)) else v) for k, v in c.items()} for c in CASES])
    report = at_report_pv(long)
    with pd.ExcelWriter(path) as writer:
        long[py_cols].to_excel(writer, sheet_name='Py_Import_sens', index=False)
        # input for the IRR model: one capture price curve per case x scenario (same column names as Py_Import)
        long.to_excel(writer, sheet_name='all', index=False)
        long[level_cols].to_excel(writer, sheet_name='case_levels', index=False)
        # absolute values per case, scenario and penetration (PtH / electrolysis TWh actually used vary with PV)
        interaction_check(long).round(4).to_excel(writer, sheet_name='interaction_check', index=False)
        report.round(3).to_excel(writer, sheet_name='capture_rate_report_pv', index=False)
        for group, d in long[long.case != 'base'].groupby('group', sort=False):
            d = pd.concat([long[long.case == 'base'], d])
            m = d.pivot_table(index=['scenario', 'penetration_pct'], columns='label', values='capture_price', sort=False)
            m.to_excel(writer, sheet_name=group[:31].replace('/', ' '))
            # rows = scenario x PV penetration, columns = base + steps, cells = capture price (EUR/MWh)
        cases.to_excel(writer, sheet_name='cases', index=False)
    print(f'wrote {path}')
    print(report.pivot(index='case', columns='scenario_key').round(3).to_string())


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    os.makedirs(CONFIG['out_dir'], exist_ok=True)
    long, failed = run_grid()
    long = long[long.case.isin([c['name'] for c in CASES])]   # dropped cases stay in the checkpoint, not in the Excel
    check_base(long)
    write_outputs(long)
    if len(failed):
        print(failed.to_string())

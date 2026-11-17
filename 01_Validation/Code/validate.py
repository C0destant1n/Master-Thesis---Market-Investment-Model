# -*- coding: utf-8 -*-
"""
validate.py -- validation of PyPSA_model_v6 on the historical years 2019-2025.

For each year the main model runs with the observed capacities, fuel and CO2 prices of that year over a
PV penetration grid plus the observed penetration. The point at the observed penetration is compared with
the observed market (capture rate, baseload price, capture price, share of hours with price <= 0) against
acceptance criteria fixed before calibration. All model logic comes from PyPSA_model_v6.py.
Output: Output/validation_YYYY.csv, validation_prices_YYYY.csv and validation.xlsx (Figure 2: plot_value_factor.py).

Structure:
  CONFIG, CRITERIA, HIST_GW   settings, acceptance criteria, historical capacities per year
  add_hist_scenario           adds one historical year as a scenario to the model
  observed, fuel_prices       observed market values and fuel prices of a year
  run_year                    model grid and observed point of one year
  report                      comparison table

Run:  python validate.py            all years
      python validate.py 2024       one year
      python validate.py report     rebuild the table only
"""

import os
import sys

import numpy as np
import pandas as pd

CODE = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(CODE)   # topic folder: Data/, Output/, Figures/
sys.path.insert(0, os.path.join(HERE, '..', '02_Main_Model', 'Code'))
import PyPSA_model_v6 as v6  # noqa: E402

CONFIG = {
    'years': [2019, 2020, 2021, 2022, 2023, 2024, 2025],
    'grid': [],                               # penetration grid in % (sheet all_points only), plus the real point; empty = real point only
    'data_dir': os.path.join(HERE, 'Data'),
    'out_dir': os.path.join(HERE, 'Output'),
    'calibration_years': [2019, 2020, 2021, 2022, 2023],   # 2024/25 = out-of-sample test
    'crisis_years': [2022],                                # reported, not a calibration target
    # time-of-day blocks for the baseload check (hours of day, local time as in the data)
    'day_blocks': {'Morning (6-10 h)': range(6, 10),
                   'Midday (10-16 h)': range(10, 16),
                   'Evening/night (16-6 h)': [*range(16, 24), *range(0, 6)]},
}
v6.CONFIG['data_dir'] = CONFIG['data_dir']

# Acceptance criteria, fixed before calibration
CRITERIA = {
    'capture_rate_abs_error': 0.05,    # |model - observed| PV capture rate
    'baseload_rel_error': 0.10,        # |model / observed - 1| baseload price
    'hours_le_zero_ratio': (0.5, 2.0), # model / observed share of hours with price <= 0
}

# ---------------------------------------------------------------------------
# Historical assumptions (GW), one row per year
#   Nuclear ... Hydro: max. hourly generation of the year (SMARD,
#       Actual_generation_All.xlsx), the capacity basis of v0
#   Wind, PV, PHS: installed capacity (SMARD, Installed_capacities.xlsx),
#       because Weather_profiles.xlsx is normalised on installed capacity
#   PV is only used for the real penetration; v6 sets PV via the grid.
#   Import: max. hourly net import of the year (SMARD commercial trade), used as
#       last-resort supply in v6 (2019-2024: imports_exports_scheduled.xlsx, 2025: SMARD download)
# ---------------------------------------------------------------------------
HIST_GW = pd.DataFrame([
    # year  Nuclear Lignite Hard coal Gas   Oil   Bioenergy Waste Hydro  Wind on Wind off PV     PHS   Import
    (2019,  9.52,   17.51,  16.72,    14.01, 2.23, 5.15,     0.23, 3.04,  52.39,  6.39,    44.04, 9.42,  3.51),
    (2020,  8.18,   16.91,  16.39,    17.35, 2.05, 5.16,     0.24, 3.02,  53.55,  7.50,    47.75, 9.42,  9.63),
    (2021,  8.20,   16.60,  13.74,    15.40, 2.24, 5.00,     0.23, 3.09,  54.34,  7.77,    50.41, 9.42, 13.27),
    (2022,  4.12,   16.26,  15.84,    15.69, 2.32, 5.10,     0.21, 2.64,  55.29,  7.79,    57.74, 9.38, 12.89),
    (2023,  3.08,   16.45,  15.24,    17.52, 2.05, 5.19,     0.20, 2.87,  57.59,  8.13,    63.07, 9.38, 17.52),
    (2024,  0.00,   17.17,  11.83,    19.14, 2.14, 4.83,     0.18, 3.12,  59.84,  8.46,    76.60, 9.45, 17.67),
    (2025,  0.00,   13.66,   8.91,    20.16, 2.68, 5.28,     0.14, 3.07,  63.40,  9.22,    86.95, 9.38, 16.60),
], columns=['year', 'Nuclear', 'Lignite', 'Hard coal', 'Natural gas', 'Oil', 'Bioenergy',
            'Waste', 'Hydro', 'Wind onshore', 'Wind offshore', 'Photovoltaics', 'PHS', 'Import']
).set_index('year')

MUSTRUN_FACTOR = {2019: 0.593, 2020: 0.500, 2021: 0.655, 2022: 0.681, 2023: 0.526, 2024: 0.502, 2025: 0.483}
MUSTRUN_BIO = {2019: 3.73, 2020: 4.02, 2021: 3.66, 2022: 3.79, 2023: 3.63, 2024: 3.39, 2025: 3.10}
# GW, lowest hourly bioenergy generation of the year (SMARD Actual_generation_All.xlsx)
# scales the plant-list must-run so that fossil must-run = lowest hourly fossil generation of the year
# (SMARD Actual_generation_All.xlsx: lignite + hard coal + gas + oil); must-run cannot exceed that minimum

BATTERIES_GW = {2019: (0.46, 0.45), 2020: (0.79, 0.50), 2021: (1.43, 0.61), 2022: (2.47, 0.74),
                2023: (5.21, 1.24), 2024: (9.19, 1.54), 2025: (12.69, 2.29)}
# GW (small = home + commercial, large), mean of monthly values of the year, Battery Charts (RWTH):
# https://battery-charts.de/de/battery-charts-de/ ; the real market price contains them, so the validation does too

HIST_OTHER = [
    # parameter, value, unit, source
    ('hours.small-batteries', 1.51, 'h',       'as S1 (Battery Charts, mean 2025)'),
    ('hours.large-batteries', 1.38, 'h',       'as S1 (Battery Charts, mean 2025)'),
]


def add_hist_scenario(year):
    """Writes the rows of year Hxxxx into v6.ASSUMPTIONS and returns the key."""
    sc = f'H{year}'
    plants = pd.read_csv(os.path.join(CONFIG['data_dir'], 'corrected_power_plants.csv'), index_col=0)
    plants = plants[plants.status == 'operating']
    # v6 derates every plant by its availability after scaling; dividing by the
    # capacity-weighted availability makes the derated fleet equal the observed value
    avail = (plants.availability * plants.capacity).groupby(plants.carrier2).sum() \
        / plants.capacity.groupby(plants.carrier2).sum()

    rows = [(sc, f'cap.{c}', gw / avail.get(c, 1.0), 'GW', f'observed {year} / availability')
            for c, gw in HIST_GW.loc[year].items()]
    rows += [(sc, p, v, u, s) for p, v, u, s in HIST_OTHER]
    small, large = BATTERIES_GW[year]
    rows.append((sc, 'cap.small-batteries', small, 'GW', 'home + commercial storage, mean of monthly values, Battery Charts (RWTH)'))
    rows.append((sc, 'cap.large-batteries', large, 'GW', 'large-scale storage, mean of monthly values, Battery Charts (RWTH)'))
    rows.append((sc, 'mustrun.Bioenergy', MUSTRUN_BIO[year], 'GW', 'observed minimum bioenergy generation (SMARD)'))
    rows.append((sc, 'mustrun_factor', MUSTRUN_FACTOR[year], 'fraction', 'observed minimum fossil generation / plant-list must-run (SMARD)'))
    # no 'demand' row -> v6 keeps the observed load; no fuel rows -> hourly prices below
    new = pd.DataFrame(rows, columns=v6.ASSUMPTIONS.columns)
    v6.ASSUMPTIONS = pd.concat([v6.ASSUMPTIONS[v6.ASSUMPTIONS.scenario != sc], new],
                               ignore_index=True)
    return sc


# ---------------------------------------------------------------------------
# Observed data
# ---------------------------------------------------------------------------


def read_hourly(filename, year, times):
    """One year of an hourly Excel file on the model's time index (v6 helper)."""
    df = pd.read_excel(os.path.join(CONFIG['data_dir'], filename), index_col=0)
    return v6.year_rows(df, year, times, filename)


def fuel_prices(year, times):
    """Hourly coal/gas/oil (daily values held for 24 h) and CO2, as in v0."""
    out = pd.DataFrame(index=times)
    for carrier, f in [('Hard coal', 'coal_corrected.csv'), ('Natural gas', 'TTF_corrected.csv'),
                       ('Oil', 'oil_corrected.csv')]:
        daily = pd.read_csv(os.path.join(CONFIG['data_dir'], f), index_col=0, parse_dates=True)
        out[carrier] = daily.iloc[:, 0].reindex(times).ffill()
    out['ETS'] = read_hourly('ETS_DE.xlsx', year, times).iloc[:, 0]
    if out.isna().any().any():
        raise ValueError(f'fuel prices incomplete for {year}: {out.columns[out.isna().any()].tolist()}')
    return out


def observed(year, yi, price, load):
    """Observed PV capture price etc. from the day-ahead price and SMARD PV generation."""
    pv =read_hourly('Actual_generation_All.xlsx', year, yi['times'])['Photovoltaics']
    capture = (price * pv).sum() / pv.sum()
    return dict(capture_price=capture, baseload_price=price.mean(),
                capture_rate=capture / price.mean(),
                hours_price_le_zero_pct=100 * (price <= 0).mean(),
                pv_share_load_pct=100 * pv.sum() / load.sum())   # PV share: SMARD PV / SMARD load


# ---------------------------------------------------------------------------
# One year: model grid + real point, and the observed values
# ---------------------------------------------------------------------------


def run_year(year):
    yi = v6.read_year_inputs([year])[year]
    sc = add_hist_scenario(year)
    load = v6.build_load(yi, sc)
    fuel = fuel_prices(year, yi['times'])

    # real penetration, same definition as v6: potential PV (capacity x profile) / load (SMARD)
    pi_real = 100 * HIST_GW.loc[year, 'Photovoltaics'] * 1e3 * yi['pu']['Photovoltaics'].sum() / load.sum()

    rows = []
    points = [(pi, 'grid') for pi in CONFIG['grid']] + [(round(pi_real, 2), 'real')]
    for pi, kind in points:
        print(f'  {year}: penetration {pi:.2f} % ({kind})', flush=True)
        r = v6.run_point(sc, pi, yi, load, fuel, keep_price=(kind == 'real'))
        if kind == 'real':
            model_price = r.pop('hourly_price')
        rows.append(dict(year=year, source='model', point=kind, penetration_pct=r['penetration_pct'],
                         capture_price=r['capture_price'], baseload_price=r['baseload_price'],
                         capture_rate=r['capture_price'] / r['baseload_price'],
                         hours_price_le_zero_pct=r['hours_price_le_zero_pct'],
                         curtailment_pct=r['curtailment_pct'], pv_share_load_pct=r['pv_share_load_pct']))
    obs_price = read_hourly('Price.xlsx', year, yi['times']).iloc[:, 0]
    rows.append(dict(year=year, source='observed', point='real', penetration_pct=round(pi_real, 2),
                     **observed(year, yi, obs_price, load)))

    out = pd.DataFrame(rows)
    os.makedirs(CONFIG['out_dir'], exist_ok=True)
    out.to_csv(os.path.join(CONFIG['out_dir'], f'validation_{year}.csv'), index=False)
    # hourly prices at the real point, for the time-of-day check in report()
    pd.DataFrame({'model': model_price.to_numpy(), 'observed': obs_price.to_numpy()},
                 index=yi['times']).to_csv(os.path.join(CONFIG['out_dir'], f'validation_prices_{year}.csv'))
    return out


def time_of_day(years):
    """Mean price per time-of-day block, model vs observed, for every year with saved hourly prices."""
    rows = []
    for y in years:
        f = os.path.join(CONFIG['out_dir'], f'validation_prices_{y}.csv')
        if not os.path.exists(f):
            continue
        p = pd.read_csv(f, index_col=0, parse_dates=True)
        for block, hours in CONFIG['day_blocks'].items():
            b = p[p.index.hour.isin(hours)]
            rows.append(dict(year=y, block=block, model=b.model.mean(), observed=b.observed.mean(),
                             error_pct=100 * (b.model.mean() / b.observed.mean() - 1)))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Report: comparison table with criteria
# ---------------------------------------------------------------------------


def report():
    files = [os.path.join(CONFIG['out_dir'], f'validation_{y}.csv') for y in CONFIG['years']]
    res = pd.concat([pd.read_csv(f) for f in files if os.path.exists(f)], ignore_index=True)

    m = res[(res.source == 'model') & (res.point == 'real')].set_index('year')
    o = res[res.source == 'observed'].set_index('year')
    cmp = pd.DataFrame({
        'penetration_pct': o.penetration_pct,
        'pv_share_load_pct_model': m.pv_share_load_pct, 'pv_share_load_pct_obs': o.pv_share_load_pct,
        'capture_price_model': m.capture_price, 'capture_price_obs': o.capture_price,
        'capture_rate_model': m.capture_rate, 'capture_rate_obs': o.capture_rate,
        'capture_rate_error': m.capture_rate - o.capture_rate,
        'baseload_model': m.baseload_price, 'baseload_obs': o.baseload_price,
        'baseload_error_pct': 100 * (m.baseload_price / o.baseload_price - 1),
        'hours_le0_model_pct': m.hours_price_le_zero_pct, 'hours_le0_obs_pct': o.hours_price_le_zero_pct,
    })
    ratio = cmp.hours_le0_model_pct / cmp.hours_le0_obs_pct
    lo, hi = CRITERIA['hours_le_zero_ratio']
    cmp['ok_capture_rate'] = cmp.capture_rate_error.abs() <= CRITERIA['capture_rate_abs_error']
    cmp['ok_baseload'] = cmp.baseload_error_pct.abs() <= 100 * CRITERIA['baseload_rel_error']
    cmp['ok_hours_le0'] = ratio.between(lo, hi)
    cmp['role'] = ['crisis (separate)' if y in CONFIG['crisis_years'] else
                   'calibration' if y in CONFIG['calibration_years'] else 'test' for y in cmp.index]

    # trend: slope of capture rate vs penetration across years (crisis years excluded)
    t = cmp[~cmp.index.isin(CONFIG['crisis_years'])]
    slope_m = np.polyfit(t.penetration_pct, t.capture_rate_model, 1)[0] if len(t) > 1 else np.nan
    slope_o = np.polyfit(t.penetration_pct, t.capture_rate_obs, 1)[0] if len(t) > 1 else np.nan
    trend = pd.DataFrame({'capture_rate_slope_per_pct': [slope_m, slope_o]}, index=['model', 'observed'])

    assumptions = v6.ASSUMPTIONS[v6.ASSUMPTIONS.scenario.str.startswith('H')]
    if assumptions.empty:                  # report-only run: rebuild the rows for the sheet
        for y in cmp.index:
            add_hist_scenario(y)
        assumptions = v6.ASSUMPTIONS[v6.ASSUMPTIONS.scenario.str.startswith('H')]

    tod = time_of_day(cmp.index)

    path = os.path.join(CONFIG['out_dir'], 'validation.xlsx')
    with pd.ExcelWriter(path) as w:
        cmp.round(3).to_excel(w, sheet_name='comparison')
        trend.round(4).to_excel(w, sheet_name='trend')
        if len(tod):
            tod.round(2).to_excel(w, sheet_name='time_of_day', index=False)
        res.round(3).to_excel(w, sheet_name='all_points', index=False)
        assumptions.to_excel(w, sheet_name='assumptions', index=False)
    print(f'\nwrote {path}')
    print(cmp[['penetration_pct', 'capture_rate_model', 'capture_rate_obs', 'capture_rate_error',
               'baseload_error_pct', 'ok_capture_rate', 'ok_baseload', 'ok_hours_le0', 'role']]
          .round(3).to_string())
    print(f'\ntrend (capture rate per %-pt penetration): model {slope_m:.4f}, observed {slope_o:.4f}')
    if len(tod):
        print('\nmean price per time-of-day block (EUR/MWh):')
        print(tod.pivot(index='year', columns='block', values='error_pct').round(1)
              .add_suffix(' err %').to_string())


if __name__ == '__main__':
    args = sys.argv[1:]
    if args != ['report']:
        years = [int(a) for a in args] or CONFIG['years']
        for year in years:
            print(f'=== {year} ===', flush=True)
            run_year(year)
    report()

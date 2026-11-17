# -*- coding: utf-8 -*-
"""
export_excel.py -- collects all final Python results into one workbook for the IRR model.

Reads the existing outputs of the main run, sensitivities, break-even search and battery analysis (no model
run), checks them and writes 06_Excel_Export/Py_Export.xlsx with one tab per Py_* sheet of the IRR model
(Py_Main, Py_Sens, Py_BESS, Py_BESS_Lever), plus Lever_steps and a README tab with sources and checks.
Each data tab is pasted as values at A1 of the tab with the same name in Investment_Modell_GER.xlsx.
Py_Main: paste columns A:Z only; AB stays a formula there that reads merchant_capture_price.csv at AI1
(steps on Py_Main). Column AB of this export holds the same value as a check.

Run:  python export_excel.py
"""
import os
import sys
from datetime import datetime

import pandas as pd

CODE = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(CODE)   # topic folder: Data/, Output/, Figures/
ROOT = os.path.abspath(os.path.join(HERE, '..'))   # project folder
OUT_DIR = HERE
MAX_ROWS = 139                                            # some IRR Excel ranges end at row 141

SRC_MAIN = os.path.join(ROOT, '02_Main_Model', 'Output', 'v6_capture_price_matrix.xlsx')
SRC_SENS = os.path.join(ROOT, '03_Sensitivity', 'Output', 'sensitivities.xlsx')
SRC_BESS = os.path.join(ROOT, '04_BESS', 'Output', 'bess_dispatch_summary.csv')
SRC_OBS = os.path.join(ROOT, '04_BESS', 'Output', 'bess_dispatch_observed_2025.csv')
SRC_MERCH = os.path.join(ROOT, '02_Main_Model', 'Output', 'merchant_capture_price.csv')
SRC_THR = os.path.join(ROOT, '03_Sensitivity', 'Output', 'thresholds.xlsx')
SRC_LEVER = os.path.join(ROOT, '04_BESS', 'Output', 'bess_dispatch_lever.xlsx')
SRC_BE = os.path.join(ROOT, '03_Sensitivity', 'Output', 'breakeven_factors.json')
SRC_STEPS = os.path.join(ROOT, '03_Sensitivity', 'Output', 'breakeven_steps.csv')
SOURCES = [SRC_MAIN, SRC_SENS, SRC_BESS, SRC_OBS, SRC_MERCH, SRC_THR, SRC_LEVER, SRC_BE, SRC_STEPS]
OBS_LABEL = 'Observed 2025 (SMARD)'


def fail(msg):
    # stop before any file is written
    sys.exit(f'ERROR: {msg}')


def no_nan(df, name, log):
    # every column is read by the IRR Excel or carried along, so all are checked
    bad = df[df.isna().any(axis=1)]
    if len(bad):
        print(bad.to_string())
        fail(f'{name}: {len(bad)} row(s) with NaN (rows {[i + 2 for i in bad.index]} in Excel)')
    log.append(f'{name}: no NaN in any column')


def row_count(df, name, log):
    # data rows start in Excel row 2
    if len(df) > MAX_ROWS:
        log.append(f'WARNING {name}: {len(df)} data rows > {MAX_ROWS} (last Excel row {len(df) + 1}); '
                   f'check that the IRR Excel ranges reach that far')
    else:
        log.append(f'{name}: {len(df)} data rows (<= {MAX_ROWS})')


def read_inputs():
    for f in SOURCES:
        if not os.path.exists(f):
            fail(f'missing input {f}')
    main = pd.read_excel(SRC_MAIN, sheet_name='Py_Import')
    # column AA empty, AB = merchant capture price (as in the IRR Excel)
    merch = pd.read_csv(SRC_MERCH).set_index(['scenario', 'penetration_pct']).capture_price_merchant
    main = main.drop(columns=['coupling_import_twh', 'export_twh'], errors='ignore')   # columns no longer used by the IRR Excel
    for k in range(26 - main.shape[1]):                     # model columns end at Z in the IRR Excel
        main[' ' * (k + 2)] = None
    main[' '] = None
    main['capture_price_merchant'] = [merch.get((sc, pi)) for sc, pi in zip(main.scenario, main.penetration_pct)]
    sens = pd.read_excel(SRC_SENS, sheet_name='Py_Import_sens')
    thr = pd.read_excel(SRC_THR, sheet_name='Py_Import_sens')
    thr = thr[~thr.case.str.contains(r'_f\d+\.\d{4}$')]   # search steps of breakeven.py stay out, only *_be rows
    if list(thr.columns) != list(sens.columns):
        fail('thresholds.xlsx has other columns than sensitivities.xlsx')
    sens = pd.concat([sens, thr], ignore_index=True)
    bess = pd.read_csv(SRC_BESS)
    obs = pd.read_csv(SRC_OBS)
    if list(obs.columns) != list(bess.columns):
        fail('bess_dispatch_observed_2025.csv has other columns than bess_dispatch_summary.csv')
    obs['scenario'] = OBS_LABEL
    bess = pd.concat([bess, obs], ignore_index=True)   # observed row directly below the model rows
    lever = pd.read_excel(SRC_LEVER, sheet_name='Py_BESS_Lever')
    return main, sens, bess, lever


def checks(main, sens, bess):
    log = []
    model = bess[bess['scenario'] != OBS_LABEL]

    # a. scenario names in Py_BESS = names in Py_Main (IRR Excel uses SUMIFS on the name)
    names_main, names_bess = set(main['scenario']), set(model['scenario'])
    if names_main != names_bess:
        fail(f'scenario names differ: only in Py_Main {names_main - names_bess}, only in Py_BESS {names_bess - names_main}')
    log.append(f'a. scenario names identical in Py_BESS and Py_Main: {sorted(names_main)}')

    # b. BESS penetrations per scenario are a subset of the main run (0 % is left out on purpose)
    for sc in sorted(names_main):
        pm = set(main.loc[main['scenario'] == sc, 'penetration_pct'].round(6))
        pb = set(model.loc[model['scenario'] == sc, 'penetration_pct'].round(6))
        if not pb <= pm:
            fail(f'{sc}: BESS penetrations not in Py_Main: {sorted(pb - pm)}')
        log.append(f'b. {sc}: {len(pb)} BESS penetrations in Py_Main, not in BESS: {sorted(pm - pb)}')

    # c. one ratio, duration and efficiency for all BESS rows (IRR Excel checks O2, P2, Q2)
    for col in ['bess_ratio_mw_per_mwp', 'bess_duration_h', 'bess_eta']:
        vals = bess[col].unique()
        if len(vals) != 1:
            fail(f'{col} is not the same in all BESS rows: {vals}')
        log.append(f'c. {col} = {vals[0]} in all {len(bess)} rows')

    # d. row count, e. NaN
    for df, name in [(main, 'Py_Main'), (sens, 'Py_Sens'), (bess, 'Py_BESS')]:
        row_count(df, f'd. {name}', log)
    for df, name in [(main.drop(columns=[c for c in main.columns if not c.strip()]), 'Py_Main'), (sens, 'Py_Sens'), (bess, 'Py_BESS')]:
        no_nan(df, f'e. {name}', log)

    # f. every case of Py_Sens unique per scenario and penetration
    dup = sens.duplicated(['case', 'scenario_key', 'penetration_pct'])
    if dup.any():
        fail(f'Py_Sens: duplicate rows {sens[dup].case.unique().tolist()}')
    log.append(f'f. Py_Sens: {sens.case.nunique()} cases, no duplicates')
    return log


def write(tabs, log):
    path = os.path.join(OUT_DIR, 'Py_Export.xlsx')
    readme = [('File', os.path.relpath(path, ROOT)), ('Created', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
              ('Scenarios', '; '.join(sorted(tabs['Py_Main'].scenario.unique()))),
              ('Break-even factors', open(SRC_BE).read().replace('\n', ' '))]
    for s in SOURCES:
        changed = datetime.fromtimestamp(os.path.getmtime(s)).strftime('%Y-%m-%d %H:%M:%S')
        readme.append(('Source', f'{os.path.relpath(s, ROOT)} (changed {changed})'))   # relative to the project folder
    for tab, df in tabs.items():
        readme.append(('Tab', f'{tab}: {len(df)} rows x {len(df.columns)} columns -> paste as values at A1 of {tab} '
                              f'in Investment_Modell_GER.xlsx' + (' (into its blocks)' if tab == 'Py_BESS_Lever' else '')
                              + (' -- INFO ONLY, not pasted' if tab == 'Lever_steps' else '')))
    readme += [('Check', line) for line in log]

    with pd.ExcelWriter(path, engine='openpyxl') as writer:
        for tab, df in tabs.items():
            df.to_excel(writer, sheet_name=tab, index=False)
            ws = writer.sheets[tab]
            ws.freeze_panes = 'A2'   # fixed header row
            for i, col in enumerate(df.columns):
                ws.column_dimensions[ws.cell(1, i + 1).column_letter].width = max(10, len(str(col)) + 2)
        pd.DataFrame(readme, columns=['item', 'value']).to_excel(writer, sheet_name='README', index=False)
        writer.sheets['README'].column_dimensions['A'].width = 24
        writer.sheets['README'].column_dimensions['B'].width = 120
    print(f'wrote {path}: tabs {list(tabs)}')


if __name__ == '__main__':
    main, sens, bess, lever = read_inputs()
    log = checks(main, sens, bess)
    print('\n'.join(log))
    os.makedirs(OUT_DIR, exist_ok=True)
    steps = pd.read_csv(SRC_STEPS)   # info only, no tab in the IRR Excel
    write({'Py_Main': main, 'Py_Sens': sens, 'Py_BESS': bess, 'Py_BESS_Lever': lever, 'Lever_steps': steps}, log)

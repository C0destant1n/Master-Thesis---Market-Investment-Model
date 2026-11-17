"""
irr_replica.py -- Python rebuild of the Utility equity IRR of the IRR model (Investment_Modell_GER.xlsx).

Reads only the input and Py_* sheets of the workbook (Utility PV, price path, no BESS) and recomputes the
equity IRR for any case, so breakeven.py can test new lever cases without Excel. Run on its own, it
compares every case of Sensitivity Tables 3 and 4 with the values saved in Excel.

Structure:  load (inputs from the workbook) > model (cash flows and IRR of one case) > compare

Run:     python irr_replica.py [workbook.xlsx]   (workbook saved in price-path mode, Inputs_Price D5 = 2)
Import:  load(path); model(case, extra=...)
"""
import os
import sys

import numpy as np
import openpyxl
from scipy.optimize import brentq

# IRR model (Excel), the single place where its location is set; used by 03_Sensitivity/breakeven.py and
# plot_irr_penetration.py (this folder). Path relative to this file (copy in 05_IRR_Model/).
XLSX = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Investment_Modell_GER.xlsx')

WB = None
P = {}
MAIN, SENS, ANCH = {}, {}, []
SCEN = {1: 'Status quo (frozen)', 2: 'NEP 2037 A', 3: 'NEP 2037 B', 4: 'NEP 2037 C'}   # index as in Inputs_Price column E


def irr(cf):
    f = lambda r: sum(c / (1 + r) ** t for t, c in enumerate(cf))   # noqa: E731
    try:
        return brentq(f, -0.9, 1.0)
    except ValueError:
        return float('nan')


def load(path):
    """Reads inputs, Py_Main and Py_Sens of one workbook (cached values)."""
    global WB
    if not os.path.exists(path):
        raise FileNotFoundError(f'IRR model not found: {path} (set XLSX in 05_IRR_Model/Code/irr_replica.py)')
    WB = openpyxl.load_workbook(path, data_only=True)
    I = lambda sh, c: WB[sh][c].value   # noqa: E731
    P.update(infl=I('Inputs_Finance', 'D7'), base_year=I('Inputs_Finance', 'D8'), tax=I('Inputs_Finance', 'D11'),
             kd=I('Inputs_Finance', 'D15'), dscr=I('Inputs_Finance', 'D16'), cap=I('Inputs_Finance', 'D17'),
             tenor=I('Inputs_Finance', 'D18'), mw=I('Inputs_Project', 'D8'), cod=I('Inputs_Project', 'D9'),
             life=I('Inputs_Project', 'D10'), degr=I('Inputs_Project', 'D14'), yld=I('Inputs_Project', 'D15'),
             p90=I('Inputs_Project', 'D16'), capex=I('Inputs_Project', 'D19'), opex=I('Inputs_Project', 'D20'),
             afa=I('Inputs_Project', 'D21'))
    ANCH.clear()
    for r in range(17, 22):
        if I('Inputs_Price', f'C{r}') is not None:
            ANCH.append((I('Inputs_Price', f'C{r}'), float(I('Inputs_Price', f'D{r}')), SCEN[I('Inputs_Price', f'E{r}')]))
    MAIN.clear()
    for r in WB['Py_Main'].iter_rows(min_row=2, values_only=True):
        if isinstance(r[0], (int, float)) and r[1]:
            MAIN[(r[1], float(r[0]))] = dict(cp=r[27], curt=r[4])   # column AB = capture_price_merchant
    SENS.clear()
    for r in WB['Py_Sens'].iter_rows(min_row=2, max_col=8, values_only=True):
        if r[0] and r[4]:
            SENS[(r[0], r[4], float(r[5]))] = r[6]


def ratio(case, sc, pen, extra):
    """Capture price case / base at one point; 1 if the case was not run for this scenario (as Calc_Price row 86)."""
    sens = {**SENS, **(extra or {})}
    if case == 'base' or (case, sc, pen) not in sens:
        return 1.0
    return sens[(case, sc, pen)] / sens[('base', sc, pen)]


def model(case='base', extra=None):
    """Equity IRR, project IRR, gearing of Utility PV for one Py_Sens case, inputs as set."""
    life = P['life']
    yrs = np.arange(1, life + 1)
    a_y = [a[0] for a in ANCH]
    cp = np.interp(yrs, a_y, [MAIN[(s, p)]['cp'] * ratio(case, s, p, extra) for _, p, s in ANCH])
    curt = np.interp(yrs, a_y, [MAIN[(s, p)]['curt'] / 100 for _, p, s in ANCH])
    idx_p = (1 + P['infl']) ** (P['cod'] - 1 + yrs - P['base_year'])   # real 2025 -> nominal
    idx_o = (1 + P['infl']) ** (yrs - 1)
    gen = P['mw'] * P['yld'] * (1 - P['degr']) ** (yrs - 1) * (1 - curt)   # MWh
    opex = -P['mw'] * P['opex'] * idx_o
    capex = P['mw'] * P['capex']
    dep = -np.where(yrs <= P['afa'], capex / P['afa'], 0)
    ebitda = gen * cp * idx_p / 1000 + opex
    ebitda_s = gen * P['p90'] * cp * idx_p / 1000 + opex   # debt sizing case (P90 volume)

    def tax_lcf(ebt):
        out, lcf = [], 0.0
        for e in ebt:
            out.append(-max(0.0, e - lcf) * P['tax'])
            lcf = max(0.0, lcf - e)
        return np.array(out)

    ds_t = np.where(yrs <= min(P['tenor'], life), np.maximum(ebitda_s + tax_lcf(ebitda_s + dep), 0) / P['dscr'], 0)
    cap_dscr = np.sum(ds_t / (1 + P['kd']) ** yrs)
    debt = min(cap_dscr, P['cap'] * capex)
    ds = ds_t * (debt / cap_dscr if cap_dscr > 0 else 0)
    bal, interest = debt, []
    for t in range(life):
        interest.append(bal * P['kd'])
        bal -= ds[t] - interest[-1]
    cfe = np.concatenate([[-(capex - debt)], ebitda + tax_lcf(ebitda + dep - np.array(interest)) - ds])
    cfp = np.concatenate([[-capex], ebitda + tax_lcf(ebitda + dep)])
    return dict(eirr=irr(cfe), pirr=irr(cfp), gearing=debt / capex)


def compare():
    """Every Table 3 / 4 case without Excel-only levers (capex, debt rate, DSCR, cap) vs the Excel result."""
    if WB['Inputs_Price']['D5'].value != 2:
        print('The workbook is saved in static price mode (Inputs_Price D5 = 1); the replica models path mode.\n'
              'Set D5 = 2, recalculate (F9) and save the workbook, then run this check again.')
        return
    xl = WB['Sensitivity']
    b = model()
    print(f"base: replica {b['eirr']:.5f} / Excel {WB['CF_Utility']['F80'].value:.5f}, "
          f"gearing {b['gearing']:.4f} / {WB['CF_Utility']['F85'].value:.4f}")
    worst = 0.0
    tables = [(59, 12, 76), (92, 12, 111)]   # (first input row, number of cases, first result row)
    for first, n, res0 in tables:
        for k in range(n):
            r = first + k
            case = xl[f'I{r}'].value
            if not case or xl[f'E{r}'].value != 1 or xl[f'F{r}'].value or xl[f'G{r}'].value or xl[f'J{r}'].value:
                continue
            m, ex, gx = model(case), xl[f'D{res0 + k}'].value, xl[f'F{res0 + k}'].value
            if not isinstance(ex, (int, float)):   # data table not yet calculated by Excel
                print(f"{xl[f'C{r}'].value:>3} {case:14} replica {m['eirr']:.5f}  Excel (not calculated, press F9)")
                continue
            worst = max(worst, abs(m['eirr'] - ex))
            flag = '' if abs(m['eirr'] - ex) < 5e-5 else '  <-- DIFF'
            print(f"{xl[f'C{r}'].value:>3} {case:14} replica {m['eirr']:.5f}  Excel {ex:.5f}  "
                  f"gearing {m['gearing']:.4f} / {gx:.4f}{flag}")
    print(f'max IRR deviation {worst * 1e4:.2f} bp')


if __name__ == '__main__':
    load(sys.argv[1] if len(sys.argv) > 1 else XLSX)
    compare()

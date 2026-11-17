# Energy Market Model Germany: PV capture prices under rising PV penetration

Electricity market model of the master's thesis. A dispatch model of the German (DE-LU) day-ahead
market built with [PyPSA](https://pypsa.org) computes hourly prices and the PV capture price as a
function of PV penetration. The results feed the project-finance model `05_IRR_Model/Investment_Modell_GER.xlsx`.

The model builds on `PyPSA_model_v4.py` and the input data of Abuzayed (2025)
([github.com/AnasAbuzayed/market_value](https://github.com/AnasAbuzayed/market_value), CC BY 4.0).
All data sources are listed in Appendix B4 of the thesis.

## Structure

Folders are numbered in the order of the workflow. Each has `Code/` and, where needed, `Data/`, `Output/` and `Figures/`.

- **01_Validation**: model run on the historical years 2019 to 2025 against the observed market
  - `validate.py`, `plot_value_factor.py` (Figure 2)
- **02_Main_Model**: dispatch model and main run
  - `PyPSA_model_v6.py`: model, all assumptions with sources (`ASSUMPTIONS`), main run
  - `merchant_capture_price.py`: capture price of a new merchant PV plant
  - `plot_feasibility.py`: Figure 3
- **03_Sensitivity**: robustness cases and lever tests
  - `sensitivities.py`: one change at a time against the base case
  - `thresholds.py`: price-path anchors and lever definitions
  - `breakeven.py`: multiplier per lever until the equity IRR reaches the hurdle rate
- **04_BESS**: co-located battery
  - `bess_dispatch.py`: battery dispatch on model prices, observed 2025 prices and lever cases
  - `bess_lever_hourly.py`: hourly prices of the lever cases
  - `plot_bess_path.py`: Figure 6
- **05_IRR_Model**: investment model (Excel) and its Python link
  - `Investment_Modell_GER.xlsx`: final investment model
  - `irr_replica.py`: Python rebuild of the equity IRR, used by `breakeven.py`
  - `plot_irr_penetration.py`: Figure 4
- **06_Excel_Export**: `export_excel.py` collects all results into `Py_Export.xlsx` for the investment model
- **Root**: `run_all.sh` (full chain), `thesis_style.py` (figure style), `requirements.txt`

Every script starts with a short description of what it does, how it is built and how to run it.

## Setup

- Python 3.11: `pip install -r requirements.txt`
- Solver: Gurobi (`gurobipy`, licence needed; free for academic use)
  - another solver can be set in `CONFIG['solver']` and `CONFIG['solver_options']` of `PyPSA_model_v6.py`

## Usage

**Rebuild figures and the export from the included results** (seconds, no solver needed):

```sh
cd 02_Main_Model/Code   && python PyPSA_model_v6.py plots    # Figure 3
cd 01_Validation/Code   && python plot_value_factor.py       # Figure 2
cd 04_BESS/Code         && python plot_bess_path.py          # Figure 6
cd 05_IRR_Model/Code    && python plot_irr_penetration.py    # Figure 4
cd 06_Excel_Export/Code && python export_excel.py            # Py_Export.xlsx
```

**Run the full chain** (main run, sensitivities, break-even search, battery, export):

```sh
sh run_all.sh                      # in the background, progress: tail -f run_all.log
sh run_all.sh --foreground         # in this terminal
PY=/path/to/python sh run_all.sh   # with a specific Python environment
```

- Runtime: about 18 hours from scratch (one model solve takes several minutes)
- Restart: every step keeps a checkpoint, so finished points are skipped; with the included checkpoints the chain only rebuilds the outputs
- Logs: `run_all.log` and one log per step in `<folder>/Output/`
- Validation is not part of the chain: `cd 01_Validation/Code && python validate.py`

## Results

- `02_Main_Model/Output/v6_capture_price_matrix.xlsx`: capture price, baseload price and capture rate per scenario and PV penetration
- `03_Sensitivity/Output/`: robustness cases, lever multipliers (`breakeven_factors.json`), lever cases (`thresholds.xlsx`)
- `04_BESS/Output/`: battery margins
- `06_Excel_Export/Py_Export.xlsx`: everything above in the format of the investment model (tabs `Py_*`)

## Scenarios

| Key | Scenario | Source |
|-----|----------|--------|
| S1 | Status quo (2025 system) | SMARD 2025 |
| S2 to S4 | NEP 2037 A, B, C | Netzentwicklungsplan Strom 2037/2045 (2025) |

- PV penetration = potential PV generation / fixed annual load
- Price path of the investment model: 2025 S1 15.94 %, 2030 S2 27.5 %, 2037 S3 35 %, 2045 S4 45 %, 2054 S4 50 % (`thresholds.py`, `ANCHOR_PATH`)

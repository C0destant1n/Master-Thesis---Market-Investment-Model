# -*- coding: utf-8 -*-
"""
PyPSA_model_v6.py -- PV capture price as a function of PV penetration (main model).

Hourly dispatch model of the German (DE-LU) day-ahead market with one node, built on PyPSA_model_v4.py
(Abuzayed, 2025). For every scenario (S1-S4), weather year (2023-2025) and potential PV penetration
(0-100 % of fixed load) it sets the PV capacity, solves the least-cost dispatch (Gurobi) and derives the
hourly price from the solved dispatch with the price rules. Results per point: capture price, baseload
price, capture rate, curtailment and diagnostics, averaged over the weather years
(Output/v6_capture_price_matrix.xlsx, v6_results_long.csv), plus the hourly prices (Output/hourly/).

Structure:
  CONFIG, ASSUMPTIONS   run settings; every scenario parameter with value, unit and source
  inputs                read_year_inputs, build_load, plant_table, marginal_costs_table
  network and price     build_network, bids, hourly_price, run_point (one solve)
  outputs               write_outputs, plot_figures (figures are drawn by plot_feasibility.py)
  __main__              main run with checkpoint (Output/v6_results_checkpoint.csv)

Run:  python PyPSA_model_v6.py           main run (a restart skips finished points)
      python PyPSA_model_v6.py S1 S3     only the given scenarios
      python PyPSA_model_v6.py plots     rebuild the figures only
      python PyPSA_model_v6.py export    rebuild Excel and figures from v6_results_long.csv (no solve)
"""

import gc
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd
import pypsa

CODE = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(CODE)   # topic folder: Data/, Output/, Figures/

CONFIG = {
    # run size
    'weather_years':          [2023, 2024, 2025],        # each solved separately, then averaged (the three most recent years)
    'penetration_low':        [0.0, 2.5, 5.0, 7.5, 10.0, 12.5],  # below today: top of the S-curve; 0 % = value of the first PV module
    'penetration_today':      15.94,                     # PV penetration 2025 (validation)
    'penetration_pct':        [17.5, 20.0, 22.5, 25.0, 27.5, 30.0, 32.5, 35.0, 37.5, 40.0, 42.5, 45.0, 47.5, 50.0,
                               60.0, 70.0, 80.0, 90.0, 100.0],
    # above 50 %: overbuild steps up to 100 %, mainly to show where the PV share actually fed in saturates
    # prices and dispatch rules
    'base_year':              2025,                      # every price is treated as real EUR of this year
    'currency':               'EUR_real_2025',           # label for the Excel output only
    'voll_price':             1000.0,                    # backstop generator (value of lost load) = price ceiling, EUR/MWh
    'voll_p_nom':             1e6,                       # backstop capacity, MW
    'tiebreak':               {'Wind offshore': 0.0001, 'Wind onshore': 0.001, 'Photovoltaics': 0.01},  # EUR/MWh, PV dispatched first (v4)
    'running_threshold':      0.01,                      # MW; below this a generator does not count as price-setting
    'curtail_threshold':      1.0,                       # MW; RES curtailed above this in an hour -> surplus hour (price floor)
    'ramp_markup':            0.025,                     # relative bid markup (+2.5 % of marginal cost) per GW of thermal ramp-up over ramp_hours (start-up costs); calibrated 2019-21+23, tested 2024/25 (validate.py)
    'ramp_hours':             3,                         # h, window of the thermal ramp-up
    'res_fleet_2025':         {'Photovoltaics': 86.95, 'Wind onshore': 63.40, 'Wind offshore': 9.22},  # GW installed 2025 (SMARD, as validate.py); capacity above this is new (Solarspitzengesetz)
    'new_res_bid':            0.0,                       # EUR/MWh, bid of wind/PV built after 2025 (Solarspitzengesetz: no payment at negative prices, so curtail at 0)
    'covered_price':          5.0,                       # EUR/MWh in hours where wind/PV cover the load down to must-run without curtailment; calibrated 2019-21+23 (observed mean 1-20 EUR)
    # storage and plant fleet
    'storage_efficiency':     {'PHS': 0.87, 'small-batteries': 0.9, 'large-batteries': 0.9},  # per direction (v4)
    'phs_hours':              8.0,                       # pumped-storage reservoir at full power, h (v4)
    'storage_marginal_cost':  0.01,                      # EUR/MWh per charge/discharge, avoids pointless cycling (v4)
    'battery_cycle_cost':     {'large-batteries': 15.0}, # EUR/MWh discharged, wear of large batteries (literature ~10-40 EUR/MWh)
    'home_discharge_hours':   [*range(18, 24), *range(0, 6)],  # home + commercial storage empties evenly over the night (18-6 h)
    'only_operating':         True,                      # only plants with status 'operating' (v4)
    # solver and folders
    'solver':                 'gurobi',
    'solver_options':         {'threads': 8, 'Seed': 0, 'Method': 1},  # fixed seed -> reproducible; dual simplex only (always wins, saves RAM)
    'data_dir':               os.path.join(HERE, 'Data'),
    'out_dir':                os.path.join(HERE, 'Output'),
    'fig_dir':                os.path.join(HERE, 'Figures'),
}

PENETRATION_GRID = np.round(np.r_[CONFIG['penetration_low'], CONFIG['penetration_today'], CONFIG['penetration_pct']], 2)
# PV shares of the main run: low shares (top of the S-curve), today, fine steps (2.5) up to 50 %,
# then steps of 10 up to 100 %

SCENARIO_NAMES = {'S1': 'Status quo (frozen)',
                  'S2': 'NEP 2037 A',
                  'S3': 'NEP 2037 B',
                  'S4': 'NEP 2037 C'}

# ---------------------------------------------------------------------------
# Every scenario number lives in this one table (also written to the Excel sheet
# 'assumptions'). A source containing 'TODO' marks an open point and is listed at start.
# Rules:
# - a carrier without a 'cap.' row keeps its capacity from corrected_power_plants.csv
# - a scenario without a 'demand' row keeps the observed load of the weather year
# ---------------------------------------------------------------------------
ASSUMPTIONS = pd.DataFrame([
    # scenario, parameter, value, unit, source
    ('S1', 'co2_price',                75.0, 'EUR/tCO2',   'EUA auction DE, mean 2025, Energy-Charts: https://www.energy-charts.info/charts/price_average/chart.htm?l=de&c=DE&stackLabelPartSumDecimals=2&legendItems=jyf&year=2025'),
    ('S1', 'fuel.Natural gas',        36.24, 'EUR/MWh_th', 'Dutch TTF front month, mean 2025, investing.com: https://www.investing.com/commodities/dutch-ttf-gas-c1-futures-historical-data'),
    ('S1', 'fuel.Hard coal',          12.80, 'EUR/MWh_th', 'API2 CIF ARA, mean 2025, investing.com: https://www.investing.com/commodities/rotterdam-coal-futures-historical-data; 1 USD ≈ 0.897 EUR, 6.978 MWh_th/tonne'),
    ('S1', 'fuel.Oil',                34.10, 'EUR/MWh_th', 'WTI front month, mean 2025, investing.com: https://www.investing.com/commodities/crude-oil-historical-data; 1 USD ≈ 0.897 EUR, 57.96 EUR/barrel, 1 barrel crude oil ≈ 1.70 MWh_th/barrel'),
    ('S1', 'cap.Nuclear',                 0, 'GW',         'German nuclear phase-out completed 15 April 2023'),
    ('S1', 'cap.Lignite',             16.07, 'GW',         'SMARD 2025, max. hourly generation 13.66 GW / availability 0.85: https://www.smard.de/home/downloadcenter/download-marktdaten/'),
    ('S1', 'cap.Hard coal',           11.13, 'GW',         'SMARD 2025, max. hourly generation 8.91 GW / availability 0.80: https://www.smard.de/home/downloadcenter/download-marktdaten/'),
    ('S1', 'cap.Natural gas',          22.4, 'GW',         'SMARD 2025, max. hourly generation 20.16 GW / availability 0.90: https://www.smard.de/home/downloadcenter/download-marktdaten/'),
    ('S1', 'cap.Oil',                  3.15, 'GW',         'Oil carrier = SMARD other conventional (oil, mine gas and the fossil half of waste incineration, priced as oil), max. hourly generation 2025 2.68 GW / availability 0.85: https://www.smard.de/home/downloadcenter/download-marktdaten/'),
    ('S1', 'cap.Bioenergy',            5.87, 'GW',         'SMARD 2025, max. hourly generation 5.28 GW / availability 0.90: https://www.smard.de/home/downloadcenter/download-marktdaten/'),
    ('S1', 'cap.Waste',                0.14, 'GW',         'Waste carrier = SMARD other renewables (e.g. geothermal, landfill and sewage gas; zero fuel cost; name kept from v4), max. hourly generation 2025: https://www.smard.de/home/downloadcenter/download-marktdaten/'),
    ('S1', 'cap.Hydro',                3.07, 'GW',         'SMARD 2025, max. hourly generation: https://www.smard.de/home/downloadcenter/download-marktdaten/'),
    ('S1', 'cap.Wind onshore',         63.4, 'GW',         'SMARD 2025, installed capacity: https://www.smard.de/home/downloadcenter/download-marktdaten/'),
    ('S1', 'cap.Wind offshore',        9.22, 'GW',         'SMARD 2025, installed capacity: https://www.smard.de/home/downloadcenter/download-marktdaten/'),
    ('S1', 'cap.PHS',                  9.38, 'GW',         'installed pumped storage 2025 (DE-LU), SMARD: https://www.smard.de/home/downloadcenter/download-marktdaten/'),
    ('S1', 'cap.small-batteries',     12.69, 'GW',         'home + commercial storage, mean of monthly values 2025 (12.10 + 0.59), Battery Charts (RWTH): https://battery-charts.de/de/battery-charts-de/'),
    ('S1', 'cap.large-batteries',      2.29, 'GW',         'large-scale storage, mean of monthly values 2025, Battery Charts (RWTH): https://battery-charts.de/de/battery-charts-de/'),
    ('S1', 'cap.Import',               16.6, 'GW',         'max. hourly net import 2025, SMARD commercial trade: https://www.smard.de/home/downloadcenter/download-marktdaten/'),
    ('S1', 'hours.small-batteries',    1.51, 'h',          'energy-to-power ratio, mean of monthly values 2025: (18.00 + 1.15 GWh) / (12.10 + 0.59 GW), home + commercial, Battery Charts (RWTH): https://battery-charts.de/de/battery-charts-de/'),
    ('S1', 'hours.large-batteries',    1.38, 'h',          'energy-to-power ratio, mean of monthly values 2025: 3.16 GWh / 2.29 GW, large-scale storage, Battery Charts (RWTH): https://battery-charts.de/de/battery-charts-de/'),
    ('S1', 'mustrun_factor',          0.483, 'fraction',   'SMARD Actual_generation_All.xlsx: lowest hourly fossil generation (lignite + hard coal + gas + oil) of 2025 = 5.54 GW / plant-list must-run 11.47 GW; must-run cannot exceed the observed minimum'),
    ('S1', 'mustrun.Bioenergy',       3.10, 'GW',         'SMARD Actual_generation_All.xlsx: lowest hourly bioenergy generation 2025 (EEG plants run flat)'),

    # S2 = NEP 2037 scenario A (NEP Strom 2037/2045, Version 2025, 2nd draft): https://www.netzentwicklungsplan.de/sites/default/files/2026-08/NEP_2037_2045_V2025_2_Entwurf_0.pdf
    ('S2', 'demand',                  774.8, 'TWh/a',      'NEP Tab. 1: net electricity consumption A 2037 (SMARD load shape rescaled; simplification: EV/heat pump profiles not modelled separately)'),
    ('S2', 'flex.Electrolysis',          20, 'GW',         'NEP Tab. 1: electrolysis capacity 2037'),
    ('S2', 'wtp.Electrolysis',         33.3, 'EUR/MWh_el', 'NEP Tab. 9: hydrogen price 47.6 EUR/MWh; NEP p. 39: electrolysis efficiency 70 %; price limit = 47.6 x 0.7 (NEP p. 39: 33.31 EUR/MWh)'),
    ('S2', 'flex.PtH',                  9.5, 'GW',         'NEP Tab. 1: power-to-heat capacity 2037 (large heat pumps + electric boilers)'),
    ('S2', 'wtp.PtH',                  52.9, 'EUR/MWh_el', 'NEP Tab. 9 and 10: price limit = gas boiler: (gas 16.9 + CO2 152.7 x 0.201) / 0.9 efficiency; simplification: large heat pumps (COP ~3) would bid higher'),
    ('S2', 'energy.PtH',               27.2, 'TWh/a',      'NEP Fig. 6: district heating A 2037 (result of the NEP market simulation) = max. annual consumption of power-to-heat (heat demand is finite)'),
    ('S2', 'shift.DSM',                 7.2, 'GW',         'NEP Tab. 7: shiftable DSM A 2037: industry 2.9 + commerce/services 4.3 GW (curtailable DSM left out, used only at price peaks)'),
    ('S2', 'shift_hours.DSM',             3, 'h',          'Consentec, Fraunhofer ISI, Fraunhofer IEG (2025): Planung von Verteilnetzen der Zukunft (VN-Zukunft), final report for BMWE, p. v and 39: max. shift duration of 3 h as plausible mean over all flexibility types (2045 analysis, used for 2037); NEP p. 43 names a max. shift duration per process but publishes no values: https://consentec.de/app/uploads/2025/08/Consentec_ISI_IEG_BMWK_VN-Zukunft_AbschlussBer_20250627-1.pdf'),
    ('S2', 'flex_demand',              79.6, 'TWh/a',      'NEP Fig. 6: electrolysis 52.4 + district heating 27.2 TWh A 2037; removed from the fixed load because these consumers are modelled as price-driven bidders (flex.*)'),
    ('S2', 'co2_price',               152.7, 'EUR/tCO2',   'NEP Tab. 9: CO2 price scenarios 2037'),
    ('S2', 'fuel.Natural gas',         16.9, 'EUR/MWh_th', 'NEP Tab. 9: natural gas 2037'),
    ('S2', 'fuel.Hydrogen',            47.6, 'EUR/MWh_th', 'NEP Tab. 9: hydrogen 2037'),
    ('S2', 'fuel.Hard coal',            5.9, 'EUR/MWh_th', 'NEP Tab. 9: hard coal 2037 (no coal capacity left, value unused)'),
    ('S2', 'fuel.Oil',                 34.4, 'EUR/MWh_th', 'NEP Tab. 9: crude oil 2037'),
    ('S2', 'cap.Hard coal',               0, 'GW',         'NEP Tab. 8: no coal plants in 2037 (coal phase-out)'),
    ('S2', 'cap.Lignite',                 0, 'GW',         'NEP Tab. 8: no lignite plants in 2037 (coal phase-out)'),
    ('S2', 'cap.Nuclear',                 0, 'GW',         'German nuclear phase-out completed 15 April 2023'),
    ('S2', 'cap.Natural gas',          13.9, 'GW',         "NEP Tab. 8: natural gas 2037 (simplification: efficiency mix of today's fleet is used)"),
    ('S2', 'cap.Hydrogen',             28.7, 'GW',         "NEP Tab. 8: hydrogen power plants 2037 (modelled as copies of today's gas fleet, burning hydrogen without CO2)"),
    ('S2', 'cap.Oil',                   4.4, 'GW',         "NEP Tab. 8: other conventional 2.5 + waste 1.9 GW (Oil carrier = SMARD other conventional incl. fossil half of waste, priced as oil, as in validation)"),
    ('S2', 'cap.Waste',                   1, 'GW',         'NEP Tab. 1: other renewable generation 2037 (Waste carrier = SMARD other renewables, zero fuel cost, name kept from v4, as in validation)'),
    ('S2', 'cap.Wind onshore',        126.6, 'GW',         'NEP Tab. 1: onshore wind A 2037 (BNetzA also approved a 140.5 GW variant)'),
    ('S2', 'cap.Wind offshore',          50, 'GW',         'NEP Tab. 1: offshore wind A 2037'),
    ('S2', 'cap.Bioenergy',               5, 'GW',         'NEP Tab. 1: biomass 2037'),
    ('S2', 'cap.Hydro',                 4.6, 'GW',         'NEP Tab. 1: hydro 2037'),
    ('S2', 'cap.PHS',                    12, 'GW',         'NEP Tab. 1: pumped storage 2037'),
    ('S2', 'cap.small-batteries',      46.7, 'GW',         'NEP Tab. 1: small battery storage A 2037'),
    ('S2', 'cap.large-batteries',      41.1, 'GW',         'NEP Tab. 1: large battery storage A 2037'),
    ('S2', 'cap.Import',                 40, 'GW',         'NEP p. 86 (highest trade exchange): net import of about 40 GW in the hour with the highest total cross-border trade (Feb 2037, all scenarios); used as max. hourly net import (the true max. is at least this high) https://www.netzentwicklungsplan.de/sites/default/files/2026-08/NEP_2037_2045_V2025_2_Entwurf_0.pdf'),
    ('S2', 'hours.small-batteries',     2.5, 'h',          'NEP p. 50: small battery storage 2.5 h'),
    ('S2', 'hours.large-batteries',       2, 'h',          'NEP p. 50: large battery storage 2 h'),
    ('S2', 'mustrun_factor',          0.483, 'fraction',   'SMARD Actual_generation_All.xlsx: lowest hourly fossil generation (lignite + hard coal + gas + oil) of 2025 = 5.54 GW / plant-list must-run 11.47 GW; must-run cannot exceed the observed minimum; 2037: same factor as 2025 (ceteris paribus, no observation)'),
    ('S2', 'mustrun.Bioenergy',        1.71, 'GW',         'NEP Abb. 33 / Fig. 21: biomass 5 GW x 3,000 full-load hours = 15 TWh in 2037 (all scenarios) / 8,760 h = 1.71 GW; a flat must-run cannot exceed the NEP biomass energy (NEP p. 47: biomass shifts its daily output with prices; the 2025 observed minimum of 3.10 GW would force 27 TWh)'),

    # S3 = NEP 2037 scenario B (NEP Strom 2037/2045, Version 2025, 2nd draft): https://www.netzentwicklungsplan.de/sites/default/files/2026-08/NEP_2037_2045_V2025_2_Entwurf_0.pdf
    ('S3', 'demand',                  956.7, 'TWh/a',      'NEP Tab. 1: net electricity consumption B 2037 (SMARD load shape rescaled; simplification: EV/heat pump profiles not modelled separately)'),
    ('S3', 'flex.Electrolysis',          42, 'GW',         'NEP Tab. 1: electrolysis capacity B 2037'),
    ('S3', 'wtp.Electrolysis',         33.3, 'EUR/MWh_el', 'NEP Tab. 9: hydrogen price 47.6 EUR/MWh; NEP p. 39: electrolysis efficiency 70 %; price limit = 47.6 x 0.7 (NEP p. 39: 33.31 EUR/MWh)'),
    ('S3', 'flex.PtH',                 25.3, 'GW',         'NEP Tab. 1: power-to-heat capacity B 2037 (Tab. 4: large heat pumps 11.5 + electric boilers 13.8 GW)'),
    ('S3', 'wtp.PtH',                  52.9, 'EUR/MWh_el', 'NEP Tab. 9 and 10: price limit = gas boiler: (gas 16.9 + CO2 152.7 x 0.201) / 0.9 efficiency; simplification: large heat pumps (COP ~3) would bid higher'),
    ('S3', 'energy.PtH',               33.8, 'TWh/a',      'NEP Fig. 6: district heating B 2037 (result of the NEP market simulation) = max. annual consumption of power-to-heat (heat demand is finite)'),
    ('S3', 'shift.DSM',                11.5, 'GW',         'NEP Tab. 7: shiftable DSM B 2037: industry 6.3 + commerce/services 5.2 GW (curtailable DSM left out, used only at price peaks)'),
    ('S3', 'shift_hours.DSM',             3, 'h',          'Consentec, Fraunhofer ISI, Fraunhofer IEG (2025): Planung von Verteilnetzen der Zukunft (VN-Zukunft), final report for BMWE, p. v and 39: max. shift duration of 3 h as plausible mean over all flexibility types (2045 analysis, used for 2037); NEP p. 43 names a max. shift duration per process but publishes no values: https://consentec.de/app/uploads/2025/08/Consentec_ISI_IEG_BMWK_VN-Zukunft_AbschlussBer_20250627-1.pdf'),
    ('S3', 'flex_demand',             148.2, 'TWh/a',      'NEP Fig. 6: electrolysis 114.4 + district heating 33.8 TWh B 2037; removed from the fixed load because these consumers are modelled as price-driven bidders (flex.*)'),
    ('S3', 'co2_price',               152.7, 'EUR/tCO2',   'NEP Tab. 9: CO2 price scenarios 2037'),
    ('S3', 'fuel.Natural gas',         16.9, 'EUR/MWh_th', 'NEP Tab. 9: natural gas 2037'),
    ('S3', 'fuel.Hydrogen',            47.6, 'EUR/MWh_th', 'NEP Tab. 9: hydrogen 2037'),
    ('S3', 'fuel.Hard coal',            5.9, 'EUR/MWh_th', 'NEP Tab. 9: hard coal 2037 (no coal capacity left, value unused)'),
    ('S3', 'fuel.Oil',                 34.4, 'EUR/MWh_th', 'NEP Tab. 9: crude oil 2037'),
    ('S3', 'cap.Hard coal',               0, 'GW',         'NEP Tab. 8: no coal plants in 2037 (coal phase-out)'),
    ('S3', 'cap.Lignite',                 0, 'GW',         'NEP Tab. 8: no lignite plants in 2037 (coal phase-out)'),
    ('S3', 'cap.Nuclear',                 0, 'GW',         'German nuclear phase-out completed 15 April 2023'),
    ('S3', 'cap.Natural gas',          15.2, 'GW',         "NEP Tab. 8: natural gas B 2037 (simplification: efficiency mix of today's fleet is used)"),
    ('S3', 'cap.Hydrogen',             40.4, 'GW',         "NEP Tab. 8: hydrogen power plants B 2037 (modelled as copies of today's gas fleet, burning hydrogen without CO2)"),
    ('S3', 'cap.Oil',                   6.4, 'GW',         'NEP Tab. 8: other conventional 4.5 + waste 1.9 GW B 2037 (Oil carrier = SMARD other conventional incl. fossil half of waste, priced as oil, as in validation)'),
    ('S3', 'cap.Waste',                   1, 'GW',         'NEP Tab. 1: other renewable generation 2037 (Waste carrier = SMARD other renewables, zero fuel cost, name kept from v4, as in validation)'),
    ('S3', 'cap.Wind onshore',        158.2, 'GW',         'NEP Tab. 1: onshore wind B 2037'),
    ('S3', 'cap.Wind offshore',          56, 'GW',         'NEP Tab. 1: offshore wind B 2037'),
    ('S3', 'cap.Bioenergy',               5, 'GW',         'NEP Tab. 1: biomass 2037'),
    ('S3', 'cap.Hydro',                 4.6, 'GW',         'NEP Tab. 1: hydro 2037'),
    ('S3', 'cap.PHS',                    12, 'GW',         'NEP Tab. 1: pumped storage 2037'),
    ('S3', 'cap.small-batteries',      59.5, 'GW',         'NEP Tab. 1: small battery storage B 2037'),
    ('S3', 'cap.large-batteries',      67.6, 'GW',         'NEP Tab. 1: large battery storage B 2037'),
    ('S3', 'cap.Import',                 40, 'GW',         'NEP p. 86 (highest trade exchange): net import of about 40 GW in the hour with the highest total cross-border trade (Feb 2037, all scenarios); used as max. hourly net import (the true max. is at least this high) https://www.netzentwicklungsplan.de/sites/default/files/2026-08/NEP_2037_2045_V2025_2_Entwurf_0.pdf'),
    ('S3', 'hours.small-batteries',     2.5, 'h',          'NEP p. 50: small battery storage 2.5 h'),
    ('S3', 'hours.large-batteries',       2, 'h',          'NEP p. 50: large battery storage 2 h'),
    ('S3', 'mustrun_factor',          0.483, 'fraction',   'SMARD Actual_generation_All.xlsx: lowest hourly fossil generation (lignite + hard coal + gas + oil) of 2025 = 5.54 GW / plant-list must-run 11.47 GW; must-run cannot exceed the observed minimum; 2037: same factor as 2025 (ceteris paribus, no observation)'),
    ('S3', 'mustrun.Bioenergy',        1.71, 'GW',         'NEP Abb. 33 / Fig. 21: biomass 5 GW x 3,000 full-load hours = 15 TWh in 2037 (all scenarios) / 8,760 h = 1.71 GW; a flat must-run cannot exceed the NEP biomass energy (NEP p. 47: biomass shifts its daily output with prices; the 2025 observed minimum of 3.10 GW would force 27 TWh)'),

    # S4 = NEP 2037 scenario C (NEP Strom 2037/2045, Version 2025, 2nd draft): https://www.netzentwicklungsplan.de/sites/default/files/2026-08/NEP_2037_2045_V2025_2_Entwurf_0.pdf
    ('S4', 'demand',                  994.2, 'TWh/a',      'NEP Tab. 1: net electricity consumption C 2037 (SMARD load shape rescaled; simplification: EV/heat pump profiles not modelled separately)'),
    ('S4', 'flex.Electrolysis',          42, 'GW',         'NEP Tab. 1: electrolysis capacity 2037'),
    ('S4', 'wtp.Electrolysis',         33.3, 'EUR/MWh_el', 'NEP Tab. 9: hydrogen price 47.6 EUR/MWh; NEP p. 39: electrolysis efficiency 70 %; price limit = 47.6 x 0.7 (NEP p. 39: 33.31 EUR/MWh)'),
    ('S4', 'flex.PtH',                 22.2, 'GW',         'NEP Tab. 1: power-to-heat capacity 2037 (large heat pumps + electric boilers)'),
    ('S4', 'wtp.PtH',                  52.9, 'EUR/MWh_el', 'NEP Tab. 9 and 10: price limit = gas boiler: (gas 16.9 + CO2 152.7 x 0.201) / 0.9 efficiency; simplification: large heat pumps (COP ~3) would bid higher'),
    ('S4', 'energy.PtH',               32.5, 'TWh/a',      'NEP Fig. 6: district heating C 2037 (result of the NEP market simulation) = max. annual consumption of power-to-heat (heat demand is finite)'),
    ('S4', 'shift.DSM',                11.8, 'GW',         'NEP Tab. 7: shiftable DSM C 2037: industry 5.7 + commerce/services 6.1 GW (curtailable DSM left out, used only at price peaks)'),
    ('S4', 'shift_hours.DSM',             3, 'h',          'Consentec, Fraunhofer ISI, Fraunhofer IEG (2025): Planung von Verteilnetzen der Zukunft (VN-Zukunft), final report for BMWE, p. v and 39: max. shift duration of 3 h as plausible mean over all flexibility types (2045 analysis, used for 2037); NEP p. 43 names a max. shift duration per process but publishes no values: https://consentec.de/app/uploads/2025/08/Consentec_ISI_IEG_BMWK_VN-Zukunft_AbschlussBer_20250627-1.pdf'),
    ('S4', 'flex_demand',             156.3, 'TWh/a',      'NEP Fig. 6: electrolysis 123.8 + district heating 32.5 TWh C 2037; removed from the fixed load because these consumers are modelled as price-driven bidders (flex.*)'),
    ('S4', 'co2_price',               152.7, 'EUR/tCO2',   'NEP Tab. 9: CO2 price scenarios 2037'),
    ('S4', 'fuel.Natural gas',         16.9, 'EUR/MWh_th', 'NEP Tab. 9: natural gas 2037'),
    ('S4', 'fuel.Hydrogen',            47.6, 'EUR/MWh_th', 'NEP Tab. 9: hydrogen 2037'),
    ('S4', 'fuel.Hard coal',            5.9, 'EUR/MWh_th', 'NEP Tab. 9: hard coal 2037 (no coal capacity left, value unused)'),
    ('S4', 'fuel.Oil',                 34.4, 'EUR/MWh_th', 'NEP Tab. 9: crude oil 2037'),
    ('S4', 'cap.Hard coal',               0, 'GW',         'NEP Tab. 8: no coal plants in 2037 (coal phase-out)'),
    ('S4', 'cap.Lignite',                 0, 'GW',         'NEP Tab. 8: no lignite plants in 2037 (coal phase-out)'),
    ('S4', 'cap.Nuclear',                 0, 'GW',         'German nuclear phase-out completed 15 April 2023'),
    ('S4', 'cap.Natural gas',          15.2, 'GW',         "NEP Tab. 8: natural gas 2037 (simplification: efficiency mix of today's fleet is used)"),
    ('S4', 'cap.Hydrogen',             40.4, 'GW',         "NEP Tab. 8: hydrogen power plants 2037 (modelled as copies of today's gas fleet, burning hydrogen without CO2)"),
    ('S4', 'cap.Oil',                   6.4, 'GW',         "NEP Tab. 8: other conventional 4.5 + waste 1.9 GW (Oil carrier = SMARD other conventional incl. fossil half of waste, priced as oil, as in validation)"),
    ('S4', 'cap.Waste',                   1, 'GW',         'NEP Tab. 1: other renewable generation 2037 (Waste carrier = SMARD other renewables, zero fuel cost, name kept from v4, as in validation)'),
    ('S4', 'cap.Wind onshore',        158.2, 'GW',         'NEP Tab. 1: onshore wind C 2037'),
    ('S4', 'cap.Wind offshore',          56, 'GW',         'NEP Tab. 1: offshore wind C 2037'),
    ('S4', 'cap.Bioenergy',               5, 'GW',         'NEP Tab. 1: biomass 2037'),
    ('S4', 'cap.Hydro',                 4.6, 'GW',         'NEP Tab. 1: hydro 2037'),
    ('S4', 'cap.PHS',                    12, 'GW',         'NEP Tab. 1: pumped storage 2037'),
    ('S4', 'cap.small-batteries',      65.3, 'GW',         'NEP Tab. 1: small battery storage C 2037'),
    ('S4', 'cap.large-batteries',      94.1, 'GW',         'NEP Tab. 1: large battery storage C 2037'),
    ('S4', 'cap.Import',                 40, 'GW',         'NEP p. 86 (highest trade exchange): net import of about 40 GW in the hour with the highest total cross-border trade (Feb 2037, all scenarios); used as max. hourly net import (the true max. is at least this high) https://www.netzentwicklungsplan.de/sites/default/files/2026-08/NEP_2037_2045_V2025_2_Entwurf_0.pdf'),
    ('S4', 'hours.small-batteries',       4, 'h',          'Expert interviews (Oct 2026), upside case: longer storage duration than NEP p. 50 (small battery storage 2.5 h)'),
    ('S4', 'hours.large-batteries',       4, 'h',          'Expert interviews (Oct 2026), upside case: longer storage duration than NEP p. 50 (large battery storage 2 h)'),
    ('S4', 'mustrun_factor',          0.483, 'fraction',   'SMARD Actual_generation_All.xlsx: lowest hourly fossil generation (lignite + hard coal + gas + oil) of 2025 = 5.54 GW / plant-list must-run 11.47 GW; must-run cannot exceed the observed minimum; 2037: same factor as 2025 (ceteris paribus, no observation)'),
    ('S4', 'mustrun.Bioenergy',        1.71, 'GW',         'NEP Abb. 33 / Fig. 21: biomass 5 GW x 3,000 full-load hours = 15 TWh in 2037 (all scenarios) / 8,760 h = 1.71 GW; a flat must-run cannot exceed the NEP biomass energy (NEP p. 47: biomass shifts its daily output with prices; the 2025 observed minimum of 3.10 GW would force 27 TWh)'),
], columns=['scenario', 'parameter', 'value', 'unit', 'source'])
assert not ASSUMPTIONS.duplicated(['scenario', 'parameter']).any(), 'ASSUMPTIONS: a parameter is listed twice in a scenario'
assert set(ASSUMPTIONS.scenario) == set(SCENARIO_NAMES), 'ASSUMPTIONS and SCENARIO_NAMES list different scenarios'
# par() reads the first hit only, so a duplicate row would be ignored without notice

# Notes on the table:
# - S1 prices: annual means 2025 of the series in 01_Validation/Data (same data as the validation).
# - S1 capacities = the 2025 system of the validation (01_Validation/validate.py, HIST_GW 2025):
#   thermal + hydro = max. hourly generation 2025, wind = installed capacity 2025 (SMARD, DE-LU).
#   Values are divided by the plant availability, because plant_table multiplies by it again,
#   so the usable capacity equals the observed value.
# - PHS and batteries: the PHS row in the plant file carries a 1 MW placeholder and the two
#   battery rows are copies of it, so all three need a capacity row in every scenario.


# ---------------------------------------------------------------------------
# Accessors for inputs from assumptions table
# ---------------------------------------------------------------------------


def par(sc, name, default=None):
    hit = ASSUMPTIONS[(ASSUMPTIONS.scenario == sc) & (ASSUMPTIONS.parameter == name)]
    return default if hit.empty else float(hit.value.iloc[0])
# par function is a search tool "give me parameter x in scenario y, or default if not found"


def group(sc, prefix):
    rows = ASSUMPTIONS[(ASSUMPTIONS.scenario == sc)
                       & ASSUMPTIONS.parameter.str.startswith(prefix)]
    return {p[len(prefix):]: float(v) for p, v in zip(rows.parameter, rows.value)}
# group function is a search tool: all parameters of scenario y that start with a prefix, e.g. 'cap.'


def carrier_mask(data, carrier):
    return data.carrier2 == carrier
# boolean mask over the plant rows of one carrier, e.g. 'Natural gas'


# ---------------------------------------------------------------------------
# Accessors for inputs from excel files
# ---------------------------------------------------------------------------


RES = ['Wind offshore', 'Wind onshore', 'Photovoltaics']
# Just a list of the renewable carriers, used to sum their output and profiles.


def datetime_index(frame, label):
    """Returns the frame with a real DatetimeIndex, whatever the export wrote.

    The SMARD exports are not written consistently: the 2019-2024 sheets carry
    Excel dates, the 2025 sheets carry strings such as 'Jan 1, 2025 12:00 AM'.
    A sheet or file that mixes both leaves pandas with an object index, which
    has neither .year nor partial string indexing, so it is parsed explicitly.
    """
    if isinstance(frame.index, pd.DatetimeIndex):
        return frame
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        idx = pd.to_datetime(frame.index, format='mixed', errors='coerce')
    if idx.isna().any():
        raise ValueError(f'{label}: index is not a usable date '
                         f'({frame.index[idx.isna()][0]!r}); re-save it as dates')
    frame = frame.copy()
    frame.index = idx
    return frame


def year_rows(frame, year, times, label):
    """Returns the rows of one calendar year on the plain hourly model index.

    Rows of a different year are dropped (some sheets carry trailing rows of the
    previous year).
    """
    frame = datetime_index(frame, label)
    keep = frame.index.year == year
    if not keep.all():
        print(f'  {label}: dropped {int((~keep).sum())} row(s) outside {year}')
    frame = frame[keep]
    if len(frame) != len(times):
        raise ValueError(f'{label}: {len(frame)} rows in {year}, expected {len(times)}')
    frame = frame.copy()
    # The sheets are in DST local time -- one hour duplicated in October, one
    # missing in March -- so the index is replaced positionally, as in v4.
    frame.index = times
    return frame


def read_year_inputs(years):
    D = CONFIG['data_dir']
    price_all = datetime_index(
        pd.read_excel(os.path.join(D, 'Price.xlsx'), index_col=0), 'Price.xlsx')
    price_all.columns = ['Price']

    out = {}
    for year in years:
        ys = str(year)
        times = pd.date_range(f'{ys}-01-01', f'{ys}-12-31 23:00:00', freq='h')
        frames = {name: year_rows(
            pd.read_excel(os.path.join(D, f), index_col=0, sheet_name=ys),
            year, times, f'{f} [{ys}]')
            for name, f in [('load', 'Load.xlsx'), ('hydro', 'Actual gen.xlsx'),
                            ('pu', 'Weather_profiles.xlsx')]}

        pu = frames['pu'].copy()
        pu['Hydro'] = frames['hydro']['Hydro'] / frames['hydro']['Hydro'].max()   # v4 line 237

        py = price_all[price_all.index.year == year]
        if py.empty:
            raise ValueError(f'Price.xlsx: no rows for {ys}')
        sel = py[py < 0].groupby(py.index.hour).mean().replace(np.nan, 0.0)
        floor = pd.Series(sel.loc[times.hour, 'Price'].to_numpy(), index=times)
        # price floor: mean negative price per hour of day of the weather year (bid of old wind/PV and must-run)

        out[year] = dict(times=times, load=frames['load'], pu=pu, floor=floor)
    return out
# gives back a dictionary of dictionaries, each year has its own dictionary with times, load, pu, floor


def build_load(yi, sc):
    # SMARD load only: the observed pumping is NOT added, the model's pumped storage pumps itself
    load = yi['load']['Load']
    demand = par(sc, 'demand')
    if demand is not None:
        # flexible demand (electrolysis, district heating) is price-driven and not part of the
        # fixed load profile, so it is subtracted before the SMARD shape is rescaled
        demand -= par(sc, 'flex_demand', 0.0)
        load = load * (demand / (load.sum() / 1e6))
    return load
# returns the load series for one year and one scenario, scaled to the scenario demand if present.


def plant_table(sc, pv_mw):
    """Returns the plant table with scenario capacities applied; capacity in MW."""
    data = pd.read_csv(os.path.join(CONFIG['data_dir'], 'corrected_power_plants.csv'), index_col=0)
    if CONFIG['only_operating']:
        data = data[data.status == 'operating'].copy()

    data['max_hours'] = 0.0                       # 0 = generator, > 0 = storage
    hours = dict(group(sc, 'hours.'), PHS=CONFIG['phs_hours'])
    for tech, eff in CONFIG['storage_efficiency'].items():
        if tech != 'PHS':
            data.loc[tech] = data.loc['PHS']      # v4 lines 130-139: copy PHS, then override
            data.loc[tech, 'carrier2'] = tech
        data.loc[tech, 'efficiency'] = eff
        data.loc[tech, 'max_hours'] = hours[tech]

    # hydrogen plants (NEP 2037): copies of the gas fleet, burning hydrogen without CO2 and without must-run
    if par(sc, 'cap.Hydrogen'):
        h2 = data[carrier_mask(data, 'Natural gas')].copy()
        h2.index = 'H2 ' + h2.index.astype(str)
        h2['carrier2'] = 'Hydrogen'
        h2['emission_factor'] = 0.0
        h2['mustrun'] = 0.0                           # peakers, no must-run
        data = pd.concat([data, h2])

    for carrier, gw in group(sc, 'cap.').items():
        mask = carrier_mask(data, carrier)
        installed = data.loc[mask, 'capacity'].sum()
        if installed > 0:                          # carrier absent from the plant list -> skip
            data.loc[mask, 'capacity'] *= gw * 1e3 / installed

    # Plain .loc assignment: v4 lines 180-181 use chained assignment, which pandas
    # copy-on-write writes to a temporary and discards, so v4 never derates at all.
    data.loc[:, 'capacity'] *= data['availability']
    # PV is set after the derating so potential output is exactly pi % of load.
    data.loc['Photovoltaics', 'capacity'] = pv_mw
    data.loc[:, 'mustrun'] *= data['capacity'] * par(sc, 'mustrun_factor')
    for carrier, gw in group(sc, 'mustrun.').items():
        m = data.carrier2 == carrier
        data.loc[m, 'mustrun'] = data.loc[m, 'capacity'] * min(gw * 1e3 / data.loc[m, 'capacity'].sum(), 1.0)
    # mustrun.<carrier> (GW): observed minimum output of a carrier without must-run in the plant
    # list, e.g. bioenergy (EEG plants run flat), spread over its plants by capacity

    return data
# plant list (operating plants) + storage rows, scaled to the scenario capacities, derated by
# availability, PV set from the penetration grid, must-run in MW


def marginal_costs_table(data, sc, yi, fuel_hourly=None):
    """Returns the hourly marginal cost per plant in EUR/MWh_el.

    fuel_hourly: optional, only used by the validation (01_Validation/validate.py).
    DataFrame with hourly 'Hard coal', 'Natural gas', 'Oil' and 'ETS' prices that
    replace the scalar fuel and CO2 prices. None = scenario behaviour, unchanged.
    """
    costs = pd.read_excel(os.path.join(CONFIG['data_dir'], 'model costs.xlsx'), index_col=0)
    fuel = data['fuel'].astype(float).copy()

    for tech in costs.index:
        fuel[data.carrier2 == tech] = costs.loc[tech, 'fuel']
    for tech, price in group(sc, 'fuel.').items():
        fuel[carrier_mask(data, tech)] = price
    # fuel price per plant, later sources overwrite earlier ones: plant file < model costs.xlsx < ASSUMPTIONS

    if fuel_hourly is None:
        mc = (data['VOM'] + fuel / data['efficiency']
              + data['emission_factor'] * par(sc, 'co2_price') / data['efficiency'])
        mc[data['efficiency'] == 1] = 0.0
        # static marginal costs in EUR/MWh_el (VOM + fuel + CO2)

        mcosts = pd.DataFrame(0.0, index=yi['times'], columns=data.index)
        mcosts[:] = mc.to_numpy()
        # hourly marginal cost per plant in EUR/MWh_el: rows = hours, columns = plants
    else:
        # validation only (as in v0): observed hourly coal/gas/oil and CO2 prices
        fuel_h = pd.DataFrame(np.tile(fuel.to_numpy(dtype=float), (len(yi['times']), 1)),
                              index=yi['times'], columns=data.index)
        for carrier in ['Hard coal', 'Natural gas', 'Oil']:
            cols = data.index[data.carrier2 == carrier]
            fuel_h[cols] = np.tile(fuel_hourly[carrier].to_numpy()[:, None], (1, len(cols)))
        eff = data['efficiency'].to_numpy(dtype=float)
        co2 = np.outer(fuel_hourly['ETS'].to_numpy(), data['emission_factor'].to_numpy(dtype=float) / eff)
        mcosts = pd.DataFrame(data['VOM'].to_numpy(dtype=float) + fuel_h.to_numpy() / eff + co2,
                              index=yi['times'], columns=data.index)
        mcosts.loc[:, (data['efficiency'] == 1).to_numpy()] = 0.0

    gas = data.index[data.carrier2.isin(['Natural gas', 'Hydrogen']) & (data.capacity > 0)]
    import_cost = mcosts[gas].max(axis=1) + 1.0 if len(gas) else pd.Series(CONFIG['voll_price'], index=yi['times'])
    # import price (last resort): 1 EUR/MWh above the most expensive gas/H2 plant

    for col, x in CONFIG['tiebreak'].items():
        mcosts[col] -= x
    # tie-breaker: PV slightly cheaper than wind, so PV is dispatched first

    mcosts['Import'] = import_cost.to_numpy()   # extra column, used by build_network only
    return mcosts
# hourly marginal cost per plant (EUR/MWh_el)


# ---------------------------------------------------------------------------
# PyPSA network builder, hourly price, and one run
# ---------------------------------------------------------------------------


def flex_consumers(sc):
    """{name: (capacity MW, price limit EUR/MWh, max. annual energy MWh or None)} from flex.*, wtp.*, energy.*"""
    return {k: (gw * 1e3, par(sc, f'wtp.{k}'),
                par(sc, f'energy.{k}') * 1e6 if par(sc, f'energy.{k}') is not None else None)
            for k, gw in group(sc, 'flex.').items()}


def shift_units(sc):
    """{name: (capacity MW, shift duration h)} from the shift.* and shift_hours.* rows."""
    return {k: (gw * 1e3, par(sc, f'shift_hours.{k}')) for k, gw in group(sc, 'shift.').items()}


def build_network(data, mcosts, load, yi, import_mw=0.0, flex=None, shift=None):
    times, pu = yi['times'], yi['pu']
    n = pypsa.Network()
    n.set_snapshots(times)                           # all hours of the year
    n.add('Bus', 'DE0 0')                            # one node: Germany, no grid
    n.add('Load', 'DE0 0', bus='DE0 0', p_set=load)  # fixed load (build_load)

    for idx in data.index:
        if data.loc[idx, 'max_hours'] > 0:           # storage (PHS, batteries)
            n.add('StorageUnit', f'DE0 {idx}', bus='DE0 0', carrier=str(idx),
                  p_nom=data.loc[idx, 'capacity'], max_hours=data.loc[idx, 'max_hours'],
                  marginal_cost=CONFIG['battery_cycle_cost'].get(idx, CONFIG['storage_marginal_cost']),
                  efficiency_dispatch=data.loc[idx, 'efficiency'],
                  efficiency_store=data.loc[idx, 'efficiency'],
                  state_of_charge_set=np.full(len(times), np.nan))
        else:                                        # generator
            carrier = data.loc[idx, 'carrier2']
            cap = data.loc[idx, 'capacity']
            n.add('Generator', f'DE0 {idx}', bus='DE0 0', carrier=carrier,
                  p_nom=cap, marginal_cost=mcosts[idx].to_numpy(),
                  p_max_pu=pu[carrier].to_numpy() if carrier in pu.columns else 1.0,
                  p_min_pu=data.loc[idx, 'mustrun'] / cap if cap > 0 else 0.0)
            # must-run (CHP, system services) runs in every hour, even when RES is curtailed

    n.add('Generator', 'DE0 VOLL', bus='DE0 0', carrier='VOLL',
          marginal_cost=pd.Series(CONFIG['voll_price'], index=times),
          p_nom=CONFIG['voll_p_nom'])
    # backstop generator at the price ceiling, keeps every run feasible

    if import_mw > 0:
        # imports as last resort (price from marginal_costs_table): they only run when domestic
        # plants and storage are exhausted, instead of the 1000 EUR backstop
        n.add('Generator', 'DE0 Import', bus='DE0 0', carrier='Import', p_nom=import_mw,
              marginal_cost=mcosts['Import'].to_numpy())

    for name, (cap_mw, wtp, energy_mwh) in (flex or {}).items():
        # flexible consumer as a bidder: a 'negative generator' that consumes up to cap_mw
        # whenever power is cheaper than its price limit (willingness to pay) wtp;
        # energy_mwh optionally caps its annual consumption (e.g. finite district heat demand)
        n.add('Generator', f'DE0 Flex {name}', bus='DE0 0', carrier='Flex', p_nom=cap_mw,
              p_min_pu=-1.0, p_max_pu=0.0, marginal_cost=wtp,
              e_sum_min=-energy_mwh if energy_mwh is not None else -np.inf)

    for name, (cap_mw, hours) in (shift or {}).items():
        # shiftable demand (e.g. industrial DSM) as loss-free storage: the same energy is consumed,
        # only earlier or later ("charging" = consuming earlier, "discharging" = consuming less later)
        n.add('StorageUnit', f'DE0 Shift {name}', bus='DE0 0', carrier='Shift', p_nom=cap_mw,
              max_hours=hours, efficiency_store=1.0, efficiency_dispatch=1.0,
              marginal_cost=CONFIG['storage_marginal_cost'],
              state_of_charge_set=np.full(len(times), np.nan))

    n.dynamic('StorageUnit')['state_of_charge_set'].loc[times[-1]] = 0.0
    # storage ends the year empty, so no energy is created or lost over the year

    return n
# unsolved one-node network for one run


def bids(n, ramp_markup=None):
    """Hourly bid of every generator (EUR/MWh) and its must-run (MW)."""
    ramp_markup = CONFIG['ramp_markup'] if ramp_markup is None else ramp_markup
    p = n.generators_t.p
    static = n.generators['marginal_cost'].reindex(p.columns).to_numpy(dtype=float)
    mc = pd.DataFrame(np.tile(static, (len(p), 1)), index=p.index, columns=p.columns)
    varying = n.generators_t.marginal_cost
    if len(varying.columns):
        mc[varying.columns] = varying
    # marginal cost of every generator in every hour (static values, overwritten by hourly ones)

    mustrun = n.generators['p_min_pu'].reindex(p.columns).to_numpy() * n.generators['p_nom'].reindex(p.columns).to_numpy()
    carrier = n.generators.carrier.reindex(p.columns)
    fossil = carrier.isin(['Lignite', 'Hard coal', 'Natural gas', 'Oil', 'Hydrogen']).to_numpy()
    thermal = (p.loc[:, fossil] - mustrun[fossil]).clip(lower=0).sum(axis=1) / 1e3
    ramp = (thermal - thermal.shift(CONFIG['ramp_hours'])).fillna(0).clip(lower=0)
    bidders = fossil | (carrier == 'Bioenergy').to_numpy()
    mc.loc[:, bidders] = mc.loc[:, bidders].mul(1 + ramp_markup * ramp, axis=0)
    # ramp markup: thermal plants bid above marginal cost when the fleet ramps up (GW over the last
    # ramp_hours); plants started for a few peak hours recover their start-up costs
    return mc, mustrun


def hourly_price(n, floor, rules=None):
    """Hourly market price of one solved network (storage never sets the price).
    Returns the price, the surplus hours (curtailed or covered down to the must-run) and the
    storage-bid sensitivity price (storage charging in a covered hour sets the price).
    rules: optional overrides (03_Sensitivity/ only): covered_price, new_res_bid, floor_factor, ramp_markup."""
    r = dict(covered_price=CONFIG['covered_price'], new_res_bid=CONFIG['new_res_bid'], floor_factor=1.0,
             ramp_markup=CONFIG['ramp_markup'])
    r.update(rules or {})
    p = n.generators_t.p
    g = n.generators
    mc, mustrun = bids(n, r['ramp_markup'])

    # 1) normal hour: the most expensive generator running above its must-run sets the price
    #    (the must-run part is sold at any price and never sets the price)
    buyers = g.carrier == 'Flex'                     # flexible consumers buy, never sell
    running = (p > mustrun + CONFIG['running_threshold']) & ~buyers.reindex(p.columns).to_numpy()
    price = mc.where(running).max(axis=1)
    # flexible consumers are buyers: they set the price only through rule 2, never as 'running generators'

    # 2) a flexible consumer that runs only partly is the last buyer and sets the price at its bid:
    #    the price limit, minus the shadow price of its annual energy cap if that cap binds
    #    (a capped consumer saves its limited energy for the cheapest hours, so it bids lower);
    #    one that runs at full power would buy less above its bid, so its bid caps the price
    flex_buying = pd.Series(False, index=p.index)
    for c in g.index[buyers]:
        cap = g.at[c, 'p_nom']
        bid = g.at[c, 'marginal_cost'] - energy_cap_value(n, c)
        buying = p[c] < -CONFIG['running_threshold']
        partly = buying & (p[c] > -cap + CONFIG['running_threshold'])
        price[partly] = bid
        price[buying & ~partly] = price[buying & ~partly].clip(upper=bid)
        flex_buying |= buying

    # wind/PV in every hour: available, curtailed, and the part from new plants (built after 2025)
    res = g.index[g.carrier.isin(RES)]
    available = n.get_switchable_as_dense('Generator', 'p_max_pu')[res] * g.loc[res, 'p_nom']
    curtailment = (available - p[res]).sum(axis=1)
    old_mw = g.loc[res, 'carrier'].map(CONFIG['res_fleet_2025']) * 1e3
    new_share = ((g.loc[res, 'p_nom'] - old_mw).clip(lower=0) / g.loc[res, 'p_nom']).fillna(0)
    new_available = (available * new_share).sum(axis=1)

    curtailed = curtailment > CONFIG['curtail_threshold']
    res_marginal = (price <= 0) | price.isna()      # only wind/PV, must-run and storage running

    # 3) wind/PV cover the load down to must-run + hydro + waste, nothing curtailed (storage takes
    #    the rest; in reality it pumps with the RES surplus): low positive price covered_price,
    #    unless a flexible consumer buys (then the surplus has a paying buyer, see 2)
    residual = n.loads_t.p_set.sum(axis=1) - p[res].sum(axis=1)
    inflexible = np.clip(mustrun, 0, None).sum() + p[g.index[g.carrier.isin(['Hydro', 'Waste'])]].sum(axis=1)
    covered = (residual <= inflexible) & ~flex_buying & ~curtailed & ~res_marginal
    price[covered] = r['covered_price']

    # 4) wind/PV curtailed or setting the price: new plants bid new_res_bid and curtail first;
    #    if the surplus is larger than their output, old plants (market premium) and must-run
    #    set the price at the negative floor
    low = curtailed | res_marginal
    new_sets = (new_available > CONFIG['curtail_threshold']) & (curtailment <= new_available)
    price[low] = floor[low] * r['floor_factor']
    price[low & new_sets] = r['new_res_bid']

    # sensitivity: storage charging in a covered hour is the last buyer and bids its break-even
    # (= shadow price of the energy balance under perfect foresight) instead of covered_price
    charging = (n.storage_units_t.p < -CONFIG['running_threshold']).any(axis=1)
    storage_sets = covered & charging
    price_storage_bid = price.copy()
    price_storage_bid[storage_sets] = n.buses_t.marginal_price.iloc[:, 0][storage_sets]
    return price, curtailed | covered, price_storage_bid


def energy_cap_value(n, c):
    """EUR/MWh value of consumer c's annual energy cap (0 if it has none or it does not bind)."""
    if not np.isfinite(n.generators.at[c, 'e_sum_min']):
        return 0.0
    name = 'Generator-e_sum_min'
    if name not in n.model.constraints:
        return 0.0
    return abs(float(n.model.constraints[name].dual.sel(name=c).item()))


def home_storage_load(pv, mw, hours, eff):
    """MW that home + commercial storage adds to the load: no market trading, fixed daily rule
    (self-consumption). Charges from PV in the morning until full, then covers household use
    evenly over the night (18-6 h, as households draw it), empty again the next morning."""
    charge = np.zeros(len(pv))
    discharge = np.zeros(len(pv))
    hour = pv.index.hour.to_numpy()
    night = np.isin(hour, CONFIG['home_discharge_hours'])
    start = np.where(hour == CONFIG['home_discharge_hours'][0])[0]   # first evening hour of each day
    for s in start:
        day = range(max(s - 18, 0), s)                 # hours of this day before the evening (0-17 h)
        stored = 0.0                                   # MWh, empty in the morning
        for i in day:
            c = min(mw, pv.iat[i], (mw * hours - stored) / eff)
            charge[i] = c
            stored += c * eff
        hrs = [i for i in range(s, min(s + 12, len(pv))) if night[i]]
        discharge[hrs] = stored * eff / len(hrs)       # delivered to the household
    return pd.Series(charge - discharge, index=pv.index)


def run_point(sc, pi, yi, load, fuel_hourly=None, flex_factor=1.0, keep_price=False,
              keep_network=False, save_hourly=True):
    """One run: scenario sc, PV penetration pi (% of fixed load), one weather year; returns the result metrics.

    fuel_hourly: observed fuel prices (validation only); flex_factor: k of the sensitivity;
    keep_price: also return the hourly price series (validation time-of-day check);
    keep_network: also return the solved network and PV weights (ex-post rule variants, 03_Sensitivity/);
    save_hourly: write the hourly results file (off in 03_Sensitivity/, cases would overwrite each other).
    """
    pv_mw = (pi / 100.0) * load.sum() / yi['pu']['Photovoltaics'].sum()
    # PV capacity so that potential PV generation (before model curtailment) = pi % of the fixed load

    data = plant_table(sc, pv_mw)
    batteries = ['small-batteries', 'large-batteries']
    data.loc[batteries, 'capacity'] *= flex_factor
    shift = {k: (mw * flex_factor, h) for k, (mw, h) in shift_units(sc).items()}
    # flexibility factor k (sensitivity only, 1 = scenario as defined): scales batteries and DSM
    battery_mw = data.loc[batteries, 'capacity'].sum()
    home = data.loc['small-batteries']
    load_run = load + home_storage_load(yi['pu']['Photovoltaics'] * pv_mw, home['capacity'], home['max_hours'],
                                        CONFIG['storage_efficiency']['small-batteries'])
    data.loc['small-batteries', 'capacity'] = 0.0
    # home + commercial storage follows its self-consumption rule (charge from PV, empty in the evening)
    # and changes the load the market sees; only large batteries are optimised
    mcosts = marginal_costs_table(data, sc, yi, fuel_hourly)
    n = build_network(data, mcosts, load_run, yi, import_mw=par(sc, 'cap.Import', 0.0) * 1e3,
                      flex=flex_consumers(sc), shift=shift)
    status, condition = n.optimize(solver_name=CONFIG['solver'], solver_options=CONFIG['solver_options'], io_api='direct')
    # io_api='direct': model handed to Gurobi in memory, no LP file on disk
    if status != 'ok' or condition != 'optimal':
        raise RuntimeError(f'{sc}, PV {pi} %: solver returned {status}/{condition}')
    # stop instead of writing a failed run into the results

    p_h, surplus, p_sb = hourly_price(n, yi['floor'])    # hourly price, EUR/MWh (p_sb: storage-bid sensitivity)
    P = n.generators_t.p
    g_h = P['DE0 Photovoltaics']                         # PV fed in (after curtailment), MWh
    potential = yi['pu']['Photovoltaics'] * pv_mw        # PV before curtailment, MWh
    flex_use = -P.loc[:, n.generators.carrier == 'Flex'].sum().sum()
    w = g_h if pv_mw > 0 else yi['pu']['Photovoltaics']
    # capture price weights: PV fed in; at 0 % PV the PV profile (what the first PV module would earn)

    out = dict(penetration_pct=float(pi), scenario=SCENARIO_NAMES.get(sc, sc), scenario_key=sc,
                flex_factor=float(flex_factor),
                battery_gw=float(battery_mw / 1e3),
                dsm_gw=float(sum(mw for mw, _ in shift.values()) / 1e3),
                dsm_twh=float(n.storage_units_t.p_store.loc[:, n.storage_units.carrier == 'Shift'].sum().sum() / 1e6),
                capture_price=float((p_h * w).sum() / w.sum()),
                baseload_price=float(p_h.mean()),
                capture_price_storage_bid=float((p_sb * w).sum() / w.sum()),
                baseload_price_storage_bid=float(p_sb.mean()),
                curtailment_pct=float(100 * (1 - g_h.sum() / potential.sum())) if pv_mw > 0 else 0.0,
                hours_price_le_zero_pct=float(100 * (p_h <= 0).mean()),
                hours_surplus_binding_pct=float(100 * surplus.mean()),
                # = surplus hours (curtailed or covered down to must-run; name kept for Py_Import)
                hours_import_pct=float(100 * (P.get('DE0 Import', 0 * g_h) > CONFIG['running_threshold']).mean()),
                hours_voll_pct=float(100 * (P['DE0 VOLL'] > CONFIG['running_threshold']).mean()),
                # scarcity: hours with last-resort imports / with the 1000 EUR backstop
                pv_capacity_gw=float(pv_mw / 1e3),
                annual_load_twh=float(load.sum() / 1e6),
                flex_twh=float(flex_use / 1e6),
                pv_share_load_pct=float(100 * g_h.sum() / (load.sum() + flex_use)))
    # pv_share_load_pct: PV share = PV fed in / total load (fixed load + flexible consumption used)
    if fuel_hourly is None and save_hourly:
        # hourly results of every scenario run, for later analysis without solving again
        folder = os.path.join(CONFIG['out_dir'], 'hourly')
        os.makedirs(folder, exist_ok=True)
        pd.DataFrame({'price': p_h, 'price_storage_bid': p_sb, 'pv_fed': g_h, 'pv_potential': potential,
                      'shadow_price': n.buses_t.marginal_price.iloc[:, 0]}).round(3).to_csv(
            os.path.join(folder, f'{sc}_pv{pi:g}_y{yi["times"][0].year}_k{flex_factor:g}.csv.gz'))
    if keep_price:
        out['hourly_price'] = p_h
    if keep_network:
        out['network'], out['weights'] = n, w
    return out


# ---------------------------------------------------------------------------
# Outputs: long CSV and Excel workbooks
# ---------------------------------------------------------------------------


def write_outputs(rows):
    long = pd.DataFrame(rows).drop(columns=['coupling_import_twh', 'export_twh'], errors='ignore')   # removed coupling bound (always 0)
    os.makedirs(CONFIG['out_dir'], exist_ok=True)
    long.to_csv(os.path.join(CONFIG['out_dir'], 'v6_results_long.csv'), index=False)

    metrics = [c for c in long.columns if c not in
               ('penetration_pct', 'scenario', 'scenario_key', 'weather_year')]
    diag = long.groupby(['penetration_pct', 'scenario'], as_index=False)[metrics].mean().round(3)
    diag['capture_rate'] = (diag.capture_price / diag.baseload_price).round(3)
    diag['capture_rate_storage_bid'] = (diag.capture_price_storage_bid / diag.baseload_price_storage_bid).round(3)

    spread = (long.groupby(['penetration_pct', 'scenario'], as_index=False)['capture_price']
              .agg(capture_price_min='min', capture_price_max='max', capture_price_std='std')
              .round(3))
    diag = diag.merge(spread, on=['penetration_pct', 'scenario'], how='left')
    # spread of the capture price across the weather years

    matrix = diag.pivot(index='penetration_pct', columns='scenario', values='capture_price').round(2)
    matrix.columns.name = None
    matrix = matrix[[v for v in SCENARIO_NAMES.values() if v in matrix.columns]]

    assumptions = pd.concat([ASSUMPTIONS, pd.DataFrame(
        [('all', 'base_year', CONFIG['base_year'], CONFIG['currency'], 'no deflation applied')],
        columns=ASSUMPTIONS.columns)], ignore_index=True)

    # Py_Import: same layout as the Py_Import sheet of DE_PV_IRR_Model (columns found there by
    # header name, scenarios by label): clear A:Z there and paste this sheet as values at A1
    excel_cols = ['penetration_pct', 'scenario', 'capture_price', 'baseload_price', 'curtailment_pct',
                  'hours_price_le_zero_pct', 'hours_surplus_binding_pct', 'pv_capacity_gw',
                  'annual_load_twh', 'capture_rate', 'capture_price_min', 'capture_price_max',
                  'capture_price_std']
    py_import = diag[excel_cols + [c for c in diag.columns if c not in excel_cols]]

    path = os.path.join(CONFIG['out_dir'], 'v6_capture_price_matrix.xlsx')
    with pd.ExcelWriter(path) as writer:
        py_import.to_excel(writer, sheet_name='Py_Import', index=False)
        matrix.to_excel(writer, sheet_name='capture_price')
        diag.to_excel(writer, sheet_name='diagnostics', index=False)
        assumptions.to_excel(writer, sheet_name='assumptions', index=False)
    print(f'\nwrote {path}')
    plot_figures(diag)

    return diag


# ---------------------------------------------------------------------------
# Figures: plotting lives in plot_feasibility.py (reads the saved results only, style from
# ../thesis_style.py). Rebuild without solving: python PyPSA_model_v6.py plots
# ---------------------------------------------------------------------------

def plot_figures(diag=None):
    """Fig. 3 and the appendix figures (figA_*) from diag, or from the saved Excel if diag is None."""
    try:
        import plot_feasibility
        plot_feasibility.plot_all(diag)
    except Exception as e:   # figures only: the Excel is already written
        print(f'figures failed: {e}', flush=True)


# ---------------------------------------------------------------------------
# Run: checks (open TODO assumptions), then plots / export / main run with checkpoint
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    todo = ASSUMPTIONS[ASSUMPTIONS.source.str.contains('TODO')]
    if len(todo):
        print('=' * 76)
        print(f'NOTE: {len(todo)} assumption(s) with an open TODO (see source column):')
        for _, r in todo.iterrows():
            print(f'  [{r.scenario}] {r.parameter:<24} = {r.value:<8} {r.unit}')
        print('=' * 76)

    if len(sys.argv) > 1 and sys.argv[1] == 'plots':
        plot_figures()
        sys.exit()
    # 'python PyPSA_model_v6.py plots' only rebuilds the figures from the saved Excel files
    if len(sys.argv) > 1 and sys.argv[1] == 'export':
        long = pd.read_csv(os.path.join(CONFIG['out_dir'], 'v6_results_long.csv'))
        write_outputs(long.drop(columns='pv_share_generation_pct', errors='ignore').to_dict('records'))
        sys.exit()
    # 'python PyPSA_model_v6.py export' rebuilds Excel + figures from the saved runs (drops the old generation share)

    checkpoint = os.path.join(CONFIG['out_dir'], 'v6_results_checkpoint.csv')
    years = CONFIG['weather_years']
    scenarios = sys.argv[1:] or list(SCENARIO_NAMES)
    rows = pd.read_csv(checkpoint).to_dict('records') if os.path.exists(checkpoint) else []
    done = {(r['scenario_key'], round(r['penetration_pct'], 2), r['weather_year']) for r in rows}
    total = len(scenarios) * len(years) * len(PENETRATION_GRID)
    print(f'{total} solves, {len(done)} already in the checkpoint', flush=True)

    year_data = read_year_inputs(years)
    os.makedirs(CONFIG['out_dir'], exist_ok=True)
    failed, k, start = [], 0, time.time()
    for sc in scenarios:
        for year in years:
            load = build_load(year_data[year], sc)   # depends on scenario and year, not on penetration
            for pi in PENETRATION_GRID:
                k += 1
                if (sc, round(float(pi), 2), year) in done:
                    continue
                t = time.time()
                print(f'scenario {sc}, penetration {pi} %, year {year}, {k}/{total}', flush=True)
                try:
                    rows.append(dict(run_point(sc, pi, year_data[year], load), weather_year=year))
                except Exception as e:   # not optimal or solver error: log it, go on with the next point
                    print(f'FAILED {sc} {pi} {year}: {e}', flush=True)
                    failed.append((sc, pi, year, str(e)))
                    continue
                pd.DataFrame(rows).to_csv(checkpoint, index=False)
                print(f'  done in {time.time() - t:.0f} s', flush=True)
                gc.collect()   # frees the solved network before the next run (limited RAM)

    print(f'\nrun time {(time.time() - start) / 3600:.1f} h, {len(failed)} failed point(s): {failed}')
    write_outputs(rows)

# Data sources

Sources of all input data of the market model, split into data taken over from Abuzayed (2025) and data added
for this thesis. Every model parameter, with value, unit and source, is also listed in the `ASSUMPTIONS` table of
`02_Main_Model/Code/PyPSA_model_v6.py`. The same tables are in Appendix B4 of the thesis. References follow APA 7.

## 1. Data taken over from Abuzayed (2025)

Files of the replication package (years 2019 to 2024), used unchanged. Primary sources as named by
Abuzayed (2025a, Section 3.2 and Appendix A). The time series were extended to 2025 with the sources in Section 2.

| Data | File | Primary source |
|------|------|----------------|
| Power plant list: capacity, efficiency, emission factor | `corrected_power_plants.csv` | Open Power System Data (Wiese et al., 2019) |
| Must-run share of conventional plants | `corrected_power_plants.csv` (column `mustrun`) | EWI Merit Order Tool (Arnold et al., 2024) |
| Variable O&M and fuel cost per technology | `model costs.xlsx` | MyPyPSA-Ger (Abuzayed & Hartmann, 2022) |
| Load, generation, PV, wind and hydro profiles, installed capacity, scheduled cross-border trade | `Load.xlsx`, `Actual gen.xlsx`, `Actual_generation_All.xlsx`, `Weather_profiles.xlsx`, `Installed_capacities.xlsx`, `imports_exports_scheduled.xlsx` | SMARD (Bundesnetzagentur, n.d.) |
| Day-ahead price and EU ETS auction price | `Price.xlsx`, `ETS_DE.xlsx` | Energy-Charts (Fraunhofer ISE, 2025) |
| Fuel futures, daily close: TTF gas, API2 coal, WTI oil | `TTF_corrected.csv`, `coal_corrected.csv`, `oil_corrected.csv` | investing.com (Investing.com, 2025) |

### References

- Abuzayed, A. (2025a). *From model optimality to market reality: Do electricity markets support renewable investments?* (EPRG Working Paper No. 2521; Cambridge Working Paper in Economics No. 2558). Energy Policy Research Group, University of Cambridge. https://www.econ.cam.ac.uk/sites/default/files/publication-cwpe-pdfs/cwpe2558.pdf
- Abuzayed, A. (2025b). *Reproducibility package – From model optimality to market reality: Do electricity markets support renewable investments?* [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.16394138 (GitHub: https://github.com/AnasAbuzayed/market_value, CC BY 4.0)
- Abuzayed, A., & Hartmann, N. (2022). MyPyPSA-Ger: Introducing CO2 taxes on a multi-regional myopic roadmap of the German electricity system towards achieving the 1.5 °C target by 2050. *Applied Energy, 310*, 118576. https://doi.org/10.1016/j.apenergy.2022.118576
- Arnold, F., Junkermann, J., & Lange, M. (2024). *EWI Merit Order Tool 2023 – Dokumentation*. Energiewirtschaftliches Institut an der Universität zu Köln (EWI). https://www.ewi.uni-koeln.de/
- Bundesnetzagentur. (n.d.). *SMARD | Download market data*. Retrieved October 22, 2026, from https://www.smard.de/en/downloadcenter/download-market-data/
- Fraunhofer ISE. (2025). *Energy-Charts*. https://energy-charts.info/
- Investing.com. (2025). *Commodities*. https://www.investing.com/commodities
- Wiese, F., Schlecht, I., Bunke, W.-D., Gerbaulet, C., Hirth, L., Jahn, M., Kunz, F., Lorenz, C., Mühlenpfordt, J., Reimann, J., & Schill, W.-P. (2019). Open Power System Data – Frictionless data for electricity system modelling. *Applied Energy, 236*, 401–409. https://doi.org/10.1016/j.apenergy.2018.11.097

## 2. Own data sources

S1 = status quo 2025, S2 to S4 = NEP 2037 scenarios A to C. Data downloaded on 23 September 2026 (SMARD,
Energy-Charts, investing.com, ECB) and 25 September 2026 (Battery Charts).

| Data | File or parameter | Source |
|------|-------------------|--------|
| Model code and input data basis | `PyPSA_model_v4.py` and the files of Section 1 | Abuzayed (2025a, 2025b) |
| Load, generation, installed capacity and commercial cross-border trade 2025 | `01_Validation/Data/Sources_2025` (SMARD downloads); S1 capacities, max. hourly generation, net import, must-run minimum | SMARD (Bundesnetzagentur, n.d.) |
| Day-ahead price and EU ETS auction price 2025 | `Sources_2025` (Energy-Charts download); CO2 price S1 | Energy-Charts (Fraunhofer ISE, 2026) |
| TTF gas futures, front month, 2025 | `Sources_2025`; gas price S1 | Investing.com (n.d.-a) |
| API2 CIF ARA coal futures 2025 | `Sources_2025`; coal price S1 | Investing.com (n.d.-b) |
| WTI crude oil futures 2025 | `Sources_2025`; oil price S1 | Investing.com (n.d.-c) |
| EUR/USD exchange rate 2025 | `Sources_2025/ECB_EURUSD_daily.csv`; conversion of coal and oil prices | European Central Bank (n.d.) |
| Battery storage capacity and energy-to-power ratio 2025 | `04_BESS/Data/Sources_BESS`; S1 batteries | Battery Charts (ISEA, RWTH Aachen University, n.d.) |
| Capacities, demand, flexibility, fuel and CO2 prices 2037 | S2 to S4 scenario inputs | NEP Strom 2037/2045 (50Hertz Transmission et al., 2026) |
| Maximum shift duration of demand-side management (3 h) | DSM in S2 to S4 | Consentec et al. (2025) |
| BESS round-trip efficiency (86 %) | `bess_dispatch.py` | Schmidt & Staffell (2023, Table 3.2) |
| PV target 2030 (215 GW) | `thresholds.py`, price path anchor 2030 | EEG 2023 (2025), § 4 |
| Longer battery durations (upside case) | battery duration levers | Expert interviews (thesis, Appendix C) |
| Modelling framework and solver | all model scripts | PyPSA (Brown et al., 2018), Gurobi (Gurobi Optimization, 2025) |

### References

- 50Hertz Transmission, Amprion, TenneT TSO, & TransnetBW. (2026). *Netzentwicklungsplan Strom 2037 mit Ausblick 2045, Version 2025: Zweiter Entwurf der Übertragungsnetzbetreiber*. Übertragungsnetzbetreiber. https://www.netzentwicklungsplan.de/
- Brown, T., Hörsch, J., & Schlachtberger, D. (2018). PyPSA: Python for Power System Analysis. *Journal of Open Research Software, 6*(1), 4. https://doi.org/10.5334/jors.188
- Bundesnetzagentur. (n.d.). *SMARD | Download market data*. Retrieved October 22, 2026, from https://www.smard.de/en/downloadcenter/download-market-data/
- Consentec, Fraunhofer ISI, & Fraunhofer IEG. (2025). *Planung von Verteilnetzen der Zukunft (VN-Zukunft): Abschlussbericht* [Final report for the BMWE]. https://consentec.de/app/uploads/2025/08/Consentec_ISI_IEG_BMWK_VN-Zukunft_AbschlussBer_20250627-1.pdf
- EEG 2023. (2025). *Gesetz für den Ausbau erneuerbarer Energien (Erneuerbare-Energien-Gesetz – EEG 2023)*. https://www.gesetze-im-internet.de/eeg_2014/
- European Central Bank. (n.d.). *Euro foreign exchange reference rates: US dollar (USD)*. Retrieved September 23, 2026, from https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/eurofxref-graph-usd.en.html
- Fraunhofer ISE. (2026). *Energy-Charts*. Retrieved September 23, 2026, from https://www.energy-charts.info/
- Gurobi Optimization, LLC. (2025). *Gurobi optimizer reference manual*. https://www.gurobi.com/documentation/
- Investing.com. (n.d.-a). *Dutch TTF natural gas futures historical data*. Retrieved September 23, 2026, from https://www.investing.com/commodities/dutch-ttf-gas-c1-futures-historical-data
- Investing.com. (n.d.-b). *Coal (API2) CIF ARA (ARGUS-McCloskey) futures historical data*. Retrieved September 23, 2026, from https://www.investing.com/commodities/rotterdam-coal-futures-historical-data
- Investing.com. (n.d.-c). *Crude oil WTI futures historical data*. Retrieved September 23, 2026, from https://www.investing.com/commodities/crude-oil-historical-data
- ISEA, RWTH Aachen University. (n.d.). *Battery Charts*. Retrieved September 25, 2026, from https://battery-charts.de/de/battery-charts-de/
- Schmidt, O., & Staffell, I. (2023). *Monetizing energy storage: A toolkit to assess future cost and value*. Oxford University Press. https://doi.org/10.1093/oso/9780192888174.001.0001

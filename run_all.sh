#!/bin/sh
# Full run (~18 h): main run, robustness cases, break-even / plateau multipliers, BESS, Excel export.
#   sh run_all.sh                 starts the chain in the background (survives closing the terminal;
#                                 on macOS caffeinate keeps the machine awake); progress: tail -f run_all.log
#   sh run_all.sh --foreground    runs the chain in this terminal
#   PY=/path/to/python sh run_all.sh   use a specific Python environment
# Each step writes its own log (<folder>/Output/run_<script>.log). A failed step stops the chain (later steps
# need its output); a restart skips finished points (checkpoints).
PY=${PY:-python}
ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG="$ROOT/run_all.log"

if [ "$1" != "--foreground" ]; then
  KEEP_AWAKE=""
  command -v caffeinate > /dev/null 2>&1 && KEEP_AWAKE="caffeinate -i"
  PY="$PY" nohup $KEEP_AWAKE sh "$ROOT/run_all.sh" --foreground > /dev/null 2>&1 &
  echo "started; progress: $LOG"
  exit 0
fi

soft() {   # soft <folder> <script>: figure only, a failure is logged but does not stop the chain
  ( step "$@" ) || echo "$(date '+%F %T') (figure step failed, chain goes on)" >> "$LOG"
}

step() {   # step <folder> <script> [args]
  dir=$1; script=$2; shift 2
  echo "$(date '+%F %T') start $dir/$script $*" >> "$LOG"
  cd "$ROOT/$dir/Code" || exit 1
  mkdir -p "$ROOT/$dir/Output"
  if $PY -u -W ignore "$script" "$@" >> "$ROOT/$dir/Output/run_$(basename "$script" .py).log" 2>&1; then
    echo "$(date '+%F %T') done  $dir/$script" >> "$LOG"
  else
    echo "$(date '+%F %T') FAILED $dir/$script -> see $dir/Output/run_$(basename "$script" .py).log, chain stopped" >> "$LOG"
    exit 1
  fi
}

# 1. main run (checkpoint) and the merchant capture price
step 02_Main_Model PyPSA_model_v6.py
step 02_Main_Model merchant_capture_price.py
# 2. co-located BESS on the model prices and on observed 2025 prices
step 04_BESS bess_dispatch.py
step 04_BESS bess_dispatch.py observed
soft 04_BESS plot_bess_path.py
# 3. sensitivities: base + robustness cases at the path anchors (base check needs the main run)
step 03_Sensitivity sensitivities.py
# 4. multiplier per lever (break-even or plateau, IRR replica), then thresholds.xlsx with these cases
step 03_Sensitivity breakeven.py
step 03_Sensitivity thresholds.py
# 5. BESS in the break-even lever cases
step 04_BESS bess_lever_hourly.py
step 04_BESS bess_dispatch.py lever
# 6. Excel export for the IRR model
step 06_Excel_Export export_excel.py
echo "$(date '+%F %T') ALL DONE" >> "$LOG"

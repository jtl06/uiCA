#!/bin/bash
# Re-score a set of random loops with the current model: drops the cached predictions of this repository's uiCA (keeps those of stock
# uiCA and llvm-mca, which do not change) and runs fuzz_report.py.   Usage: rescore.sh SET [-details]
set -e
cd "$(dirname "$0")/.."
SET=$1; shift
M=measurements/fuzz
PY=${PYTHON:-~/uica-zen/venv/bin/python}
$PY - "$M/${SET}_predictions.json" <<'P'
import json, os, sys
f = sys.argv[1]
if os.path.exists(f):
   c = json.load(open(f))
   json.dump({k: v for k, v in c.items() if not k.startswith('uiCA ')}, open(f, 'w'), indent=0)
P
args=()
[ -f $M/${SET}_zen3plus_ryzen7-7735U.json ] && args+=(ZEN3=$M/${SET}_zen3plus_ryzen7-7735U.json)
[ -f $M/${SET}_adl-p_i7-12650H.json ] && args+=(ADL-P=$M/${SET}_adl-p_i7-12650H.json)
[ -f $M/${SET}_icl-sp_xeon-6314U.json ] && args+=(ICL=$M/${SET}_icl-sp_xeon-6314U.json)
$PY fuzz/fuzz_report.py $M/$SET.json out_fuzz/$SET $M/${SET}_predictions.json "${args[@]}" "$@"

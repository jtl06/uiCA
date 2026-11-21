#!/bin/bash
# prints uiCA throughput for every zenbench loop on every Intel arch
cd "$(dirname "$0")"; V=${PYTHON:-python3}
for f in out/*.o; do case $f in *.exe.o) continue;; esac
  printf "%-22s" "$(basename $f .o)"
  for a in SNB IVB HSW BDW SKL SKX KBL CFL CLX ICL TGL RKL; do printf " %s" "$($V ../uiCA.py $f -arch $a -TPonly 2>&1 | tail -1)"; done; echo
done

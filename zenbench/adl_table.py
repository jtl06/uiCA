#!/usr/bin/env python3
"""Compare predictions for Alder Lake-P with the measurements from a Core i7-12650H P-core (measurements/adl-p_i7-12650H/, made with selftimed.py).

Columns: measured; uiCA ADL-P with the (unvalidated) front-end model; uiCA ADL-P -simpleFrontEnd; stock uiCA for RKL (the closest
microarchitecture supported upstream); llvm-mca -mcpu=alderlake.
Usage: adl_table.py dev|heldout|fold
"""
import json, os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
UICA = os.path.join(HERE, '..', 'uiCA.py')
LLVM_MCA = os.environ.get('LLVM_MCA', 'llvm-mca-22')
DIRS = {'dev': 'out', 'heldout': 'out_heldout', 'fold': 'out_fold'}

def uica(obj, *args):
   r = subprocess.run([sys.executable, UICA, obj, '-TPonly'] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
   try: return float(r.stdout.strip().splitlines()[-1])
   except Exception: return None

def mca(asm):
   r = subprocess.run([LLVM_MCA, '-mcpu=alderlake', '-iterations=1000', asm], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
   m = re.search(r'Total Cycles:\s+(\d+)', r.stdout)
   return int(m.group(1)) / 1000 if m else None

def main(setName):
   d = os.path.join(HERE, DIRS[setName])
   mdir = os.path.join(HERE, 'measurements', 'adl-p_i7-12650H')
   if os.path.exists(os.path.join(mdir, 'perf_%s.json' % setName)): # cycle counts from perf (perf_measure.py)
      measured = {k: v['cycles'] for k, v in json.load(open(os.path.join(mdir, 'perf_%s.json' % setName))).items()}
   else: # self-timed (selftimed.py)
      measured = json.load(open(os.path.join(mdir, 'measured_%s.json' % setName)))
   cols = ['uiCA ADL-P', 'ADL-P simpleFE', 'uiCA RKL', 'llvm-mca']
   print('%-16s %8s' % ('test', 'measured') + ''.join(' %15s' % c for c in cols))
   errs = {c: [] for c in cols}
   for name, t in measured.items():
      o, s = os.path.join(d, name + '.o'), os.path.join(d, name + '.s')
      preds = [uica(o, '-arch', 'ADL-P'), uica(o, '-arch', 'ADL-P', '-simpleFrontEnd'), uica(o, '-arch', 'RKL'), mca(s)]
      line = '%-16s %8.2f' % (name, t)
      for c, p in zip(cols, preds):
         if p is None: line += ' %15s' % 'fail'; continue
         e = abs(p - t) / t * 100; errs[c].append(e)
         line += ' %8.2f (%3.0f%%)' % (p, e)
      print(line)
   print('%-16s %8s' % ('mean abs error', '') + ''.join(' %14.1f%%' % (sum(errs[c]) / max(1, len(errs[c]))) for c in cols))
   print('%-16s %8s' % ('within 5%', '') + ''.join(' %12d/%-2d' % (sum(e <= 5 for e in errs[c]), len(errs[c])) for c in cols))

if __name__ == '__main__':
   main(sys.argv[1])

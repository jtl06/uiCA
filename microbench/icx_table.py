#!/usr/bin/env python3
"""Compare predictions for Ice Lake server with perf measurements from a Xeon Gold 6314U (measurements/icl-sp_xeon-6314U/perf_<set>.json).

Columns: measured; uiCA ICX (v2); uiCA ICL; stock uiCA ICL (upstream master, see fuzz/fuzz_report.py); llvm-mca -mcpu=icelake-server.
Usage: icx_table.py SET...   (SET: out, out_heldout, out_fold, out_fixes, out_rmw, out_movs, out_sf, sl, ld)
"""
import json, os, re, statistics, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
UICA = os.path.join(HERE, '..', 'uiCA.py')
STOCK = os.path.join(HERE, '..', '..', 'uiCA-master', 'uiCA.py')
OBJ = {'sl': 'out_sl', 'ld': 'out_ld'}

def uica(path, obj, arch):
   r = subprocess.run([sys.executable, path, obj, '-arch', arch, '-TPonly'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
   try: return float(r.stdout.strip().splitlines()[-1])
   except Exception: return None

def mca(asm):
   src = re.sub(r'\{(load|store)\} ', '', open(asm).read())
   r = subprocess.run(['llvm-mca-22', '-mcpu=icelake-server', '-iterations=1000'], input=src, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
   m = re.search(r'Total Cycles:\s+(\d+)', r.stdout)
   return int(m.group(1)) / 1000 if m else None

def main(sets, quiet=False):
   cols = ['ICX', 'ICL', 'stock ICL', 'llvm-mca']
   allErr = {c: [] for c in cols}
   for s in sets:
      m = json.load(open(os.path.join(HERE, 'measurements', 'icl-sp_xeon-6314U', 'perf_%s.json' % s)))
      d = os.path.join(HERE, OBJ.get(s, s)); rows = []
      for name, v in sorted(m.items()):
         obj = os.path.join(d, name + '.o')
         if not os.path.exists(obj): continue
         p = [uica(UICA, obj, 'ICX'), uica(UICA, obj, 'ICL'), uica(STOCK, obj, 'ICL'), mca(obj[:-2] + '.s')]
         rows.append((name, v['cycles'], p))
      errs = {c: [abs(r[2][i] - r[1]) / r[1] * 100 for r in rows if r[2][i] is not None] for i, c in enumerate(cols)}
      for c in cols: allErr[c] += errs[c]
      print('== %s (%d loops): mean error %s' % (s, len(rows), '  '.join('%s %.1f%%' % (c, statistics.mean(errs[c])) for c in cols if errs[c])))
      if not quiet:
         for name, t, p in rows:
            if abs(p[0] - t) / t > 0.05: print('   %-18s measured %6.2f  ICX %6.2f  stock ICL %6.2f  llvm-mca %s' % (name, t, p[0], p[2], '%.2f' % p[3] if p[3] else '-'))
   print('== all: ' + '  '.join('%s %.1f%% (%d)' % (c, statistics.mean(allErr[c]), len(allErr[c])) for c in cols if allErr[c]))

if __name__ == '__main__':
   q = '-q' in sys.argv
   main([a for a in sys.argv[1:] if a != '-q'], q)

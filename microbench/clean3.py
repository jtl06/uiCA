#!/usr/bin/env python3
"""Score uiCA ZEN3 / ADL-P / ICX on bench.py loop sets (SET=...) that were measured on all three machines: Ryzen 7 7735U (bench.py measure),
Core i7-12650H and Xeon Gold 6314U (perf_measure.py); the measurements are in measurements/. Re-predicts unless -cached.
Usage: clean3.py SET... [-cached] [-v]"""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
M = os.path.join(HERE, 'measurements')
ARCHS = [('ZEN3', 'zen3plus_ryzen7-7735U/measured_%s.json'), ('ADL-P', 'adl-p_i7-12650H/perf_%s.json'), ('ICX', 'icl-sp_xeon-6314U/perf_%s.json')]
def load(path, n=20e6):
   d = json.load(open(path))
   return {os.path.basename(k).replace('.exe', ''): (v['cycles'] if v['cycles'] < 1000 else v['cycles'] / n) for k, v in d.items()}
sets = [a for a in sys.argv[1:] if not a.startswith('-')]
tot = {a: [0, 0, 0.0] for a, _ in ARCHS}
for s in sets:
   out = os.path.join(HERE, 'out_' + s)
   for a, f in ARCHS:
      if '-cached' not in sys.argv:
         subprocess.run([sys.executable, os.path.join(HERE, 'bench.py'), 'uica', a], env=dict(os.environ, SET=s), stdout=subprocess.DEVNULL, check=True)
      m = load(os.path.join(M, f % s)); p = json.load(open(os.path.join(out, 'uica_%s.json' % a)))
      for k, c in m.items():
         if p.get(k) is None: continue
         e = abs(p[k] - c) / c; tot[a][0] += 1; tot[a][1] += e <= 0.1; tot[a][2] += e
         if '-v' in sys.argv and e > 0.1: print('  %-5s %-28s meas %6.2f pred %6.2f' % (a, k, c, p[k]))
for a, (n, ok, se) in tot.items():
   print('%-6s %3d loops: within 10%% %5.1f%%, mean error %5.1f%%' % (a, n, 100 * ok / n, 100 * se / n))

#!/usr/bin/env python3
"""Measure the loops made by bhive_gen.py with perf (standard library only; copy it to the machine together with the executables).

For each block: a smoke run (must exit normally), then REPS runs of each of the two executables (K1 and K2 inner iterations, interleaved).
cycles per iteration = (min cycles(K2) - min cycles(K1)) / (NOUTER * (K2 - K1)); likewise for instructions. 'spread': relative difference
between this and the same computation with the second-fastest runs. Output has the format of fuzz/fuzz_measure.py, for fuzz/fuzz_report.py.
Usage: real_measure.py CPU METADATA_JSON EXE_DIR OUT_JSON [REPS]
"""
import json, os, subprocess, sys

def main():
   cpu, meta, exeDir, outFile = sys.argv[1], json.load(open(sys.argv[2])), sys.argv[3], sys.argv[4]
   reps = int(sys.argv[5]) if len(sys.argv) > 5 else 3
   hybrid = os.path.exists('/sys/devices/cpu_core')
   events = 'cpu_core/cycles/u,cpu_core/instructions/u' if hybrid else 'cycles:u,instructions:u'
   n = float(meta['nouter'] * (meta['k2'] - meta['k1']))
   res = json.load(open(outFile)) if os.path.exists(outFile) else {}
   for i, loop in enumerate(meta['loops']):
      if loop['name'] in res: continue
      p = os.path.join(exeDir, loop['name'])
      try:
         r = subprocess.run(['taskset', '-c', cpu, p + '.smoke.exe'], timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
         if r.returncode != 0:
            res[loop['name']] = {'error': 'smoke run: exit status %d' % r.returncode}; continue
         vals = {'k1': [], 'k2': []}
         for _ in range(reps):
            for k in ('k1', 'k2'):
               r = subprocess.run(['taskset', '-c', cpu, 'perf', 'stat', '-x,', '-e', events, p + '.' + k + '.exe'], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, universal_newlines=True, timeout=120)
               if r.returncode != 0: raise Exception('exit status %d' % r.returncode)
               vals[k].append([float(l.split(',')[0]) for l in r.stderr.splitlines() if l and l[0].isdigit()][:2])
         for k in vals: vals[k].sort()
         c = (vals['k2'][0][0] - vals['k1'][0][0]) / n
         c2 = (vals['k2'][1][0] - vals['k1'][1][0]) / n if reps > 1 else c
         ins = (min(v[1] for v in vals['k2']) - min(v[1] for v in vals['k1'])) / n
         res[loop['name']] = {'cycles': c, 'spread': abs(c2 - c) / c if c > 0 else 1, 'instructions': ins}
      except Exception as e:
         res[loop['name']] = {'error': type(e).__name__ + ': ' + str(e)[:80]}
      if (i + 1) % 100 == 0:
         print('%d blocks done' % (i + 1), flush=True)
         json.dump(res, open(outFile, 'w'), indent=0)
   json.dump(res, open(outFile, 'w'), indent=0)
   errs = [v['error'] for v in res.values() if 'error' in v]
   print('measured %d blocks, %d failed %s' % (len(res), len(errs), sorted(set(errs))[:5]))

if __name__ == '__main__':
   main()

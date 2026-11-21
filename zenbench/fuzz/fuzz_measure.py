#!/usr/bin/env python3
"""Measure the loops made by fuzz_gen.py with perf (standard library only; copy it to the machine together with the executables).

For each loop: a short smoke run (must exit normally), then REPS full runs; cycles and instructions per iteration are recorded.
Usage: fuzz_measure.py CPU METADATA_JSON EXE_DIR OUT_JSON [REPS]
"""
import json, os, subprocess, sys

def main():
   cpu, meta, exeDir, outFile = sys.argv[1], json.load(open(sys.argv[2])), sys.argv[3], sys.argv[4]
   reps = int(sys.argv[5]) if len(sys.argv) > 5 else 3
   hybrid = os.path.exists('/sys/devices/cpu_core')
   events = 'cpu_core/cycles/u,cpu_core/instructions/u' if hybrid else 'cycles:u,instructions:u'
   n = float(meta['iterations'])
   res = {}
   for i, loop in enumerate(meta['loops']):
      p = os.path.join(exeDir, loop['name'])
      try:
         r = subprocess.run(['taskset', '-c', cpu, p + '.smoke.exe'], timeout=10)
         if r.returncode != 0:
            res[loop['name']] = {'error': 'smoke run: exit status %d' % r.returncode}; continue
         cycles, instrs = [], []
         for _ in range(reps):
            r = subprocess.run(['taskset', '-c', cpu, 'perf', 'stat', '-x,', '-e', events, p + '.exe'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               universal_newlines=True, timeout=120)
            if r.returncode != 0: raise Exception('exit status %d' % r.returncode)
            vals = [float(l.split(',')[0]) for l in r.stderr.splitlines() if l and l[0].isdigit()]
            cycles.append(vals[0] / n); instrs.append(vals[1] / n)
         cycles.sort()
         # spread: difference between the two fastest runs
         res[loop['name']] = {'cycles': cycles[0], 'spread': (cycles[1] - cycles[0]) / cycles[0] if reps > 1 else 0, 'instructions': min(instrs)}
      except Exception as e:
         res[loop['name']] = {'error': type(e).__name__ + ': ' + str(e)[:80]}
      if (i + 1) % 100 == 0:
         print('%d loops done' % (i + 1), flush=True)
         json.dump(res, open(outFile, 'w'), indent=0)
   json.dump(res, open(outFile, 'w'), indent=0)
   errs = [v['error'] for v in res.values() if 'error' in v]
   print('measured %d loops, %d failed %s' % (len(res), len(errs), sorted(set(errs))[:5]))

if __name__ == '__main__':
   main()

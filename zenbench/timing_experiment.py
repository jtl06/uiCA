#!/usr/bin/env python3
"""Can we measure cycles per iteration without performance counters (e.g., in a cloud VM)?

Method: run each loop executable and a reference loop ('dec r15; jnz l', which takes exactly one cycle per iteration) for the same number of
iterations, and divide the wall-clock times. Process start-up time is removed by subtracting the time of the same reference loop with one
iteration. Runs are interleaved and the minimum over several repetitions is used, so that both loops are timed at the same clock frequency.

This script compares the result with the cycle counts that bench.py obtained with perf.

Note: this only works if the clock frequency is the same for all runs. On a laptop whose frequency ramps up at the start of each process
(Core i7-12650H), the results were off by up to 30%. Use selftimed.py instead, which times the loops inside one warmed-up process.
Usage: timing_experiment.py [repetitions]   (run 'bench.py gen' and 'bench.py measure' for both sets first)
"""
import json, os, subprocess, sys, time
import bench

REPS = int(sys.argv[1]) if len(sys.argv) > 1 else 15
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.join(HERE, 'out_timing')
REF = '.intel_syntax noprefix\n.globl _start\n.text\n_start:\nmov r15, {n}\n.balign 64\nl:\ndec r15\njnz l\nmov eax, 60\nxor edi, edi\nsyscall\n'

def build(name, n):
   p = os.path.join(TMP, name)
   open(p + '.s', 'w').write(REF.format(n=n))
   subprocess.run(['as', p + '.s', '-o', p + '.o'], check=True)
   subprocess.run(['ld', '-o', p + '.exe', p + '.o'], check=True)
   return p + '.exe'

def wall(exe):
   t = time.perf_counter_ns()
   subprocess.run(['taskset', '-c', bench.CPU, exe], check=True)
   return time.perf_counter_ns() - t

def main():
   os.makedirs(TMP, exist_ok=True)
   ref, empty = build('ref', bench.N), build('empty', 1)
   rows = []
   for setName, tests, out in [('dev', bench.TESTS if not os.environ.get('SET') else None, os.path.join(HERE, 'out')),
                               ('heldout', bench.HELDOUT, os.path.join(HERE, 'out_heldout'))]:
      if tests is None: continue
      perf = json.load(open(os.path.join(out, 'measured.json')))
      for name in tests:
         exe = os.path.join(out, name + '.exe')
         tLoop, tRef, tEmpty = [], [], []
         for _ in range(REPS):
            tEmpty.append(wall(empty)); tRef.append(wall(ref)); tLoop.append(wall(exe))
         est = (min(tLoop) - min(tEmpty)) / (min(tRef) - min(tEmpty))
         rows.append((setName, name, perf[name]['cycles'], est))
   print('%-8s %-15s %8s %8s %7s' % ('set', 'test', 'perf', 'timing', 'err%'))
   errs = []
   for setName, name, p, e in rows:
      errs.append(abs(e - p) / p * 100)
      print('%-8s %-15s %8.3f %8.3f %7.2f' % (setName, name, p, e, errs[-1]))
   errs.sort()
   print('timing vs perf over %d loops: mean abs error %.2f%%, median %.2f%%, max %.2f%%' % (len(errs), sum(errs) / len(errs), errs[len(errs) // 2], errs[-1]))
   json.dump({name: e for _, name, _, e in rows}, open(os.path.join(TMP, 'timing.json'), 'w'), indent=1)

if __name__ == '__main__':
   main()

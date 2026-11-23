#!/usr/bin/env python3
"""mb.py LOOPS_FILE OUTDIR CPU [build|measure|both]: small hand-written loops. LOOPS_FILE: one loop per line, 'name: instr; instr; ...'
(Intel syntax, vector registers initialized from memory like the random loops). build: assemble; measure: perf (cycles per iteration,
best of 3) -> OUTDIR/meas.json. Run measure under an exclusive lease."""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'fuzz'))
N = 10_000_000
loopsFile, out, cpu = sys.argv[1], sys.argv[2], sys.argv[3]
mode = sys.argv[4] if len(sys.argv) > 4 else 'both'
os.makedirs(out, exist_ok=True)
loops = []
for line in open(loopsFile):
   line = line.strip()
   if not line or line.startswith('#'): continue
   name, body = line.split(':', 1)
   loops.append((name.strip(), [x.strip() for x in body.split(';') if x.strip()]))
if mode in ('build', 'both'):
   import fuzz_gen
   for name, lines in loops:
      p = os.path.join(out, name)
      vm = 'avx' if any('YMM' in l.upper() or l.upper().startswith('V') for l in lines) else ('sse' if any('XMM' in l.upper() for l in lines) else 'int')
      open(p + '.s', 'w').write('.intel_syntax noprefix\nl:\n' + '\n'.join(lines) + '\ndec r15\njnz l\n')
      subprocess.run(['as', p + '.s', '-o', p + '.o'], check=True)
      open(p + '.exe.s', 'w').write(fuzz_gen.EXE.format(vecInit=fuzz_gen.VEC_INIT[vm], body='\n'.join(lines)))
      subprocess.run(['as', '--defsym', 'NITER=%d' % N, p + '.exe.s', '-o', p + '.exe.o'], check=True)
      subprocess.run(['ld', '-o', p + '.exe', p + '.exe.o'], check=True)
if mode in ('measure', 'both'):
   hybrid = os.path.exists('/sys/devices/cpu_core')
   ev = 'cpu_core/cycles/u' if hybrid else 'cycles:u'
   res = {}
   for name, lines in loops:
      best = None
      for _ in range(3):
         r = subprocess.run(['taskset', '-c', cpu, 'perf', 'stat', '-x,', '-e', ev, os.path.join(out, name + '.exe')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
         c = float(r.stderr.split(',')[0]) / N
         best = c if best is None else min(best, c)
      res[name] = best
      print('%-12s %6.2f  %s' % (name, best, '; '.join(lines)), flush=True)
   import socket; json.dump(res, open(os.path.join(out, 'meas_' + socket.gethostname() + '.json'), 'w'), indent=0)

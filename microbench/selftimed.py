#!/usr/bin/env python3
"""Self-timed loop executables: cycles per iteration without performance counters, independent of the clock frequency.

Each executable warms up the core, then runs  reference loop / test loop / reference loop  back to back and reads the time-stamp counter
in between. The reference loop ('dec r15; jnz', one cycle per iteration) and the test loop run for the same number of iterations, so
   cycles per iteration = TSC ticks of the test loop / mean TSC ticks of the two reference loops,
and a difference between the two reference runs shows a frequency drift during the measurement. Nothing but the loops is timed, so process
start-up and frequency ramp-up do not matter (unlike in timing_measure.py).

Usage: selftimed.py gen OUTDIR            build executables for all loop sets of bench.py into OUTDIR/<set>/
       selftimed.py run CPU REPS OUT_JSON EXE...   (standard library only; can be copied to another machine together with the executables)
"""
import json, os, struct, subprocess, sys

N = int(os.environ.get('SELFTIMED_N', 400_000_000))
WARM = int(os.environ.get('SELFTIMED_WARM', 4_000_000_000))
RDTSC = 'lfence\nrdtsc\nshl rdx, 32\nor rax, rdx\nmov [rip+res+{off}], rax\n'
EXE = '''.intel_syntax noprefix
.globl _start
.bss
.balign 4096
buf: .skip 8192
res: .skip 32
.text
_start:
mov r15, {warm}
.balign 64
w:
dec r15
jnz w
''' + RDTSC.format(off=0) + '''mov r15, {n}
.balign 64
ra:
dec r15
jnz ra
''' + RDTSC.format(off=8) + '''xor eax, eax
xor ebx, ebx
xor ecx, ecx
xor edx, edx
xor edi, edi
xor r8d, r8d
xor r9d, r9d
lea rsi, [rip+buf]
{init}
mov r15, {n}
.balign 64
l:
{body}
dec r15
jnz l
''' + RDTSC.format(off=16) + '''mov r15, {n}
.balign 64
rb:
dec r15
jnz rb
''' + RDTSC.format(off=24) + '''mov eax, 1
mov edi, 1
lea rsi, [rip+res]
mov edx, 32
syscall
mov eax, 60
xor edi, edi
syscall
'''

def gen(outDir):
   import bench
   for setName, tests in [('dev', bench.__dict__.get('DEV', None) or DEV_TESTS(bench)), ('heldout', bench.HELDOUT), ('fold', bench.FOLD)]:
      d = os.path.join(outDir, setName)
      os.makedirs(d, exist_ok=True)
      for name, (init, body) in tests.items():
         p = os.path.join(d, name)
         open(p + '.s', 'w').write(EXE.format(warm=WARM, n=N, init=init, body=body))
         subprocess.run(['as', p + '.s', '-o', p + '.o'], check=True)
         subprocess.run(['ld', '-o', p + '.exe', p + '.o'], check=True)
         os.remove(p + '.o')

def DEV_TESTS(bench):
   # bench.TESTS is replaced when SET is given; the development set is the one with 'add_indep6'
   assert 'add_indep6' in bench.TESTS, 'run without SET'
   return bench.TESTS

def run(cpu, reps, outFile, exes):
   res = {}
   worstDrift = 0
   for exe in exes:
      vals = []
      for _ in range(reps):
         out = subprocess.run(['taskset', '-c', cpu, exe], check=True, stdout=subprocess.PIPE, timeout=300).stdout
         t0, t1, t2, t3 = struct.unpack('<4Q', out)
         refA, loop, refB = t1 - t0, t2 - t1, t3 - t2
         vals.append((loop / ((refA + refB) / 2), abs(refA - refB) / refA * 100))
      vals.sort()
      c, drift = vals[len(vals) // 2]
      worstDrift = max(worstDrift, drift)
      name = os.path.basename(exe)[:-len('.exe')]
      res[name] = c
      print('%-18s %7.3f   (runs: %s; reference drift %.2f%%)' % (name, c, ' '.join('%.3f' % v for v, _ in vals), drift), flush=True)
   print('largest reference drift: %.2f%%' % worstDrift)
   json.dump(res, open(outFile, 'w'), indent=1)

if __name__ == '__main__':
   if sys.argv[1] == 'gen': gen(sys.argv[2])
   elif sys.argv[1] == 'run': run(sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5:])

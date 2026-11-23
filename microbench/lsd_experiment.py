#!/usr/bin/env python3
"""Loop stream detector (LSD) experiment for Intel CPUs: K nops + 'dec r15; jnz' for K = 0..MAXK, i.e., loops with K+1 fused-domain uops.

'gen DIR' builds the executables; they are measured with perf_measure.py (cycles per iteration and the share of uops delivered by the LSD).
If the LSD issues the uops of U unrolled iterations of an n-uop loop without crossing the end of the unrolled body, the loop needs
ceil(U*n/issueWidth)/U cycles per iteration; 'fit JSON ISSUEWIDTH' finds the U that explains each measurement best.
"""
import json, math, os, subprocess, sys
N = 50_000_000
MAXK = 44
T = '.intel_syntax noprefix\n.globl _start\n.text\n_start:\nmov r15, %d\n.balign 64\nl:\n%sdec r15\njnz l\nmov eax, 60\nxor edi, edi\nsyscall\n'

def gen(d):
   os.makedirs(d, exist_ok=True)
   for k in range(MAXK + 1):
      p = os.path.join(d, 'nop%02d' % k)
      open(p + '.s', 'w').write(T % (N, 'nop\n' * k))
      subprocess.run(['as', p + '.s', '-o', p + '.o'], check=True); subprocess.run(['ld', '-o', p + '.exe', p + '.o'], check=True); os.remove(p + '.o')

def fit(jsonFile, width):
   m = json.load(open(jsonFile))
   table = {}
   for name in sorted(m):
      n = int(name[3:]) + 1; v = m[name]; c = v['cycles']; lsd = v['lsd.uops'] / max(1e-9, v['uops_issued.any'])
      best = min(range(1, 80), key=lambda u: (abs(math.ceil(u * n / width) / u - c), u))
      err = abs(math.ceil(best * n / width) / best - c)
      print('n=%2d uops: %.3f cycles/iter, LSD share %.2f, ideal %.3f -> unroll %2d (%.3f, off by %.3f)' % (n, c, lsd, max(1, n / width), best, math.ceil(best * n / width) / best, err))
      if lsd > 0.9 and err < 0.02: table[n] = best
   print('LSDUnrolling =', table)

if __name__ == '__main__':
   if sys.argv[1] == 'gen': gen(sys.argv[2])
   else: fit(sys.argv[2], int(sys.argv[3]))

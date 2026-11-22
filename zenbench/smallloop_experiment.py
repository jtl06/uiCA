#!/usr/bin/env python3
"""Small loops on Intel P-cores: does the number of loads change how fast a loop of n fused-domain uops is delivered?

Loops of L loads ('mov rX, [rsi+64*i]') and F independent ALU or vector instructions, plus 'dec r15; jnz' (one fused uop), for
n = L + F + 1 = 3..8. 'gen DIR' builds the executables (50M iterations); they are measured with perf_measure.py.
"""
import os, subprocess, sys
N = 50_000_000
GPRS = ['rax', 'rbx', 'rcx', 'rdx', 'rdi', 'rbp', 'r8', 'r9', 'r10', 'r11', 'r12', 'r13']
T = '.intel_syntax noprefix\n.globl _start\n.bss\n.balign 4096\nbuf: .skip 8192\n.text\n_start:\nlea rsi, [rip+buf]\nmov r15, %d\n.balign 64\nl:\n%s\ndec r15\njnz l\nmov eax, 60\nxor edi, edi\nsyscall\n'
def body(loads, fill, kind):
   lines = ['mov %s, qword ptr [rsi+%d]' % (GPRS[i], 64 * i) for i in range(loads)]
   for j in range(fill):
      if kind == 'alu': lines.append('or %s, r14' % GPRS[loads + j])
      else: lines.append('vpaddd xmm%d, xmm%d, xmm14' % (j, j))
   return '\n'.join(lines)
def gen(d):
   os.makedirs(d, exist_ok=True)
   for n in range(3, 9):
      for loads in range(0, 4):
         for kind in ('alu', 'vec'):
            fill = n - 1 - loads
            if fill < 0 or (kind == 'vec' and fill == 0 and loads == 0): continue
            name = 'n%d_l%d_%s' % (n, loads, kind)
            p = os.path.join(d, name)
            open(p + '.s', 'w').write(T % (N, body(loads, fill, kind)))
            subprocess.run(['as', p + '.s', '-o', p + '.o'], check=True); subprocess.run(['ld', '-o', p + '.exe', p + '.o'], check=True); os.remove(p + '.o')
if __name__ == '__main__':
   gen(sys.argv[2])

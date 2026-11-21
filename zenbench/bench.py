#!/usr/bin/env python3
"""Micro-benchmarks for validating uiCA's AMD model.

Each test is a loop body. For every test we build
  * <name>.o    - object file with only the loop (input for uiCA)
  * <name>.s    - the same loop as assembly text (input for llvm-mca)
  * <name>.exe  - a static executable that runs the loop N times (measured with perf)

Usage: bench.py gen | measure | mca | uica <ARCH> | table <ARCH>
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out')
UICA = os.path.join(HERE, '..', 'uiCA.py')
N = 50_000_000
CPU = '2'
LLVM_MCA = os.environ.get('LLVM_MCA', 'llvm-mca-22')

# name -> (init code run once before the loop, loop body). rsi points to a zeroed 8 KiB buffer.
TESTS = {
   'add_indep6':   ('', 'add rax, 1\nadd rbx, 1\nadd rcx, 1\nadd rdx, 1\nadd rdi, 1\nadd r8, 1'),
   'add_chain4':   ('', 'add rax, rbx\nadd rax, rbx\nadd rax, rbx\nadd rax, rbx'),
   'imul_chain2':  ('mov rax, 1\nmov rbx, 1', 'imul rax, rbx\nimul rax, rbx'),
   'imul_indep3':  ('mov r8, 3', 'imul rax, r8, 5\nimul rbx, r8, 5\nimul rcx, r8, 5'),
   'shl_indep4':   ('', 'shl rax, 1\nshl rbx, 1\nshl rcx, 1\nshl rdx, 1'),
   'lea_chain2':   ('', 'lea rax, [rax+rbx*2+8]\nlea rax, [rax+rbx*2+8]'),
   'mov_chain':    ('', 'mov rbx, rax\nmov rcx, rbx\nmov rax, rcx\nadd rax, 1'),
   'test_jcc3':    ('', 'test rax, rax\njnz 1f\n1: test rbx, rbx\njnz 2f\n2: test rcx, rcx\njnz 3f\n3:'),
   'ptr_chase':    ('mov [rsi], rsi\nmov rax, rsi', 'mov rax, [rax]'),
   'loadop_chain2':('', 'add rax, [rsi]\nadd rax, [rsi+8]'),
   'load_indep6':  ('', 'mov rax, [rsi]\nmov rbx, [rsi+8]\nmov rcx, [rsi+16]\nmov rdx, [rsi+24]\nmov rdi, [rsi+32]\nmov r8, [rsi+40]'),
   'store_indep4': ('', 'mov [rsi], rax\nmov [rsi+8], rbx\nmov [rsi+16], rcx\nmov [rsi+24], rdx'),
   'store_fwd':    ('', 'mov [rsi], rax\nmov rax, [rsi]\nadd rax, 1'),
   'div64':        ('mov r8, 1000000007\nmov r9, 12345', 'xor edx, edx\nmov rax, r8\ndiv r9'),
   'addsd_chain2': ('', 'addsd xmm0, xmm1\naddsd xmm0, xmm1'),
   'vmulpd_indep6':('', 'vmulpd xmm0, xmm8, xmm9\nvmulpd xmm1, xmm8, xmm9\nvmulpd xmm2, xmm8, xmm9\nvmulpd xmm3, xmm8, xmm9\n'
                        'vmulpd xmm4, xmm8, xmm9\nvmulpd xmm5, xmm8, xmm9'),
   'vpaddd_indep6':('', 'vpaddd ymm0, ymm8, ymm9\nvpaddd ymm1, ymm8, ymm9\nvpaddd ymm2, ymm8, ymm9\nvpaddd ymm3, ymm8, ymm9\n'
                        'vpaddd ymm4, ymm8, ymm9\nvpaddd ymm5, ymm8, ymm9'),
   'fma_mem_chain':('', 'vfmadd231pd ymm0, ymm1, [rsi]'),
   'mixed_hash':   ('', 'mov eax, [rsi+rcx*4]\nadd edx, eax\nxor eax, edx\nrol edx, 5\nadd rcx, 1\nand rcx, 255'),
   'mixed_fp':     ('', 'movsd xmm1, [rsi+rcx*8]\nmulsd xmm1, xmm2\naddsd xmm0, xmm1\nadd rcx, 1\nand rcx, 255'),
}

# Loops that were NOT used while developing the Zen 3 model (select with SET=heldout).
HELDOUT = {
   'cmov_chain':   ('', 'cmp rax, rbx\ncmovne rcx, rdx\nadd rcx, 1\ncmp rcx, rdi\ncmove rdx, rcx'),
   'setcc_mix':    ('', 'test rax, rax\nsetz bl\nmovzx ecx, bl\nadd rdx, rcx'),
   'popcnt_indep4':('', 'popcnt rax, r8\npopcnt rbx, r8\npopcnt rcx, r8\npopcnt rdx, r8'),
   'load_add_store':('', 'mov rax, [rsi+rcx*8]\nadd rax, rdx\nmov [rsi+rcx*8+4096], rax\nadd rcx, 1\nand rcx, 63'),
   'zero_idiom':   ('', 'xor eax, eax\nadd rax, rbx\nadd rcx, rax\nadd rcx, rax'),
   'movzx_shift':  ('', 'movzx eax, bl\nshl rax, 3\nadd rbx, rax\nror rbx, 7'),
   'vec_fp_mix':   ('', 'vaddps ymm0, ymm0, ymm1\nvmulps ymm2, ymm0, ymm3\nvxorps ymm4, ymm2, ymm5'),
   'vec_store_load':('', 'movaps [rsi], xmm0\nmovaps xmm1, [rsi+64]\naddps xmm0, xmm1'),
   'push_pop':     ('', 'push rax\npop rbx\nadd rax, rbx'),
   'bitops':       ('', 'bt rax, 5\nadc rbx, 0\nlzcnt rcx, rdx\nbswap rdi'),
   'poly_hash':    ('mov rax, 1', 'imul rax, rax, 31\nadd rax, rbx\nlea rbx, [rbx+rax*2]'),
   'cvt_add':      ('', 'cvtsi2sd xmm0, rax\naddsd xmm1, xmm0\nadd rax, 1'),
   'vec_int_mul':  ('', 'vpmulld ymm0, ymm1, ymm2\nvpaddd ymm3, ymm3, ymm0'),
   'store_indexed':('', 'mov [rsi+rcx*8], rax\nadd rcx, 1\nand rcx, 63'),
   'div32':        ('mov r8, 1000000007\nmov r9, 12345', 'xor edx, edx\nmov eax, r8d\ndiv r9d'),
   'memcpy_like':  ('', 'mov rax, [rsi+rcx*8]\nmov rdx, [rsi+rcx*8+8]\nmov [rsi+rcx*8+4096], rax\nmov [rsi+rcx*8+4104], rdx\nadd rcx, 2\nand rcx, 62'),
}
if os.environ.get('SET') == 'heldout':
   TESTS = HELDOUT
   OUT = OUT + '_heldout'

LOOP = '.intel_syntax noprefix\nl:\n{body}\ndec r15\njnz l\n'
EXE = '''.intel_syntax noprefix
.globl _start
.bss
.balign 4096
buf: .skip 8192
.text
_start:
xor eax, eax
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
mov eax, 60
xor edi, edi
syscall
'''

def run(cmd, **kw):
   return subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, **kw)

def gen():
   os.makedirs(OUT, exist_ok=True)
   for name, (init, body) in TESTS.items():
      p = os.path.join(OUT, name)
      with open(p + '.s', 'w') as f: f.write(LOOP.format(body=body))
      with open(p + '.exe.s', 'w') as f: f.write(EXE.format(init=init, body=body, n=N))
      run(['as', p + '.s', '-o', p + '.o'])
      run(['as', p + '.exe.s', '-o', p + '.exe.o'])
      run(['ld', '-o', p + '.exe', p + '.exe.o'])

def nInstr(name):
   out = run(['objdump', '-d', '--no-show-raw-insn', os.path.join(OUT, name + '.o')]).stdout
   return len(re.findall(r'^\s+[0-9a-f]+:\s+\S', out, re.M))

def measure():
   res = {}
   for name in TESTS:
      best = None
      for _ in range(5):
         r = run(['taskset', '-c', CPU, 'perf', 'stat', '-x,', '-e', 'cycles:u,instructions:u', os.path.join(OUT, name + '.exe')])
         vals = {l.split(',')[2]: float(l.split(',')[0]) for l in r.stderr.splitlines() if l and l[0].isdigit()}
         if best is None or vals['cycles:u'] < best['cycles:u']: best = vals
      res[name] = {'cycles': best['cycles:u'] / N, 'instr': best['instructions:u'] / N, 'expectedInstr': nInstr(name)}
   json.dump(res, open(os.path.join(OUT, 'measured.json'), 'w'), indent=1)
   return res

def mca(cpu='znver3'):
   res = {}
   for name in TESTS:
      r = run([LLVM_MCA, '-mcpu=' + cpu, '-iterations=1000', os.path.join(OUT, name + '.s')])
      res[name] = int(re.search(r'Total Cycles:\s+(\d+)', r.stdout).group(1)) / 1000
   json.dump(res, open(os.path.join(OUT, 'mca_%s.json' % cpu), 'w'), indent=1)
   return res

def uica(arch):
   res = {}
   for name in TESTS:
      try:
         r = run([sys.executable, UICA, os.path.join(OUT, name + '.o'), '-arch', arch, '-TPonly'])
         res[name] = float(r.stdout.strip().splitlines()[-1])
      except Exception as e:
         res[name] = None
   json.dump(res, open(os.path.join(OUT, 'uica_%s.json' % arch), 'w'), indent=1)
   return res

def table(arch):
   m = json.load(open(os.path.join(OUT, 'measured.json')))
   u = json.load(open(os.path.join(OUT, 'uica_%s.json' % arch)))
   l = json.load(open(os.path.join(OUT, 'mca_znver3.json')))
   def err(p, t): return abs(p - t) / t * 100 if p is not None else None
   print('%-15s %9s %9s %7s %9s %7s' % ('test', 'measured', 'uiCA', 'err%', 'llvm-mca', 'err%'))
   eu, el = [], []
   for name in TESTS:
      t = m[name]['cycles']
      e1, e2 = err(u.get(name), t), err(l[name], t)
      if e1 is not None: eu.append(e1)
      el.append(e2)
      print('%-15s %9.2f %9s %7s %9.2f %7.1f' % (name, t, '%.2f' % u[name] if u.get(name) is not None else 'fail',
                                                '%.1f' % e1 if e1 is not None else '-', l[name], e2))
   print('mean abs error: uiCA %.1f%% (%d tests), llvm-mca %.1f%%' % (sum(eu) / max(1, len(eu)), len(eu), sum(el) / len(el)))

if __name__ == '__main__':
   cmd = sys.argv[1]
   if cmd == 'gen': gen()
   elif cmd == 'measure':
      for k, v in measure().items(): print('%-15s %6.2f c/iter  instr/iter %.2f (expected %d)' % (k, v['cycles'], v['instr'], v['expectedInstr']))
   elif cmd == 'mca':
      for k, v in mca().items(): print('%-15s %6.2f' % (k, v))
   elif cmd == 'uica':
      for k, v in uica(sys.argv[2]).items(): print('%-15s %s' % (k, v))
   elif cmd == 'table': table(sys.argv[2])

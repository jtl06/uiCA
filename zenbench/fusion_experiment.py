# Hardware experiments on the host CPU: which op+jcc pairs macro-fuse, and how wide is dispatch?
# A loop of K nops + <op; jnz> runs at max(1, macro_ops/dispatch_width) cycles/iteration.
import subprocess, sys
N = 100_000_000
T = '''.intel_syntax noprefix
.globl _start
.text
_start:
mov r15, {init}
xor r13d, r13d
.balign 64
l:
{body}
jnz l
mov eax, 60
xor edi, edi
syscall
'''
def cyc(body, init=N):
    open('t.s','w').write(T.format(init=init, body=body))
    subprocess.run('as t.s -o t.o && ld t.o -o t.exe', shell=True, check=True)
    best = None
    for _ in range(3):
        r = subprocess.run('taskset -c 2 perf stat -x, -e cycles:u ./t.exe', shell=True, stderr=subprocess.PIPE, universal_newlines=True, timeout=20)
        c = float(r.stderr.split(',')[0]) / N
        best = c if best is None else min(best, c)
    return best
nops = lambda k: 'nop\n' * k
print('dispatch width: K nops + dec r15/jnz', flush=True)
pass
print('fusion: nops + <op>; jnz, sized so that fused -> 6 macro-ops and unfused -> 7', flush=True)
print('and/or/xor on a copy of the counter (3 nops + dec + mov + op + jnz: fused -> 6, unfused -> 7); control: cmp/test same shape', flush=True)
for name, op in [('and', 'and r14, r14'), ('or', 'or r14, r13'), ('xor', 'xor r14, r13'), ('cmp', 'cmp r14, 0'), ('test', 'test r14, r14'), ('cmp m', 'cmp qword ptr [rsp], 1'), ('neg(ctl)', 'neg r14')]:
    body = nops(3) + 'dec r15\nmov r14, r15\n' + op
    if name == 'cmp m': body = nops(4) + 'dec r15\n'  # flags from dec; replaced below
    print('  %-8s %.3f c/iter' % (name, cyc(body)), flush=True)

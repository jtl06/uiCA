import subprocess
N = 100_000_000
T = '.intel_syntax noprefix\n.globl _start\n.text\n_start:\nmov r15, %d\n.balign 64\nl:\n%s\ndec r15\njnz l\nmov eax, 60\nxor edi, edi\nsyscall\n'
regs = ['rax','rbx','rcx','rdx','rdi','r8','r9','r10','r11','r12']
def cyc(body):
    open('t.s','w').write(T % (N, body)); subprocess.run('as t.s -o t.o && ld t.o -o t.exe', shell=True, check=True)
    return min(float(subprocess.run('taskset -c 2 perf stat -x, -e cycles:u ./t.exe', shell=True, stderr=subprocess.PIPE, universal_newlines=True, timeout=30).stderr.split(',')[0]) / N for _ in range(3))
for k in range(1, 11):
    print('K=%2d adds + dec/jnz: %.3f c/iter   (ALU-only bound %.2f, with BRU1 for the branch %.2f)' % (k, cyc('\n'.join('add %s, 1' % r for r in regs[:k])), max(1,(k+1)/4), max(1,k/4)), flush=True)

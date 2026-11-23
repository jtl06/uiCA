#!/usr/bin/env python3
"""lb.py SPEC OUTDIR: build a loop benchmark (OUTDIR/lb, static) from SPEC lines 'name: instr; instr; ...' (Intel syntax, label .L).
Each loop is a function; on entry rdi = source buffer, rsi = destination buffer (64-byte aligned, 64 KiB each, zero except where noted),
rcx = number of iterations n, r8 = rdi + 32*n, r9 = rsi + 32*n, rax = rdx = r10 = r11 = 0, ymm0-ymm15 = small floats (from memory).
The loop must run exactly n iterations. 'lb CPU [NAME...]' measures user-mode cycles (perf_event_open) of calls with n = 256 and 512
(median of 31 trials of 100 calls) and prints the slope per iteration. Also writes OUTDIR/NAME.s (the loop alone) for the analyzers."""
import os, subprocess, sys
spec, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
loops = []
for line in open(spec):
    line = line.strip()
    if not line or line.startswith('#'): continue
    name, body = line.split(':', 1)
    loops.append((name.strip(), [x.strip() for x in body.split(';') if x.strip()]))
asm = ['.intel_syntax noprefix', '.section .rodata', '.balign 64', 'lbconsts: .float 1.5, 0.25, 0.75, 1.25, 0.5, 1.0, 0.125, 2.0', '.text']
for name, lines in loops:
    asm += ['.globl lb_%s' % name, '.type lb_%s, @function' % name, 'lb_%s:' % name,
            'push rbx', 'push r12', 'push r13', 'push r14', 'push r15',
            'mov rcx, rdx', 'mov r8, rcx', 'shl r8, 5', 'mov r9, r8', 'add r8, rdi', 'add r9, rsi',
            'xor eax, eax', 'xor edx, edx', 'xor r10d, r10d', 'xor r11d, r11d', 'xor ebx, ebx', 'xor r12d, r12d', 'xor r13d, r13d',
            'xor r14d, r14d', 'xor r15d, r15d']
    asm += ['vmovups ymm%d, [rip+lbconsts]' % i for i in range(16)]
    asm += ['.p2align 6', '.L%s:' % name]
    body = [l.replace('.L', '.L' + name) if l.split()[0].lower().startswith('j') else l for l in lines]
    asm += body
    asm += ['vzeroupper', 'pop r15', 'pop r14', 'pop r13', 'pop r12', 'pop rbx', 'ret']
    open(os.path.join(out, name + '.s'), 'w').write('.intel_syntax noprefix\n.L:\n' + '\n'.join(lines) + '\n')
open(os.path.join(out, 'loops.s'), 'w').write('\n'.join(asm) + '\n')
c = r'''#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <sched.h>
#include <sys/syscall.h>
#include <linux/perf_event.h>
typedef void (*fn)(void *, void *, long);
%s
static struct { const char *name; fn f; } loops[] = { %s };
static int fd;
static uint64_t rd(void) { uint64_t v; if (read(fd, &v, 8) != 8) exit(2); return v; }
static int cmp(const void *a, const void *b) { double x = *(double *)a, y = *(double *)b; return x < y ? -1 : x > y; }
static char A[65536 + 4096] __attribute__((aligned(64))), O[65536 + 4096] __attribute__((aligned(64)));
static double run(fn f, long n) {
  double t[31];
  for (int w = 0; w < 30; w++) f(A, O, n);
  for (int tr = 0; tr < 31; tr++) { uint64_t c0 = rd(); for (int r = 0; r < 100; r++) f(A, O, n); t[tr] = (double)(rd() - c0) / 100; }
  qsort(t, 31, sizeof t[0], cmp); return t[15];
}
int main(int argc, char **argv) {
  cpu_set_t s; CPU_ZERO(&s); CPU_SET(atoi(argv[1]), &s); if (sched_setaffinity(0, sizeof s, &s)) { perror("affinity"); return 1; }
  struct perf_event_attr pe; memset(&pe, 0, sizeof pe); pe.type = PERF_TYPE_HARDWARE; pe.size = sizeof pe;
  pe.config = PERF_COUNT_HW_CPU_CYCLES; pe.exclude_kernel = 1; pe.exclude_hv = 1;
  FILE *ty = fopen("/sys/devices/cpu_core/type", "r"); /* hybrid CPU: count on the P-core PMU (extended type) */
  if (ty) { unsigned long long t; if (fscanf(ty, "%%llu", &t) == 1) pe.config |= t << 32; fclose(ty); }
  fd = syscall(__NR_perf_event_open, &pe, 0, -1, -1, 0); if (fd < 0) { perror("perf_event_open"); return 1; }
  for (unsigned i = 0; i < sizeof loops / sizeof loops[0]; i++) {
    if (argc > 2) { int found = 0; for (int a = 2; a < argc; a++) if (!strcmp(argv[a], loops[i].name)) found = 1; if (!found) continue; }
    double best = 1e30;
    for (int k = 0; k < 3; k++) { double a = run(loops[i].f, 256), b = run(loops[i].f, 512); double v = (b - a) / 256; if (v < best) best = v; }
    printf("%%-12s %%7.3f\n", loops[i].name, best); fflush(stdout);
  }
  return 0;
}
''' % ('\n'.join('void lb_%s(void *, void *, long);' % n for n, _ in loops), ', '.join('{"%s", lb_%s}' % (n, n) for n, _ in loops))
open(os.path.join(out, 'lb.c'), 'w').write(c)
subprocess.run(['gcc', '-O2', '-static', '-o', os.path.join(out, 'lb'), os.path.join(out, 'lb.c'), os.path.join(out, 'loops.s')], check=True)
print('built', len(loops), 'loops')

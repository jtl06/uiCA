#!/usr/bin/env python3
"""Make loops from real-code basic blocks (BHive benchmark, https://github.com/ithemal/bhive) for measurement and scoring.

Each block becomes the body of a loop "l: BLOCK; dec CNT; jnz l" (CNT: an r8-r15 register the block does not use), the same form as the
random loops of fuzz/fuzz_gen.py, so that fuzz/fuzz_report.py can score the predictions.

Executables: the inner loop runs K iterations; an outer loop re-initializes all registers and runs the inner loop again (NOUTER times), so
that registers that the block changes (pointer increments etc.) stay in range. Two executables per block (K1 and K2 inner iterations);
cycles per iteration = (cycles(K2) - cycles(K1)) / (NOUTER * (K2 - K1)), so that the outer loop and the start-up cancel (real_measure.py).

Registers and memory:
- a 32 MB memory region at BASE is mapped and filled with the 64-bit value V (so that pointers loaded from memory point into the region);
- each GPR that the block uses as an index register gets the value 8; every other GPR (including RSP) gets its own value
  V + i * 0x10140 (different registers point to different addresses, as uiCA assumes; the 0x140 avoids 4K aliasing between them);
  RDX is 0 if the block divides;
- vector registers are loaded from memory (not zeroed: Ice Lake-SP has a higher latency for vector instructions that read a register
  zeroed by an idiom); MXCSR has FTZ and DAZ set (the region holds denormal doubles).
Blocks are dropped if they branch, use x87/MMX, string instructions, RIP-relative addresses or instructions with side effects.
Blocks whose executable crashes are dropped by the measurement.

Every block gets the tag 'dev' or 'held' (from a hash of its code): inspect individual blocks only in 'dev'.
Blocks that change RSP by a constant in every iteration (function prologues and epilogues: push without pop, sub rsp, 88, ...) get the tag
'exclude:stack-drift', and fuzz_report.py does not score them: repeated in a loop, they access a new part of the stack in every iteration
(e.g., a store to a new cache line), which never happens in the programs they come from.

Retag an existing set (after changing the rules): bhive_gen.py -retag META_JSON

Usage: bhive_gen.py BHIVE_DIR SEED PER_GROUP OUT_DIR META_JSON [ARCH ...]
"""
import collections, hashlib, json, os, random, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
LLVM_MC = os.environ.get('LLVM_MC', 'llvm-mc-22')

BASE = 0x10000000
SIZE = 32 << 20
V = BASE + (8 << 20) + 0x40
INDEX_VALUE = 8
STEP = 0x10140
K1, K2, NOUTER, NOUTER_SMOKE = 500, 1000, 20000, 20
FAMILIES = ['rax', 'rcx', 'rdx', 'rbx', 'rsp', 'rbp', 'rsi', 'rdi'] + ['r%d' % i for i in range(8, 16)]

def family(reg):
   reg = reg.lower()
   m = re.fullmatch(r'r(\d+)[dwb]?', reg)
   if m: return 'r' + m.group(1)
   m = re.fullmatch(r'[re]?([abcd])[xlh]', reg)
   if m: return 'r' + m.group(1) + 'x'
   m = re.fullmatch(r'[re]?(sp|bp|si|di)l?', reg)
   if m: return 'r' + m.group(1)
   return None

REJECT = re.compile(r'^(j\w+|call\w*|ret\w*|loop\w*|jmp|syscall|sysenter|int\w*|iret\w*|cpuid|rdtsc\w*|rdrand|rdseed|rdpmc|hlt|pause|ud\d|'
                    r'xgetbv|xsave\w*|xrstor\w*|fxsave\w*|fxrstor\w*|enter|lods[bwdq]|ins[bwd]|outs[bwd]|'
                    r'in|out|cli|sti|lgdt|lidt|wrmsr|rdmsr|emms|femms|ldmxcsr|stmxcsr|vldmxcsr|vstmxcsr|clflush\w*|'
                    r'f\w+|vzeroall|vzeroupper)$')

def disas(code, variant):
   r = subprocess.run([LLVM_MC, '--disassemble', '-triple=x86_64', '-output-asm-variant=%d' % variant],
                      input=' '.join('0x' + code[i:i + 2] for i in range(0, len(code), 2)), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                      universal_newlines=True)
   if r.returncode != 0 or 'warning' in r.stderr or 'error' in r.stderr: return None
   return [l.strip() for l in r.stdout.splitlines() if l.strip() and not l.strip().startswith('.')]

def stackDrift(intel):
   """True if the block changes RSP by a nonzero constant (or in an unknown way) per execution."""
   delta = 0
   for line in intel:
      toks = line.split('#')[0].strip().split(None, 1)
      mn = toks[0].lower(); ops = toks[1].lower().replace(' ', '') if len(toks) > 1 else ''
      if mn in ('push', 'pushf', 'pushfq'): delta -= 8
      elif mn in ('pop', 'popf', 'popfq'): delta += 8
      elif mn == 'leave': return False # rsp = rbp
      elif re.match(r'(rsp|esp),', ops) and not mn.startswith(('cmp', 'test', 'mov' if '[' in ops.split(',')[0] else '-')):
         m = re.fullmatch(r'(rsp|esp),(-?(0x)?[0-9a-f]+)', ops)
         if mn in ('add', 'sub') and m:
            v = int(m.group(2), 0); delta += v if mn == 'add' else -v
         else:
            return True
   return delta != 0

def analyze(intel):
   """Returns (used families, index families, divides, uses VEX, reason to reject or None)."""
   used, index = set(), set()
   divides = vex = False
   for line in intel:
      line = line.split('#')[0].strip()
      toks = line.split(None, 1)
      mn = toks[0].lower()
      while mn in ('lock', 'rep', 'repe', 'repne', 'repz', 'repnz', 'data16', 'rex64') and len(toks) > 1:
         if mn.startswith('rep'): return None, None, None, None, 'rep prefix'
         toks = toks[1].split(None, 1); mn = toks[0].lower()
      ops = toks[1] if len(toks) > 1 else ''
      if REJECT.match(mn): return None, None, None, None, 'instruction ' + mn
      if re.search(r'\b(rip|eip)\b', ops): return None, None, None, None, 'rip-relative'
      if re.search(r'\b(mm\d|st\(?\d?\)?|[cdefgs]s:|cr\d|dr\d|zmm\d+|k\d)\b', ops): return None, None, None, None, 'mmx/x87/segment/avx512'
      if mn in ('div', 'idiv'): divides = True
      if mn.startswith('v') and re.search(r'\b[xy]mm\d+\b', ops): vex = True
      if mn in ('push', 'pop', 'pushf', 'popf', 'pushfq', 'popfq', 'leave'): used.add('rsp')
      if mn in ('mul', 'imul', 'div', 'idiv', 'cqo', 'cdq', 'cwd', 'cdqe', 'cwde', 'cbw', 'cmpxchg', 'cmpxchg8b', 'cmpxchg16b', 'xlat', 'lahf', 'sahf'): used |= {'rax', 'rdx'}
      if mn.startswith(('sh', 'sa', 'ro', 'rc')) and 'cl' in ops.split(','): used.add('rcx')
      if mn in ('mulx', 'pdep', 'pext'): used.add('rdx')
      for r in re.findall(r'\b([a-z0-9]+)\b', ops):
         f = family(r)
         if f: used.add(f)
      for mem in ([] if mn in ('lea', 'nop', 'nopw', 'nopl') else re.findall(r'\[([^\]]*)\]', ops)):
         for m in re.finditer(r'(\d)\s*\*\s*([a-z0-9]+)|([a-z0-9]+)\s*\*\s*(\d)', mem):
            f = family(m.group(2) or m.group(3))
            if f: index.add(f)
         terms = [t.strip() for t in re.split(r'[+-]', mem) if t.strip()]
         regs = [t for t in terms if family(t)]
         if len(regs) == 2 and not any('*' in t for t in terms): index.add(family(regs[1]))
   return used, index, divides, vex, None

EXE = '''.intel_syntax noprefix
.globl _start
.data
.balign 64
vconst: .double 1.5, 2.5, 1.5, 2.5
mxcsr: .long 0x9FC0
outer: .quad {nouter}
.text
_start:
ldmxcsr [rip+mxcsr]
mov eax, 9
mov rdi, {base}
mov esi, {size}
mov edx, 3
mov r10d, 0x32
mov r8, -1
xor r9d, r9d
syscall
cmp rax, rdi
jne fail
mov rax, {v}
mov ecx, {size8}
rep stosq
o:
{init}
mov {cnt}, {k}
.balign 64
l:
.byte {bytes}
dec {cnt}
jnz l
dec qword ptr [rip+outer]
jnz o
mov eax, 60
xor edi, edi
syscall
fail:
mov eax, 60
mov edi, 1
syscall
'''

def run(cmd, **kw):
   return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, **kw)

def groups(bhive):
   g = collections.defaultdict(set)
   d = os.path.join(bhive, 'benchmark', 'sources')
   for f in sorted(os.listdir(d)):
      name = re.split(r'[-.]', f)[0]
      for line in open(os.path.join(d, f)):
         code = line.split(',')[0].strip().lower()
         if code and re.fullmatch(r'[0-9a-f]+', code): g[name].add(code)
   return g

def retag(metaFile):
   meta = json.load(open(metaFile))
   n = 0
   for l in meta['loops']:
      tags = set(t for t in l['tags'] if not t.startswith('exclude:'))
      if stackDrift(disas(l['code'], 1)): tags.add('exclude:stack-drift'); n += 1
      l['tags'] = sorted(tags)
   json.dump(meta, open(metaFile, 'w'), indent=0)
   print('%d of %d blocks tagged exclude:stack-drift' % (n, len(meta['loops'])))

def main():
   if sys.argv[1] == '-retag': return retag(sys.argv[2])
   bhive, seed, perGroup, outDir, metaFile = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5]
   archs = sys.argv[6:] or ['ZEN3', 'ADL-P', 'ICX']
   import importlib, xed
   from instructions import getInstructions, UnknownInstr
   from microArchConfigs import MicroArchConfigs
   archData = {a: importlib.import_module('instrData.' + a + '_data') for a in archs}
   cats = {}
   for line in open(os.path.join(bhive, 'benchmark', 'categories.csv')):
      p = line.strip().split(',')
      if len(p) == 2: cats[p[0].lower()] = p[1]

   rnd = random.Random(seed)
   os.makedirs(outDir, exist_ok=True)
   loops = []; stats = collections.Counter(); reasons = collections.Counter()
   for gname, codes in sorted(groups(bhive).items()):
      codes = sorted(codes); rnd.shuffle(codes)
      taken = 0
      for code in codes:
         if taken >= perGroup: break
         intel, att = disas(code, 1), disas(code, 0)
         if not intel or not att or len(intel) != len(att): stats['not disassembled'] += 1; continue
         if len(intel) > 60: stats['more than 60 instructions'] += 1; continue
         used, index, divides, vex, reason = analyze(intel)
         if reason: stats['rejected'] += 1; reasons[reason.split()[0] if not reason.startswith('instruction') else reason] += 1; continue
         cnt = next((r for r in ['r15', 'r14', 'r13', 'r12', 'r11', 'r10', 'r9', 'r8'] if r not in used), None)
         if not cnt: stats['no free counter register'] += 1; continue
         name = '%s_s%d_%04d' % (gname, seed, len(loops))
         p = os.path.join(outDir, name)
         bytesDir = ', '.join('0x' + code[i:i + 2] for i in range(0, len(code), 2))
         with open(p + '.o.s', 'w') as f: f.write('.intel_syntax noprefix\nl:\n.byte %s\ndec %s\njnz l\n' % (bytesDir, cnt))
         if run(['as', p + '.o.s', '-o', p + '.o']).returncode != 0: stats['rejected by the assembler'] += 1; continue
         os.remove(p + '.o.s')
         with open(p + '.s', 'w') as f: f.write('l:\n' + '\n'.join(att) + '\ndec %%%s\njnz l\n' % cnt)
         ok = True
         for a in archs:
            cfg = MicroArchConfigs[a]
            try:
               instrs = getInstructions(xed.disasHex(code.upper(), chip=cfg.XEDName), cfg, archData[a], 0)
            except BaseException:
               instrs = None
            if (not instrs) or any(isinstance(i, UnknownInstr) for i in instrs): ok = False
         if not ok: stats['no uiCA data on some machine'] += 1
         init = []
         for i, f in enumerate(FAMILIES):
            if f == cnt: continue
            val = INDEX_VALUE if f in index else (0 if (f == 'rdx' and divides) else V + i * STEP)
            init.append('mov %s, %d' % (f, val))
         vinit = ['%s %smm%d, [rip+vconst]' % ('vmovdqu' if vex else 'movdqu', 'y' if vex else 'x', i) for i in range(16)]
         good = True
         for suffix, k, n in [('.k1.exe', K1, NOUTER), ('.k2.exe', K2, NOUTER), ('.smoke.exe', K2, NOUTER_SMOKE)]:
            src = EXE.format(nouter=n, base=BASE, size=SIZE, size8=SIZE // 8, v=V, init='\n'.join(vinit + init), cnt=cnt, k=k, bytes=bytesDir)
            with open(p + '.exe.s', 'w') as f: f.write(src)
            if run(['as', p + '.exe.s', '-o', p + '.exe.o']).returncode != 0 or run(['ld', '-o', p + suffix, p + '.exe.o']).returncode != 0:
               good = False; break
         for t in ('.exe.s', '.exe.o'):
            if os.path.exists(p + t): os.remove(p + t)
         if not good: stats['executable not built'] += 1; continue
         split = 'dev' if int(hashlib.sha1(code.encode()).hexdigest(), 16) % 2 == 0 else 'held'
         tags = {split, 'app:' + gname, 'cat:' + cats.get(code, '?'), 'avx' if vex else ('sse' if any(re.search(r'\bxmm\d', l) for l in intel) else 'int')}
         if stackDrift(intel): tags.add('exclude:stack-drift')
         loops.append({'name': name, 'code': code, 'asm': att, 'tags': sorted(tags), 'probes': [], 'probeMnemonics': sorted(set(l.split()[0] for l in intel)),
                       'instructions': len(intel) + 2})
         taken += 1; stats['generated'] += 1
   json.dump({'seed': seed, 'k1': K1, 'k2': K2, 'nouter': NOUTER, 'iterations': NOUTER * (K2 - K1), 'archs': archs, 'loops': loops},
             open(metaFile, 'w'), indent=0)
   print('stats: %s' % dict(stats))
   print('rejected because of: %s' % dict(reasons.most_common(25)))
   print('blocks per group: %s' % dict(collections.Counter(t for l in loops for t in l['tags'] if t.startswith('app:'))))
   print('categories: %s' % dict(collections.Counter(t for l in loops for t in l['tags'] if t.startswith('cat:'))))

if __name__ == '__main__':
   main()

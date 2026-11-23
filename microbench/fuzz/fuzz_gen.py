#!/usr/bin/env python3
"""Generate random loops for testing uiCA models on hardware.

Each loop consists of a few plain integer instructions ("fillers") and one or two "probe" instructions, followed by 'dec r15; jnz'. The probes
cycle through all usable mnemonics, so that a misprediction can be attributed to an instruction. Only instructions that uops.info measured on
all given microarchitectures are used.

Rules that keep the loops safe to run and their timing independent of data:
  * only whitelisted instruction categories; no branches, stack, string, system, x87/MMX, gather, non-temporal, lock-prefixed or
    division instructions, no high-8 registers, no implicit memory operands
  * rsp, rsi (buffer), r14 and r15 (loop counter) are never operands; memory operands are [rsi + 64*k]; loads read the first KiB of an 8-KiB
    buffer, stores (and read-modify-write instructions) write a region that does not overlap or 4K-alias with it, each at its own offset
  * a loop uses either legacy-SSE or VEX-encoded vector instructions, never both; MXCSR has FTZ and DAZ set
  * vector registers 8-15 hold constants and are only read
Loops are tagged (vector mode, load, store, rmw, value-dependent probe such as FP division) so that results can be reported per tag.

Profiles (environment variable FUZZ_PROFILE):
  default: as described above
  mem:     4-10 fillers instead of 2-5; loads also at offsets within a cache line (aligned to their size) and, in a quarter of the cases,
           with an index register that advances in every iteration ([rsi+r14+disp]; 'add r14, 64; and r14, 448' at the end of the loop);
           in half of the loops a store and a later load from the same address (64-bit, load-op, 32-bit load of a 64-bit store, or vector),
           in a separate region of the buffer (tag 'stfwd')

Usage: fuzz_gen.py XMLFILE SEED COUNT OUTDIR METADATA_JSON [ARCH ...]     (default architectures: ZEN3 ADL-P)
"""
import collections, json, os, random, re, subprocess, sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
N_FULL, N_SMOKE = 10_000_000, 2000

CATEGORIES = ['BINARY', 'LOGICAL', 'SHIFT', 'ROTATE', 'BITBYTE', 'CMOV', 'SETCC', 'DATAXFER', 'CONVERT', 'SSE', 'AVX', 'AVX2', 'VFMA', 'LOGICAL_FP',
              'BROADCAST', 'BMI1', 'BMI2', 'LZCNT', 'AES', 'VAES', 'SHA', 'STTNI', 'PCLMULQDQ', 'VPCLMULQDQ', 'ADOX_ADCX', 'SEMAPHORE', 'MISC', 'WIDENOP', 'NOP']
DROP_ICLASS = re.compile(r'^(DIV|IDIV|V?LDMXCSR|V?STMXCSR|V?MOVNT.*|V?MASKMOV.*|VPMASKMOV.*|XLAT|ENTER|LEAVE|CPUID|PAUSE|UD.*|XGETBV|RDTSC.*|MOVDIR.*|V?ZEROALL)$')
VALUE_DEPENDENT = re.compile(r'DIV|SQRT|RCP|RSQRT')
GPR = {64: ['RAX', 'RBX', 'RCX', 'RDX', 'RDI', 'RBP', 'R8', 'R9', 'R10', 'R11', 'R12', 'R13'],
       32: ['EAX', 'EBX', 'ECX', 'EDX', 'EDI', 'EBP', 'R8D', 'R9D', 'R10D', 'R11D', 'R12D', 'R13D'],
       16: ['AX', 'BX', 'CX', 'DX', 'DI', 'BP', 'R8W', 'R9W', 'R10W', 'R11W', 'R12W', 'R13W'],
       8: ['AL', 'BL', 'CL', 'DL', 'DIL', 'BPL', 'R8B', 'R9B', 'R10B', 'R11B', 'R12B', 'R13B']}
ALLOWED_GPR = set(r for l in GPR.values() for r in l)
RESERVED = set('RSP ESP SP SPL RSI ESI SI SIL R14 R14D R14W R14B R15 R15D R15W R15B RIP EIP IP'.split())
FILLERS = ['ADD_01 (R64, R64)', 'SUB_29 (R64, R64)', 'AND_21 (R64, R64)', 'XOR_31 (R64, R64)', 'OR_09 (R64, R64)', 'MOV_89 (R64, R64)', 'MOV_89 (R32, R32)',
           'ADD (R64, I8)', 'CMP_39 (R64, R64)', 'TEST (R64, R64)', 'LEA_B_I (R64)', 'LEA_B_D8 (R64)', 'SHL (R64, I8)', 'MOVZX (R32, R8l)', 'IMUL (R64, R64)',
           'ADD_01 (R32, R32)', 'MOV (R64, M64)', 'MOV (R64, M64)', 'MOV (M64, R64)', 'ADD (R64, M64)']

def vecReg(name):
   m = re.match(r'^([XY])MM(\d+)$', name)
   return (m.group(1), int(m.group(2))) if m else None

def loadPool(xmlFile, archs):
   pool = []
   dropped = collections.Counter()
   for _, node in ET.iterparse(xmlFile):
      if node.tag != 'instruction': continue
      measured = {an.attrib['name'] for an in node.iter('architecture') if an.find('measurement') is not None}
      a = node.attrib
      ops = [dict(o.attrib, text=(o.text or '')) for o in node.iter('operand')]
      node.clear()
      if not all(arch in measured for arch in archs): continue
      reason = None
      if a['category'] not in CATEGORIES: reason = 'category'
      elif a['category'] == 'MISC' and a['iclass'] != 'LEA': reason = 'category'
      elif a.get('cpl', '3') != '3' or a.get('locked') == '1' or a.get('rep') or a.get('high8'): reason = 'locked/rep/high8'
      elif DROP_ICLASS.match(a['iclass']): reason = 'iclass'
      elif any(o['type'] not in ('reg', 'mem', 'imm', 'flags', 'agen') for o in ops): reason = 'operand type'
      elif any(o['type'] == 'mem' and (o.get('suppressed') == '1' or any(k in o for k in ('base', 'seg', 'moffs', 'index', 'VSIB'))) for o in ops): reason = 'memory operand'
      elif a['iclass'].startswith('BT') and any(o['type'] == 'mem' for o in ops) and sum(o['type'] == 'reg' and o.get('suppressed') != '1' for o in ops): reason = 'bt mem, reg'
      else:
         for o in ops:
            if o['type'] != 'reg': continue
            regs = o['text'].split(',')
            if o.get('suppressed') == '1':
               if o.get('w') == '1' and any(r in RESERVED for r in regs): reason = 'implicit write to a reserved register'
               if any((r not in ALLOWED_GPR) and (r not in RESERVED) and (not vecReg(r)) and r not in ('RFLAGS', 'EFLAGS') for r in regs): reason = 'other implicit register'
            else:
               usable = [r for r in regs if r in ALLOWED_GPR or vecReg(r)]
               if not usable: reason = 'no usable register'
      if reason: dropped[reason] += 1; continue
      vec = any(vecReg(r) for o in ops if o['type'] == 'reg' for r in o['text'].split(','))
      pool.append({'string': a['string'], 'iclass': a['iclass'], 'asm': a['asm'], 'agen': a.get('agen'), 'ops': ops,
                   'mode': ('avx' if a.get('vex') == '1' else 'sse') if vec else 'int'})
   return pool, dropped

PROFILE = os.environ.get('FUZZ_PROFILE', 'default')

class LoopBuilder:
   def __init__(self, rnd):
      self.rnd = rnd
      self.storeSlots = list(range(16)); rnd.shuffle(self.storeSlots)
      self.pairSlots = list(range(16))
      if PROFILE == "mem": rnd.shuffle(self.pairSlots)
      self.tags = set()
      self.usesIndex = False

   def loadAddress(self, o):
      rnd = self.rnd
      if PROFILE != 'mem':
         return '[RSI+%d]' % (64 * rnd.randrange(16))
      size = max(8, min(64, int(o.get('width', '64')) // 8))
      if rnd.random() < 0.25:
         self.usesIndex = True
         self.tags.add('index')
         return '[RSI+R14+%d]' % (64 * rnd.randrange(8) + size * rnd.randrange(64 // size))
      return '[RSI+%d]' % (64 * rnd.randrange(16) + size * rnd.randrange(64 // size))

   def pair(self, mode):
      # a store and a later load from the same address
      rnd = self.rnd
      off = 4096 + 3072 + 64 * self.pairSlots.pop()
      kinds = ['gpr', 'loadop', 'narrow'] + (['vec'] if mode != 'int' else [])
      kind = rnd.choice(kinds)
      self.tags.add('stfwd')
      if kind == 'vec':
         mov = 'VMOVAPS' if mode == 'avx' else 'MOVAPS'
         return ('%s xmmword ptr [RSI+%d], XMM%d' % (mov, off, rnd.randrange(16)), '%s XMM%d, xmmword ptr [RSI+%d]' % (mov, rnd.randrange(8), off))
      store = 'MOV qword ptr [RSI+%d], %s' % (off, rnd.choice(GPR[64]))
      if kind == 'gpr': return (store, 'MOV %s, qword ptr [RSI+%d]' % (rnd.choice(GPR[64]), off))
      if kind == 'loadop': return (store, 'ADD %s, qword ptr [RSI+%d]' % (rnd.choice(GPR[64]), off))
      return (store, 'MOV %s, dword ptr [RSI+%d]' % (rnd.choice(GPR[32]), off))

   def asm(self, e):
      rnd = self.rnd
      parts = []
      for o in e['ops']:
         if o.get('suppressed') == '1' or o['type'] == 'flags': continue
         if o['type'] == 'reg':
            regs = [r for r in o['text'].split(',') if r in ALLOWED_GPR or vecReg(r)]
            if vecReg(regs[0]):
               # registers 8-15 are constants: never written, and preferred for operands that are only read
               lo = [r for r in regs if vecReg(r)[1] < 8]; hi = [r for r in regs if vecReg(r)[1] >= 8]
               regs = lo if (o.get('w') == '1' or not hi or rnd.random() < 0.5) else hi
            parts.append(rnd.choice(regs))
         elif o['type'] == 'mem':
            if o.get('w') == '1':
               off = 4096 + 2048 + 64 * self.storeSlots.pop()
               self.tags.add('rmw' if o.get('r') == '1' else 'store')
               parts.append((o.get('memory-prefix', '') + ' [RSI+%d]' % off).strip())
            else:
               self.tags.add('load')
               parts.append((o.get('memory-prefix', '') + ' ' + self.loadAddress(o)).strip())
         elif o['type'] == 'agen':
            g = e['agen']; addr = []
            if 'R' in g: return None
            if 'B' in g: addr.append(rnd.choice(GPR[64]))
            if 'IS' in g: addr.append('%d*%s' % (rnd.choice([2, 4, 8]), rnd.choice(GPR[64])))
            elif 'I' in g: addr.append('1*' + rnd.choice(GPR[64]))
            if 'D8' in g: addr.append('8')
            if 'D32' in g: addr.append('1024')
            parts.append('[' + '+'.join(addr) + ']')
         elif o['type'] == 'imm':
            w = int(o['width'])
            parts.append(o['text'] if o['text'] else str(rnd.choice([1, 2, 3, 5, 7]) if w == 8 else (0x1234 if w == 16 else 0x12345)))
      return (e['asm'] + ' ' + ', '.join(parts)).strip()

EXE = '''.intel_syntax noprefix
.globl _start
.data
.balign 64
consts: .double 1.5, 2.5, 1.5, 2.5
mxcsr: .long 0x9FC0
.bss
.balign 4096
buf: .skip 8192
.text
_start:
ldmxcsr [rip+mxcsr]
mov rax, 0x1234567
mov rbx, 0x7654321
mov rcx, 3
mov rdx, 0x55aa55
mov rdi, 0x1111
mov rbp, 0x2223
mov r8, 0x10001
mov r9, 0x777
mov r10, 0x31
mov r11, 0x123
mov r12, 0xabcdef
mov r13, 0x99
lea rsi, [rip+buf]
xor r14d, r14d
{vecInit}mov r15, NITER
.balign 64
l:
{body}
dec r15
jnz l
mov eax, 60
xor edi, edi
syscall
'''
VEC_INIT = {'int': '', 'sse': ''.join('movupd xmm%d, [rip+consts]\n' % i for i in range(16)), 'avx': ''.join('vmovupd ymm%d, [rip+consts]\n' % i for i in range(16))}

def run(cmd):
   return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)

def main():
   xmlFile, seed, count, outDir, metaFile = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5]
   archs = sys.argv[6:] or ['ZEN3', 'ADL-P']
   import importlib
   import xed
   from instructions import getInstructions, UnknownInstr
   from microArchConfigs import MicroArchConfigs
   archData = {a: importlib.import_module('instrData.' + a + '_data') for a in archs}

   pool, dropped = loadPool(xmlFile, archs)
   byString = {e['string']: e for e in pool}
   fillers = [byString[s] for s in FILLERS]
   byIclass = collections.defaultdict(list)
   for e in pool: byIclass[e['iclass']].append(e)
   iclasses = sorted(byIclass)
   print('instruction forms measured on %s and usable: %d (%d mnemonics); dropped by rule: %s' % (' and '.join(archs), len(pool), len(iclasses), dict(dropped)))
   print('mnemonics: ' + ' '.join(iclasses))

   rnd = random.Random(seed)
   rnd.shuffle(iclasses)
   os.makedirs(outDir, exist_ok=True)
   loops = []; stats = collections.Counter(); noData = collections.Counter(); attempt = 0
   while len(loops) < count and attempt < count * 20:
      probe = rnd.choice(byIclass[iclasses[attempt % len(iclasses)]])
      attempt += 1
      mode = probe['mode']
      probes = [probe]
      if rnd.random() < 0.4:
         probes.append(rnd.choice([e for e in pool if e['mode'] in ('int', mode)]))
      b = LoopBuilder(rnd)
      entries = probes + [rnd.choice(fillers) for _ in range(rnd.randint(4, 10) if PROFILE == 'mem' else rnd.randint(2, 5))]
      rnd.shuffle(entries)
      lines = [b.asm(e) for e in entries]
      if any(l is None for l in lines): stats['unusable operand'] += 1; continue
      if PROFILE == 'mem':
         if rnd.random() < 0.5:
            st, ld = b.pair(mode)
            i = rnd.randrange(len(lines) + 1); lines.insert(i, st)
            j = rnd.randrange(i + 1, len(lines) + 1); lines.insert(j, ld)
         if b.usesIndex:
            lines += ['ADD R14, 64', 'AND R14, 448'] # multiples of 64: keeps the alignment of the memory operands
      name = 's%d_%04d' % (seed, len(loops))
      p = os.path.join(outDir, name)
      with open(p + '.s', 'w') as f: f.write('.intel_syntax noprefix\nl:\n' + '\n'.join(lines) + '\ndec r15\njnz l\n')
      if run(['as', p + '.s', '-o', p + '.o']).returncode != 0: stats['rejected by the assembler'] += 1; continue
      ok = True
      # the machine code is passed to the decoder directly (xed.disasFile does not close the file)
      assert run(['objcopy', '-O', 'binary', '-j', '.text', p + '.o', p + '.bin']).returncode == 0
      with open(p + '.bin', 'rb') as f: code = f.read().hex().upper()
      os.remove(p + '.bin')
      for a in archs:
         cfg = MicroArchConfigs[a]
         try:
            disas = xed.disasHex(code, chip=cfg.XEDName)
            instrs = getInstructions(disas, cfg, archData[a], 0)
         except BaseException:
            instrs = None
         if (not instrs) or len(instrs) != len(lines) + 2 or any(isinstance(i, UnknownInstr) for i in instrs):
            ok = False
            for e in probes: noData[e['string']] += 1
      if not ok: stats['no uiCA data for an instruction'] += 1; continue
      with open(p + '.exe.s', 'w') as f: f.write(EXE.format(vecInit=VEC_INIT[mode], body='\n'.join(lines)))
      for suffix, n in [('.exe', N_FULL), ('.smoke.exe', N_SMOKE)]:
         r = run(['as', '--defsym', 'NITER=%d' % n, p + '.exe.s', '-o', p + '.exe.o'])
         assert r.returncode == 0, r.stderr
         assert run(['ld', '-o', p + suffix, p + '.exe.o']).returncode == 0
      os.remove(p + '.exe.o')
      tags = sorted(b.tags | {mode} | ({'value-dependent'} if any(VALUE_DEPENDENT.search(e['iclass']) for e in probes) else set()))
      loops.append({'name': name, 'asm': lines, 'probes': [e['string'] for e in probes], 'probeMnemonics': [e['iclass'] for e in probes], 'tags': tags,
                    'instructions': len(lines) + 2})
   json.dump({'seed': seed, 'iterations': N_FULL, 'archs': archs, 'loops': loops}, open(metaFile, 'w'), indent=0)
   print('generated %d loops in %d attempts; discarded: %s' % (len(loops), attempt, dict(stats)))
   print('probe forms discarded for lack of uiCA data (most frequent): %s' % dict(noData.most_common(12)))
   print('tags: %s' % dict(collections.Counter(t for l in loops for t in l['tags'])))

if __name__ == '__main__':
   main()

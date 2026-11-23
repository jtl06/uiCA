#!/usr/bin/env python3
"""Find which instruction makes a loop slower than predicted: for each loop, build variants with one instruction removed, measure them
(perf, cycles) and predict them (uiCA). The culprit is the instruction whose removal reduces the measured time much more than the
predicted time. Only for the development set.

Usage: ablate.py METADATA_JSON ARCH CPU OUTDIR LOOPNAME...
"""
import json, os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fuzz_gen
UICA = os.path.join(HERE, '..', '..', 'uiCA.py')
N = 10_000_000
KEEP = re.compile(r'^(ADD R14, 64|AND R14, 448)$')

def build(name, lines, mode, outDir):
   p = os.path.join(outDir, name)
   open(p + '.s', 'w').write('.intel_syntax noprefix\nl:\n' + '\n'.join(lines) + '\ndec r15\njnz l\n')
   subprocess.run(['as', p + '.s', '-o', p + '.o'], check=True)
   open(p + '.exe.s', 'w').write(fuzz_gen.EXE.format(vecInit=fuzz_gen.VEC_INIT[mode], body='\n'.join(lines)))
   subprocess.run(['as', '--defsym', 'NITER=%d' % N, p + '.exe.s', '-o', p + '.exe.o'], check=True)
   subprocess.run(['ld', '-o', p + '.exe', p + '.exe.o'], check=True)
   return p

def measure(cpu, exe):
   best = None
   for _ in range(2):
      r = subprocess.run(['taskset', '-c', cpu, 'perf', 'stat', '-x,', '-e', 'cycles:u', exe], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
      if r.returncode != 0: return None
      c = float(r.stderr.split(',')[0]) / N
      best = c if best is None else min(best, c)
   return best

def predict(arch, obj):
   r = subprocess.run([sys.executable, UICA, obj, '-arch', arch, '-TPonly'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
   try: return float(r.stdout.split()[-1])
   except Exception: return None

def main():
   meta = {l['name']: l for l in json.load(open(sys.argv[1]))['loops']}
   arch, cpu, outDir = sys.argv[2], sys.argv[3], sys.argv[4]
   os.makedirs(outDir, exist_ok=True)
   res = {}
   for name in sys.argv[5:]:
      l = meta[name]; mode = next(t for t in ('int', 'sse', 'avx') if t in l['tags'])
      base = build(name, l['asm'], mode, outDir)
      variants = [('full', None, measure(cpu, base + '.exe'), predict(arch, base + '.o'))]
      for i, line in enumerate(l['asm']):
         if KEEP.match(line): continue
         p = build('%s_v%d' % (name, i), l['asm'][:i] + l['asm'][i + 1:], mode, outDir)
         variants.append((line, i, measure(cpu, p + '.exe'), predict(arch, p + '.o')))
      res[name] = variants
      full = variants[0]
      # culprit: removal reduces the gap (measured - predicted) the most
      best = max(variants[1:], key=lambda v: ((full[2] - full[3]) - (v[2] - v[3])) if (v[2] and v[3]) else -99)
      print('%s full meas %.2f pred %.2f | removing "%s": meas %.2f pred %.2f' % (name, full[2], full[3], best[0], best[2], best[3]), flush=True)
   json.dump(res, open(os.path.join(outDir, 'ablation.json'), 'w'), indent=0)

if __name__ == '__main__':
   main()

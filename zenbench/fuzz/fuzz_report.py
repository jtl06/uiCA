#!/usr/bin/env python3
"""Compare predictions with the measurements of the random loops (fuzz_gen.py, fuzz_measure.py).

A loop is excluded for a machine if its smoke run or measurement failed, if the measured number of instructions per iteration differs from
the expected one, or if the two fastest of the measurement runs differ by more than 2%. Loops are never excluded because of a prediction.
Tools are compared on the loops for which all of them produced a prediction.

Usage: fuzz_report.py METADATA_JSON OBJ_DIR PREDICTIONS_CACHE_JSON ARCH=MEASURED_JSON ... [-details]
       (-details: also list the mnemonics and loops with the largest errors; use this only for the set that is used for development)
"""
import collections, json, os, re, statistics, subprocess, sys
from multiprocessing import Pool
HERE = os.path.dirname(os.path.abspath(__file__))
UICA = os.path.join(HERE, '..', '..', 'uiCA.py')
LLVM_MCA = os.environ.get('LLVM_MCA', 'llvm-mca-22')
# 'stock uiCA X': the upstream version of uiCA (a checkout of its master branch in STOCK_UICA_DIR, with its own instruction data)
TOOLS = {'ZEN3': ['uiCA ZEN3', 'llvm-mca znver3'], 'ADL-P': ['uiCA ADL-P', 'stock uiCA RKL', 'llvm-mca alderlake'],
         'ICL': ['uiCA ICX', 'uiCA ICL', 'stock uiCA ICL', 'llvm-mca icelake-server']} # measured on Ice Lake-SP; uops.info data is from client Ice Lake
STOCK_UICA = os.path.join(os.environ.get('STOCK_UICA_DIR', os.path.join(HERE, '..', '..', '..', 'uiCA-master')), 'uiCA.py')

def predict(job):
   tool, obj = job
   try:
      if tool.startswith('uiCA') or tool.startswith('stock uiCA'):
         r = subprocess.run([sys.executable, STOCK_UICA if tool.startswith('stock') else UICA, obj, '-arch', tool.split()[-1], '-TPonly'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True, timeout=300)
         return float(r.stdout.strip().splitlines()[-1])
      # llvm-mca: the encoding hints ({load}, {store}) are not needed
      src = re.sub(r'\{(load|store)\} ', '', open(obj[:-2] + '.s').read())
      r = subprocess.run([LLVM_MCA, '-mcpu=' + tool.split()[1], '-iterations=1000'], input=src, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True, timeout=300)
      return int(re.search(r'Total Cycles:\s+(\d+)', r.stdout).group(1)) / 1000
   except Exception:
      return None

def findUnknown(meta, objDir, archs):
   # names of the loops that contain an instruction for which uiCA has no data, per architecture
   sys.path.insert(0, os.path.join(HERE, '..', '..'))
   import importlib, xed
   from instructions import getInstructions, UnknownInstr
   from microArchConfigs import MicroArchConfigs
   res = {}
   for arch in archs:
      cfg = MicroArchConfigs[arch]; data = importlib.import_module('instrData.' + arch + '_data')
      res[arch] = set()
      for l in meta['loops']:
         obj = os.path.join(objDir, l['name'] + '.o')
         code = subprocess.run(['objcopy', '-O', 'binary', '-j', '.text', obj, '/dev/stdout'], stdout=subprocess.PIPE).stdout.hex().upper()
         try:
            instrs = getInstructions(xed.disasHex(code, chip=cfg.XEDName), cfg, data, 0)
         except BaseException:
            instrs = None
         if (not instrs) or any(isinstance(i, UnknownInstr) for i in instrs): res[arch].add(l['name'])
   return res

def summary(errs):
   a = [abs(e) for e in errs]
   return '%5d loops: mean %5.1f%%, median %5.1f%%, within 10%%: %5.1f%%, too fast/too slow by >10%%: %4.1f%% / %4.1f%%' % (
      len(a), statistics.mean(a), statistics.median(a), 100.0 * sum(x <= 10 for x in a) / len(a), 100.0 * sum(e < -10 for e in errs) / len(a), 100.0 * sum(e > 10 for e in errs) / len(a))

def main():
   args = [a for a in sys.argv[1:] if a != '-details']
   details = '-details' in sys.argv
   meta, objDir, cacheFile = json.load(open(args[0])), args[1], args[2]
   measured = {a.split('=')[0]: json.load(open(a.split('=')[1])) for a in args[3:]}
   cache = json.load(open(cacheFile)) if os.path.exists(cacheFile) else {}
   jobs = [(t, os.path.join(objDir, l['name'] + '.o')) for arch in measured for t in TOOLS[arch] for l in meta['loops'] if (t + '|' + l['name']) not in cache]
   if jobs:
      with Pool(14) as pool:
         for (t, obj), p in zip(jobs, pool.map(predict, jobs, chunksize=8)):
            cache[t + '|' + os.path.basename(obj)[:-2]] = p
      json.dump(cache, open(cacheFile, 'w'), indent=0)

   unknown = findUnknown(meta, objDir, list(measured))
   for arch, m in measured.items():
      tools = TOOLS[arch]
      excl = collections.Counter(); rows = []
      for l in meta['loops']:
         v = m.get(l['name'])
         if v is None or 'error' in v: excl['run failed'] += 1; continue
         if abs(v['instructions'] - l['instructions']) > 0.01: excl['instruction count differs'] += 1; continue
         if v['spread'] > 0.02: excl['unstable measurement'] += 1; continue
         if l['name'] in unknown.get(arch, set()): excl['instruction without uiCA data'] += 1; continue
         preds = [cache.get(t + '|' + l['name']) for t in tools]
         if any(p is None for p in preds): excl['no prediction from ' + tools[[p is None for p in preds].index(True)]] += 1; continue
         rows.append((l, v['cycles'], preds))
      print('== %s: %d loops generated, %d compared; excluded: %s' % (arch, len(meta['loops']), len(rows), dict(excl)))
      err = lambda p, t: (p - t) / t * 100
      for i, t in enumerate(tools):
         print('   %-20s %s' % (t, summary([err(r[2][i], r[1]) for r in rows])))
      print('   by tag (%s | %s):' % (tools[0], tools[-1]))
      tagsets = [('plain (no rmw, not value-dependent)', lambda l: 'rmw' not in l['tags'] and 'value-dependent' not in l['tags'])]
      tagsets += [(t, (lambda l, t=t: t in l['tags'])) for t in ['int', 'sse', 'avx', 'load', 'store', 'rmw', 'value-dependent']]
      for name, f in tagsets:
         rs = [r for r in rows if f(r[0])]
         if len(rs) < 3: continue
         e0 = [abs(err(r[2][0], r[1])) for r in rs]; e1 = [abs(err(r[2][-1], r[1])) for r in rs]
         print('      %-36s %4d loops: mean %5.1f%% | %5.1f%%   within 10%%: %5.1f%% | %5.1f%%' % (name, len(rs), statistics.mean(e0), statistics.mean(e1),
               100.0 * sum(x <= 10 for x in e0) / len(rs), 100.0 * sum(x <= 10 for x in e1) / len(rs)))
      if details:
         by = collections.defaultdict(list)
         for l, t, preds in rows:
            for mn in set(l['probeMnemonics']): by[mn].append(err(preds[0], t))
         worst = sorted(((statistics.mean(abs(e) for e in es), mn, es) for mn, es in by.items() if len(es) >= 2), reverse=True)
         print('   mnemonics (as probe in >= 2 loops) with the largest mean error of %s:' % tools[0])
         print('      ' + ', '.join('%s %.0f%% (%d loops, %s)' % (mn, me, len(es), 'too fast' if statistics.mean(es) < 0 else 'too slow') for me, mn, es in worst[:24]))
         print('   loops with the largest errors:')
         for l, t, preds in sorted(rows, key=lambda r: -abs(err(r[2][0], r[1])))[:10]:
            print('      %s measured %.2f, predicted %.2f [%s]: %s' % (l['name'], t, preds[0], ' '.join(l['tags']), '; '.join(l['asm'])))

if __name__ == '__main__':
   main()

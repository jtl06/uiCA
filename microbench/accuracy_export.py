#!/usr/bin/env python3
"""accuracy_export.py OUT.jsonl.gz SET[:CACHEDIR] ... [-reference=REF.json]: the measured loops of the held-out sets and the dogfood loops
as an accuracy table for wuica's accuracy gate (crates/wuica/tests/accuracy_gate.rs), one JSON object per line, gzip.

First line, the header: {"format": "wuica-accuracy-1", "options": {...the analysis options...}, "sets": {SET: {"kind", "tpDecimals"}}, "cpus":
{CPU: machine}}. Then one line per loop: {"set", "name", "hex", "mode": "loop"|"unroll", "cycles": {CPU: measured cycles per iteration}};
a CPU is present for a loop exactly if the loop counts for that CPU in docs/ACCURACY.md (the exclusion rules of fuzz/accuracy_table.py:
exclude tags, failed or unstable measurement, a different instruction count, an instruction without uiCA data, and a missing prediction
of any tool of its table in the prediction caches of the set, which are in CACHEDIR (default: measurements/fuzz)).
Predictions are compared rounded to tpDecimals decimals (2: as the command-line tool prints them, which the tables used; None: unrounded,
as dogfood/dogfood.py). CPUs: ZEN3 (Ryzen 7 7735U), ADL-P (Core i7-12650H), ICX (Xeon Gold 6314U, the measurement key ICL).

With -reference=REF.json, also predicts every loop with the uiCA of this repository and writes the per-set, per-CPU numbers (loops, within
5/10/20 %, MAPE) that the gate must reproduce.
"""
import contextlib, gzip, importlib, io, json, os, statistics, subprocess, sys, tempfile
from multiprocessing import Pool
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'fuzz'))
import fuzz_report
FILES = {'ZEN3': 'zen3plus_ryzen7-7735U', 'ADL-P': 'adl-p_i7-12650H', 'ICL': 'icl-sp_xeon-6314U'}
CPU_OF = {'ZEN3': 'ZEN3', 'ADL-P': 'ADL-P', 'ICL': 'ICX'}
MACHINE = {'ZEN3': 'Ryzen 7 7735U (Zen 3+)', 'ADL-P': 'Core i7-12650H P-core (Alder Lake)', 'ICX': 'Xeon Gold 6314U (Ice Lake-SP)'}
OPTIONS = {'alignmentOffset': 0, 'initPolicy': 'diff', 'noMicroFusion': False, 'noMacroFusion': False, 'simpleFrontEnd': False, 'minIterations': 10,
           'minCycles': 500}

def hexOf(obj):
   return subprocess.run(['objcopy', '-O', 'binary', '-j', '.text', obj, '/dev/stdout'], stdout=subprocess.PIPE, check=True).stdout.hex()

def setRows(s, cacheDir):
   M = os.path.join(HERE, 'measurements', 'fuzz')
   meta = json.load(open(os.path.join(M, s + '.json')))
   objDir = os.path.join(HERE, 'out_fuzz', s)
   measured = {a: json.load(open(os.path.join(M, '%s_%s.json' % (s, f)))) for a, f in FILES.items() if os.path.exists(os.path.join(M, '%s_%s.json' % (s, f)))}
   caches = [json.load(open(os.path.join(cacheDir, '%s_predictions_base.json' % s))), json.load(open(os.path.join(cacheDir, '%s_predictions.json' % s)))]
   unknown = fuzz_report.findUnknown(meta, objDir, list(measured))
   cycles = {}
   for arch, m in measured.items():
      for l in meta['loops']:
         if any(t.startswith('exclude:') for t in l['tags']): continue
         v = m.get(l['name'])
         if v is None or 'error' in v: continue
         if abs(v['instructions'] - l['instructions']) > 0.01: continue
         if v['spread'] > 0.02: continue
         if l['name'] in unknown.get(arch, set()): continue
         # every tool of the table: the reference tools from the first cache, the own models from both
         preds = [caches[0].get(t + '|' + l['name']) for t in fuzz_report.TOOLS[arch]]
         preds += [c.get(t + '|' + l['name']) for c in caches[1:] for t in fuzz_report.TOOLS[arch] if t.startswith('uiCA ')]
         if any(p is None for p in preds): continue
         cycles.setdefault(l['name'], {})[CPU_OF[arch]] = v['cycles']
   loops = [l for l in meta['loops'] if l['name'] in cycles]
   with Pool(8) as p:
      hexes = p.map(hexOf, [os.path.join(objDir, l['name'] + '.o') for l in loops])
   return [{'set': s, 'name': l['name'], 'hex': h, 'cycles': cycles[l['name']]} for l, h in zip(loops, hexes)]

def dogfoodRows():
   d = json.load(open(os.path.join(HERE, 'dogfood', 'measured.json')))
   rows = []
   for name in sorted(d['ZEN3']):
      with tempfile.TemporaryDirectory() as t:
         subprocess.run(['as', os.path.join(HERE, 'dogfood', 'loops', name + '.s'), '-o', t + '/a.o'], check=True)
         rows.append({'set': 'dogfood', 'name': name, 'hex': hexOf(t + '/a.o'), 'cycles': {'ZEN3': d['ZEN3'][name]['cycles']}})
   return rows

def init():
   global uiCA, xed, MAC
   sys.path.insert(0, os.path.join(HERE, '..')); os.chdir(os.path.join(HERE, '..'))
   import uiCA as u, xed as x
   from microArchConfigs import MicroArchConfigs
   uiCA, xed, MAC = u, x, MicroArchConfigs

def predict(job):
   hexStr, cpu = job
   cfg = MAC[cpu]
   from instructions import getInstructions
   with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
      disas = xed.disasHex(hexStr, chip=cfg.XEDName)
      instrs = getInstructions(disas, cfg, importlib.import_module('instrData.' + cfg.name + '_data'), 0)
      mode = 'unroll' if not instrs[-1].isBranchInstr else 'loop'
      tp = uiCA.runSimulation(disas, cfg, 0, 'diff', False, False, False, 10, 500)
   return mode, tp

def main():
   args = [a for a in sys.argv[1:] if not a.startswith('-')]
   ref = [a[len('-reference='):] for a in sys.argv[1:] if a.startswith('-reference=')]
   out, specs = args[0], args[1:]
   rows, sets = [], {}
   for spec in specs:
      s, _, cacheDir = spec.partition(':')
      if s == 'dogfood':
         rows += dogfoodRows(); sets[s] = {'kind': 'dogfood', 'tpDecimals': None}
      else:
         rows += setRows(s, cacheDir or os.path.join(HERE, 'measurements', 'fuzz'))
         sets[s] = {'kind': 'real-code blocks' if s.startswith('bhive') else 'random loops', 'tpDecimals': 2}
   jobs = [(r['hex'], cpu) for r in rows for cpu in sorted(r['cycles'])]
   with Pool(15, initializer=init) as p:
      res = dict(zip(jobs, p.map(predict, jobs, chunksize=16)))
   for r in rows:
      modes = set(res[(r['hex'], c)][0] for c in r['cycles'])
      assert len(modes) == 1, r['name']
      r['mode'] = modes.pop()
   header = {'format': 'wuica-accuracy-1', 'options': OPTIONS, 'sets': sets, 'cpus': MACHINE}
   with gzip.GzipFile(out, 'wb', mtime=0) as f:
      f.write((json.dumps(header, separators=(',', ':')) + '\n').encode())
      for r in rows:
         f.write((json.dumps({k: r[k] for k in ('set', 'name', 'hex', 'mode', 'cycles')}, separators=(',', ':')) + '\n').encode())
   print('%d rows, %d bytes' % (len(rows), os.path.getsize(out)))
   if ref:
      table = {}
      for s, info in sets.items():
         for cpu in MACHINE:
            errs = []
            for r in rows:
               if r['set'] != s or cpu not in r['cycles']: continue
               tp = res[(r['hex'], cpu)][1]
               if info['tpDecimals'] is not None: tp = float('{:.{}f}'.format(tp, info['tpDecimals']))
               errs.append(abs(tp - r['cycles'][cpu]) / r['cycles'][cpu] * 100)
            if not errs: continue
            n = len(errs)
            table['%s %s' % (s, cpu)] = {'loops': n, 'within5': sum(e <= 5 for e in errs), 'within10': sum(e <= 10 for e in errs),
                                         'within20': sum(e <= 20 for e in errs), 'mape': statistics.mean(errs)}
            t = table['%s %s' % (s, cpu)]
            print('%-9s %-6s %5d loops  %5.1f%% %5.1f%% %5.1f%%  MAPE %4.1f%%' % (s, cpu, n, 100.0 * t['within5'] / n, 100.0 * t['within10'] / n,
                                                                               100.0 * t['within20'] / n, t['mape']))
      json.dump(table, open(ref[0], 'w'), indent=1)

if __name__ == '__main__':
   main()

#!/usr/bin/env python3
"""Accuracy table for a measured set: per machine and tool, the number of loops, % within 5/10/20 % and the mean absolute percentage error.
Same exclusion rules as fuzz/fuzz_report.py; all tools are compared on the loops for which every tool (in every given cache) has a prediction.

Usage (from microbench/): fuzz/accuracy_table.py SET LABEL=PREDICTIONS_JSON [LABEL=PREDICTIONS_JSON ...] [-only=TAG]
   e.g. fuzz/accuracy_table.py holdout4 before=measurements/fuzz/holdout4_predictions_base.json after=measurements/fuzz/holdout4_predictions.json
   The first cache provides the reference tools (llvm-mca, stock uiCA); the own-model tools ('uiCA X') are taken from every cache, labelled.
"""
import collections, json, os, statistics, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'fuzz'))
import fuzz_report

FILES = {'ZEN3': 'zen3plus_ryzen7-7735U', 'ADL-P': 'adl-p_i7-12650H', 'ICL': 'icl-sp_xeon-6314U'}
CPU = {'ZEN3': 'Ryzen 7 7735U (Zen 3+)', 'ADL-P': 'Core i7-12650H P-core (Alder Lake)', 'ICL': 'Xeon Gold 6314U (Ice Lake-SP)'}

def main():
   args = [a for a in sys.argv[1:] if not a.startswith('-only=')]
   only = [a[6:] for a in sys.argv[1:] if a.startswith('-only=')]
   s = args[0]
   caches = [(a.split('=')[0], json.load(open(a.split('=', 1)[1]))) for a in args[1:]]
   M = os.path.join(HERE, '..', 'measurements', 'fuzz')
   meta = json.load(open(os.path.join(M, s + '.json')))
   objDir = os.path.join(HERE, '..', 'out_fuzz', s)
   measured = {a: json.load(open(os.path.join(M, '%s_%s.json' % (s, f)))) for a, f in FILES.items() if os.path.exists(os.path.join(M, '%s_%s.json' % (s, f)))}
   unknown = fuzz_report.findUnknown(meta, objDir, list(measured))
   for arch, m in measured.items():
      cols = []
      for t in fuzz_report.TOOLS[arch]:
         if t.startswith('uiCA '):
            for label, c in caches: cols.append(('%s (%s)' % (t, label), c, t))
         else:
            cols.append((t, caches[0][1], t))
      excl = collections.Counter(); rows = []
      for l in meta['loops']:
         if only and only[0] not in l['tags']: continue
         ex = [t for t in l['tags'] if t.startswith('exclude:')]
         if ex: excl[ex[0][8:]] += 1; continue
         v = m.get(l['name'])
         if v is None or 'error' in v: excl['run failed'] += 1; continue
         if abs(v['instructions'] - l['instructions']) > 0.01: excl['instruction count differs'] += 1; continue
         if v['spread'] > 0.02: excl['unstable measurement'] += 1; continue
         if l['name'] in unknown.get(arch, set()): excl['no uiCA data'] += 1; continue
         preds = [c.get(t + '|' + l['name']) for _, c, t in cols]
         if any(p is None for p in preds): excl['no prediction from ' + cols[[p is None for p in preds].index(True)][0]] += 1; continue
         rows.append((v['cycles'], preds))
      print('## %s %s, measured on %s: %d loops of %d compared; excluded: %s' % (s + ((' -only=' + only[0]) if only else ''), arch, CPU[arch], len(rows), len(meta['loops']), dict(excl)))
      print('   %-32s %6s %8s %8s %8s %8s' % ('tool', 'loops', '<=5%', '<=10%', '<=20%', 'MAPE'))
      for i, (name, _, _) in enumerate(cols):
         e = [abs(r[1][i] - r[0]) / r[0] * 100 for r in rows]
         print('   %-32s %6d %7.1f%% %7.1f%% %7.1f%% %7.1f%%' % (name, len(e), 100.0 * sum(x <= 5 for x in e) / len(e), 100.0 * sum(x <= 10 for x in e) / len(e),
                                                              100.0 * sum(x <= 20 for x in e) / len(e), statistics.mean(e)))

if __name__ == '__main__':
   main()

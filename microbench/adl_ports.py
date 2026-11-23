#!/usr/bin/env python3
"""Compare uiCA's port usage and uop sources for Alder Lake-P with perf counters from a Core i7-12650H P-core
(measurements/adl-p_i7-12650H/perf_<set>.json, made with perf_measure.py). All numbers are uops per loop iteration.
Usage: adl_ports.py [dev heldout fold]
"""
import collections, json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
DIRS = {'dev': 'out', 'heldout': 'out_heldout', 'fold': 'out_fold'}
GROUPS = [('p0', ['Port0'], 'uops_dispatched.port_0'), ('p1', ['Port1'], 'uops_dispatched.port_1'), ('p5+11', ['Port5', 'PortB'], 'uops_dispatched.port_5_11'),
          ('p6', ['Port6'], 'uops_dispatched.port_6'), ('load', ['Port2', 'Port3', 'PortA'], 'uops_dispatched.port_2_3_10'),
          ('std', ['Port4', 'Port9'], 'uops_dispatched.port_4_9'), ('sta', ['Port7', 'Port8'], 'uops_dispatched.port_7_8')]

def simulate(obj):
   f = tempfile.mktemp(suffix='.json')
   subprocess.run([sys.executable, os.path.join(HERE, '..', 'uiCA.py'), obj, '-arch', 'ADL-P', '-json', f], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
   j = json.load(open(f)); os.remove(f)
   ports, sources, issued = collections.Counter(), collections.Counter(), collections.Counter()
   # only rounds that were retired completely within the simulated cycles
   maxRnd = max(u['rnd'] for c in j['cycles'] for u in c.get('removedFromRB', [])) - 1
   lo, hi = maxRnd // 3, 2 * maxRnd // 3
   for c in j['cycles']:
      for p, u in c.get('dispatched', {}).items():
         if lo <= u['rnd'] < hi: ports[p] += 1
      for u in c.get('addedToIDQ', []):
         if lo <= u['rnd'] < hi: sources[u['source']] += 1
      for u in c.get('addedToRB', []):
         if lo <= u['rnd'] < hi: issued['n'] += 1
   n = float(hi - lo)
   if all(i.get('source') == 'LSD' for i in j['instructions'] if i.get('source')): sources = {'LSD': issued['n']}
   return {g: sum(ports[p] for p in ps) / n for g, ps, _ in GROUPS}, {s: v / n for s, v in sources.items()}, issued['n'] / n

def main(sets):
   diffs = collections.defaultdict(list); worst = []; issuedDiff = []; lsdModel = lsdReal = total = 0
   for s in sets:
      perf = json.load(open(os.path.join(HERE, 'measurements', 'adl-p_i7-12650H', 'perf_%s.json' % s)))
      for name, m in perf.items():
         ports, sources, issued = simulate(os.path.join(HERE, DIRS[s], name + '.o'))
         issuedDiff.append(abs(issued - m['uops_issued.any']))
         total += 1
         lsdModel += sources.get('LSD', 0) > 0.5 * issued
         lsdReal += m['lsd.uops'] > 0.5 * m['uops_issued.any']
         for g, _, ev in GROUPS:
            d = ports[g] - m[ev]; diffs[g].append(abs(d))
            if abs(d) >= 0.3: worst.append((abs(d), '%s/%s %s: model %.2f, measured %.2f' % (s, name, g, ports[g], m[ev])))
   print('%d loops; uops per iteration, mean absolute difference between model and perf:' % total)
   for g, _, _ in GROUPS: print('   %-6s %.3f   (largest %.2f)' % (g, sum(diffs[g]) / len(diffs[g]), max(diffs[g])))
   print('   issued (fused-domain) uops: mean difference %.3f, largest %.2f' % (sum(issuedDiff) / len(issuedDiff), max(issuedDiff)))
   print('   loops mostly delivered by the LSD: model %d, measured %d' % (lsdModel, lsdReal))
   print('differences of 0.3 uops or more (%d):' % len(worst))
   for _, w in sorted(worst, reverse=True)[:22]: print('   ' + w)

if __name__ == '__main__':
   main(sys.argv[1:] or ['dev', 'heldout', 'fold'])

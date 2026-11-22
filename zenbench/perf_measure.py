#!/usr/bin/env python3
"""Count cycles, uops per port and uops per front-end source for loop executables with perf (standard library only).

For Intel P-cores of hybrid CPUs (Alder Lake) and for Ice Lake (non-hybrid; the port groups are mapped to the same names); the executables are the plain ones built by 'bench.py gen' (N iterations of the loop).
Usage: perf_measure.py CPU ITERATIONS OUT_JSON EXE...
"""
import json, os, subprocess, sys

HYBRID = os.path.exists('/sys/devices/cpu_core')
GROUPS = [['cycles', 'instructions', 'uops_dispatched.port_0', 'uops_dispatched.port_1', 'uops_dispatched.port_5_11', 'uops_dispatched.port_6'],
          ['cycles', 'uops_dispatched.port_2_3_10', 'uops_dispatched.port_4_9', 'uops_dispatched.port_7_8', 'uops_issued.any', 'uops_retired.slots'],
          ['cycles', 'idq.dsb_uops', 'idq.mite_uops', 'idq.ms_uops', 'lsd.uops']]
# Ice Lake: event name -> name used in the output
ICL_NAMES = {'uops_dispatched.port_5': 'uops_dispatched.port_5_11', 'uops_dispatched.port_2_3': 'uops_dispatched.port_2_3_10'}

def main():
   cpu, n, outFile = sys.argv[1], float(sys.argv[2]), sys.argv[3]
   res = {}
   for exe in sys.argv[4:]:
      vals = {}
      for group in GROUPS:
         if HYBRID:
            ev = ','.join('cpu_core/%s/u' % e for e in group)
         else:
            ev = ','.join('%s:u' % {v: k for k, v in ICL_NAMES.items()}.get(e, e) for e in group)
         r = subprocess.run(['taskset', '-c', cpu, 'perf', 'stat', '-x,', '-e', ev, exe], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=120)
         for line in r.stderr.splitlines():
            f = line.split(',')
            if len(f) > 4 and f[0].replace('.', '').isdigit():
               name = f[2].replace('cpu_core/', '').replace('/u', '').replace(':u', '')
               name = ICL_NAMES.get(name, name)
               assert float(f[4]) > 99.9, 'event was multiplexed: ' + line
               v = float(f[0]) / n
               vals[name] = min(v, vals[name]) if (name == 'cycles' and name in vals) else v
      name = os.path.basename(exe)[:-len('.exe')]
      res[name] = vals
      print('%-18s cycles %6.3f  uops issued %5.2f  p0 %.2f p1 %.2f p5+11 %.2f p6 %.2f | load %.2f std %.2f sta %.2f | DSB %.2f MITE %.2f MS %.2f LSD %.2f' % (
            name, vals['cycles'], vals['uops_issued.any'], vals['uops_dispatched.port_0'], vals['uops_dispatched.port_1'], vals['uops_dispatched.port_5_11'],
            vals['uops_dispatched.port_6'], vals['uops_dispatched.port_2_3_10'], vals['uops_dispatched.port_4_9'], vals['uops_dispatched.port_7_8'],
            vals['idq.dsb_uops'], vals['idq.mite_uops'], vals['idq.ms_uops'], vals['lsd.uops']), flush=True)
   json.dump(res, open(outFile, 'w'), indent=1)

if __name__ == '__main__':
   main()

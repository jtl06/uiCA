#!/usr/bin/env python3
"""Front-end and dispatch-stall counters on Zen 3 for loop executables (standard library only).
Usage: zen_perf.py CPU ITERATIONS OUT_JSON EXE..."""
import json, os, subprocess, sys
GROUPS = [['cycles', 'instructions', 'op_cache_hit_miss.op_cache_hit', 'op_cache_hit_miss.op_cache_miss', 'de_dis_cops_from_decoder.disp_op_type.any_integer_dispatch', 'ex_ret_ops'],
          ['cycles', 'de_dis_dispatch_token_stalls2.int_sch0_token_stall', 'de_dis_dispatch_token_stalls2.int_sch1_token_stall', 'de_dis_dispatch_token_stalls2.int_sch2_token_stall',
           'de_dis_dispatch_token_stalls2.int_sch3_token_stall', 'de_dis_dispatch_token_stalls2.retire_token_stall'],
          ['cycles', 'de_dis_dispatch_token_stalls1.load_queue_rsrc_stall', 'de_dis_dispatch_token_stalls1.store_queue_rsrc_stall', 'de_dis_dispatch_token_stalls1.int_phy_reg_file_rsrc_stall',
           'de_dis_dispatch_token_stalls2.agsq_token_stall', 'de_dis_dispatch_token_stalls1.taken_brnch_buffer_rsrc'],
          ['cycles', 'de_dis_cops_from_decoder.disp_op_type.any_fp_dispatch', 'de_dis_dispatch_token_stalls1.fp_sch_rsrc_stall', 'de_dis_dispatch_token_stalls1.fp_reg_file_rsrc_stall',
           'de_dis_uop_queue_empty_di0', 'ex_ret_fused_instr']]
def main():
   cpu, n, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
   res = {}
   for exe in sys.argv[4:]:
      vals = {}
      for g in GROUPS:
         r = subprocess.run(['taskset', '-c', cpu, 'perf', 'stat', '-x,', '-e', ','.join(e + ':u' if e in ('cycles', 'instructions') else e for e in g), exe],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=120)
         for line in r.stderr.splitlines():
            f = line.split(',')
            if len(f) > 4 and f[0].replace('.', '').isdigit():
               name = f[2].replace(':u', ''); v = float(f[0]) / n
               vals[name] = min(v, vals[name]) if name == 'cycles' and name in vals else v
      res[os.path.basename(exe)[:-4]] = vals
   json.dump(res, open(out, 'w'), indent=1)
if __name__ == '__main__': main()

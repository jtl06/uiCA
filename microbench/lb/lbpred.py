#!/usr/bin/env python3
"""lbpred.py TREE ARCH SPEC MEAS [-save=FILE]: predictions of the uiCA in TREE for the loops of SPEC (see lb.py) that MEAS (the output of
'lb CPU' on one machine) has measured, with the error of each loop and the share within 10%."""
import contextlib, io, json, os, subprocess, sys, tempfile
args = [a for a in sys.argv[1:] if not a.startswith('-save=')]
save = [os.path.abspath(a[6:]) for a in sys.argv[1:] if a.startswith('-save=')]
TREE, ARCH, SPEC, MEAS = os.path.abspath(args[0]), args[1], os.path.abspath(args[2]), os.path.abspath(args[3])
sys.path.insert(0, TREE); os.chdir(TREE)
import uiCA, xed
from microArchConfigs import MicroArchConfigs
cfg = MicroArchConfigs[ARCH]

def hexOf(lines):
   with tempfile.TemporaryDirectory() as t:
      open(t + '/a.s', 'w').write('.intel_syntax noprefix\n.L:\n' + '\n'.join(lines) + '\n')
      subprocess.run(['as', t + '/a.s', '-o', t + '/a.o'], check=True)
      return subprocess.run(['objcopy', '-O', 'binary', '-j', '.text', t + '/a.o', '/dev/stdout'], stdout=subprocess.PIPE, check=True).stdout.hex()

loops = {}
for line in open(SPEC):
   line = line.strip()
   if line and not line.startswith('#'):
      name, body = line.split(':', 1)
      loops[name.strip()] = [x.strip() for x in body.split(';') if x.strip()]
n10 = tot = 0
preds = {}
for line in open(MEAS):
   parts = line.split()
   if len(parts) != 2 or parts[0] not in loops: continue
   name, m = parts[0], float(parts[1])
   disas = xed.disasHex(hexOf(loops[name]), chip=cfg.XEDName)
   with contextlib.redirect_stdout(io.StringIO()):
      tp = uiCA.runSimulation(disas, cfg, 0, 'diff', False, False, False, 10, 500)
   preds[name] = tp
   e = (tp - m) / m * 100
   tot += 1; n10 += abs(e) <= 10
   print('%-12s %7.2f %7.2f %+5.0f%%' % (name, m, tp, e))
print('%s %s: %d of %d within 10%%' % (ARCH, os.path.basename(MEAS), n10, tot))
if save:
   json.dump(preds, open(save[0], 'w'), indent=1)

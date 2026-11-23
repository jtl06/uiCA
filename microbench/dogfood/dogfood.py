#!/usr/bin/env python3
"""dogfood.py [TREE] [ARCH...] [-save=FILE] [-cmp=FILE]: the dogfood regression set (real loops measured on hardware, measured.json) predicted
by the uiCA in TREE (default: this repository), with the error of each loop and the share within 10%.
   ARCH: default ZEN3 (only architectures with measurements in measured.json are compared; others are printed without error)
   -save=FILE: write the predictions as JSON; -cmp=FILE: add a column with the predictions in FILE
Loops: loops/*.s (Intel syntax), assembled with 'as'."""
import contextlib, importlib, io, json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
args = [a for a in sys.argv[1:] if not a.startswith('-')]
opts = {k: os.path.abspath(v) for k, v in (a[1:].split('=', 1) for a in sys.argv[1:] if a.startswith('-') and '=' in a)}
TREE = os.path.abspath(args[0]) if args and os.path.isdir(args[0]) else os.path.join(HERE, '..', '..')
ARCHS = [a for a in args if not os.path.isdir(a)] or ['ZEN3']
sys.path.insert(0, TREE); os.chdir(TREE)
import uiCA, xed
from microArchConfigs import MicroArchConfigs

def hexOf(path):
   with tempfile.TemporaryDirectory() as t:
      subprocess.run(['as', path, '-o', t + '/a.o'], check=True)
      return subprocess.run(['objcopy', '-O', 'binary', '-j', '.text', t + '/a.o', '/dev/stdout'], stdout=subprocess.PIPE, check=True).stdout.hex()

meas = json.load(open(os.path.join(HERE, 'measured.json')))
names = sorted(f[:-2] for f in os.listdir(os.path.join(HERE, 'loops')) if f.endswith('.s'))
old = json.load(open(opts['cmp'])) if 'cmp' in opts else {}
preds = {}
for arch in ARCHS:
   cfg = MicroArchConfigs[arch]
   preds[arch] = {}
   within = []
   print('%-8s %8s %8s %8s %7s' % (arch, 'measured', 'pred', 'before' if old else '', 'error'))
   for n in names:
      disas = xed.disasHex(hexOf(os.path.join(HERE, 'loops', n + '.s')), chip=cfg.XEDName)
      with contextlib.redirect_stdout(io.StringIO()):
         tp = uiCA.runSimulation(disas, cfg, 0, 'diff', False, False, False, 10, 500)
      preds[arch][n] = tp
      m = meas.get(arch, {}).get(n, {}).get('cycles')
      o = old.get(arch, {}).get(n)
      err = '' if m is None else '%+6.0f%%' % ((tp - m) / m * 100)
      if m is not None: within.append(abs(tp - m) / m <= 0.10)
      print('%-8s %8s %8.2f %8s %7s' % (n, '%.2f' % m if m else '', tp, '%.2f' % o if o is not None else '', err))
   if within:
      print('%s: %d of %d loops within 10%%' % (arch, sum(within), len(within)))
if 'save' in opts:
   json.dump(preds, open(opts['save'], 'w'), indent=1)

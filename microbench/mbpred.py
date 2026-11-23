#!/usr/bin/env python3
# mbpred.py LOOPS_FILE OUTDIR TREE ARCH... : predictions for the loops built by mb.py (TPonly), printed with the measurements found in
# OUTDIR/meas_*.json (written by mb.py measure on each machine and copied back)
import glob, json, os, subprocess, sys
loopsFile, out, tree = sys.argv[1], sys.argv[2], sys.argv[3]
archs = sys.argv[4:]
names = [l.split(':', 1)[0].strip() for l in open(loopsFile) if l.strip() and not l.startswith('#')]
bodies = {l.split(':', 1)[0].strip(): l.split(':', 1)[1].strip() for l in open(loopsFile) if l.strip() and not l.startswith('#')}
meas = {os.path.basename(f)[5:-5]: json.load(open(f)) for f in glob.glob(os.path.join(out, 'meas_*.json'))}
print('%-6s %s | %s | loop' % ('name', ' '.join('%7s' % m[:7] for m in sorted(meas)), ' '.join('%7s' % a[:7] for a in archs)))
for n in names:
   preds = []
   for a in archs:
      r = subprocess.run([sys.executable, os.path.join(tree, 'uiCA.py'), os.path.join(out, n + '.o'), '-arch', a, '-TPonly'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
      preds.append(r.stdout.strip().split()[-1] if r.stdout.strip() else '?')
   print('%-6s %s | %s | %s' % (n, ' '.join('%7.2f' % meas[m].get(n, -1) for m in sorted(meas)), ' '.join('%7s' % p for p in preds), bodies[n]))

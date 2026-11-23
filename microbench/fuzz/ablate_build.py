#!/usr/bin/env python3
"""Build the variants of ablate.py (one instruction removed) without measuring them, for measuring on another machine.
Usage: ablate_build.py METADATA_JSON OUTDIR LOOPNAME...   (writes OUTDIR/variants.json: variant name -> removed instruction)"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import ablate
meta = {l['name']: l for l in json.load(open(sys.argv[1]))['loops']}
out = sys.argv[2]; os.makedirs(out, exist_ok=True)
variants = {}
for name in sys.argv[3:]:
   l = meta[name]; lines = l['asm']
   mode = 'avx' if 'avx' in l['tags'] else ('sse' if 'sse' in l['tags'] else 'int')
   ablate.build(name, lines, mode, out); variants[name] = None
   for j, x in enumerate(lines):
      if ablate.KEEP.match(x): continue
      v = '%s_no%d' % (name, j); ablate.build(v, lines[:j] + lines[j + 1:], mode, out); variants[v] = x
json.dump(variants, open(os.path.join(out, 'variants.json'), 'w'), indent=1)

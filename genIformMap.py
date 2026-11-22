#!/usr/bin/env python3
"""Map iform names in a (newer) uops.info XML file to the iform names that uiCA's bundled XED version reports.

uiCA looks instructions up by the iform reported by its XED version. Newer uops.info XML files use iform names from newer XED versions,
which differ for some instructions (e.g., ANDN_GPR64q_GPR64q_GPR64q vs. ANDN_VGPR64q_VGPR64q_VGPR64q, MOVZX_GPR64_MEMw vs. MOVZX_GPRv_MEMw),
so that these instructions get no data. This script assembles one instance of each instruction whose iform is unknown to the bundled XED,
decodes it with the bundled XED, and writes the resulting mapping to xedIformMap.py, which convertXML.py uses.

Usage: genIformMap.py XMLFILE   (needs the GNU assembler)
"""
import argparse, collections, os, re, subprocess, sys, tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import xed

AVOID = {'RSP', 'ESP', 'SP', 'SPL', 'RIP', 'EIP', 'IP'}

def knownIforms():
   path = os.path.join(HERE, 'XED-to-XML', 'obj', 'xed-iform-enum.txt')
   return set(l.split()[0] for l in open(path) if l.strip() and not l.startswith('#'))

def render(a, ops):
   parts = []
   for o in ops:
      if o.get('suppressed') == '1' or o['type'] == 'flags': continue
      if o['type'] == 'reg':
         regs = [r for r in o['text'].split(',') if r not in AVOID]
         if not regs: return None
         parts.append(regs[0])
      elif o['type'] == 'mem':
         if any(k in o for k in ('base', 'seg', 'moffs', 'index')): return None
         addr = '[RSI]'
         if 'VSIB' in o: addr = '[RSI+%sMM1*1]' % {'xmm': 'X', 'ymm': 'Y', 'zmm': 'Z'}[o['VSIB']]
         parts.append((o.get('memory-prefix', '') + ' ' + addr).strip())
      elif o['type'] == 'agen':
         parts.append('[RAX+RBX*1+8]')
      elif o['type'] == 'imm':
         parts.append(o['text'] if o['text'] else '1')
      else:
         return None
   s = a['asm'] + ' ' + ', '.join(parts)
   if a.get('rep') in ('1', 'REP'): s = 'REP ' + s
   return s.strip()

def assemble(lines):
   """Returns machine code (hex) per line; None for lines the assembler rejects."""
   result = [None] * len(lines)
   todo = list(range(len(lines)))
   with tempfile.TemporaryDirectory() as tmp:
      while todo:
         src = os.path.join(tmp, 'a.s'); obj = os.path.join(tmp, 'a.o')
         # one section per instruction, so that each one can be extracted on its own
         with open(src, 'w') as f:
            f.write('.intel_syntax noprefix\n')
            for k, i in enumerate(todo):
               f.write('.section .text.i%d,"ax"\n%s\n' % (k, lines[i]))
         p = subprocess.run(['as', '--64', src, '-o', obj], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
         bad = set(int(m.group(1)) for m in re.finditer(r':(\d+): Error', p.stderr))
         if bad:
            # line n of the source is instruction (n-2)//2 of todo
            todo = [i for k, i in enumerate(todo) if (2 * k + 3) not in bad]
            continue
         for k, i in enumerate(todo):
            q = subprocess.run(['objcopy', '-O', 'binary', '--only-section=.text.i%d' % k, obj, os.path.join(tmp, 'b')])
            result[i] = open(os.path.join(tmp, 'b'), 'rb').read().hex()
         break
   return result

def main():
   parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
   parser.add_argument('xmlfile')
   parser.add_argument('-o', default=os.path.join(HERE, 'xedIformMap.py'))
   args = parser.parse_args()

   known = knownIforms()
   entries = []
   for _, node in ET.iterparse(args.xmlfile):
      if node.tag != 'instruction': continue
      a = dict(node.attrib)
      ops = [dict(o.attrib, text=(o.text or '')) for o in node.iter('operand')]
      node.clear()
      if a['iform'] in known or '_APX' in a['iform']: continue
      s = render(a, ops)
      if s: entries.append((a['iform'], a['string'], s))

   codes = assemble([e[2] for e in entries])
   mapping = {}
   conflicts = {}
   unresolved = set()
   for (iform, string, asm), code in zip(entries, codes):
      if code is None: unresolved.add(iform); continue
      try:
         d = xed.disasHex(code, chip='ALL')
      except Exception:
         d = None
      if not d or len(d) != 1 or d[0]['iform'] not in known: unresolved.add(iform); continue
      old = d[0]['iform']
      if old.split('_')[0] != iform.split('_')[0]: unresolved.add(iform); continue
      if mapping.get(iform, (old,))[0] != old: conflicts.setdefault(iform, {mapping[iform][0]}).add(old)
      mapping[iform] = (old, d[0].get('eosz'))
   for iform in conflicts: del mapping[iform]
   unresolved -= set(mapping)
   # several new iforms can map to one old iform that covers several operand sizes (e.g., MOVZX_GPR32_MEMw and MOVZX_GPR64_MEMw to
   # MOVZX_GPRv_MEMw); uiCA then needs the operand size (eosz attribute) to tell them apart
   targets = collections.Counter(v[0] for v in mapping.values())
   mapping = {k: (v[0], v[1] if targets[v[0]] > 1 else None) for k, v in mapping.items()}

   with open(args.o, 'w') as f:
      f.write('# Generated by genIformMap.py from %s; do not edit.\n' % os.path.basename(args.xmlfile))
      f.write('# Maps iform names of the uops.info XML file to (iform name reported by the XED version bundled with uiCA, eosz attribute or None).\n')
      f.write('xedIformMap = {\n')
      for k in sorted(mapping): f.write('   %r: %r,\n' % (k, mapping[k]))
      f.write('}\n')
   sys.stdout.flush()
   print('mapped %d iforms; %d conflicting, %d unresolved (not assemblable or unknown to the bundled XED)' % (len(mapping), len(conflicts), len(unresolved)), file=sys.stderr)
   for k in sorted(conflicts): print('  conflict', k, sorted(conflicts[k]), file=sys.stderr)

if __name__ == '__main__':
   main()

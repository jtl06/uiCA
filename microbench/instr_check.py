#!/usr/bin/env python3
"""Check a uiCA microarchitecture model against the per-instruction throughputs measured by uops.info.

For every instruction variant with a measurement for the given microarchitecture, one instance is assembled and simulated on its own,
unrolled and with all dependencies between the instances removed. The predicted cycles per instruction are compared with
min(TP_unrolled, TP_loop) from instructions.xml. No hardware is needed.

A prediction that is too high means that the model is wrong for this instruction. A prediction that is too low can also mean that
uops.info could not avoid a dependency between the instances in its measurement (e.g., instructions with implicit operands).

Usage: instr_check.py ARCH instructions.xml [-simpleFrontEnd] [-limit N] [-jobs N]
"""
import argparse, collections, json, os, re, signal, subprocess, sys, tempfile
import xml.etree.ElementTree as ET
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
SKIP_CATEGORIES = ['COND_BR', 'UNCOND_BR', 'CALL', 'RET', 'SYSCALL', 'SYSRET', 'SYSTEM', 'INTERRUPT', 'IO', 'IOSTRINGOP', 'STRINGOP']

def getAsm(instrNode):
   # adapted from XED-to-XML/xmlToAssembler.py
   asm = instrNode.attrib['asm']
   first = True
   for operandNode in instrNode.iter('operand'):
      operandIdx = int(operandNode.attrib['idx'])
      if operandNode.attrib.get('suppressed', '0') == '1':
         continue
      if not first and not operandNode.attrib.get('opmask', '') == '1':
         asm += ', '
      else:
         asm += ' '
         first = False
      t = operandNode.attrib['type']
      if t == 'reg':
         registers = operandNode.text.split(',')
         register = registers[min(operandIdx, len(registers)-1)]
         if not operandNode.attrib.get('opmask', '') == '1':
            asm += register
         else:
            asm += '{' + register + '}'
            if instrNode.attrib.get('zeroing', '') == '1':
               asm += '{z}'
      elif t == 'mem':
         memoryPrefix = operandNode.attrib.get('memory-prefix', '')
         if memoryPrefix:
            asm += memoryPrefix + ' '
         if operandNode.attrib.get('VSIB', '0') != '0':
            asm += '[' + operandNode.attrib.get('VSIB') + '0]'
         elif operandNode.attrib.get('moffs', '0') != '0':
            asm += '[0x1111111111111111]'
         else:
            asm += '[RAX]'
         memorySuffix = operandNode.attrib.get('memory-suffix', '')
         if memorySuffix:
            asm += ' ' + memorySuffix
      elif t == 'agen':
         agen = instrNode.attrib['agen']
         address = []
         if 'R' in agen: address.append('RIP')
         if 'B' in agen: address.append('RAX')
         if 'IS' in agen: address.append('2*RBX')
         elif 'I' in agen: address.append('1*RBX')
         if 'D8' in agen: address.append('8')
         if 'D32' in agen: address.append('128')
         asm += ' [' + '+'.join(address) + ']'
      elif t == 'imm':
         if instrNode.attrib.get('roundc', '') == '1':
            asm += '{rn-sae}, '
         elif instrNode.attrib.get('sae', '') == '1':
            asm += '{sae}, '
         width = int(operandNode.attrib['width'])
         asm += str(operandNode.text if operandNode.text is not None else (1 << (width-8)) + 1)
      elif t == 'relbr':
         return None
   if not 'sae' in asm:
      if instrNode.attrib.get('roundc', '') == '1':
         asm += ', {rn-sae}'
      elif instrNode.attrib.get('sae', '') == '1':
         asm += ', {sae}'
   return asm

def readXML(xmlFile, arch):
   entries = []
   for _, node in ET.iterparse(xmlFile):
      if node.tag != 'instruction': continue
      m = None
      for an in node.iter('architecture'):
         if an.attrib['name'] == arch: m = an.find('measurement')
      if m is not None and node.attrib['category'] not in SKIP_CATEGORIES and node.attrib.get('cpl', '3') == '3':
         TPs = [float(m.attrib[a]) for a in ['TP_unrolled', 'TP_loop'] if a in m.attrib]
         asm = getAsm(node)
         if TPs and asm:
            memOps = [o for o in node.iter('operand') if o.attrib.get('type') == 'mem']
            entries.append({'string': node.attrib['string'], 'asm': asm, 'measured': min(TPs), 'uops': int(m.attrib.get('uops', 0)),
                            'portsFromUopsInfo': 'ports' in m.attrib, 'category': node.attrib['category'], 'extension': node.attrib['extension'],
                            'iclass': node.attrib['iclass'], 'mem': bool(memOps), 'locked': node.attrib.get('locked', '') == '1'})
      node.clear()
   return entries

def assemble(entries):
   # returns the machine code (hex) for each entry, or None if the assembler rejects it
   d = tempfile.mkdtemp()
   src, obj, binFile = os.path.join(d, 'a.s'), os.path.join(d, 'a.o'), os.path.join(d, 'a.bin')
   active = list(range(len(entries)))
   for _ in range(5):
      with open(src, 'w') as f:
         f.write('.intel_syntax noprefix\n')
         for i in active:
            f.write('i%d: %s\n' % (i, entries[i]['asm']))
         f.write('iend: nop\n')
      r = subprocess.run(['as', '--64', src, '-o', obj], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
      badLines = set(int(x) for x in re.findall(r'a\.s:(\d+): Error', r.stderr))
      if not badLines:
         break
      active = [i for n, i in enumerate(active) if (n + 2) not in badLines]
   else:
      raise Exception('could not assemble')
   subprocess.run(['objcopy', '-O', 'binary', '-j', '.text', obj, binFile], check=True)
   code = open(binFile, 'rb').read()
   nm = subprocess.run(['nm', obj], stdout=subprocess.PIPE, universal_newlines=True, check=True).stdout
   addr = {name: int(a, 16) for a, _, name in (l.split() for l in nm.splitlines() if len(l.split()) == 3)}
   res = [None] * len(entries)
   for n, i in enumerate(active):
      end = addr['i%d' % active[n + 1]] if n + 1 < len(active) else addr['iend']
      res[i] = code[addr['i%d' % i]:end].hex().upper()
   return res

STATE = {}

def initWorker(arch, simpleFrontEnd):
   devnull = os.open(os.devnull, os.O_WRONLY) # the decoder prints an error for each instruction that the chip does not support
   os.dup2(devnull, 1); os.dup2(devnull, 2)
   import uiCA, xed
   from microArchConfigs import MicroArchConfigs
   STATE.update(uiCA=uiCA, xed=xed, cfg=MicroArchConfigs[arch], simple=simpleFrontEnd)
   orig = uiCA.computeUopProperties
   def patched(instructions, uArchConfig):
      orig(instructions, uArchConfig)
      STATE['matched'] = [instr.instrStr for instr in instructions]
      for instr in instructions:
         for prop in instr.UopPropertiesList + instr.regMergeUopPropertiesList:
            # remove all dependencies between instruction instances
            prop.inputOperands = [op for op in prop.inputOperands if isinstance(op, uiCA.PseudoOperand)]
            if prop.isLoadUop:
               prop.memAddr = {'base': None, 'index': None, 'scale': 1, 'disp': 0x12345678} # no store-to-load forwarding
   uiCA.computeUopProperties = patched

def alarm(signum, frame):
   raise TimeoutError()

def simulate(item):
   idx, code = item
   signal.signal(signal.SIGALRM, alarm)
   signal.alarm(60)
   try:
      disas = STATE['xed'].disasHex(code, chip=STATE['cfg'].XEDName)
      TP = STATE['uiCA'].runSimulation(disas, STATE['cfg'], 0, 'diff', False, False, STATE['simple'], 10, 500)
      return idx, TP, STATE['matched'], None
   except BaseException as e:
      return idx, None, None, type(e).__name__ + ': ' + str(e)[:100]
   finally:
      signal.alarm(0)

def classify(pred, meas):
   if abs(pred - meas) <= max(0.1 * meas, 0.05): return 'match'
   return 'too slow' if pred > meas else 'too fast'

def main():
   parser = argparse.ArgumentParser()
   parser.add_argument('arch'); parser.add_argument('xmlfile')
   parser.add_argument('-simpleFrontEnd', action='store_true'); parser.add_argument('-limit', type=int, default=0); parser.add_argument('-jobs', type=int, default=os.cpu_count())
   args = parser.parse_args()

   entries = readXML(args.xmlfile, args.arch)
   if args.limit: entries = entries[::max(1, len(entries) // args.limit)]
   byString = {e['string']: e for e in entries}
   codes = assemble(entries)
   work = [(i, c) for i, c in enumerate(codes) if c]
   sys.stderr = open(os.devnull, 'w') # warnings from the workers
   with Pool(args.jobs, initWorker, (args.arch, args.simpleFrontEnd)) as pool:
      results = pool.map(simulate, work, chunksize=20)

   stats = collections.Counter(); rows = []
   stats['instruction variants with a measurement'] = len(entries)
   stats['not assembled'] = sum(c is None for c in codes)
   for idx, TP, matched, err in results:
      e = entries[idx]
      if err and err.startswith('SystemExit'): stats['not decodable for this microarchitecture'] += 1; continue
      if err: stats['simulation failed'] += 1; rows.append(dict(e, result='failed', error=err)); continue
      if (len(matched) != 1) or (not matched[0]): stats['no uiCA data for the encoding'] += 1; continue
      ref = byString.get(matched[0])
      if ref is None: stats['encoding matched an entry without measurement'] += 1; continue
      if matched[0] in STATE: continue # an earlier variant produced the same encoding
      STATE[matched[0]] = 1
      rows.append(dict(ref, predicted=TP, result=classify(TP, ref['measured'])))
   checked = [r for r in rows if r['result'] != 'failed']
   print('%s%s' % (args.arch, ' (simple front end)' if args.simpleFrontEnd else ''))
   for k, v in stats.items(): print('   %s: %d' % (k, v))
   def line(label, rs):
      c = collections.Counter(r['result'] for r in rs); n = max(1, len(rs))
      print('   %-46s %5d checked: %5.1f%% match, %5.1f%% too fast, %5.1f%% too slow' % (label, len(rs), 100 * c['match'] / n, 100 * c['too fast'] / n, 100 * c['too slow'] / n))
   line('all', checked)
   line('integer (BASE etc.), no memory operand', [r for r in checked if not r['portsFromUopsInfo'] and not r['mem']] if any(not r['portsFromUopsInfo'] for r in checked) else [])
   line('one uop, no memory operand', [r for r in checked if r['uops'] == 1 and not r['mem']])
   line('several uops, no memory operand', [r for r in checked if r['uops'] > 1 and not r['mem']])
   line('with memory operand', [r for r in checked if r['mem'] and not r['locked']])
   line('lock prefix', [r for r in checked if r['locked']])
   line('ports taken from uops.info', [r for r in checked if r['portsFromUopsInfo']])
   line('no port data in uops.info', [r for r in checked if not r['portsFromUopsInfo']])
   for res in ['too slow', 'too fast']:
      c = collections.Counter(r['iclass'] for r in checked if r['result'] == res)
      print('   %s, most frequent instructions: %s' % (res, ', '.join('%s (%d)' % kv for kv in c.most_common(14))))
   out = os.path.join(HERE, 'out_instr'); os.makedirs(out, exist_ok=True)
   json.dump(rows, open(os.path.join(out, '%s%s.json' % (args.arch, '_simpleFE' if args.simpleFrontEnd else '')), 'w'), indent=0)

if __name__ == '__main__':
   main()

#!/usr/bin/env python3
"""Micro-benchmarks for validating uiCA's AMD model.

Each test is a loop body. For every test we build
  * <name>.o    - object file with only the loop (input for uiCA)
  * <name>.s    - the same loop as assembly text (input for llvm-mca)
  * <name>.exe  - a static executable that runs the loop N times (measured with perf)

Usage: bench.py gen | measure | mca | uica <ARCH> | table <ARCH>
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, os.environ.get('ZENBENCH_OUT', 'out'))
UICA = os.path.join(HERE, '..', 'uiCA.py')
N = int(os.environ.get('ZENBENCH_N', 50_000_000))
CPU = '2'
LLVM_MCA = os.environ.get('LLVM_MCA', 'llvm-mca-22')

# name -> (init code run once before the loop, loop body). rsi points to a zeroed 8 KiB buffer.
TESTS = {
   'add_indep6':   ('', 'add rax, 1\nadd rbx, 1\nadd rcx, 1\nadd rdx, 1\nadd rdi, 1\nadd r8, 1'),
   'add_chain4':   ('', 'add rax, rbx\nadd rax, rbx\nadd rax, rbx\nadd rax, rbx'),
   'imul_chain2':  ('mov rax, 1\nmov rbx, 1', 'imul rax, rbx\nimul rax, rbx'),
   'imul_indep3':  ('mov r8, 3', 'imul rax, r8, 5\nimul rbx, r8, 5\nimul rcx, r8, 5'),
   'shl_indep4':   ('', 'shl rax, 1\nshl rbx, 1\nshl rcx, 1\nshl rdx, 1'),
   'lea_chain2':   ('', 'lea rax, [rax+rbx*2+8]\nlea rax, [rax+rbx*2+8]'),
   'mov_chain':    ('', 'mov rbx, rax\nmov rcx, rbx\nmov rax, rcx\nadd rax, 1'),
   'test_jcc3':    ('', 'test rax, rax\njnz 1f\n1: test rbx, rbx\njnz 2f\n2: test rcx, rcx\njnz 3f\n3:'),
   'ptr_chase':    ('mov [rsi], rsi\nmov rax, rsi', 'mov rax, [rax]'),
   'loadop_chain2':('', 'add rax, [rsi]\nadd rax, [rsi+8]'),
   'load_indep6':  ('', 'mov rax, [rsi]\nmov rbx, [rsi+8]\nmov rcx, [rsi+16]\nmov rdx, [rsi+24]\nmov rdi, [rsi+32]\nmov r8, [rsi+40]'),
   'store_indep4': ('', 'mov [rsi], rax\nmov [rsi+8], rbx\nmov [rsi+16], rcx\nmov [rsi+24], rdx'),
   'store_fwd':    ('', 'mov [rsi], rax\nmov rax, [rsi]\nadd rax, 1'),
   'div64':        ('mov r8, 1000000007\nmov r9, 12345', 'xor edx, edx\nmov rax, r8\ndiv r9'),
   'addsd_chain2': ('', 'addsd xmm0, xmm1\naddsd xmm0, xmm1'),
   'vmulpd_indep6':('', 'vmulpd xmm0, xmm8, xmm9\nvmulpd xmm1, xmm8, xmm9\nvmulpd xmm2, xmm8, xmm9\nvmulpd xmm3, xmm8, xmm9\n'
                        'vmulpd xmm4, xmm8, xmm9\nvmulpd xmm5, xmm8, xmm9'),
   'vpaddd_indep6':('', 'vpaddd ymm0, ymm8, ymm9\nvpaddd ymm1, ymm8, ymm9\nvpaddd ymm2, ymm8, ymm9\nvpaddd ymm3, ymm8, ymm9\n'
                        'vpaddd ymm4, ymm8, ymm9\nvpaddd ymm5, ymm8, ymm9'),
   'fma_mem_chain':('', 'vfmadd231pd ymm0, ymm1, [rsi]'),
   'mixed_hash':   ('', 'mov eax, [rsi+rcx*4]\nadd edx, eax\nxor eax, edx\nrol edx, 5\nadd rcx, 1\nand rcx, 255'),
   'mixed_fp':     ('', 'movsd xmm1, [rsi+rcx*8]\nmulsd xmm1, xmm2\naddsd xmm0, xmm1\nadd rcx, 1\nand rcx, 255'),
}

# Loops that were NOT used while developing the Zen 3 model (select with SET=heldout).
HELDOUT = {
   'cmov_chain':   ('', 'cmp rax, rbx\ncmovne rcx, rdx\nadd rcx, 1\ncmp rcx, rdi\ncmove rdx, rcx'),
   'setcc_mix':    ('', 'test rax, rax\nsetz bl\nmovzx ecx, bl\nadd rdx, rcx'),
   'popcnt_indep4':('', 'popcnt rax, r8\npopcnt rbx, r8\npopcnt rcx, r8\npopcnt rdx, r8'),
   'load_add_store':('', 'mov rax, [rsi+rcx*8]\nadd rax, rdx\nmov [rsi+rcx*8+4096], rax\nadd rcx, 1\nand rcx, 63'),
   'zero_idiom':   ('', 'xor eax, eax\nadd rax, rbx\nadd rcx, rax\nadd rcx, rax'),
   'movzx_shift':  ('', 'movzx eax, bl\nshl rax, 3\nadd rbx, rax\nror rbx, 7'),
   'vec_fp_mix':   ('', 'vaddps ymm0, ymm0, ymm1\nvmulps ymm2, ymm0, ymm3\nvxorps ymm4, ymm2, ymm5'),
   'vec_store_load':('', 'movaps [rsi], xmm0\nmovaps xmm1, [rsi+64]\naddps xmm0, xmm1'),
   'push_pop':     ('', 'push rax\npop rbx\nadd rax, rbx'),
   'bitops':       ('', 'bt rax, 5\nadc rbx, 0\nlzcnt rcx, rdx\nbswap rdi'),
   'poly_hash':    ('mov rax, 1', 'imul rax, rax, 31\nadd rax, rbx\nlea rbx, [rbx+rax*2]'),
   'cvt_add':      ('', 'cvtsi2sd xmm0, rax\naddsd xmm1, xmm0\nadd rax, 1'),
   'vec_int_mul':  ('', 'vpmulld ymm0, ymm1, ymm2\nvpaddd ymm3, ymm3, ymm0'),
   'store_indexed':('', 'mov [rsi+rcx*8], rax\nadd rcx, 1\nand rcx, 63'),
   'div32':        ('mov r8, 1000000007\nmov r9, 12345', 'xor edx, edx\nmov eax, r8d\ndiv r9d'),
   'memcpy_like':  ('', 'mov rax, [rsi+rcx*8]\nmov rdx, [rsi+rcx*8+8]\nmov [rsi+rcx*8+4096], rax\nmov [rsi+rcx*8+4104], rdx\nadd rcx, 2\nand rcx, 62'),
}
# Golden Cove: uops.info reports zero uops for the 64-bit forms of add/sub with an 8-bit immediate, inc, dec and lea with base (+ displacement)
# on Alder Lake-P. These loops test how that behaves (select with SET=fold).
FOLD = {
   'addimm_chain1': ('', 'add rax, 1'),
   'addimm_chain2': ('', 'add rax, 1\n' * 2),
   'addimm_chain4': ('', 'add rax, 1\n' * 4),
   'addimm_chain8': ('', 'add rax, 1\n' * 8),
   'inc_chain4':    ('', 'inc rax\n' * 4),
   'inc_chain8':    ('', 'inc rax\n' * 8),
   'sub_chain4':    ('', 'sub rax, 1\n' * 4),
   'lea_bd_chain4': ('', 'lea rax, [rax+1]\n' * 4),
   'add32_chain4':  ('', 'add eax, 1\n' * 4),
   'addimm32_chain4':('', 'add rax, 1000\n' * 4),
   'addimm_indep8': ('', 'add rax, 1\nadd rbx, 1\nadd rcx, 1\nadd rdx, 1\nadd rdi, 1\nadd r8, 1\nadd r9, 1\nadd r10, 1'),
   'fold_then_alu': ('', 'add rax, 1\nadd rax, 1\nxor rbx, rax\nadd rax, 1\nadd rax, 1\nxor rbx, rax'),
   'fold_then_load':('', 'add rcx, 8\nand rcx, 255\nmov rax, [rsi+rcx]\nadd rdx, rax'),
   'addreg_chain8': ('', 'add rax, rbx\n' * 8),
}
if os.environ.get('SET') == 'fold':
   TESTS = FOLD
   OUT = OUT + '_fold'
# Loops for the model changes that were derived from the per-instruction throughputs of uops.info (see instr_check.py): vector loads,
# read-modify-write instructions, lock prefix, FP divider, microcoded instructions (select with SET=fixes).
FP_INIT = 'mov rax, 0x4000000000000000\nmovq xmm8, rax\nmov rax, 0x4008000000000000\nmovq xmm9, rax\nmov r8, 3'
FIXES = {
   'vec_load4':     ('', 'movaps xmm0, [rsi]\nmovaps xmm1, [rsi+16]\nmovaps xmm2, [rsi+32]\nmovaps xmm3, [rsi+48]'),
   'vec_load4_add2':('', 'movaps xmm0, [rsi]\nmovaps xmm1, [rsi+16]\nmovaps xmm2, [rsi+32]\nmovaps xmm3, [rsi+48]\nadd rax, 1\nadd rbx, 1'),
   'rmw_inc4':      ('', 'inc qword ptr [rsi]\ninc qword ptr [rsi+8]\ninc qword ptr [rsi+16]\ninc qword ptr [rsi+24]'),
   'rmw_inc2_load2':('', 'inc qword ptr [rsi]\ninc qword ptr [rsi+8]\nmov rax, [rsi+64]\nmov rbx, [rsi+72]'),
   'lock_add':      ('', 'lock add [rsi], rax\nadd rbx, 1\nadd rcx, 1'),
   'sqrt2':         (FP_INIT, 'vsqrtsd xmm0, xmm8, xmm8\nvsqrtsd xmm1, xmm9, xmm9'),
   'sqrt_div':      (FP_INIT, 'vsqrtsd xmm0, xmm8, xmm8\nvdivsd xmm1, xmm8, xmm9'),
   'div_add4':      (FP_INIT, 'vdivsd xmm1, xmm8, xmm9\nadd rax, 1\nadd rbx, 1\nadd rcx, 1\nadd rdx, 1'),
   'shld_indep2':   (FP_INIT, 'shld rax, r8, 3\nshld rbx, r8, 5'),
   'bsf_indep2':    (FP_INIT, 'bsf rax, r8\nbsf rbx, r8'),
   'rcl2':          ('', 'rcl rax, 1\nrcl rbx, 1'),
   'cvt_indep2':    (FP_INIT, 'vcvtsi2sd xmm0, xmm8, r8\nvcvtsi2sd xmm1, xmm8, r8'),
   'xadd':          ('', 'xadd rax, rbx\nadd rcx, 1'),
}
if os.environ.get('SET') == 'fixes':
   TESTS = FIXES
   OUT = OUT + '_fixes'
# Read-modify-write instructions that update the same address in every iteration (memory renaming; select with SET=rmw)
RMW = {
   'rmw_neg32':      ('', 'neg dword ptr [rsi+64]'),
   'rmw_neg16':      ('', 'neg word ptr [rsi+64]'),
   'rmw_add32_imm':  ('', 'add dword ptr [rsi+64], 3'),
   'rmw_add32_reg':  ('', 'add dword ptr [rsi+64], ecx'),
   'rmw_add64_reg':  ('', 'add qword ptr [rsi+64], rcx'),
   'rmw_xor64_imm':  ('', 'xor qword ptr [rsi+64], 0x12345'),
   'rmw_sar64_1':    ('', 'sar qword ptr [rsi+64], 1'),
   'rmw_add8_imm':   ('', 'add byte ptr [rsi+64], 3'),
   'rmw_bts64_imm':  ('', 'bts qword ptr [rsi+64], 3'),
   'rmw_inc32_add2': ('', 'inc dword ptr [rsi+64]\nadd rax, 1\nadd rbx, 1'),
}
if os.environ.get('SET') == 'rmw':
   TESTS = RMW
   OUT = OUT + '_rmw'
# Read-modify-write chains through one address: operation x operand width (select with SET=rmw2)
RMW2 = {}
for _w, _p, _r in [(8, 'byte', 'cl'), (16, 'word', 'cx'), (32, 'dword', 'ecx'), (64, 'qword', 'rcx')]:
   for _op, _body in [('add_imm', 'add {p} ptr [rsi+64], 3'), ('add_reg', 'add {p} ptr [rsi+64], {r}'), ('and_imm', 'and {p} ptr [rsi+64], 0x7f'),
                      ('neg', 'neg {p} ptr [rsi+64]'), ('not', 'not {p} ptr [rsi+64]'), ('inc', 'inc {p} ptr [rsi+64]'),
                      ('shl1', 'shl {p} ptr [rsi+64], 1'), ('shl3', 'shl {p} ptr [rsi+64], 3'), ('shlcl', 'shl {p} ptr [rsi+64], cl'),
                      ('rol3', 'rol {p} ptr [rsi+64], 3'), ('btc_imm', 'btc {p} ptr [rsi+64], 3'), ('adc_imm', 'adc {p} ptr [rsi+64], 3')]:
      if _w == 8 and _op == 'btc_imm': continue
      RMW2['rmw%d_%s' % (_w, _op)] = ('mov ecx, 1', _body.format(p=_p, r=_r))
if os.environ.get('SET') == 'rmw2':
   TESTS = RMW2
   OUT = OUT + '_rmw2'
# Read-modify-write chains through memory in the presence of other instructions (select with SET=rmwctx)
RMWCTX = {}
_FILL = ['add rax, 1', 'add rbx, 1', 'add rdx, 1', 'add rdi, 1', 'add r8, 1', 'add r9, 1', 'add r10, 1', 'add r11, 1', 'add r12, 1', 'add r13, 1']
for _name, _rmw in [('add32reg', 'add dword ptr [rsi+64], ecx'), ('add16imm', 'add word ptr [rsi+64], 3'), ('shl32', 'shl dword ptr [rsi+64], 3')]:
   for _k in [0, 1, 2, 4, 8]:
      RMWCTX['ctx_%s_f%d' % (_name, _k)] = ('mov ecx, 1', '\n'.join([_rmw] + _FILL[:_k]))
   for _k in [1, 2, 4]:
      RMWCTX['ctx_%s_ld%d' % (_name, _k)] = ('mov ecx, 1', '\n'.join([_rmw] + ['mov %s, qword ptr [rsi+%d]' % (r, 256 + 64 * j) for j, r in enumerate(['rax', 'rbx', 'rdx', 'rdi'][:_k])]))
   for _k in [1, 2]:
      RMWCTX['ctx_%s_st%d' % (_name, _k)] = ('mov ecx, 1', '\n'.join([_rmw] + ['mov qword ptr [rsi+%d], %s' % (1024 + 64 * j, r) for j, r in enumerate(['rax', 'rbx'][:_k])]))
   RMWCTX['ctx_%s_imul' % _name] = ('mov ecx, 1', '\n'.join([_rmw, 'imul rax, rax', 'imul rax, rax']))
   RMWCTX['ctx_%s_ld_before' % _name] = ('mov ecx, 1', '\n'.join(['mov rax, qword ptr [rsi+256]', 'mov rbx, qword ptr [rsi+320]', _rmw]))
if os.environ.get('SET') == 'rmwctx':
   TESTS = RMWCTX
   OUT = OUT + '_rmwctx'
# What makes read-modify-write chains in random loops faster on Ice Lake (select with SET=rmwwhy)
_F0895 = ['mov rcx, qword ptr [rsi+160]', 'shl r8, 3', 'shl byte ptr [rsi+6848], 0', 'mov qword ptr [rsi+6912], r10', 'vpunpckhwd ymm6, ymm1, ymmword ptr [rsi+320]', 'and r13, r9', 'cmp r11, rbx']
RMWWHY = {
   'why_add32_64':       ('mov ecx, 1', 'add dword ptr [rsi+64], ecx'),
   'why_add32_6848':     ('mov ecx, 1', 'add dword ptr [rsi+6848], ecx'),
   'why_shl8_3_6848':    ('', 'shl byte ptr [rsi+6848], 3'),
   'why_shl8_0_6848':    ('', 'shl byte ptr [rsi+6848], 0'),
   'why_shl8_0_64':      ('', 'shl byte ptr [rsi+64], 0'),
   'why_0895':           ('', '\n'.join(_F0895)),
}
for _j in range(len(_F0895)):
   if _j != 2: RMWWHY['why_0895_no%d' % _j] = ('', '\n'.join(_F0895[:_j] + _F0895[_j + 1:]))
RMWWHY['why_0895_shl3'] = ('', '\n'.join(_F0895[:2] + ['shl byte ptr [rsi+6848], 3'] + _F0895[3:]))
RMWWHY['why_add32_st_next'] = ('mov ecx, 1', 'add dword ptr [rsi+6848], ecx\nmov qword ptr [rsi+6912], r10')
RMWWHY['why_add32_st_far'] = ('mov ecx, 1', 'add dword ptr [rsi+6848], ecx\nmov qword ptr [rsi+4096], r10')
RMWWHY['why_add32_st_before'] = ('mov ecx, 1', 'mov qword ptr [rsi+6912], r10\nadd dword ptr [rsi+6848], ecx')
if os.environ.get('SET') == 'rmwwhy':
   TESTS = RMWWHY
   OUT = OUT + '_rmwwhy'
# Read-modify-write chains with a separate store and reload in the same loop (select with SET=rmwpair)
RMWPAIR = {}
for _name, _rmw in [('add32reg', 'add dword ptr [rsi+64], ecx'), ('add16imm', 'add word ptr [rsi+64], 3'), ('shl32', 'shl dword ptr [rsi+64], 3'),
                    ('shl16cl', 'shl word ptr [rsi+64], cl'), ('rcl8', 'rcl byte ptr [rsi+64], 2')]:
   RMWPAIR['pair_%s_none' % _name] = ('mov ecx, 1', _rmw)
   RMWPAIR['pair_%s_gpr' % _name] = ('mov ecx, 1', '\n'.join([_rmw, 'mov qword ptr [rsi+1024], rax', 'mov rbx, qword ptr [rsi+1024]']))
   RMWPAIR['pair_%s_narrow' % _name] = ('mov ecx, 1', '\n'.join([_rmw, 'mov qword ptr [rsi+1024], rax', 'mov ebx, dword ptr [rsi+1024]']))
   RMWPAIR['pair_%s_loadop' % _name] = ('mov ecx, 1', '\n'.join([_rmw, 'mov qword ptr [rsi+1024], rax', 'add rbx, qword ptr [rsi+1024]']))
   RMWPAIR['pair_%s_first' % _name] = ('mov ecx, 1', '\n'.join(['mov qword ptr [rsi+1024], rax', 'mov rbx, qword ptr [rsi+1024]', _rmw]))
   RMWPAIR['pair_%s_split' % _name] = ('mov ecx, 1', '\n'.join(['mov qword ptr [rsi+1024], rax', _rmw, 'mov rbx, qword ptr [rsi+1024]']))
if os.environ.get('SET') == 'rmwpair':
   TESTS = RMWPAIR
   OUT = OUT + '_rmwpair'
# Register moves: same register (never eliminated) and zero-extending moves that may be eliminated (select with SET=movs)
MOVS = {
   'mov_samereg32':  ('', 'mov r11d, r11d\nsub r11, r12'),
   'movzx_samereg':  ('', 'movzx ebx, bl\nor rbx, r8'),
   'movzx_other':    ('', 'movzx ebx, r9b\nor rbx, r8'),
   'movzx_chain':    ('', 'movzx r9d, bl\nmovzx ebx, r9b\nadd rbx, 1'),
   'movzx_chain_or': ('', 'movzx r9d, bl\nmovzx ebx, r9b\nor rbx, r8'),
   'mov32_chain':    ('', 'mov r9d, ebx\nmov ebx, r9d\nor rbx, r8'),
   'mov64_chain':    ('', 'mov r9, rbx\nmov rbx, r9\nor rbx, r8'),
}
if os.environ.get('SET') == 'movs':
   TESTS = MOVS
   OUT = OUT + '_movs'
# Zen 3 stores (select with SET=stores): same-line pairing, store-to-load forwarding into a load-op instruction, 8- and 16-bit stores
STORES = {
   'st2_lines':      ('', 'mov qword ptr [rsi+64], rax\nmov qword ptr [rsi+128], rbx'),
   'st2_sameline':   ('', 'mov qword ptr [rsi+64], rax\nmov qword ptr [rsi+72], rbx'),
   'st4_lines':      ('', 'mov qword ptr [rsi+64], rax\nmov qword ptr [rsi+128], rbx\nmov qword ptr [rsi+192], rcx\nmov qword ptr [rsi+256], rdx'),
   'st4_sameline':   ('', 'mov qword ptr [rsi+64], rax\nmov qword ptr [rsi+72], rbx\nmov qword ptr [rsi+80], rcx\nmov qword ptr [rsi+88], rdx'),
   'fwd_mov':        ('', 'mov [rsi+2048], rax\nmov rax, [rsi+2048]\nadd rax, 1'),
   'fwd_loadop':     ('', 'mov [rsi+2048], rax\nadd rax, [rsi+2048]'),
   'fwd_loadop32':   ('', 'mov [rsi+2048], eax\nadd eax, dword ptr [rsi+2048]'),
   'fwd_narrow':     ('', 'mov [rsi+2048], rax\nmov eax, dword ptr [rsi+2048]\nadd rax, 1'),
   'byte_alone':     ('', 'mov byte ptr [rsi+64], al'),
   'byte_q':         ('', 'mov byte ptr [rsi+64], al\nmov qword ptr [rsi+192], rbx'),
   'byte_q_sameline':('', 'mov byte ptr [rsi+64], al\nmov qword ptr [rsi+72], rbx'),
   'dword_q':        ('', 'mov dword ptr [rsi+64], eax\nmov qword ptr [rsi+192], rbx'),
   'setcc_q':        ('', 'setbe byte ptr [rsi+64]\nmov qword ptr [rsi+192], rbx'),
   'word_word':      ('', 'mov word ptr [rsi+64], ax\nmov word ptr [rsi+192], bx'),
   'bytes3':         ('', 'mov byte ptr [rsi+64], al\nmov byte ptr [rsi+192], bl\nmov byte ptr [rsi+320], cl'),
   'byte_q3':        ('', 'mov byte ptr [rsi+64], al\nmov qword ptr [rsi+192], rbx\nmov qword ptr [rsi+320], rcx\nmov qword ptr [rsi+448], rdx'),
   'byte_q_add4':    ('', 'mov byte ptr [rsi+64], al\nmov qword ptr [rsi+192], rbx\nadd r8, 1\nadd r9, 1\nadd r10, 1\nadd r11, 1'),
}
if os.environ.get('SET') == 'stores':
   TESTS = STORES
   OUT = OUT + '_stores'
if os.environ.get('SET') == 'heldout':
   TESTS = HELDOUT
   OUT = OUT + '_heldout'

LOOP = '.intel_syntax noprefix\nl:\n{body}\ndec r15\njnz l\n'
EXE = '''.intel_syntax noprefix
.globl _start
.bss
.balign 4096
buf: .skip 8192
.text
_start:
xor eax, eax
xor ebx, ebx
xor ecx, ecx
xor edx, edx
xor edi, edi
xor r8d, r8d
xor r9d, r9d
lea rsi, [rip+buf]
{init}
mov r15, {n}
.balign 64
l:
{body}
dec r15
jnz l
mov eax, 60
xor edi, edi
syscall
'''

def run(cmd, **kw):
   return subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, **kw)

def gen():
   os.makedirs(OUT, exist_ok=True)
   for name, (init, body) in TESTS.items():
      p = os.path.join(OUT, name)
      with open(p + '.s', 'w') as f: f.write(LOOP.format(body=body))
      with open(p + '.exe.s', 'w') as f: f.write(EXE.format(init=init, body=body, n=N))
      run(['as', p + '.s', '-o', p + '.o'])
      run(['as', p + '.exe.s', '-o', p + '.exe.o'])
      run(['ld', '-o', p + '.exe', p + '.exe.o'])

def nInstr(name):
   out = run(['objdump', '-d', '--no-show-raw-insn', os.path.join(OUT, name + '.o')]).stdout
   return len(re.findall(r'^\s+[0-9a-f]+:\s+\S', out, re.M))

def measure():
   res = {}
   for name in TESTS:
      best = None
      for _ in range(5):
         r = run(['taskset', '-c', CPU, 'perf', 'stat', '-x,', '-e', 'cycles:u,instructions:u', os.path.join(OUT, name + '.exe')])
         vals = {l.split(',')[2]: float(l.split(',')[0]) for l in r.stderr.splitlines() if l and l[0].isdigit()}
         if best is None or vals['cycles:u'] < best['cycles:u']: best = vals
      res[name] = {'cycles': best['cycles:u'] / N, 'instr': best['instructions:u'] / N, 'expectedInstr': nInstr(name)}
   json.dump(res, open(os.path.join(OUT, 'measured.json'), 'w'), indent=1)
   return res

def mca(cpu='znver3'):
   res = {}
   for name in TESTS:
      r = run([LLVM_MCA, '-mcpu=' + cpu, '-iterations=1000', os.path.join(OUT, name + '.s')])
      res[name] = int(re.search(r'Total Cycles:\s+(\d+)', r.stdout).group(1)) / 1000
   json.dump(res, open(os.path.join(OUT, 'mca_%s.json' % cpu), 'w'), indent=1)
   return res

def uica(arch):
   res = {}
   for name in TESTS:
      try:
         r = run([sys.executable, UICA, os.path.join(OUT, name + '.o'), '-arch', arch, '-TPonly'])
         res[name] = float(r.stdout.strip().splitlines()[-1])
      except Exception as e:
         res[name] = None
   json.dump(res, open(os.path.join(OUT, 'uica_%s.json' % arch), 'w'), indent=1)
   return res

def table(arch):
   m = json.load(open(os.path.join(OUT, 'measured.json')))
   u = json.load(open(os.path.join(OUT, 'uica_%s.json' % arch)))
   l = json.load(open(os.path.join(OUT, 'mca_znver3.json')))
   def err(p, t): return abs(p - t) / t * 100 if p is not None else None
   print('%-15s %9s %9s %7s %9s %7s' % ('test', 'measured', 'uiCA', 'err%', 'llvm-mca', 'err%'))
   eu, el = [], []
   for name in TESTS:
      t = m[name]['cycles']
      e1, e2 = err(u.get(name), t), err(l[name], t)
      if e1 is not None: eu.append(e1)
      el.append(e2)
      print('%-15s %9.2f %9s %7s %9.2f %7.1f' % (name, t, '%.2f' % u[name] if u.get(name) is not None else 'fail',
                                                '%.1f' % e1 if e1 is not None else '-', l[name], e2))
   print('mean abs error: uiCA %.1f%% (%d tests), llvm-mca %.1f%%' % (sum(eu) / max(1, len(eu)), len(eu), sum(el) / len(el)))

if __name__ == '__main__':
   cmd = sys.argv[1]
   if cmd == 'gen': gen()
   elif cmd == 'measure':
      for k, v in measure().items(): print('%-15s %6.2f c/iter  instr/iter %.2f (expected %d)' % (k, v['cycles'], v['instr'], v['expectedInstr']))
   elif cmd == 'mca':
      for k, v in mca().items(): print('%-15s %6.2f' % (k, v))
   elif cmd == 'uica':
      for k, v in uica(sys.argv[2]).items(): print('%-15s %s' % (k, v))
   elif cmd == 'table': table(sys.argv[2])

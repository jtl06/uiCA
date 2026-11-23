#!/bin/bash
# Latency of vector instructions that read a register zeroed by an idiom (or never written since the process started).
# Makes NAME.exe (50M iterations of the loop body); run: for f in *.exe; do taskset -c CPU perf stat -e cycles:u ./$f; done (cycles / 50e6).
# Results: measurements/zero_idiom_latency.txt
mk() {
cat > $1.s <<S
.intel_syntax noprefix
.globl _start
.section .data
.balign 64
z: .quad 0,0,0,0,0,0,0,0
o: .quad 1,1,1,1
.section .text
_start:
$2
mov r15, 50000000
.balign 64
l:
$3
dec r15
jne l
mov eax, 60
xor edi, edi
syscall
S
as --64 $1.s -o $1.o && ld $1.o -o $1.exe
}
mk zero_idiom   "vpxor xmm14,xmm14,xmm14; vpcmpeqd xmm0,xmm0,xmm0" "vpaddd xmm0,xmm0,xmm14"
mk zero_load    "vmovdqa xmm14,[rip+z]; vpcmpeqd xmm0,xmm0,xmm0" "vpaddd xmm0,xmm0,xmm14"
mk one_load     "vmovdqa xmm14,[rip+o]" "vpaddd xmm0,xmm0,xmm14"
mk ones_idiom   "vpcmpeqd xmm14,xmm14,xmm14" "vpaddd xmm0,xmm0,xmm14"
mk acc_zero     "vpcmpeqd xmm14,xmm14,xmm14; vpsubd xmm14,xmm14,xmm14" "vpaddd xmm0,xmm0,xmm14"
mk uninit       "" "vpaddd xmm0,xmm0,xmm14"
mk mixed_zero   "vpxor xmm14,xmm14,xmm14" "vpaddd xmm0,xmm0,xmm14; vpaddd xmm0,xmm0,xmm13"
mk gpr_zidiom   "xor ebx,ebx" "add rax, rbx"
mk tp_zero      "vpxor xmm14,xmm14,xmm14" "vpaddd xmm0,xmm1,xmm14; vpaddd xmm2,xmm3,xmm14; vpaddd xmm4,xmm5,xmm14; vpaddd xmm6,xmm7,xmm14"
mk tp_load      "vmovdqa xmm14,[rip+z]" "vpaddd xmm0,xmm1,xmm14; vpaddd xmm2,xmm3,xmm14; vpaddd xmm4,xmm5,xmm14; vpaddd xmm6,xmm7,xmm14"
mk ymm_zero     "vpxor xmm14,xmm14,xmm14; vmovdqu ymm0,[rip+z]" "vpaddd ymm0,ymm0,ymm14"
mk zmm_zero     "vpxord zmm14,zmm14,zmm14; vmovdqu64 zmm0,[rip+z]" "vpaddd zmm0,zmm0,zmm14"
mk logic_zero   "vpxor xmm14,xmm14,xmm14; vmovdqa xmm0,[rip+z]" "vpor xmm0,xmm0,xmm14"
mk shuf_zero    "vpxor xmm14,xmm14,xmm14; vmovdqa xmm0,[rip+z]" "vpshufb xmm0,xmm0,xmm14"
mk fp_zero      "vxorps xmm14,xmm14,xmm14; vmovdqa xmm0,[rip+z]" "vaddps xmm0,xmm0,xmm14"
mk movd_zero    "vpxor xmm14,xmm14,xmm14" "vpaddd xmm0,xmm0,xmm14; vmovd eax,xmm0; vmovd xmm0,eax"
mk movd_load    "vmovdqa xmm14,[rip+z]" "vpaddd xmm0,xmm0,xmm14; vmovd eax,xmm0; vmovd xmm0,eax"

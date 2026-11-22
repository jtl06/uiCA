#!/bin/bash
# Store-reload chains (memory renaming, store forwarding), setcc and shift-by-cl loops; makes NAME.exe (50M iterations) and NAME.o (loop only).
# Usage: mkdir d && cd d && bash ../renaming_test.sh && for f in *.exe; do taskset -c CPU perf stat -e cycles:u ./$f; done   (cycles / 50e6 = cycles per iteration)
# Results: measurements/renaming_chains.txt
mk() { n=$1; shift; body=$(printf '%s\n' "$@")
cat > $n.s <<S
.intel_syntax noprefix
.globl _start
.bss
.balign 4096
buf: .skip 8192
.text
_start:
lea rsp, [rip+buf+4096]
mov rbp, rsp
mov rbx, rsp
mov rcx, 1
mov r15, 50000000
.balign 64
l:
$body
dec r15
jnz l
mov eax, 60
xor edi, edi
syscall
S
as $n.s -o $n.full.o && ld $n.full.o -o $n.exe
printf '.intel_syntax noprefix\nl:\n%s\ndec r15\njnz l\n' "$body" > $n.l.s && as $n.l.s -o $n.o
}
mk A32from64 "mov eax, [rsp+8]" "add rax, 1" "mov [rsp+8], eax"
mk B64       "mov rax, [rsp+8]" "add rax, 1" "mov [rsp+8], rax"
mk C32       "mov eax, [rsp+8]" "add eax, 1" "mov [rsp+8], eax"
mk Drbp64    "mov rax, [rbp+8]" "add rax, 1" "mov [rbp+8], rax"
mk Erbx64    "mov rax, [rbx+8]" "add rax, 1" "mov [rbx+8], rax"
mk Frcx64    "mov rax, [rsp+8]" "add rax, rcx" "mov [rsp+8], rax"
mk Gmov64    "mov rax, [rsp+8]" "mov [rsp+8], rax"
mk Hmov32    "mov eax, [rsp+8]" "mov [rsp+8], eax"
mk Irbp32    "mov eax, [rbp+8]" "add eax, 1" "mov [rbp+8], eax"
mk Jmovzx    "movzx eax, word ptr [rsp+8]" "add eax, 1" "mov [rsp+8], ax"
mk Kclang184 "mov eax, [rbp+8]" "lea rdx, [rsp+8]" "add rax, 1" "mov [rbp+8], eax" "cmp rbx, rdx"
mk Lrmw      "add qword ptr [rsp+8], 1"
mk Mrmwrbx   "add qword ptr [rbx+8], 1"
mk Nsub      "mov rax, [rsp+8]" "sub rax, 1" "mov [rsp+8], rax"
mk Oinc      "mov rax, [rsp+8]" "inc rax" "mov [rsp+8], rax"
mk Pimul     "mov rax, [rsp+8]" "imul rax, rcx" "mov [rsp+8], rax"
mk Z1ld16st32 "movzx eax, word ptr [rsp+8]" "add eax, 1" "mov [rsp+8], eax"
mk Z2w16       "mov ax, [rsp+8]" "add ax, 1" "mov [rsp+8], ax"
mk Z3b8        "movzx eax, byte ptr [rsp+8]" "add eax, 1" "mov [rsp+8], al"
mk Z4b8mov     "mov al, [rsp+8]" "add al, 1" "mov [rsp+8], al"
mk Z5w16zx32w  "movzx eax, word ptr [rsp+8]" "add ax, 1" "mov [rsp+8], ax"
mk A2st64of32  "mov rax, [rsp+8]" "add eax, 1" "mov [rsp+8], rax"
mk A3mov32of64 "mov eax, [rsp+8]" "mov rdx, rax" "mov [rsp+8], edx"
mk A4lea       "mov eax, [rsp+8]" "lea rax, [rax+1]" "mov [rsp+8], eax"
mk A5ld32of64st "mov rax, [rsp+8]" "mov [rsp+8], eax"
mk A6add32st32b "mov eax, [rsp+8]" "add rax, rcx" "mov [rsp+8], eax"
mk A7movsxd    "movsxd rax, dword ptr [rsp+8]" "add rax, 1" "mov [rsp+8], eax"
mk A8ldst32via64 "mov eax, [rsp+8]" "add rax, 1" "mov rdx, rax" "mov [rsp+8], edx"
mk T1movsxd   "movsxd rax, dword ptr [rsp+8]" "add rax, rcx" "mov [rsp+8], eax"
mk T4leaRR    "mov rax, [rsp+8]" "lea rax, [rax+rcx]" "mov [rsp+8], eax"
mk T5b8fold64 "movzx eax, byte ptr [rsp+8]" "add rax, 1" "mov [rsp+8], al"
mk T6fold32st8 "mov eax, [rsp+8]" "add eax, 1" "mov [rsp+8], eax" "movzx edx, byte ptr [rsp+8]" "mov [rsp+16], dl"
mk T7pop      "pop rax" "add rax, rcx" "push rax"
mk T8sub64st32 "mov eax, [rsp+8]" "sub rax, 1" "mov [rsp+8], eax"
mk T9movsxdmov "movsxd rax, dword ptr [rsp+8]" "mov [rsp+8], eax"
mk S1sete     "test ebp, ebp" "sete al"
mk S2seteonly "sete al"
mk S3shlcl    "shl rdx, cl"
mk S4shlclor  "mov ecx, r13d" "lea eax, [r14+5]" "shl rdx, cl" "or rbx, rdx"
mk S5setmovzx "test ebp, ebp" "setne dl" "movzx edx, dl"
mk S6xorsete  "xor eax, eax" "test ebp, ebp" "sete al"
mk S7shlcl2   "shl rdx, cl" "add rdx, 1"
mk S8sarcl    "sar rdx, cl"
mk S9setcmp   "cmp rax, rbx" "setne al"

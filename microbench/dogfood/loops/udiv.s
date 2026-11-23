.intel_syntax noprefix
.L:
	mov    eax,DWORD PTR [r8+rsi*4]
	xor    edx,edx
	div    ecx
	mov    DWORD PTR [r9+rsi*4],eax
	inc    rsi
	cmp    rdi,rsi
	jne .L

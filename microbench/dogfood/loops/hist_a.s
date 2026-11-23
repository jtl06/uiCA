.intel_syntax noprefix
.L:
	movzx  eax,BYTE PTR [rsi]
	inc    rsi
	inc    DWORD PTR [rdi+rax*4]
	cmp    rdx,rsi
	jne    .L

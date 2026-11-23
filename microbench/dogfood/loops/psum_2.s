.intel_syntax noprefix
.L:
	mov    edx,DWORD PTR [rdi+rax*4-0x8]
	mov    r8d,DWORD PTR [rdi+rax*4-0x4]
	add    r8d,edx
	add    edx,ecx
	add    ecx,r8d
	mov    DWORD PTR [rsi+rax*4-0x8],edx
	mov    DWORD PTR [rsi+rax*4-0x4],ecx
	add    rax,0x2
	cmp    r9,rax
	jae .L

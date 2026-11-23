.intel_syntax noprefix
.L3:
	crc32	rax, QWORD PTR [rdi+rdx]
	crc32	rax, QWORD PTR [rdi+8+rdx]
	add	rdx, 16
	cmp	rdx, rsi
	jb	.L3

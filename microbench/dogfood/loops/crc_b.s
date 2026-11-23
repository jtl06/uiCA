.intel_syntax noprefix
.L:
	crc32  rax,QWORD PTR [rdi]
	crc32  rsi,QWORD PTR [rdi+rdx*1]
	crc32  rcx,QWORD PTR [rdi+rdx*2]
	add    rdi,0x8
	cmp    r8,rdi
	jne    .L

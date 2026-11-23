.intel_syntax noprefix
.L:
	vmovups ymm9,YMMWORD PTR [rdi]
	vmovups ymm10,YMMWORD PTR [rdi+0x20]
	add    rsi,0x100
	add    rdi,0x100
	vmovups ymm11,YMMWORD PTR [rdi-0xc0]
	vmovups ymm12,YMMWORD PTR [rdi-0xa0]
	vmovups ymm13,YMMWORD PTR [rdi-0x80]
	vmovups ymm14,YMMWORD PTR [rdi-0x60]
	vmovups ymm15,YMMWORD PTR [rdi-0x40]
	vmovups ymm8,YMMWORD PTR [rdi-0x20]
	vfmadd231ps ymm6,ymm9,YMMWORD PTR [rsi-0x100]
	vfmadd231ps ymm3,ymm10,YMMWORD PTR [rsi-0xe0]
	vfmadd231ps ymm7,ymm11,YMMWORD PTR [rsi-0xc0]
	vfmadd231ps ymm0,ymm12,YMMWORD PTR [rsi-0xa0]
	vfmadd231ps ymm4,ymm13,YMMWORD PTR [rsi-0x80]
	vfmadd231ps ymm2,ymm14,YMMWORD PTR [rsi-0x60]
	vfmadd231ps ymm5,ymm15,YMMWORD PTR [rsi-0x40]
	vfmadd231ps ymm1,ymm8,YMMWORD PTR [rsi-0x20]
	cmp    rsi,rax
	jne    .L

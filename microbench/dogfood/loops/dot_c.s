.intel_syntax noprefix
.L:
	vmovups ymm4,YMMWORD PTR [rdi]
	vmovups ymm5,YMMWORD PTR [rdi+0x20]
	sub    rsi,0xffffffffffffff80
	sub    rdi,0xffffffffffffff80
	vmovups ymm6,YMMWORD PTR [rdi-0x40]
	vmovups ymm7,YMMWORD PTR [rdi-0x20]
	vfmadd231ps ymm0,ymm4,YMMWORD PTR [rsi-0x80]
	vfmadd231ps ymm2,ymm5,YMMWORD PTR [rsi-0x60]
	vfmadd231ps ymm1,ymm6,YMMWORD PTR [rsi-0x40]
	vfmadd231ps ymm3,ymm7,YMMWORD PTR [rsi-0x20]
	cmp    rax,rsi
	jne    .L

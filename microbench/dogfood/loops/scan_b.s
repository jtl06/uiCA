.intel_syntax noprefix
.L:
	sub    rax,0xffffffffffffff80
	sub    rdi,0xffffffffffffff80
	cmp    rax,rsi
	jae    .L
	vpcmpeqb ymm2,ymm1,YMMWORD PTR [rdi+0x40]
	vpcmpeqb ymm0,ymm1,YMMWORD PTR [rdi+0x60]
	vpor   ymm0,ymm0,ymm2
	vpcmpeqb ymm2,ymm1,YMMWORD PTR [rdi]
	vpor   ymm0,ymm0,ymm2
	vpcmpeqb ymm2,ymm1,YMMWORD PTR [rdi+0x20]
	vpor   ymm0,ymm0,ymm2
	vptest ymm0,ymm3
	je     .L

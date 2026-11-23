.intel_syntax noprefix
.L:
	sub    rdi,0xffffffffffffff80
	cmp    rdi,rsi
	jae    .L
	vpcmpeqb ymm2,ymm1,YMMWORD PTR [rdi+0x40]
	vpcmpeqb ymm0,ymm1,YMMWORD PTR [rdi+0x60]
	vpor   ymm0,ymm0,ymm2
	vpcmpeqb ymm2,ymm1,YMMWORD PTR [rdi]
	vpor   ymm0,ymm0,ymm2
	vpcmpeqb ymm2,ymm1,YMMWORD PTR [rdi+0x20]
	vpor   ymm0,ymm0,ymm2
	vpmovmskb eax,ymm0
	test   eax,eax
	je     .L

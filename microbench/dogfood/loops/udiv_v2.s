.intel_syntax noprefix
.L:
	vmovdqu ymm0,YMMWORD PTR [r8+rdx*4-0x20]
	vpmuludq ymm2,ymm0,ymm3
	vpsrlq ymm1,ymm0,0x20
	vpmuludq ymm1,ymm1,ymm3
	vpsrlq ymm2,ymm2,0x20
	vpblendd ymm1,ymm1,ymm2,0x55
	vpsubd ymm0,ymm0,ymm1
	vpsrld ymm0,ymm0,xmm5
	vpaddd ymm0,ymm0,ymm1
	vpsrld ymm0,ymm0,xmm4
	vmovdqu YMMWORD PTR [rdi+rdx*4-0x20],ymm0
	add    rdx,0x8
	cmp    rsi,rdx
	jae .L

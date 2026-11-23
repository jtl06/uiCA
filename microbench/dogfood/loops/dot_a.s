.intel_syntax noprefix
.L:
	vmovups ymm1,YMMWORD PTR [rsi+rax*1]
	vmulps ymm1,ymm1,YMMWORD PTR [rdi+rax*1]
	add    rax,0x20
	vshufps xmm3,xmm1,xmm1,0x55
	vshufps xmm2,xmm1,xmm1,0xff
	vaddss xmm0,xmm0,xmm1
	vaddss xmm0,xmm0,xmm3
	vunpckhps xmm3,xmm1,xmm1
	vextractf128 xmm1,ymm1,0x1
	vaddss xmm0,xmm0,xmm3
	vaddss xmm0,xmm0,xmm2
	vshufps xmm2,xmm1,xmm1,0x55
	vaddss xmm0,xmm0,xmm1
	vaddss xmm0,xmm0,xmm2
	vunpckhps xmm2,xmm1,xmm1
	vshufps xmm1,xmm1,xmm1,0xff
	vaddss xmm0,xmm0,xmm2
	vaddss xmm0,xmm0,xmm1
	cmp    r8,rax
	jne    .L

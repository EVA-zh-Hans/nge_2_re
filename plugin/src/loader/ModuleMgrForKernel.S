	.set noreorder

#include "pspimport.s"

	IMPORT_START "ModuleMgrForKernel",0x00090011
	// 3.xx NID (0xA1A78C58); 6.60/6.61 CFW NID resolvers map it to 0xCE0A74A5,
	// and PPSSPP implements 0xA1A78C58 as sceKernelLoadModuleForLoadExecVSHDisc.
	IMPORT_FUNC  "ModuleMgrForKernel",0xA1A78C58,sceKernelLoadModuleDisc

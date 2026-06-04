#include <pspkernel.h>
#include <pspmodulemgr.h>

#include "runtime_args.h"
#include "runtime_patch.h"

PSP_MODULE_INFO("EVA2Runtime", PSP_MODULE_USER, 1, 0);
PSP_NO_CREATE_MAIN_THREAD();

static int RuntimeMain(SceSize args, void *argp)
{
    Eva2RuntimeStartArgs start_args;
    SceKernelModuleInfo info;

    if (args < sizeof(start_args) || !argp) {
        return sceKernelExitDeleteThread(0);
    }

    start_args = *(Eva2RuntimeStartArgs *)argp;
    if (start_args.boot_mid < 0) {
        return sceKernelExitDeleteThread(0);
    }

    info.size = sizeof(info);
    if (sceKernelQueryModuleInfo(start_args.boot_mid, &info) < 0) {
        return sceKernelExitDeleteThread(0);
    }

    RuntimePatch_InstallAll(info.segmentaddr[0], start_args.flags);
    return sceKernelExitDeleteThread(0);
}

int module_start(SceSize args, void *argp)
{
    int th = sceKernelCreateThread("eva2_runtime", RuntimeMain, 0x1f, 0x2000, 0, 0);
    if (th >= 0) {
        sceKernelStartThread(th, args, argp);
    }
    return 0;
}

int module_stop(SceSize args, void *argp)
{
    return 0;
}

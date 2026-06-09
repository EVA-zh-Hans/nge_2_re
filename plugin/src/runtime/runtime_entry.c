#include <pspkernel.h>
#include <pspmodulemgr.h>

#include "runtime_args.h"
#include "runtime_patch.h"
#include "staff_roll_log.h"

PSP_MODULE_INFO("EVA2Runtime", PSP_MODULE_USER, 1, 0);

int module_start(SceSize args, void *argp)
{
    Eva2RuntimeStartArgs start_args;
    SceKernelModuleInfo info;

    StaffRollLog_Init();
    StaffRollLog_Printf("runtime module_start args=%u", (unsigned)args);
    if (args < sizeof(start_args) || !argp) {
        StaffRollLog_Printf("runtime module_start: invalid args or argp");
        return 0;
    }

    start_args = *(Eva2RuntimeStartArgs *)argp;
    StaffRollLog_Printf(
        "runtime start_args boot_mid=%d flags=%08x",
        start_args.boot_mid,
        start_args.flags);
    if (start_args.boot_mid < 0) {
        StaffRollLog_Printf("runtime module_start: boot_mid < 0");
        return 0;
    }

    info.size = sizeof(info);
    if (sceKernelQueryModuleInfo(start_args.boot_mid, &info) < 0) {
        StaffRollLog_Printf("runtime module_start: sceKernelQueryModuleInfo failed for %d", start_args.boot_mid);
        return 0;
    }

    StaffRollLog_Printf("runtime game_base=%08x", (unsigned)info.segmentaddr[0]);
    RuntimePatch_InstallAll(info.segmentaddr[0], start_args.flags);
    StaffRollLog_Printf("runtime install all done");
    return 0;
}

int module_stop(SceSize args, void *argp)
{
    return 0;
}

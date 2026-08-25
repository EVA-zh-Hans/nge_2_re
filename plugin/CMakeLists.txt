cmake_minimum_required(VERSION 3.10)

# Set project name  
project(EBOOT C ASM)

# Check if DEBUG is set  
if(DEFINED DEBUG)
    add_definitions(-DPSPDEBUG)
endif()

# Define loader source files
set(LOADER_SOURCES
    src/loader/loader.c
    src/loader/ui_draw.c
    src/loader/image_display.c
    src/bin/atlas.c
    src/bin/atlas_palette.c
)

# Define runtime source files
set(RUNTIME_SOURCES
    src/runtime/runtime_entry.c
    src/runtime/runtime_patch.c
    src/runtime/hook_write.c
    src/runtime/character_status_overlay.c
    src/runtime/character_status_overlay_core.c
    src/runtime/character_status_renderer.c
    src/runtime/patches/text_encoding_patch.c
    src/runtime/patches/sentence_patch.c
    src/runtime/patches/external_translation_patch.c
    src/runtime/patches/font_patch.c
    src/runtime/patches/savedata_patch.c
    src/runtime/patches/message_dialog_patch.c
    src/runtime/patches/debug_patch.c
    src/runtime/patches/frame_rate_patch.c
    src/runtime/patches/runtime_log.c
    src/runtime/patches/staff_roll_patch.c
    src/runtime/patches/memtalk/memtalk_patch.c
    src/runtime/patches/memtalk/memtalk_game_calls.c
    src/runtime/patches/memtalk/memtalk_templates.c
    src/transform.c
    src/bin/atlas.c
    src/bin/gb2312.c
    src/bin/sjis.c
    src/bin/utf16.c
    src/utils/log.c
    src/sceLibFont.S
    src/scefttt.c
    src/psputil.c
)

# Create PRX modules with exports
add_prx_module(EBOOT ${LOADER_SOURCES} src/loader/exports_loader.exp)
add_prx_module(EVA2RT ${RUNTIME_SOURCES} src/runtime/exports_runtime.exp)

# Set compiler flags for C files only  
target_compile_options(EBOOT PRIVATE -O2 -Wall)
target_compile_options(EVA2RT PRIVATE -O2 -G0 -Wall -fno-pic)

# Set assembly flags for PSP import functions  
set_property(SOURCE src/sceLibFont.S APPEND PROPERTY COMPILE_DEFINITIONS
    F_sceLibFont_0000 # sceLibFont
    F_sceLibFont_0003 # sceFontGetFontInfo
    F_sceLibFont_0014 # sceFontOpenUserFile
    F_sceLibFont_0017 # sceFontNewLib
)

# Link all required libraries  
target_link_libraries(EBOOT PRIVATE
    pspgu
    pspdisplay
    pspctrl
    pspge
)

target_link_libraries(EVA2RT PRIVATE
    pspdisplay
    pspctrl
)

# Include directories  
target_include_directories(EBOOT PRIVATE include)
target_include_directories(EVA2RT PRIVATE include src/runtime/patches/memtalk)

add_custom_command(
    TARGET EBOOT
    POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE_DIR:EBOOT>/EBOOT.prx $<TARGET_FILE_DIR:EBOOT>/EBOOT.BIN
    COMMENT "Creating EBOOT.BIN copy"
)

add_custom_command(
    TARGET EVA2RT
    POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE_DIR:EVA2RT>/EVA2RT.prx $<TARGET_FILE_DIR:EVA2RT>/EVA2RT.PRX
    COMMENT "Creating EVA2RT.PRX copy"
)

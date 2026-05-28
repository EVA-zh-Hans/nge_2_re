cmake_minimum_required(VERSION 3.10)

# Set project name  
project(EBOOT)

# Check if DEBUG is set  
if(DEFINED DEBUG)
    add_definitions(-DPSPDEBUG)
endif()

# Define source files  
set(SOURCES
    src/loader/loader.c
    src/loader/ui_draw.c
    src/loader/image_display.c
    src/patcher.c
    src/transform.c
    src/bin/gb2312.c
    src/bin/sjis.c
    src/bin/utf16.c
    src/utils/log.c
    src/bin/atlas.c
    src/bin/atlas_palette.c
    src/sceLibFont.S
    src/scefttt.c
    src/psputil.c
    src/fs.c
    src/utils/utils.c
)

# Create PRX module with exports  
add_prx_module(EBOOT ${SOURCES} src/loader/exports_loader.exp)

# Set compiler flags for C files only  
target_compile_options(EBOOT PRIVATE -O2 -Wall)

# Set C++ specific flags (only for .cpp files)  
set_source_files_properties(${SOURCES} PROPERTIES LANGUAGE C)

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

# Include directories  
target_include_directories(EBOOT PRIVATE include)

add_custom_command(
    TARGET EBOOT
    POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE_DIR:EBOOT>/EBOOT.prx $<TARGET_FILE_DIR:EBOOT>/EBOOT.BIN
    COMMENT "Creating EBOOT.BIN copy"
)

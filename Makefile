# ==========================================
# Configuration & Path Definitions
# ==========================================
GAME_ID ?= 00064
GAME_IDS := 00061 00064

# Temporary and Build Directories
TEMP_DIR        := temp
DOWNLOAD_DIR    := $(TEMP_DIR)/downloads
BUILD_DIR       := build
EXPORT_GAME_DIR := $(BUILD_DIR)/ULJS00064/PSP_GAME
EXPORT_BIN_DIR  := $(EXPORT_GAME_DIR)/USRDIR
EXPORT_SYSDIR   := $(EXPORT_GAME_DIR)/SYSDIR
EXPORT_USRDIR   := $(EXPORT_GAME_DIR)/USRDIR
TOOLS_DIR       := $(BUILD_DIR)/tools

# Source Directories
PSP_GAME_DIR    := $(TEMP_DIR)/ULJS00064/PSP_GAME
USRDIR          := $(PSP_GAME_DIR)/USRDIR

# HGAR Directories List (Used for loop)
HGAR_DIRS       := btdemo btface btl chara event face free game im map

# Tool Commands
UV_RUN          := uv run
PYTHON_MAIN     := $(UV_RUN) -m app.cli.main

# ==========================================
# Default Target: Help
# ==========================================
.DEFAULT_GOAL := help

help:
	@echo "Available commands:"
	@echo "  make init_db             - Initialize the database"
	@echo "  make import_all          - Import all assets (hgar, text, bind)"
	@echo "  make download_trans      - Download translations from ParaTranz"
	@echo "  make generate_memtalk_templates - Generate Runtime MemTalk C templates"
	@echo "  make generate_staff_roll - Generate translated Staff Roll assets"
	@echo "  make preview_staff_roll  - Generate and open the Staff Roll PNG preview"
	@echo "  make inject_staff_roll   - Inject staff21.hpt into exported staff.har"
	@echo "  make import_trans        - Import downloaded translations to DB"
	@echo "  make export_all          - Export all game files (text, hgar, eboot)"
	@echo "  make gen_metadata        - Generate patch metadata (JSON and image)"
	@echo "  make patch_iso           - Create the patched ISO and xdelta"
	@echo "  make patch_all_ids       - Generate patches for all GAME_IDS (00061 & 00064)"
	@echo "  make full_build          - Run the complete pipeline"
	@echo "  make clean               - Clean build artifacts"

# ==========================================
# Database & Import Tasks
# ==========================================

init_db:
	@echo "Initializing database..."
	$(PYTHON_MAIN) --init_db

# Combined Import HGAR Target using Loop
import_hgar:
	@echo "Importing HGAR archives..."
	@for dir in $(HGAR_DIRS); do \
		echo "  -> Importing $$dir..."; \
		$(PYTHON_MAIN) --import_har "$(USRDIR)/$$dir"; \
	done

import_text:
	@echo "Importing text entries..."
	$(PYTHON_MAIN) --import_text '$(USRDIR)/free/f2info.bin'
	$(PYTHON_MAIN) --import_text '$(USRDIR)/free/f2tuto.bin'

import_bind:
	@echo "Importing binding entries..."
	$(PYTHON_MAIN) --import_bind '$(USRDIR)/btl/btimtext.bin'
	$(PYTHON_MAIN) --import_bind '$(USRDIR)/game/imtext.bin'

import_all: import_hgar import_text import_bind

# ==========================================
# Translation Management
# ==========================================

download_trans:
	@echo "Downloading translations..."
	@mkdir -p $(DOWNLOAD_DIR)
	$(UV_RUN) -m scripts.paratranz.download --action download --dest_folder $(DOWNLOAD_DIR)
	$(UV_RUN) -m scripts.paratranz.download --action merge --dest_folder $(DOWNLOAD_DIR)

generate_memtalk_templates:
	@echo "Generating MemTalk Runtime templates..."
	$(UV_RUN) -m scripts.memtalk.memtalk_generate_c_templates \
		--input '$(DOWNLOAD_DIR)/utf8/memtalk.json' \
		--output 'plugin/src/runtime/patches/memtalk/memtalk_templates.c'

# TODO: Add specific check targets if needed, or group them here
check_trans:
	@echo "Checking translations..."
	$(UV_RUN) -m scripts.check '$(DOWNLOAD_DIR)/evs_trans.json' $(BUILD_DIR)/evs_report.json evs
	# ... (Add other checks here if needed)

import_trans: generate_memtalk_templates
	@echo "Importing translations..."
	$(PYTHON_MAIN) --import_translation '$(DOWNLOAD_DIR)/evs_trans.json'
	$(PYTHON_MAIN) --import_translation '$(DOWNLOAD_DIR)/utf8/free/info.json'
	$(PYTHON_MAIN) --import_translation '$(DOWNLOAD_DIR)/utf8/free/tuto.json'
	$(PYTHON_MAIN) --import_translation '$(DOWNLOAD_DIR)/utf8/game/btimtext.json'
	$(PYTHON_MAIN) --import_translation '$(DOWNLOAD_DIR)/utf8/game/imtext.json'

import_images:
	@echo "Importing images..."
	$(PYTHON_MAIN) --import_images 'resources/trans_pic/trans'

# ==========================================
# Export Tasks
# ==========================================

export_text:
	@echo "Exporting text entries..."
	$(PYTHON_MAIN) --export_text $(EXPORT_USRDIR)/free --text_filename f2info.bin
	$(PYTHON_MAIN) --export_text $(EXPORT_USRDIR)/free --text_filename f2tuto.bin

export_bind:
	@echo "Exporting binding entries..."
	$(PYTHON_MAIN) --export_bind $(EXPORT_USRDIR)/btl --bind_filename btimtext.bin
	$(PYTHON_MAIN) --export_bind $(EXPORT_USRDIR)/game --bind_filename imtext.bin

export_hgar:
	@echo "Generating hgar..."
	$(PYTHON_MAIN) --output_hgar $(EXPORT_USRDIR)

generate_staff_roll:
	@echo "Generating translated Staff Roll..."
	$(UV_RUN) scripts/staff/generate_staff_roll.py

preview_staff_roll: generate_staff_roll
	@echo "Opening $(BUILD_DIR)/generated/staff_roll/staff21.png..."
	@if command -v open >/dev/null 2>&1; then \
		open $(BUILD_DIR)/generated/staff_roll/staff21.png; \
	elif command -v xdg-open >/dev/null 2>&1; then \
		xdg-open $(BUILD_DIR)/generated/staff_roll/staff21.png; \
	else \
		echo "Preview: $(BUILD_DIR)/generated/staff_roll/staff21.png"; \
	fi

inject_staff_roll: export_hgar generate_staff_roll
	@echo "Injecting translated Staff Roll..."
	$(UV_RUN) scripts/staff/generate_staff_roll.py \
		--inject-har $(EXPORT_USRDIR)/game/staff.har

export_eboot_trans:
	@echo "Generating EBOOT translation binary..."
	@mkdir -p $(EXPORT_BIN_DIR)
	$(UV_RUN) -m app.elf_patch.patcher -t $(DOWNLOAD_DIR)/eboot_trans.json -o $(EXPORT_BIN_DIR)/EBTRANS.BIN

export_all: export_text export_bind inject_staff_roll export_eboot_trans

# ==========================================
# Tools & Plugins Build
# ==========================================

plugin: generate_staff_roll
	@echo "Building plugin..."
	$(MAKE) -C plugin
	@mkdir -p $(EXPORT_SYSDIR)
	@echo "Copying EBOOT.BIN to SYSDIR..."
	@cp -r plugin/EBOOT.BIN $(EXPORT_SYSDIR)/EBOOT.BIN
	@echo "Copying EVA2RT.PRX to SYSDIR..."
	@cp -r plugin/EVA2RT.prx $(EXPORT_SYSDIR)/EVA2RT.PRX

pgftool:
	@echo "Building pgftool..."
	$(MAKE) -C third_party/pgftool
	@mkdir -p $(TOOLS_DIR)
	@cp third_party/pgftool/{dump_pgf,mix_pgf,ttf_pgf} $(TOOLS_DIR)/

pspdecrypt:
	@echo "Building pspdecrypt..."
	$(MAKE) CC=gcc CXX=g++ -C third_party/pspdecrypt
	@mkdir -p $(TOOLS_DIR)
	@cp third_party/pspdecrypt/pspdecrypt $(TOOLS_DIR)/

# ==========================================
# ISO & Patch Operations
# ==========================================

extract_iso:
	@echo "Extracting game files..."
	$(UV_RUN) scripts/pack/unpack.py -o '$(TEMP_DIR)/ULJS00064' '$(TEMP_DIR)/ULJS00064.iso'

decrypt_eboot: pspdecrypt
	@echo "Decrypting EBOOT..."
	@mkdir -p $(EXPORT_SYSDIR)
	./$(TOOLS_DIR)/pspdecrypt '$(PSP_GAME_DIR)/SYSDIR/EBOOT.BIN' -o '$(EXPORT_SYSDIR)/BOOT.BIN'

copy_font:
	@echo "Copying font files..."
	@cp resources/assets/fonts.pgf $(EXPORT_USRDIR)/fonts.pgf

# Timestamped output filenames to avoid overwriting previous builds
TIMESTAMP := $(shell TZ=Asia/Shanghai date +%Y%m%d-%H%M%S)
PATCHED_ISO := $(BUILD_DIR)/ULJS$(GAME_ID)_patched_$(TIMESTAMP).iso
PATCH_XDELTA := $(BUILD_DIR)/ULJS$(GAME_ID)_patch_$(TIMESTAMP).xdelta

gen_metadata:
	@echo "Generating patch metadata..."
	$(UV_RUN) -m scripts.gen_metadata --output $(BUILD_DIR)/metadata.json --image $(BUILD_DIR)/metadata.png --pic0 $(EXPORT_GAME_DIR)/PIC0.PNG
	@echo "Copying metadata.raw to game directory..."
	@mkdir -p $(EXPORT_GAME_DIR)
	@cp $(BUILD_DIR)/metadata.raw $(EXPORT_BIN_DIR)/metadata.raw

repack_iso:
	@echo "Repacking game files into ISO..."
	@mkdir -p $(BUILD_DIR)
	$(UV_RUN) scripts/pack/repack_add.py '$(TEMP_DIR)/ULJS$(GAME_ID).iso' '$(PATCHED_ISO)' '$(BUILD_DIR)/ULJS00064'

gen_xdelta:
	@echo "Generating xdelta patch..."
	xdelta3 -e -9 -S djw -f -s '$(TEMP_DIR)/ULJS$(GAME_ID).iso' '$(PATCHED_ISO)' '$(PATCH_XDELTA)'

patch_iso: repack_iso gen_xdelta

# ==========================================
# Meta Targets
# ==========================================

# Full Build Pipeline
# Note: We keep strictly ordered steps here to avoid DB locking issues
full_build:
	$(MAKE) extract_iso
	$(MAKE) init_db
	$(MAKE) import_all
	$(MAKE) import_images
	$(MAKE) import_trans
	$(MAKE) export_all
	$(MAKE) plugin
	$(MAKE) decrypt_eboot
	$(MAKE) copy_font
	$(MAKE) gen_metadata
	$(MAKE) patch_all_ids

rebuild:
	$(MAKE) download_trans
	$(MAKE) import_trans
	$(MAKE) import_images
	$(MAKE) export_all
	$(MAKE) plugin
	$(MAKE) decrypt_eboot
	$(MAKE) copy_font
	$(MAKE) gen_metadata
	$(MAKE) patch_all_ids

# Build patches for all GAME_IDS
patch_all_ids: $(addprefix patch_id_,$(GAME_IDS))

patch_id_%:
	@echo "Generating patch for GAME_ID $*..."
	$(MAKE) patch_iso GAME_ID=$*

clean:
	@echo "Cleaning build directory..."
	rm -rf $(BUILD_DIR)
	# Optional: Clean plugin and tools
	# $(MAKE) -C plugin clean

.PHONY: generate_staff_roll preview_staff_roll inject_staff_roll
	# $(MAKE) -C third_party/pspdecrypt clean

# Mark targets as PHONY (not real files)
.PHONY: help init_db import_hgar import_text import_bind import_images import_all \
        download_trans generate_memtalk_templates check_trans import_trans \
        export_text export_bind export_hgar export_eboot_trans export_all \
        plugin pgftool pspdecrypt \
        extract_iso decrypt_eboot copy_font repack_iso gen_xdelta gen_metadata patch_iso \
        full_build rebuild patch_all_ids patch_id_% clean

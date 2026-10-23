# ==========================================
# Configuration & Path Definitions
# ==========================================
GAME_ID ?= 00064
GAME_IDS := 00064 00061

# Temporary and Build Directories
TEMP_DIR        := temp
DOWNLOAD_DIR    := $(TEMP_DIR)/downloads
BUILD_DIR       := build
EXPORT_DIR      := $(BUILD_DIR)/common
EXPORT_GAME_DIR := $(EXPORT_DIR)/PSP_GAME
EXPORT_BIN_DIR  := $(EXPORT_GAME_DIR)/USRDIR
EXPORT_SYSDIR   := $(EXPORT_GAME_DIR)/SYSDIR
EXPORT_USRDIR   := $(EXPORT_GAME_DIR)/USRDIR
TOOLS_DIR       := $(BUILD_DIR)/tools
PATCH_DIR       := $(BUILD_DIR)/ULJS$(GAME_ID)
PATCH_GAME_DIR  := $(PATCH_DIR)/PSP_GAME

# Source Directories
PSP_GAME_DIR    := $(TEMP_DIR)/ULJS$(GAME_ID)/PSP_GAME
USRDIR          := $(PSP_GAME_DIR)/USRDIR

# Tool Commands
UV_RUN          := uv run

# ==========================================
# Default Target: Help
# ==========================================
.DEFAULT_GOAL := help

help:
	@echo "Available commands:"
	@echo "  make download_trans      - Download translations, terminology, and run checks"
	@echo "  make generate_memtalk_templates - Generate Runtime MemTalk C templates"
	@echo "  make generate_staff_roll - Generate translated Staff Roll assets"
	@echo "  make preview_staff_roll  - Generate and open the Staff Roll PNG preview"
	@echo "  make inject_staff_roll   - Deprecated; requires exported game/staff.har"
	@echo "  make export_resources    - Build translated resources on demand"
	@echo "  make export_eboot_trans  - Generate the EBOOT translation binary"
	@echo "  make gen_metadata        - Generate patch metadata (JSON and image)"
	@echo "  make edit_sfo GAME_ID=id - Update the title in that ISO's PARAM.SFO"
	@echo "  make patch_iso GAME_ID=id - Create one patched ISO and xdelta"
	@echo "  make patch_all_ids       - Generate patches for all GAME_IDS (00061 & 00064)"
	@echo "  make full_build          - Run the complete pipeline"
	@echo "  make clean               - Clean build artifacts"

# ==========================================
# Translation Management
# ==========================================

download_trans:
	@echo "Downloading translations..."
	@mkdir -p $(DOWNLOAD_DIR)
	$(UV_RUN) -m scripts.paratranz.download --action download --dest_folder $(DOWNLOAD_DIR)
	$(UV_RUN) -m scripts.paratranz.download --action merge --dest_folder $(DOWNLOAD_DIR)
	$(MAKE) check_trans

generate_memtalk_templates:
	@echo "Generating MemTalk Runtime templates..."
	$(UV_RUN) -m scripts.memtalk.memtalk_generate_c_templates \
		--input '$(DOWNLOAD_DIR)/utf8/memtalk.json' \
		--output 'plugin/src/runtime/patches/memtalk/memtalk_templates.c'

check_trans:
	@echo "Checking translations..."
	$(UV_RUN) -m scripts.check \
		--downloads-dir '$(DOWNLOAD_DIR)' \
		--terms-file '$(DOWNLOAD_DIR)/terms-10882.json' \
		--report '$(BUILD_DIR)/translation_report.json'

# ==========================================
# Export Tasks
# ==========================================

generate_staff_roll:
	@echo "Generating translated Staff Roll..."
	$(UV_RUN) scripts/staff/generate_staff_roll.py

preview_staff_roll: generate_staff_roll
	@echo "Opening $(BUILD_DIR)/generated/staff_roll/staff_roll.png..."
	@if command -v open >/dev/null 2>&1; then \
		open $(BUILD_DIR)/generated/staff_roll/staff_roll.png; \
	elif command -v xdg-open >/dev/null 2>&1; then \
		xdg-open $(BUILD_DIR)/generated/staff_roll/staff_roll.png; \
	else \
		echo "Preview: $(BUILD_DIR)/generated/staff_roll/staff_roll.png"; \
	fi

# Deprecated: this only reinjects the staff roll into an existing exported
# game/staff.har. Run export_resources first to create that archive.
inject_staff_roll: generate_staff_roll
	@echo "Warning: inject_staff_roll is deprecated and requires an existing exported game/staff.har."
	$(UV_RUN) scripts/staff/generate_staff_roll.py \
		--inject-har $(EXPORT_USRDIR)/game/staff.har

export_eboot_trans:
	@echo "Generating EBOOT translation binary..."
	@mkdir -p $(EXPORT_BIN_DIR)
	$(UV_RUN) -m app.elf_patch.patcher -t $(DOWNLOAD_DIR)/eboot_trans.json -o $(EXPORT_BIN_DIR)/EBTRANS.BIN

export_resources:
	@echo "Building translated resources on demand..."
	$(UV_RUN) -m app.pipeline.stream_build \
		--source $(USRDIR) \
		--output $(EXPORT_USRDIR) \
		--downloads $(DOWNLOAD_DIR) \
		--images resources/trans_pic/trans \
		--report $(BUILD_DIR)/resource-report.json

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
	@if [ -d '$(USRDIR)' ] && [ -f '$(PSP_GAME_DIR)/SYSDIR/EBOOT.BIN' ]; then \
		echo "ISO already extracted for GAME_ID=$(GAME_ID)."; \
	else \
		echo "Extracting game files for GAME_ID=$(GAME_ID)..."; \
		$(UV_RUN) scripts/pack/unpack.py \
			-o '$(TEMP_DIR)/ULJS$(GAME_ID)' \
			'$(TEMP_DIR)/ULJS$(GAME_ID).iso'; \
	fi

extract_sfo:
	@echo "Extracting PARAM.SFO for GAME_ID=$(GAME_ID)..."
	$(UV_RUN) scripts/pack/unpack.py \
		--only '/PSP_GAME/PARAM.SFO' \
		-o '$(TEMP_DIR)/ULJS$(GAME_ID)' \
		'$(TEMP_DIR)/ULJS$(GAME_ID).iso'

decrypt_eboot: pspdecrypt
	@echo "Decrypting EBOOT..."
	@mkdir -p $(EXPORT_SYSDIR)
	./$(TOOLS_DIR)/pspdecrypt '$(PSP_GAME_DIR)/SYSDIR/EBOOT.BIN' -o '$(EXPORT_SYSDIR)/BOOT.BIN'

copy_font:
	@echo "Copying font files..."
	@cp resources/assets/fonts.pgf $(EXPORT_USRDIR)/fonts.pgf

edit_sfo:
	@echo "Editing PARAM.SFO for GAME_ID=$(GAME_ID)..."
	@mkdir -p $(PATCH_GAME_DIR)
	$(UV_RUN) -m scripts.sfo \
		--output '$(PATCH_GAME_DIR)/PARAM.SFO' \
		'$(PSP_GAME_DIR)/PARAM.SFO'

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
	$(UV_RUN) scripts/pack/repack_add.py '$(TEMP_DIR)/ULJS$(GAME_ID).iso' '$(PATCHED_ISO)' '$(PATCH_DIR)'

gen_xdelta:
	@echo "Generating xdelta patch..."
	xdelta3 -e -9 -S djw -f -s '$(TEMP_DIR)/ULJS$(GAME_ID).iso' '$(PATCHED_ISO)' '$(PATCH_XDELTA)'

patch_iso:
	$(MAKE) extract_sfo GAME_ID=$(GAME_ID)
	$(MAKE) prepare_patch_dir GAME_ID=$(GAME_ID)
	$(MAKE) edit_sfo GAME_ID=$(GAME_ID)
	$(MAKE) repack_iso GAME_ID=$(GAME_ID) TIMESTAMP=$(TIMESTAMP)
	$(MAKE) gen_xdelta GAME_ID=$(GAME_ID) TIMESTAMP=$(TIMESTAMP)

# ==========================================
# Meta Targets
# ==========================================

# Full Build Pipeline
full_build:
	$(MAKE) extract_iso
	$(MAKE) generate_memtalk_templates
	$(MAKE) export_resources
	$(MAKE) export_eboot_trans
	$(MAKE) plugin
	$(MAKE) decrypt_eboot
	$(MAKE) copy_font
	$(MAKE) gen_metadata
	$(MAKE) patch_all_ids

rebuild:
	$(MAKE) download_trans
	$(MAKE) generate_memtalk_templates
	$(MAKE) export_resources
	$(MAKE) export_eboot_trans
	$(MAKE) plugin
	$(MAKE) decrypt_eboot
	$(MAKE) copy_font
	$(MAKE) gen_metadata
	$(MAKE) patch_all_ids

# Each patch gets a disposable copy of the common overlay so the two game IDs
# can replace PARAM.SFO and repack concurrently.
prepare_patch_dir:
	@test -d '$(EXPORT_GAME_DIR)' || { \
		echo "Common export is missing; run full_build or rebuild first." >&2; \
		exit 1; \
	}
	@rm -rf '$(PATCH_DIR)'
	@cp -R '$(EXPORT_DIR)' '$(PATCH_DIR)'

patch_all_ids:
	$(MAKE) -j$(words $(GAME_IDS)) $(addprefix patch_id_,$(GAME_IDS)) TIMESTAMP=$(TIMESTAMP)

patch_id_%:
	@echo "Generating patch for GAME_ID $*..."
	$(MAKE) patch_iso GAME_ID=$* TIMESTAMP=$(TIMESTAMP)

clean:
	@echo "Cleaning build directory..."
	rm -rf $(BUILD_DIR)
	# Optional: Clean plugin and tools
	# $(MAKE) -C plugin clean

.PHONY: generate_staff_roll preview_staff_roll inject_staff_roll export_resources
	# $(MAKE) -C third_party/pspdecrypt clean

# Mark targets as PHONY (not real files)
.PHONY: help download_trans generate_memtalk_templates check_trans \
        export_resources export_eboot_trans \
        plugin pgftool pspdecrypt \
        extract_iso extract_sfo decrypt_eboot copy_font edit_sfo repack_iso gen_xdelta gen_metadata patch_iso \
        full_build rebuild prepare_patch_dir patch_all_ids patch_id_% clean

PYTHON ?= uv run python

GENERATED_DIR := build/generated/plugin
ASSET_DIR := assets

GB2312_BIN := $(GENERATED_DIR)/GB2312_CUSTOM.BIN
GB2312_MAP := $(GENERATED_DIR)/GB2312_Custom_Map.json
ATLAS_BIN := $(GENERATED_DIR)/atlas.bin
ATLAS_PALETTE_BIN := $(GENERATED_DIR)/atlas_palette.bin
GB2312_STAMP := $(GENERATED_DIR)/gb2312.stamp
ATLAS_STAMP := $(GENERATED_DIR)/atlas.stamp

UI_ATLAS_FONT := $(ASSET_DIR)/fonts/ChillRoundFBold.ttf
UI_ATLAS_CHARS := $(ASSET_DIR)/ui_atlas_chars.txt
STAFF_ROLL_FONT := ../resources/assets/font/SourceHanSerifSC-Heavy.otf
STAFF_ROLL_TITLE_FONT := ../resources/assets/font/SourceHanSansSC-Medium.otf

GB2312_C := src/bin/gb2312.c
ATLAS_C := src/bin/atlas.c
ATLAS_PALETTE_C := src/bin/atlas_palette.c
ATLAS_HEADER := include/atlas_data.h
STAFF_ROLL_HEADER := src/runtime/patches/generated_staff_roll.h
STAFF_ROLL_MANIFEST := ../resources/staff_roll/credits.json
STAFF_ROLL_GENERATOR := ../scripts/staff/generate_staff_roll.py

release: generate-assets
	make -f Makefile.loader
	mv EBOOT.prx EBOOT.BIN
	make -f Makefile.runtime
debug: generate-assets
	make -f Makefile.loader DEBUG=1
	mv EBOOT.prx EBOOT.BIN
	make -f Makefile.runtime DEBUG=1
clean: 
	make -f Makefile.loader clean
	make -f Makefile.runtime clean
	rm -f EBOOT.BIN
	rm -f EVA2RT.prx
	rm -rf $(GENERATED_DIR)
cmake:
	cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DCMAKE_TOOLCHAIN_FILE=$PSPDEV/psp/share/pspdev.cmake -B build .

generate-assets: $(GB2312_C) $(ATLAS_C) $(ATLAS_PALETTE_C) $(ATLAS_HEADER) $(STAFF_ROLL_HEADER)

$(STAFF_ROLL_HEADER): $(STAFF_ROLL_GENERATOR) $(STAFF_ROLL_MANIFEST) \
		$(STAFF_ROLL_FONT) $(STAFF_ROLL_TITLE_FONT)
	cd .. && $(PYTHON) scripts/staff/generate_staff_roll.py

$(GB2312_BIN) $(GB2312_MAP): $(GB2312_STAMP)

$(GB2312_STAMP): scripts/gentable.py
	@mkdir -p $(GENERATED_DIR)
	$(PYTHON) scripts/gentable.py --out-bin $(GB2312_BIN) --out-map $(GB2312_MAP)
	@touch $@

$(GB2312_C): $(GB2312_BIN) $(GB2312_STAMP) scripts/bin2c.py
	$(PYTHON) scripts/bin2c.py --symbol GB2312_CUSTOM_BIN $(GB2312_BIN) $(GB2312_C)

$(ATLAS_BIN) $(ATLAS_PALETTE_BIN) $(ATLAS_HEADER): $(ATLAS_STAMP)

$(ATLAS_STAMP): scripts/gen_ttf_atlas.py $(UI_ATLAS_FONT) $(UI_ATLAS_CHARS)
	@mkdir -p $(GENERATED_DIR)
	$(PYTHON) scripts/gen_ttf_atlas.py --font $(UI_ATLAS_FONT) --chars $(UI_ATLAS_CHARS) --out-dir $(GENERATED_DIR) --header $(ATLAS_HEADER)
	@touch $@

$(ATLAS_C): $(ATLAS_BIN) $(ATLAS_STAMP) scripts/bin2c.py
	$(PYTHON) scripts/bin2c.py --symbol atlas_bin $(ATLAS_BIN) $(ATLAS_C)

$(ATLAS_PALETTE_C): $(ATLAS_PALETTE_BIN) $(ATLAS_STAMP) scripts/bin2c.py
	$(PYTHON) scripts/bin2c.py --symbol atlas_palette_bin $(ATLAS_PALETTE_BIN) $(ATLAS_PALETTE_C)

check-generated:
	@$(MAKE) generate-assets
	@git diff --exit-code -- $(GB2312_C) $(ATLAS_C) $(ATLAS_PALETTE_C) $(ATLAS_HEADER)

.PHONY: release debug clean cmake generate-assets check-generated

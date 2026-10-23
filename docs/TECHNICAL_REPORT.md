# Technical Report: NGE2 Localization Patch Toolchain

## Overview

This repository builds Chinese localization patches for the PSP game *Neon
Genesis Evangelion 2: Another Cases*. The build reads an extracted source game
tree, applies translations and image replacements on demand, rebuilds the
affected proprietary resources, builds the PSP runtime plugin, and repacks the
result as ISO and xdelta files.

The resource path does not use an intermediate database. Source files remain
the authoritative binary input for every build.

## Architecture

- `app/parser/tools/` reads and writes HGAR, HGPT, TEXT, BIND, EVS, and related
  formats.
- `app/pipeline/` indexes translation and image inputs in memory and transforms
  resources directly from the extracted game tree.
- `app/elf_patch/patcher.py` generates `EBTRANS.BIN` for runtime EBOOT text.
- `plugin/` contains the PSP loader, runtime patches, font support, and generated
  assets.
- `scripts/` contains translation download/checking, staff roll, metadata, and
  ISO pack/unpack utilities.
- `Makefile` is the supported operator interface.

## Resource Build

`make export_resources` invokes `app.pipeline.stream_build` with the extracted
`USRDIR`, downloaded translations, and translated PNG assets. It writes the
result to `build/common/PSP_GAME/USRDIR`.

The pipeline loads translation and image catalogs once, then processes
standalone TEXT and BIND files and HGAR archives. Unchanged resources are copied
from the source tree. Changed archives are written atomically and parsed again
to verify their entry metadata and content before replacing the output.

EVS translations can be selected by generic text hash or by a CEV-specific
file and entry index. HGPT replacements are selected by the hash prefix in the
PNG filename. Replacements must preserve the original dimensions; indexed
images are rebuilt with a compatible palette size.

The resource report at `build/resource-report.json` records timings, applied
changes, conflicts, mismatches, and unmatched translation/image inputs.

## Full Build

`make full_build` runs these stages in order:

1. Extract the source ISO selected by `GAME_ID`.
2. Generate runtime MemTalk templates.
3. Build translated resources directly from source assets.
4. Generate `EBTRANS.BIN`.
5. Build and install the PSP plugin.
6. Decrypt and prepare the original EBOOT.
7. Copy font assets and generate metadata.
8. Repack both supported game IDs and generate xdelta patches.

The supported IDs are `ULJS-00061` and `ULJS-00064`. Shared assets are built
under `build/common`, then copied to separate per-ID staging directories. Each
staging directory receives the `PARAM.SFO` extracted from its matching source
ISO before both outputs are repacked in parallel.

## Binary Formats

Changes to HGAR, HGPT, TEXT, BIND, EVS, ELF, or EBOOT code must preserve field
widths, byte order, offsets, padding, alignment, compression metadata, and
runtime encoding assumptions. Parser acceptance alone is insufficient:
serializer changes require focused round-trip tests and validation through the
affected resource build stage.

The Chinese text path depends on the custom EVA Shift-JIS mapping, generated
font assets, translation data, and PSP runtime hooks remaining synchronized.

## Development And Verification

Set up dependencies with:

```sh
uv venv
uv sync
```

Run the local quality gate with:

```sh
uv run ruff check .
uv run python -m unittest discover -s tests -v
```

Use `make export_resources` for a representative resource build when the
extracted game and downloaded translation inputs are available. PSP plugin,
EBOOT, and final ISO validation additionally require their external toolchains
and source ISO files.

Build output under `build/`, extracted inputs under `temp/`, and local logs are
not source. `AUTH_KEY` and other credentials must never be committed or written
to build reports.

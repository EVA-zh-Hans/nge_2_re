# Technical Report: NGE2 Localization Patch Toolchain

## 1. Executive Summary

This repository implements a localization patch production pipeline for the PSP game *Neon Genesis Evangelion 2: Another Cases* / *The Created World*. Its main technical goal is to make a Chinese localization patch reproducible from a clean game ISO, translation data, edited image resources, and checked-in tooling.

The project combines reverse-engineered binary parsers, a SQLite-backed asset database, translation import/export utilities, PSP-side runtime patching code, and ISO repacking scripts. The preferred operator interface is the top-level `Makefile`, which orchestrates the full workflow from ISO extraction through final xdelta patch generation.

The implementation is primarily Python, with PSP plugin code in C/assembly and a partial C++ parser implementation for performance experiments and cross-checking.

## 2. Project Scope

The repository targets two known PSP game IDs:

- `ULJS-00061`
- `ULJS-00064`

Both IDs are handled by the build pipeline, while the working extracted tree is normalized under `ULJS00064` for patch assembly. The pipeline emits patched ISO images and xdelta patch files for the supported IDs.

The localization scope includes:

- EVS scenario/dialogue resources inside HGAR archives.
- Standalone `TEXT` resources such as `f2info.bin` and `f2tuto.bin`.
- `BIND` text containers such as `btimtext.bin` and `imtext.bin`.
- HGPT image resources extracted from HGAR archives.
- EBOOT/runtime text replacement through generated `EBTRANS.BIN` and PSP-side patching.
- Font and encoding support for Simplified Chinese text rendering.

## 3. Repository Architecture

### 3.1 Python Application Layer

The `app/` directory contains the main Python implementation:

- `app/cli/main.py` provides the command-line interface used by the Makefile.
- `app/database/` defines SQLAlchemy models and DAO classes for imported assets.
- `app/parser/tools/` contains binary parsers and serializers for HGAR, HGPT, TEXT, BIND, EVS, PNG-related helpers, compression, and common encoding logic.
- `app/elf_patch/patcher.py` generates `EBTRANS.BIN`, the runtime translation table consumed by the PSP patch.

The CLI exposes focused import/export actions instead of a single monolithic command. This design lets the Makefile compose the pipeline while still allowing developers to debug individual stages.

### 3.2 Database Layer

The project uses SQLite through SQLAlchemy. The default database is:

```text
example.db
```

`app/database/db.py` enables SQLite WAL mode and performance-oriented pragmas:

- `journal_mode=WAL`
- `synchronous=NORMAL`
- `cache_size=-10000`
- `temp_store=MEMORY`

The database is not just a cache; it is the intermediate representation that connects resource extraction, translation import, image replacement, and binary reconstruction.

Core tables include:

- `hgars`: HGAR archive records, including archive name, version, and relative path.
- `hgar_files`: files inside each HGAR archive, including names, sizes, identifiers, compression-related metadata, and optional HGPT links.
- `sentences`: deduplicated original text strings keyed by hash.
- `translations`: imported translation strings keyed to original text identifiers.
- `evs_entries`: parsed EVS command entries that may reference sentence keys.
- `text_entries`: structured entries from standalone TEXT binaries.
- `bind_entries`: entries from BIND containers.
- `hgpts`: deduplicated HGPT images with original binary content, exported PNG data, translated PNG data, dimensions, format metadata, palette metadata, and division metadata.
- `raws`: fallback storage for HGAR contents that are not parsed as EVS or HGPT.

### 3.3 Parser Layer

The parser layer handles proprietary game formats discovered through reverse engineering.

Important formats:

- `HGAR`: archive container used throughout `USRDIR`.
- `HGPT`: image format, including tiled/paletted and RGBA variants.
- `TEXT`: standalone string-table format.
- `BIND`: block-aligned binary container format.
- `EVS`: event/script entries, including dialogue-like strings.

The serializers preserve enough binary metadata to reconstruct game-compatible files. This is critical because localization changes are not limited to text replacement; archive identifiers, compression flags, string offsets, block alignment, image palettes, and encoded text bytes must remain valid.

### 3.4 PSP Plugin Layer

The `plugin/` directory contains the PSP-side loader and runtime patch code.

Key responsibilities:

- Generate a patched `EBOOT.BIN`.
- Patch text decoding behavior so Simplified Chinese text can be represented inside otherwise Shift-JIS-oriented game paths.
- Provide generated GB2312 mapping data and UI atlas/font assets.
- Load runtime translation resources such as `EBTRANS.BIN`.

The plugin build is driven by `plugin/Makefile`, with `make release`, `make debug`, and asset generation targets. Generated C arrays live under `plugin/src/bin/` so the PSP build does not always need to regenerate conversion tables and atlas assets.

### 3.5 Scripts and Tooling

The `scripts/` directory contains support tools for:

- ParaTranz download and merge workflows.
- Machine translation helper flows.
- ISO unpack/repack operations.
- Translation checks.
- Metadata generation.
- Benchmarks and profiling.
- OCR/image-related experiments.

`scripts/gen_metadata.py` produces build metadata in JSON and PNG form. Metadata includes Git commit information, submodule versions, optional ParaTranz statistics, and a PSP-resolution visual summary intended for inclusion in the patched game tree.

### 3.6 C++ Parser Work

The `cpp/` directory contains a C++ implementation of part of the parser logic, notably HGPT-related code. It appears to serve as a performance and correctness comparison path for selected binary parsing tasks. Any changes to shared binary formats should keep the Python and C++ implementations aligned.

## 4. Build and Release Pipeline

The top-level `Makefile` is the canonical build interface. It decomposes the patch build into independently runnable stages.

### 4.1 Full Build Flow

`make full_build` runs the following ordered stages:

1. Extract the source ISO into `temp/ULJS00064`.
2. Initialize the SQLite database.
3. Import HGAR, TEXT, and BIND resources.
4. Import translated images.
5. Import downloaded translations.
6. Export translated TEXT, BIND, HGAR, and EBOOT translation resources.
7. Build the PSP plugin and copy the resulting `EBOOT.BIN`.
8. Decrypt the original EBOOT into `BOOT.BIN`.
9. Copy font assets.
10. Generate metadata.
11. Build patched ISO and xdelta patches for all supported IDs.

This strict ordering is important because the database is shared state and SQLite locking can otherwise become a practical failure mode.

### 4.2 Main Inputs

Required and optional inputs include:

- `temp/ULJS00064.iso`: required original ISO.
- `temp/ULJS00061.iso`: optional second original ISO for additional patch output.
- `AUTH_KEY`: optional/required depending on whether translations and ParaTranz statistics are downloaded during the run.
- `resources/trans_pic/trans`: translated image resources.
- Source assets under `resources/assets/` and `plugin/assets/`.

### 4.3 Main Outputs

Build outputs are written under `build/`, including:

- `build/ULJS00064/...`: reconstructed game tree.
- `build/ULJS*_patched_<timestamp>.iso`: patched ISO images.
- `build/ULJS*_patch_<timestamp>.xdelta`: binary patch files.
- `build/metadata.json`: machine-readable build metadata.
- `build/metadata.png`: visual metadata image.
- `build/ULJS00064/PSP_GAME/USRDIR/metadata.raw`: metadata packaged for the game tree.

The timestamped output names reduce accidental overwrites and make repeated builds easier to compare.

## 5. Translation Data Workflow

Translation data is managed externally through ParaTranz and imported into the local database.

The standard download flow is:

```sh
AUTH_KEY=<token> make download_trans
```

This performs two steps:

- Download translation files into `temp/downloads`.
- Merge/preprocess them into the JSON shapes expected by import commands.

The standard import flow is:

```sh
make import_trans
```

The Makefile imports:

- `temp/downloads/evs_trans.json`
- `temp/downloads/utf8/free/info.json`
- `temp/downloads/utf8/free/tuto.json`
- `temp/downloads/utf8/game/btimtext.json`
- `temp/downloads/utf8/game/imtext.json`

The same translation table model is reused across several resource types by keying translations to original strings or technical contexts.

## 6. Resource Handling Details

### 6.1 HGAR Archives

HGAR archives are imported from multiple game directories:

```text
btdemo btface btl chara event face free game im map
```

The parser supports known HGAR versions `1` and `3`. File entries preserve:

- Long and short names.
- Encoded identifiers.
- Decoded identifiers.
- Compression flag embedded in the identifier.
- Unknown metadata fields.
- Original relative path.

On export, HGAR files are rebuilt into their original directory structure under `build/ULJS00064/PSP_GAME/USRDIR`.

### 6.2 EVS Text

EVS entries are stored as parsed script/event entries. Text-bearing entries reference deduplicated `Sentence` rows. Export to JSON can be grouped by event prefix or by original relative path. Context includes avatar/expression metadata when parameters are available, which helps translators understand dialogue ownership.

### 6.3 TEXT Files

`TextArchive` parses files beginning with the `TEXT` magic. It preserves:

- Entry unknown fields.
- String index relationships.
- String unknown fields.
- Header and entry padding observations.
- Shift-JIS/EVA custom encoding conversion.

During serialization, string offsets are regenerated, strings are null-terminated, and output is aligned to the format's expectations.

### 6.4 BIND Files

`BindArchive` parses files beginning with the `BIND` magic. It preserves:

- Size field width: 1, 2, or 4 bytes.
- Entry count.
- Block size.
- Header size.
- Entry binary contents.

Serialization rebuilds the header, entry size table, header padding, and per-entry block padding.

### 6.5 HGPT Images

HGPT images are deduplicated by MD5 hash. The image workflow stores:

- Original HGPT binary content.
- Original exported PNG.
- Optional translated PNG.
- Width, height, pixel format, palette metadata, and division metadata.

The import/export behavior prioritizes translated image data during rebuild:

1. Use `png_translated` if available.
2. Otherwise use exported original PNG data.
3. Otherwise fall back to the original HGPT binary content.

Translated image import relies on the hash fragment embedded in exported filenames, so filename stability is part of the workflow contract.

### 6.6 EBOOT Translation Binary

`app/elf_patch/patcher.py` produces `EBTRANS.BIN`. The binary format is simple:

- Header: little-endian `u32` entry count.
- Entry: little-endian `u32 offset`, `u32 size`, and a fixed 1024-byte buffer.

The patcher reads translation JSON entries with technical context fields such as ELF data offset, RAM address, and size. Entries are sorted by address, encoded through the project EVA Shift-JIS conversion logic, checked against available space, then emitted for runtime use.

## 7. Encoding and Font Strategy

The game is originally built around Shift-JIS-oriented text processing. The localization patch extends this pipeline to support Simplified Chinese by reusing otherwise unused byte ranges and mapping GB2312 characters into a custom code area.

The plugin documentation describes the core mapping concept:

```c
index = (first_byte - 0xA1) * 94 + (second_byte - 0xA1);
mapped_code = 0xA600 + index;
```

The practical implication is that text conversion, font assets, runtime hooks, and binary patch generation must stay synchronized. A valid translated string is not just Unicode text; it must be convertible to the custom EVA Shift-JIS representation and renderable by the patched runtime.

Font and atlas generation are handled through plugin asset scripts:

- `plugin/scripts/gentable.py`
- `plugin/scripts/gen_ttf_atlas.py`
- `plugin/scripts/bin2c.py`

The checked-in generated files make PSP builds more reproducible.

## 8. User Interfaces

### 8.1 Makefile Interface

The Makefile is the preferred automation interface. It captures the complete pipeline and exposes stage-level targets for recovery and debugging:

- `make init_db`
- `make import_all`
- `make import_images`
- `make download_trans`
- `make import_trans`
- `make export_all`
- `make plugin`
- `make decrypt_eboot`
- `make gen_metadata`
- `make patch_iso`
- `make patch_all_ids`
- `make full_build`

### 8.2 CLI Interface

The CLI entry point is:

```sh
uv run -m app.cli.main
```

It supports import/export operations for HGAR, EVS, translations, images, TEXT, BIND, and EBOOT translation resources. This is useful for isolating failed stages during development.

## 9. Development Environment

The project expects Python `>=3.9` and uses `uv` for dependency management. Key Python dependencies include:

- `sqlalchemy`
- `requests`
- `openai<1.0`
- `pycdlib`
- `tqdm`
- `numpy`
- `pillow`

Development dependencies include:

- `ruff`

For PSP-side work, the PSPDEV toolchain is required. Docker support is provided to make PSP builds and CI more stable.

Recommended local setup:

```sh
uv venv
uv sync
uv run python -m unittest discover -s tests -v
uv run ruff check .
```

## 10. CI and Release Automation

The repository includes GitHub Actions workflows for:

- Building the PSP translation patch inside a custom Docker environment.
- Mirroring the repository to Codeberg.

The main build workflow:

- Updates submodules manually.
- Restores or downloads ISO inputs from a private Hugging Face source.
- Builds or reuses a Docker image.
- Runs `make download_trans` and `make full_build` inside the container.
- Displays generated metadata.
- Uploads xdelta patches and metadata artifacts.

## 11. Testing and Quality Controls

The documented minimum checks are:

```sh
uv run ruff check .
uv run python -m unittest discover -s tests -v
```

Current tests cover selected model and encoding behavior, while profiling scripts exist for import/export performance analysis. The strongest practical validation remains stage-level rebuild testing because the project manipulates complex binary formats where round-trip correctness is essential.

For parser or binary format changes, the minimum meaningful validation should include:

- Parsing the affected format.
- Rebuilding the affected file.
- Running the relevant Makefile export target.
- Confirming downstream ISO patching does not fail.

For PSP plugin or EBOOT behavior changes, validation should include PPSSPP or real PSP execution because static checks cannot verify runtime hook behavior.

## 12. Operational Failure Modes

Common failure classes include:

- Missing ISO files in `temp/`.
- Missing `AUTH_KEY` for translation download or metadata statistics.
- SQLite lock contention from concurrent import or export processes.
- Missing PSPDEV, `pspdecrypt`, `xdelta3`, or other external tools.
- Translated text that cannot be encoded into the custom EVA Shift-JIS mapping.
- Translated text that exceeds binary/runtime space constraints.
- Translated images with changed dimensions or renamed hash-bearing filenames.
- Generated `build/` contents becoming inconsistent with the current database.

The project supports safe recovery by rerunning individual Makefile targets rather than always restarting the full build. For severe local state issues, the documented recovery path is to clean `build/`, delete `example.db`, then rerun import and export stages in order.

## 13. Engineering Risks

### 13.1 Binary Format Drift

The project depends on reverse-engineered binary layouts. Small changes to field order, alignment, padding, compression flags, or offset bases can produce files that parse locally but fail in game. Parser and serializer changes should therefore be treated as high risk.

### 13.2 Cross-Language Consistency

Some parsing logic exists in both Python and C++. Any shared HGPT/HGAR behavior must remain consistent across implementations.

### 13.3 Runtime Patch Fragility

The PSP plugin and EBOOT patching logic depend on fixed runtime assumptions. Address changes, loader behavior changes, or font/encoding divergence can break text rendering or game startup.

### 13.4 Secret Handling

`AUTH_KEY` is an operational secret. It must remain outside committed source, logs, artifacts, and documentation examples.

### 13.5 Generated Artifact Noise

The repository uses several generated or cache-heavy directories. Build artifacts under `build/`, `build_cpp/`, `temp/`, and `logs/` should not be treated as source changes unless a task explicitly targets them.

## 14. Recommendations

1. Expand round-trip tests for HGAR, HGPT, TEXT, and BIND using small fixture files.
2. Add explicit tests for `EBTRANS.BIN` serialization and overflow/space-limit behavior.
3. Add a preflight command that checks ISO presence, required tools, writable output paths, and token availability before `make full_build`.
4. Keep generated plugin assets reproducible with `make check-generated` in CI when PSP toolchain availability permits.
5. Document the expected JSON schemas for EVS, TEXT, BIND, and EBOOT translation files.
6. Consider migration tooling for the SQLite schema if the database becomes long-lived across versions.
7. Preserve stage-level Makefile targets because they are essential for debugging large patch builds.

## 15. Conclusion

This project is a practical reverse-engineering and localization build system rather than a simple text replacement script. Its core strength is the integrated pipeline: proprietary resource parsing, database-backed translation management, image replacement, runtime PSP patching, metadata generation, and reproducible ISO/xdelta output are all connected through Makefile targets.

The highest-value maintenance principle is to protect round-trip correctness. Every parser, database record, exporter, font table, and runtime hook participates in the final patched game. Changes should therefore be small, format-aware, and validated through the closest relevant build stage, with full patch builds used for release confidence.

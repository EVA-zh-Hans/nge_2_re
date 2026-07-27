# Repository Agent Guide

This file defines how coding agents should work in this repository safely and
efficiently.

## Project Purpose

This repository builds a Chinese localization patch and supporting tools for
the PSP game *Neon Genesis Evangelion 2: Another Cases*. Its primary goals are:

- A reproducible, one-command build pipeline from source ISO to xdelta patch.
- Maintainable import, export, parsing, and binary patching tools.
- Round-trip correctness for reverse-engineered game resource formats.

## Source-of-Truth Boundary

- Treat files reported by `git ls-files` as the project source of truth.
- Ignore untracked files when inferring architecture, behavior, test coverage,
  performance, or intended workflows unless the user explicitly includes them.
- Do not modify, delete, move, or depend on untracked files unless the user
  explicitly asks you to do so.
- Preserve unrelated tracked changes already present in the working tree.
- Do not treat generated output or local caches as source code.

## Repository Layout

- `app/cli/`: command-line entry point, normally invoked through
  `uv run -m app.cli.main` or a Make target.
- `app/database/`: SQLAlchemy entities, DAOs, and SQLite setup.
- `app/parser/`: Python parsers and writers for HGAR, HGPT, TEXT, BIND, EVS,
  and related formats.
- `app/elf_patch/`: EBOOT translation binary generation and patch support.
- `scripts/`: translation, checking, metadata, ISO packaging, OCR, and staff
  roll utilities.
- `plugin/`: PSP-side C and assembly code built with the PSP toolchain.
- `third_party/`: tracked submodules for external PSP tools.
- `resources/`: tracked fonts, images, and translation assets.
- `docs/`: usage notes and format documentation.
- `tests/`: unittest coverage and profiling entry points.
- `Makefile`: canonical interface for the build pipeline.

There is no tracked general-purpose C++ parser implementation in the current
tree. Do not assume one exists based on local untracked files or other branches.

## Development Environment

Prefer `uv` for Python environment and dependency management:

```sh
uv venv
uv sync
```

Run Python modules through `uv run` to avoid dependency drift.

The default SQLite database is `example.db` in the repository root. Close other
database clients before retrying an operation that reports a lock.

PSP plugin and decryption targets require external toolchains. When those are
not available locally, isolate and validate the Python stage first; use the
repository Docker workflow for the complete toolchain where appropriate.

## Canonical Commands

Use `make help` before assembling custom command sequences. Prefer the existing
Make target that matches the task.

| Task | Preferred command | Main input | Main output |
| --- | --- | --- | --- |
| Full patch build | `make full_build` | `temp/ULJS00064.iso`, optionally `temp/ULJS00061.iso` | Patched ISOs, xdelta patches, metadata |
| Download translations | `AUTH_KEY=... make download_trans` | `AUTH_KEY` | `temp/downloads/` |
| Initialize the database | `make init_db` | Extracted game data as needed by later stages | `example.db` |
| Import game resources | `make import_all` | `temp/ULJS00064/PSP_GAME/USRDIR/` | `example.db` |
| Import translations | `make import_trans` | `temp/downloads/` | Updated `example.db` and generated MemTalk source |
| Import translated images | `make import_images` | `resources/trans_pic/trans` | Updated `example.db` |
| Export game resources | `make export_all` | `example.db` | `build/ULJS00064/PSP_GAME/USRDIR/` |
| Build the PSP plugin | `make plugin` | PSPDEV toolchain | `EBOOT.BIN` and `EVA2RT.PRX` in the build tree |
| Decrypt EBOOT | `make decrypt_eboot` | Original `EBOOT.BIN` | `build/ULJS00064/PSP_GAME/SYSDIR/BOOT.BIN` |
| Generate metadata | `make gen_metadata` | Exported game tree | `build/metadata.json`, image, and raw metadata |
| Build one patch | `make patch_iso GAME_ID=00064` | Original ISO and exported game tree | Timestamped patched ISO and xdelta |
| Build both game IDs | `make patch_all_ids` | `00061` and `00064` source ISOs | Patches for both IDs |
| Run tests | `uv run python -m unittest discover -s tests -v` | Python dependencies | Test report |
| Run lint checks | `uv run ruff check .` | Development dependencies | Lint report |

Never put `AUTH_KEY` or any other token in source, documentation, logs, or
commits.

## Build Pipeline

`make full_build` intentionally runs these stages in order:

1. Extract the source ISO.
2. Initialize the database.
3. Import HGAR, TEXT, and BIND resources.
4. Import translated images.
5. Import downloaded translations.
6. Export translated resources and inject the generated staff roll.
7. Build the PSP plugin.
8. Decrypt and prepare EBOOT files.
9. Copy font assets.
10. Generate metadata.
11. Repack both supported game IDs and generate xdelta patches.

Keep this ordering deterministic and idempotent. The shared SQLite state makes
uncontrolled parallel execution unsafe.

When a stage fails, rerun the smallest corresponding Make target first. Do not
restart the complete pipeline by default. Cleaning `build/` or recreating
`example.db` is destructive and must only be done when the task calls for it or
the user approves it.

## Implementation Rules

- Extend existing modules and workflows before introducing new scripts or
  alternate entry points.
- Keep changes scoped to the requested subsystem. Avoid unrelated refactors,
  formatting churn, and generated-file changes.
- Use structured binary and data APIs rather than ad hoc string processing.
- Keep parser objects, database representations, exported resources, and PSP
  runtime expectations consistent.
- Do not edit tracked submodule contents casually. Treat updates to
  `resources/trans_pic`, `third_party/pgftool`, and `third_party/pspdecrypt` as
  explicit dependency changes.

## Binary Format Changes

Treat changes involving HGAR, HGPT, TEXT, BIND, EVS, ELF, EBOOT, compression,
encoding, alignment, offsets, checksums, or structure layout as high risk.

Before changing a binary format implementation, identify:

- Field order, field width, signedness, and byte order.
- Padding and alignment rules.
- Count units and offset bases.
- Compression headers, flags, and raw/encoded size semantics.
- Parser and writer call sites, including database import/export paths.

Every such change must cover both reading and writing and must include at least
one focused round-trip regression test or equivalent fixture-based check. A
parser that accepts a file is not sufficient evidence that the rebuilt file is
valid.

For text rendering or encoding changes, verify the custom character mapping,
font assets, generated translation data, and PSP runtime hooks together. Do not
change fixed PSP addresses, import tables, hook layouts, or binary block layouts
without format- and runtime-specific evidence.

## Verification

The default local quality gate is:

```sh
uv run ruff check .
uv run python -m unittest discover -s tests -v
```

Scale verification with the change:

- Parser or writer changes: add focused tests for valid, invalid, and
  round-trip behavior.
- Database import/export changes: run the affected import or export Make target.
- Makefile or pipeline changes: parse the Makefile and run through the affected
  stage with representative inputs.
- Plugin or EBOOT changes: run `make plugin` or `make decrypt_eboot` where the
  toolchain is available, then validate behavior in PPSSPP or on real hardware.
- Release-path binary changes: confirm the exported files can be repacked and
  `make patch_iso GAME_ID=00064` completes without error.

If a required tool, ISO, credential, or runtime is unavailable, report exactly
which verification could not be performed. Do not claim success based only on
static inspection.

## Generated and Local Data

Avoid source edits in build output and cache locations, including `build/`,
`temp/`, and `logs/`. Do not add ISOs, patched ISOs, databases, credentials,
profiles, local settings, or one-off analysis output to commits.

Use `git status --short` before and after work. Only attribute changes to your
task when you actually made them.

## Pull Requests

Use the title format `[<area>] <Title>`, for example:

- `[parser] Fix HGPT header parsing`
- `[cli] Improve workflow logs`

Before merge, run the lint and unittest commands above. Changes to binary
formats or write-back paths must document the relevant round-trip or build-stage
verification, including successful export into the build tree and downstream
ISO repacking where applicable.

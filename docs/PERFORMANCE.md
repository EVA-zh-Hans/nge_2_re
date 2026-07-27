# Resource Pipeline Performance

This document records reproducible performance measurements for the game
resource transformation stages. ISO extraction, plugin compilation, EBOOT
decryption, ISO repacking, and xdelta generation are outside this benchmark so
that parser/database changes can be compared independently.

## Benchmark Method

The benchmark is driven by `scripts/benchmark_resource_pipeline.py`. The
database pipeline runs the existing CLI commands in separate processes, just
as the Makefile does, but uses an isolated working directory. Its `example.db`,
logs, generated staff assets, and exported files therefore do not modify the
repository's current database or build tree.

Inputs for the baseline run:

- Extracted `ULJS00064` USRDIR: 783 MiB, 1,377 files.
- HGAR archives: 1,158.
- Translated PNG files: 393.
- Translation files from `temp/downloads` used by `make import_trans`.

Environment:

- Historical baseline base revision:
  `8d8bc961a7c138ce6ec3ee99f7c3ef443cf3b083`.
- Corrected and streaming measurements: `feat/stream` working tree containing
  the correctness fixes and streaming implementation described below.
- Platform: macOS 26.2, arm64.
- Python: CPython 3.13.5.
- Date: 2026-07-27.

This is one wall-clock run with local filesystem caches in their natural state.
Absolute timings will vary by machine; comparisons should use the same machine,
inputs, and benchmark command.

## Historical Database Baseline

This first run records the behavior before the correctness fixes described
below. It remains useful as a historical reference, but it is not the baseline
used to calculate the final streaming speedup.

Command:

```sh
uv run python scripts/benchmark_resource_pipeline.py \
  --mode database \
  --work-dir /private/tmp/nge2-old-baseline.w2IgGR \
  --json /private/tmp/nge2-old-baseline.w2IgGR/database-baseline.json
```

| Stage | Commands | Time (seconds) | Database after stage | Export after stage |
| --- | ---: | ---: | ---: | ---: |
| Initialize database | 1 | 0.285 | 152 KiB | 0 |
| Import HGAR | 10 | 15.694 | 345.8 MiB | 0 |
| Import TEXT | 2 | 0.392 | 345.8 MiB | 0 |
| Import BIND | 2 | 7.752 | 393.5 MiB | 0 |
| Import translated images | 1 | 9.895 | 396.9 MiB | 0 |
| Import translations | 6 | 4.909 | 402.5 MiB | 0 |
| Export TEXT | 2 | 0.410 | 402.5 MiB | 30.8 KiB |
| Export BIND | 2 | 2.211 | 402.5 MiB | 6.1 MiB |
| Export HGAR | 1 | 21.530 | 402.5 MiB | 233.8 MiB |
| Generate and inject staff roll | 1 | 0.397 | 402.5 MiB | 233.9 MiB |
| **Total** | **28** | **63.521** | **402.5 MiB** | **233.9 MiB** |

Database row counts after import:

| Table | Rows |
| --- | ---: |
| `hgars` | 1,158 |
| `hgar_files` | 29,241 |
| `evs_entries` | 37,774 |
| `sentences` | 10,842 |
| `translations` | 34,882 |
| `hgpts` | 3,382 |
| `text_entries` | 243,582 |
| `bind_entries` | 1,942 |

The isolated output contains 1,162 files. Import and persistence account for
38.929 seconds; reconstruction and export account for 24.548 seconds. The
database is approximately 1.7 times the size of the exported resource tree.

## Historical Correctness Findings

The baseline completed, but its logs exposed issues that must be included in
the streaming-path acceptance criteria:

1. Nine RGBA HGPT files fail parsing because the NumPy tile code reshapes four
   channels as if each pixel were a scalar palette index. The database keeps
   their raw data as a fallback.
2. Four duplicate HGAR entries are collapsed by the database import's
   `(short_name, encoded_identifier) -> id` map. Their Raw records are skipped,
   and the later export reports missing data for those entries.
3. Every CLI process logs failure to import the optional `pngfilters` module and
   falls back to the pure-Python PNG filter implementation.

These findings were fixed before the final database and streaming comparison.

## Corrected Database Baseline

The corrected database path was rerun in a new isolated directory:

```sh
uv run python scripts/benchmark_resource_pipeline.py \
  --mode database \
  --work-dir /private/tmp/nge2-database-final.Q7xDXn \
  --json /private/tmp/nge2-database-final.Q7xDXn/database-final.json
```

| Stage | Time (seconds) |
| --- | ---: |
| Initialize database | 0.283 |
| Import HGAR | 15.042 |
| Import TEXT | 0.348 |
| Import BIND | 7.406 |
| Import translated images | 8.925 |
| Import translations | 2.026 |
| Export TEXT | 0.405 |
| Export BIND | 2.298 |
| Export HGAR | 20.964 |
| Generate and inject staff roll | 0.347 |
| **Total** | **58.086** |

The run produced a 421,830,656-byte database (approximately 402 MiB). The
corrected row counts relevant to the fixes are:

| Table | Historical | Corrected |
| --- | ---: | ---: |
| `raws` | 15,376 | 15,380 |
| `hgpts` | 3,382, with 9 parse fallbacks | 3,382, all parsed |
| `translations` | 34,882, including duplicate keys | 32,547 unique keys |

No HGPT parse failures, missing Raw records, duplicate-Raw warnings, or optional
`pngfilters` errors remain in the corrected logs. Translation import fell from
4.909 to 2.026 seconds because each input is collapsed by key and existing rows
are loaded in batches instead of queried once per item.

The following correctness changes are included:

- RGBA tile/untile keeps its channel dimension, including padded dimensions.
- RGBA rows are flattened correctly when exporting HGPT previews to PNG.
- Raw and EVS data are associated with HGAR rows by archive position, so valid
  duplicate names and identifiers cannot overwrite one another.
- Generic translation keys use deterministic last-value-wins import semantics;
  duplicate database rows are removed.
- An absent optional `pngfilters` accelerator uses the normal Python fallback
  without logging an application error.
- HGAR short names ending in a dot, such as `f.`, survive a read/write round
  trip instead of becoming `f..`.

The trailing-dot writer fix was verified by rerunning the smallest affected
database stages. `export_hgar` completed in 21.43 seconds, followed by a
successful staff-roll reinjection and full output comparison.

## Streaming Pipeline

The database-free path loads translation and translated-image indexes once,
then processes one standalone file or HGAR archive at a time. Unchanged HGARs
are copied byte-for-byte. Changed archives preserve entry order, identifiers,
compression flags, and unchanged entry bytes, and are parsed again after their
atomic write.

Command:

```sh
uv run python scripts/benchmark_resource_pipeline.py \
  --mode streaming \
  --work-dir /private/tmp/nge2-streaming-final.Y9HfFj \
  --json /private/tmp/nge2-streaming-final.Y9HfFj/streaming-final.json
```

| Stage | Time (seconds) |
| --- | ---: |
| Load translation and image catalogs | 0.150 |
| Transform standalone TEXT | 0.007 |
| Transform BIND | 0.364 |
| Transform HGAR/EVS/HGPT | 11.338 |
| Generate and inject staff roll | 0.234 |
| In-process work | 12.092 |
| Process startup and report writing | 0.155 |
| **Total wall clock** | **12.248** |

Compared with the corrected 58.086-second database path, the streaming path is
**4.743 times faster**, a **78.9% wall-clock reduction**. It also avoids the
approximately 402 MiB intermediate SQLite database.

The first streaming implementation took 39.430 seconds. Profiling showed that
1,218 HGPT occurrences referred to only 371 unique source hashes. Caching the
rebuilt bytes by the complete source hash produced 847 cache hits and reduced
the HGAR stage from 38.355 to 11.338 seconds. Archive objects themselves are
still released after each archive.

Final workload counters:

| Counter | Value |
| --- | ---: |
| HGAR archives | 1,158 |
| Archive entries | 29,241 |
| Changed / byte-copied archives | 618 / 540 |
| Round-trip verified archives | 618 |
| EVS files changed | 933 |
| EVS entries translated | 16,191 |
| HGPT occurrences changed | 1,218 |
| Unique translated images matched | 371 / 371 |
| Generic translation keys matched | 32,547 / 32,547 |
| Scoped CEV translations matched | 2,788 / 2,788 |
| Duplicate archive occurrences preserved | 6 |

The report also records 826 generic-translation conflict occurrences across
655 keys and 18 translated-image path conflicts. These are not build failures:
generic translations use deterministic import order, and images use the more
specific deeper path with a stable path tie-break. All selected translations
and images were matched, with no CEV original mismatches.

## Output Comparison

The corrected database and streaming trees were compared using
`scripts/compare_resource_outputs.py`. It checks ordinary files byte-for-byte,
then compares HGAR metadata and order, decompressed entry data, raw custom
encoded TEXT/EVS/BIND structures, and HGPT pixels and metadata.

```sh
uv run python scripts/compare_resource_outputs.py \
  /private/tmp/nge2-database-final.Q7xDXn/old_output/ULJS00064/PSP_GAME/USRDIR \
  /private/tmp/nge2-streaming-final.Y9HfFj/new_output/ULJS00064/PSP_GAME/USRDIR \
  --json /private/tmp/nge2-streaming-final.Y9HfFj/compare-final.json
```

| Result | Files |
| --- | ---: |
| Files in each tree | 1,162 |
| Byte-identical | 249 |
| Structurally/semantically equal | 913 |
| Different | **0** |

The semantic-only matches are expected: the database path reconstructs and
recompresses every archive, while the streaming path retains unchanged source
bytes. No translated text, image, archive order, identifier, or Raw content
differences remain.

## Usage

Use the streaming resource stage in the canonical build tree with:

```sh
make stream_export
```

Run the complete alternate patch workflow with:

```sh
make stream_full_build
```

The direct command defaults to a separate `build/direct` tree and writes a JSON
match/timing report. The database workflow remains available as a development
and parity reference. SQLite is useful for interactive querying and persistent
editing, but for a one-shot deterministic build it is a net cost: the corrected
run spends about 34.0 seconds importing/persisting data and another 24.0 seconds
reconstructing it, while the streaming path transforms the same resources in
12.2 seconds.

## Remaining Verification

Both final benchmark modes used the same input tree and override catalogs. The
reported boundary covers catalog loading, standalone TEXT and BIND transforms,
HGAR transforms, and staff-roll generation/injection.

The resource-stage acceptance requirements have passed:

- All intended generic and CEV translations are matched or explicitly reported.
- Every translated image is matched uniquely or explicitly reported.
- Unchanged archive entries remain byte-identical.
- Changed archives pass format-specific parse/write round trips.
- Duplicate HGAR entries are preserved in order.
- The database pipeline remains available as a parity reference.

The focused HGPT and streaming regression suite passes all seven tests. Targeted
Ruff checks cover the pipeline, benchmark/comparison tools, translation DAO,
and focused tests. The repository-wide quality gate still includes unrelated
legacy failures, so those results are not attributed to this performance work.

This benchmark intentionally excludes ISO extraction, plugin compilation,
EBOOT decryption, ISO repacking, xdelta generation, and PPSSPP/hardware runtime
testing. `stream_full_build` wires the streaming stage into that workflow, but
the release ISO stages still require their external inputs and toolchains.

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

- Commit: `8d8bc961a7c138ce6ec3ee99f7c3ef443cf3b083`
- Platform: macOS 26.2, arm64.
- Python: CPython 3.13.5.
- Date: 2026-07-27.

This is one wall-clock run with local filesystem caches in their natural state.
Absolute timings will vary by machine; comparisons should use the same machine,
inputs, and benchmark command.

## Database Pipeline Baseline

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

## Baseline Correctness Findings

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

The streaming implementation must preserve duplicate archive entries by
position, correctly support RGBA HGPT data, and avoid reporting an absent
optional accelerator as an application error.

## Comparison Requirements

The streaming benchmark must use the same inputs and report the same stage
boundary: load override catalogs, transform standalone TEXT and BIND files,
transform HGAR archives, and generate/inject the staff roll.

Success requires:

- All intended generic and CEV translations are matched or explicitly reported.
- Every translated image is matched uniquely or explicitly reported.
- Unchanged archive entries remain byte-identical.
- Changed archives pass format-specific parse/write round trips.
- Duplicate HGAR entries are preserved in order.
- The database pipeline remains available until semantic comparison and ISO
  repacking have both passed.


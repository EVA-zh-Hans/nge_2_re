#!/usr/bin/env python3

"""Benchmark the resource import/export pipelines in an isolated directory."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HGAR_DIRS = ("btdemo", "btface", "btl", "chara", "event", "face", "free", "game", "im", "map")


@dataclass(frozen=True)
class StageResult:
    name: str
    seconds: float
    commands: int
    database_bytes: int
    output_bytes: int


def tree_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def run_command(command: list[str], cwd: Path, log_path: Path) -> float:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    started = time.perf_counter()
    with log_path.open("ab") as log:
        log.write(("\n$ " + " ".join(command) + "\n").encode("utf-8"))
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
        raise RuntimeError(
            f"command failed with exit code {completed.returncode}: {' '.join(command)}\n"
            + "\n".join(tail)
        )
    return elapsed


def cli(*args: str) -> list[str]:
    return [sys.executable, "-m", "app.cli.main", *args]


def benchmark_database(work_dir: Path) -> list[StageResult]:
    source_usrdir = ROOT / "temp" / "ULJS00064" / "PSP_GAME" / "USRDIR"
    downloads = ROOT / "temp" / "downloads"
    image_dir = ROOT / "resources" / "trans_pic" / "trans"
    output_root = work_dir / "old_output" / "ULJS00064" / "PSP_GAME" / "USRDIR"
    logs = work_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    required = (
        source_usrdir,
        downloads / "evs_trans.json",
        downloads / "utf8" / "EVS" / "cev",
        downloads / "utf8" / "free" / "info.json",
        downloads / "utf8" / "free" / "tuto.json",
        downloads / "utf8" / "game" / "btimtext.json",
        downloads / "utf8" / "game" / "imtext.json",
        image_dir,
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("missing benchmark inputs:\n" + "\n".join(missing))

    results: list[StageResult] = []

    def stage(name: str, commands: list[list[str]]) -> None:
        log_path = logs / f"{name}.log"
        elapsed = sum(run_command(command, work_dir, log_path) for command in commands)
        results.append(
            StageResult(
                name=name,
                seconds=elapsed,
                commands=len(commands),
                database_bytes=tree_size(work_dir / "example.db"),
                output_bytes=tree_size(output_root),
            )
        )
        print(f"{name}: {elapsed:.3f}s", flush=True)

    stage("init_db", [cli("--init_db")])
    stage(
        "import_hgar",
        [cli("--import_har", str(source_usrdir / directory)) for directory in HGAR_DIRS],
    )
    stage(
        "import_text",
        [
            cli("--import_text", str(source_usrdir / "free" / "f2info.bin")),
            cli("--import_text", str(source_usrdir / "free" / "f2tuto.bin")),
        ],
    )
    stage(
        "import_bind",
        [
            cli("--import_bind", str(source_usrdir / "btl" / "btimtext.bin")),
            cli("--import_bind", str(source_usrdir / "game" / "imtext.bin")),
        ],
    )
    stage("import_images", [cli("--import_images", str(image_dir))])
    stage(
        "import_translations",
        [
            cli("--import_translation", str(downloads / "evs_trans.json")),
            cli("--import_cev_translation", str(downloads / "utf8" / "EVS" / "cev")),
            cli("--import_translation", str(downloads / "utf8" / "free" / "info.json")),
            cli("--import_translation", str(downloads / "utf8" / "free" / "tuto.json")),
            cli("--import_translation", str(downloads / "utf8" / "game" / "btimtext.json")),
            cli("--import_translation", str(downloads / "utf8" / "game" / "imtext.json")),
        ],
    )
    stage(
        "export_text",
        [
            cli("--export_text", str(output_root / "free"), "--text_filename", "f2info.bin"),
            cli("--export_text", str(output_root / "free"), "--text_filename", "f2tuto.bin"),
        ],
    )
    stage(
        "export_bind",
        [
            cli("--export_bind", str(output_root / "btl"), "--bind_filename", "btimtext.bin"),
            cli("--export_bind", str(output_root / "game"), "--bind_filename", "imtext.bin"),
        ],
    )
    stage("export_hgar", [cli("--output_hgar", str(output_root))])

    staff_output = work_dir / "generated_staff"
    staff_header = work_dir / "generated_staff_roll.h"
    staff_har = output_root / "game" / "staff.har"
    stage(
        "generate_and_inject_staff_roll",
        [
            [
                sys.executable,
                str(ROOT / "scripts" / "staff" / "generate_staff_roll.py"),
                "--output-dir",
                str(staff_output),
                "--header",
                str(staff_header),
                "--inject-har",
                str(staff_har),
            ]
        ],
    )
    return results


def benchmark_streaming(work_dir: Path) -> list[StageResult]:
    source_usrdir = ROOT / "temp" / "ULJS00064" / "PSP_GAME" / "USRDIR"
    output_root = work_dir / "new_output" / "ULJS00064" / "PSP_GAME" / "USRDIR"
    detail_report = work_dir / "streaming-details.json"
    log_path = work_dir / "logs" / "streaming.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if output_root.exists():
        raise FileExistsError(
            f"streaming benchmark output already exists; use a fresh work directory: {output_root}"
        )

    command = [
        sys.executable,
        "-m",
        "app.pipeline.stream_build",
        "--source",
        str(source_usrdir),
        "--output",
        str(output_root),
        "--downloads",
        str(ROOT / "temp" / "downloads"),
        "--images",
        str(ROOT / "resources" / "trans_pic" / "trans"),
        "--report",
        str(detail_report),
        "--staff-output",
        str(work_dir / "generated_staff"),
        "--staff-header",
        str(work_dir / "generated_staff_roll.h"),
    ]
    run_command(command, work_dir, log_path)
    detail = json.loads(detail_report.read_text(encoding="utf-8"))
    timings = detail["stats"]["timings"]
    results = []
    for name in (
        "load_catalogs",
        "transform_text",
        "transform_bind",
        "transform_hgar",
        "generate_and_inject_staff_roll",
    ):
        result = StageResult(
            name=name,
            seconds=timings[name],
            commands=1,
            database_bytes=0,
            output_bytes=tree_size(output_root),
        )
        results.append(result)
        print(f"{name}: {result.seconds:.3f}s", flush=True)
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("database", "streaming"), default="database"
    )
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--keep-work-dir", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    temporary = None
    if args.work_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="nge2-pipeline-benchmark-")
        work_dir = Path(temporary.name)
    else:
        work_dir = args.work_dir.resolve()
        work_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    if args.mode == "database":
        results = benchmark_database(work_dir)
    else:
        results = benchmark_streaming(work_dir)
    payload = {
        "mode": args.mode,
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "platform": platform.platform(),
        "python": sys.version,
        "work_dir": str(work_dir),
        "total_seconds": time.perf_counter() - started,
        "stages": [asdict(result) for result in results],
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"total: {payload['total_seconds']:.3f}s")
    print(f"results: {args.json}")

    if temporary is not None and args.keep_work_dir:
        destination = Path(tempfile.mkdtemp(prefix="nge2-pipeline-benchmark-kept-"))
        shutil.copytree(work_dir, destination, dirs_exist_ok=True)
        print(f"kept work directory: {destination}")


if __name__ == "__main__":
    main()

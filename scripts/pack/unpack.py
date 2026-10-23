#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from pathlib import Path, PurePosixPath
import pycdlib


def unpack_iso9660(
    iso_path: Path, out_dir: Path, *, strip_version: bool = True
) -> None:
    """
    Extract all files from an ISO9660 image using pycdlib.

    Parameters
    ----------
    iso_path : Path
        Input ISO file.
    out_dir : Path
        Output folder for extracted files.
    strip_version : bool
        Remove the ISO9660 version suffix ";1" from filenames.
    """
    if not iso_path.exists():
        raise FileNotFoundError(f"ISO file not found: {iso_path}")

    out_dir.mkdir(parents=True, exist_ok=True)

    iso = pycdlib.PyCdlib()
    iso.open(str(iso_path))

    for dirname, _, files in iso.walk(iso_path="/"):
        # dirname: e.g. "/PSP_GAME/SYSDIR"
        # drop leading "/" for local path building
        relative = dirname.lstrip("/")
        current_dir = out_dir / relative
        current_dir.mkdir(parents=True, exist_ok=True)

        for file in files:
            filename = file
            if strip_version:
                filename = filename.replace(";1", "")

            output_file = current_dir / filename

            print(f"Extracting: {relative}/{filename}")

            # Extract file
            with output_file.open("wb") as f:
                iso.get_file_from_iso_fp(f, iso_path=f"{dirname}/{file}")

    iso.close()


def unpack_iso_file(
    iso_path: Path,
    out_dir: Path,
    iso_file: str,
    *,
    strip_version: bool = True,
) -> None:
    """Extract one file while preserving its directory path inside the ISO."""
    if not iso_path.exists():
        raise FileNotFoundError(f"ISO file not found: {iso_path}")
    if not iso_file.startswith("/") or ".." in PurePosixPath(iso_file).parts:
        raise ValueError("ISO file path must be absolute and cannot contain '..'")

    iso = pycdlib.PyCdlib()
    iso.open(str(iso_path))
    try:
        requested = _strip_iso_version(iso_file.lstrip("/")).casefold()
        matched_path = None
        for dirname, _, files in iso.walk(iso_path="/"):
            for filename in files:
                candidate = f"{dirname}/{filename}".lstrip("/")
                if _strip_iso_version(candidate).casefold() == requested:
                    matched_path = f"/{candidate}"
                    break
            if matched_path:
                break

        if not matched_path:
            raise FileNotFoundError(f"ISO file not found: {iso_file}")

        relative = matched_path.lstrip("/")
        if strip_version:
            relative = _strip_iso_version(relative)
        output_file = out_dir / relative
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("wb") as file_handle:
            iso.get_file_from_iso_fp(file_handle, iso_path=matched_path)
    finally:
        iso.close()

    print(f"Extracting: {relative}")


def _strip_iso_version(path: str) -> str:
    base, separator, version = path.rpartition(";")
    if separator and version.isdigit():
        return base
    return path


def build_cli():
    parser = argparse.ArgumentParser(description="Extract files from an ISO9660 image.")

    parser.add_argument("iso", type=Path, help="Path to the input ISO file.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Directory to output extracted files.",
    )
    parser.add_argument(
        "--keep-version",
        action="store_true",
        help="Keep ISO9660 filename version suffix (e.g., ';1').",
    )
    parser.add_argument(
        "--only",
        metavar="ISO_PATH",
        help="Extract only this absolute ISO9660 file path.",
    )

    return parser


def main():
    parser = build_cli()
    args = parser.parse_args()

    try:
        if args.only:
            unpack_iso_file(
                iso_path=args.iso,
                out_dir=args.output,
                iso_file=args.only,
                strip_version=not args.keep_version,
            )
        else:
            unpack_iso9660(
                iso_path=args.iso,
                out_dir=args.output,
                strip_version=not args.keep_version,
            )
    except Exception as e:
        print(f"Error: {e}")
        raise SystemExit(1)

    print("Extraction complete.")


if __name__ == "__main__":
    main()

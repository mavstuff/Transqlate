"""Zip / directory helpers for dump packages."""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path


def is_zip_path(path: Path) -> bool:
    return path.suffix.lower() == ".zip"


def work_dir_for_output(output: Path) -> tuple[Path, bool]:
    """Return (work directory, whether final artifact is a zip)."""
    make_zip = is_zip_path(output)
    work_dir = output.with_suffix("") if make_zip else output
    return work_dir, make_zip


def zip_directory(source_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(source_dir).as_posix())


def resolve_dump_dir(input_path: Path) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if input_path.is_dir():
        return input_path, None
    if input_path.suffix.lower() != ".zip" or not input_path.is_file():
        raise FileNotFoundError(f"Dump not found: {input_path}")

    tmp = tempfile.TemporaryDirectory(prefix="transqlate_import_")
    with zipfile.ZipFile(input_path, "r") as zf:
        zf.extractall(tmp.name)
    return Path(tmp.name), tmp

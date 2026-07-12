from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterator

from .config import Settings
from .validation import validate_hardware, validate_version


IO_BLOCK_SIZE = 64 * 1024


def firmware_path(settings: Settings, hardware: str, version: str) -> Path:
    validate_hardware(hardware)
    validate_version(version)
    root = settings.firmware_dir.resolve()
    path = (root / hardware / version / "firmware.bin").resolve()
    if root not in path.parents:
        raise ValueError("firmware path escaped storage root")
    return path


def hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while block := source.read(IO_BLOCK_SIZE):
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    fd, temporary_name = tempfile.mkstemp(prefix=".firmware-", suffix=".tmp", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as target, source.open("rb") as origin:
            shutil.copyfileobj(origin, target, length=IO_BLOCK_SIZE)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def iter_file(path: Path, start: int, length: int) -> Iterator[bytes]:
    remaining = length
    with path.open("rb") as source:
        source.seek(start)
        while remaining:
            block = source.read(min(IO_BLOCK_SIZE, remaining))
            if not block:
                break
            remaining -= len(block)
            yield block

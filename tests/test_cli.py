from __future__ import annotations

import hashlib
from pathlib import Path

from app.cli import main as cli_main
from app.config import Settings
from app.db import Database
from app.storage import firmware_path


def test_publish_is_atomic_and_does_not_silently_overwrite(
    settings: Settings, tmp_path: Path, capsys
) -> None:
    source = tmp_path / "firmware.bin"
    payload = b"esp32 firmware" * 100
    source.write_bytes(payload)
    arguments = [
        "publish", "--hardware", "walkie-v1", "--version", "0.12.0",
        "--channel", "stable", "--file", str(source), "--notes", "notes",
    ]
    assert cli_main(arguments, settings) == 0
    destination = firmware_path(settings, "walkie-v1", "0.12.0")
    assert destination.read_bytes() == payload
    release = Database(settings.database_path).get_release("walkie-v1", "0.12.0")
    assert release is not None
    assert release["size"] == len(payload)
    assert release["sha256"] == hashlib.sha256(payload).hexdigest()

    source.write_bytes(b"replacement")
    assert cli_main(arguments, settings) == 1
    assert destination.read_bytes() == payload
    assert "already exists" in capsys.readouterr().err


def test_release_list_enable_and_disable(settings: Settings, tmp_path: Path, capsys) -> None:
    source = tmp_path / "firmware.bin"
    source.write_bytes(b"release")
    publish = [
        "publish", "--hardware", "walkie-v1", "--version", "0.12.0",
        "--file", str(source),
    ]
    assert cli_main(publish, settings) == 0
    assert cli_main(["list"], settings) == 0
    assert "walkie-v1\t0.12.0\tstable\tenabled" in capsys.readouterr().out

    assert cli_main([
        "disable", "--hardware", "walkie-v1", "--version", "0.12.0"
    ], settings) == 0
    assert Database(settings.database_path).get_release("walkie-v1", "0.12.0") is None
    assert Database(settings.database_path).get_release(
        "walkie-v1", "0.12.0", enabled_only=False
    )["enabled"] == 0

    assert cli_main([
        "enable", "--hardware", "walkie-v1", "--version", "0.12.0"
    ], settings) == 0
    assert Database(settings.database_path).get_release("walkie-v1", "0.12.0") is not None


def test_empty_firmware_is_rejected(settings: Settings, tmp_path: Path) -> None:
    source = tmp_path / "empty.bin"
    source.write_bytes(b"")
    assert cli_main([
        "publish", "--hardware", "walkie-v1", "--version", "0.12.0",
        "--file", str(source),
    ], settings) == 1

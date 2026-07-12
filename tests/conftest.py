from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cli import main as cli_main
from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        public_base_url="http://139.129.17.67:18082",
        data_dir=tmp_path / "data",
        log_level="INFO",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def firmware_bytes() -> bytes:
    return bytes(range(256)) * 500 + b"final-fragment"


@pytest.fixture
def published_firmware(settings: Settings, firmware_bytes: bytes, tmp_path: Path) -> bytes:
    source = tmp_path / "firmware.bin"
    source.write_bytes(firmware_bytes)
    result = cli_main(
        [
            "publish",
            "--hardware", "walkie-v1",
            "--version", "0.12.0",
            "--channel", "stable",
            "--file", str(source),
            "--notes", "first OTA release",
        ],
        settings,
    )
    assert result == 0
    return firmware_bytes

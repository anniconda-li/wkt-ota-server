from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cli import main as cli_main
from app.config import Settings
from app.db import Database
from app.storage import firmware_path


VERSION = "0.11.7"
REV_1 = "walkie-v1-rev-1"
REV_2 = "walkie-v1-rev-2"
LEGACY = "walkie-v1"
REV_1_BYTES = b"revision-one-firmware\x00" * 37
REV_2_BYTES = b"revision-two-has-different-electronics\xff" * 53


def publish(
    settings: Settings,
    tmp_path: Path,
    hardware: str,
    content: bytes,
) -> int:
    source = tmp_path / f"{hardware}-{VERSION}.bin"
    source.write_bytes(content)
    return cli_main(
        [
            "publish",
            "--hardware", hardware,
            "--channel", "stable",
            "--version", VERSION,
            "--file", str(source),
            "--notes", f"{hardware} release",
        ],
        settings,
    )


def check(
    client: TestClient,
    *,
    device_id: str,
    hardware: str,
    channel: str = "stable",
) -> dict:
    response = client.get(
        "/api/v1/ota/check",
        params={
            "device_id": device_id,
            "hardware": hardware,
            "current_version": "0.11.6",
            "network": "wifi",
            "channel": channel,
        },
    )
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def published_revisions(
    settings: Settings,
    tmp_path: Path,
) -> dict[str, bytes]:
    assert publish(settings, tmp_path, REV_1, REV_1_BYTES) == 0
    assert publish(settings, tmp_path, REV_2, REV_2_BYTES) == 0
    return {REV_1: REV_1_BYTES, REV_2: REV_2_BYTES}


def test_same_version_can_be_published_for_both_hardware_revisions(
    settings: Settings,
    published_revisions: dict[str, bytes],
) -> None:
    database = Database(settings.database_path)
    rev_1_release = database.get_release(REV_1, VERSION)
    rev_2_release = database.get_release(REV_2, VERSION)

    assert rev_1_release is not None
    assert rev_2_release is not None
    assert rev_1_release["hardware"] == REV_1
    assert rev_2_release["hardware"] == REV_2
    assert rev_1_release["version"] == rev_2_release["version"] == VERSION
    assert rev_1_release["size"] == len(REV_1_BYTES)
    assert rev_2_release["size"] == len(REV_2_BYTES)
    assert rev_1_release["size"] != rev_2_release["size"]
    assert rev_1_release["sha256"] == hashlib.sha256(REV_1_BYTES).hexdigest()
    assert rev_2_release["sha256"] == hashlib.sha256(REV_2_BYTES).hexdigest()
    assert rev_1_release["sha256"] != rev_2_release["sha256"]

    rows = [
        release
        for release in database.list_releases()
        if release["version"] == VERSION
    ]
    assert {row["hardware"] for row in rows} == {REV_1, REV_2}
    assert firmware_path(settings, REV_1, VERSION).read_bytes() == published_revisions[REV_1]
    assert firmware_path(settings, REV_2, VERSION).read_bytes() == published_revisions[REV_2]


def test_each_revision_check_returns_only_its_own_release(
    client: TestClient,
    published_revisions: dict[str, bytes],
) -> None:
    rev_1 = check(client, device_id="walkie-01", hardware=REV_1)
    rev_2 = check(client, device_id="walkie-02", hardware=REV_2)

    assert rev_1["update"] is True
    assert rev_1["hardware"] == REV_1
    assert rev_1["size"] == len(published_revisions[REV_1])
    assert rev_1["sha256"] == hashlib.sha256(published_revisions[REV_1]).hexdigest()
    assert rev_1["firmware_url"].endswith(f"/firmware/{REV_1}/{VERSION}")

    assert rev_2["update"] is True
    assert rev_2["hardware"] == REV_2
    assert rev_2["size"] == len(published_revisions[REV_2])
    assert rev_2["sha256"] == hashlib.sha256(published_revisions[REV_2]).hexdigest()
    assert rev_2["firmware_url"].endswith(f"/firmware/{REV_2}/{VERSION}")


@pytest.mark.parametrize(
    ("published_hardware", "requested_hardware", "device_id", "content"),
    [
        (REV_2, REV_1, "walkie-01", REV_2_BYTES),
        (REV_1, REV_2, "walkie-02", REV_1_BYTES),
    ],
)
def test_revision_check_never_falls_back_to_the_other_revision(
    client: TestClient,
    settings: Settings,
    tmp_path: Path,
    published_hardware: str,
    requested_hardware: str,
    device_id: str,
    content: bytes,
) -> None:
    assert publish(settings, tmp_path, published_hardware, content) == 0
    assert check(client, device_id=device_id, hardware=requested_hardware) == {
        "update": False
    }


def test_revisions_never_fall_back_to_legacy_hardware(
    client: TestClient,
    settings: Settings,
    tmp_path: Path,
) -> None:
    assert publish(settings, tmp_path, LEGACY, b"legacy firmware") == 0
    assert check(client, device_id="walkie-01", hardware=REV_1) == {"update": False}
    assert check(client, device_id="walkie-02", hardware=REV_2) == {"update": False}

    legacy_result = check(client, device_id="legacy-device", hardware=LEGACY)
    assert legacy_result["update"] is True
    assert legacy_result["hardware"] == LEGACY


def test_unknown_hardware_and_other_channel_return_no_update(
    client: TestClient,
    settings: Settings,
    tmp_path: Path,
) -> None:
    assert publish(settings, tmp_path, REV_1, REV_1_BYTES) == 0
    assert check(
        client, device_id="unknown-device", hardware="walkie-v1-rev-3"
    ) == {"update": False}
    assert check(
        client, device_id="walkie-01", hardware=REV_1, channel="beta"
    ) == {"update": False}


def test_device_id_does_not_override_requested_hardware(
    client: TestClient,
    published_revisions: dict[str, bytes],
) -> None:
    result = check(client, device_id="walkie-01", hardware=REV_2)
    assert result["hardware"] == REV_2
    assert result["sha256"] == hashlib.sha256(published_revisions[REV_2]).hexdigest()


def test_duplicate_revision_release_is_rejected_without_overwrite(
    settings: Settings,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert publish(settings, tmp_path, REV_1, REV_1_BYTES) == 0
    original_path = firmware_path(settings, REV_1, VERSION)
    original_hash = Database(settings.database_path).get_release(REV_1, VERSION)["sha256"]

    assert publish(settings, tmp_path, REV_1, b"replacement must not win") == 1
    assert "already exists" in capsys.readouterr().err
    assert original_path.read_bytes() == REV_1_BYTES
    assert Database(settings.database_path).get_release(REV_1, VERSION)["sha256"] == original_hash


def test_download_urls_are_isolated_by_hardware_directory(
    client: TestClient,
    published_revisions: dict[str, bytes],
) -> None:
    rev_1_download = client.get(f"/api/v1/ota/firmware/{REV_1}/{VERSION}")
    rev_2_download = client.get(f"/api/v1/ota/firmware/{REV_2}/{VERSION}")

    assert rev_1_download.status_code == 200
    assert rev_2_download.status_code == 200
    assert rev_1_download.content == published_revisions[REV_1]
    assert rev_2_download.content == published_revisions[REV_2]
    assert rev_1_download.content != published_revisions[REV_2]
    assert rev_2_download.content != published_revisions[REV_1]


@pytest.mark.parametrize(
    ("published_hardware", "requested_hardware", "content"),
    [
        (REV_2, REV_1, REV_2_BYTES),
        (REV_1, REV_2, REV_1_BYTES),
    ],
)
def test_download_does_not_cross_hardware_when_only_other_revision_exists(
    client: TestClient,
    settings: Settings,
    tmp_path: Path,
    published_hardware: str,
    requested_hardware: str,
    content: bytes,
) -> None:
    assert publish(settings, tmp_path, published_hardware, content) == 0
    response = client.get(f"/api/v1/ota/firmware/{requested_hardware}/{VERSION}")
    assert response.status_code == 404


def test_reports_preserve_device_id_and_hardware_without_mapping(
    client: TestClient,
    settings: Settings,
) -> None:
    reports = [
        ("walkie-01", REV_1),
        ("walkie-02", REV_2),
    ]
    for device_id, hardware in reports:
        response = client.post(
            "/api/v1/ota/report",
            json={
                "device_id": device_id,
                "hardware": hardware,
                "from_version": "0.11.6",
                "to_version": VERSION,
                "network": "wifi",
                "status": "success",
            },
        )
        assert response.status_code == 201

    with sqlite3.connect(settings.database_path) as connection:
        saved = connection.execute(
            "SELECT device_id, hardware FROM ota_reports ORDER BY id"
        ).fetchall()
    assert saved == reports

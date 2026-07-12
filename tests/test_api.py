from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cli import main as cli_main
from app.config import Settings
from app.storage import firmware_path


def check_params(**overrides: str) -> dict[str, str]:
    params = {
        "device_id": "esp32-001",
        "hardware": "walkie-v1",
        "current_version": "0.11.2",
        "network": "wifi",
    }
    params.update(overrides)
    return params


def test_health_does_not_expose_configuration(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "service": "wkt-ota-server",
        "version": "1.0.0",
        "status": "healthy",
    }


def test_no_update_and_wifi_is_accepted(client: TestClient) -> None:
    response = client.get("/api/v1/ota/check", params=check_params())
    assert response.status_code == 200
    assert response.json() == {"update": False}


def test_ml307c_is_rejected_by_check(client: TestClient) -> None:
    response = client.get(
        "/api/v1/ota/check", params=check_params(network="ml307c")
    )
    assert response.status_code == 422


def test_update_contract_has_no_chunk_fields(
    client: TestClient, published_firmware: bytes
) -> None:
    response = client.get(
        "/api/v1/ota/check", params=check_params(channel="stable")
    )
    assert response.status_code == 200
    assert response.json() == {
        "update": True,
        "version": "0.12.0",
        "hardware": "walkie-v1",
        "channel": "stable",
        "size": len(published_firmware),
        "sha256": hashlib.sha256(published_firmware).hexdigest(),
        "mandatory": False,
        "min_battery": 40,
        "release_notes": "first OTA release",
        "firmware_url": (
            "http://139.129.17.67:18082/api/v1/ota/firmware/"
            "walkie-v1/0.12.0"
        ),
    }


def test_semver_check_is_not_lexicographic(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    source = tmp_path / "new.bin"
    source.write_bytes(b"new")
    assert cli_main(
        [
            "publish", "--hardware", "walkie-v2", "--version", "0.10.0",
            "--file", str(source),
        ],
        settings,
    ) == 0
    response = client.get(
        "/api/v1/ota/check",
        params=check_params(hardware="walkie-v2", current_version="0.9.9"),
    )
    assert response.json()["update"] is True


def test_no_update_when_current_is_same_or_newer(
    client: TestClient, published_firmware: bytes
) -> None:
    for current in ("0.12.0", "0.13.0"):
        response = client.get(
            "/api/v1/ota/check", params=check_params(current_version=current)
        )
        assert response.json() == {"update": False}


def test_missing_release_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/ota/firmware/walkie-v1/9.9.9")
    assert response.status_code == 404


def test_missing_firmware_file_returns_404(
    client: TestClient, settings: Settings, published_firmware: bytes
) -> None:
    firmware_path(settings, "walkie-v1", "0.12.0").unlink()
    response = client.get("/api/v1/ota/firmware/walkie-v1/0.12.0")
    assert response.status_code == 404


def test_metadata_size_mismatch_returns_500(
    client: TestClient, settings: Settings, published_firmware: bytes
) -> None:
    path = firmware_path(settings, "walkie-v1", "0.12.0")
    with path.open("ab") as firmware:
        firmware.write(b"corrupt")
    response = client.get("/api/v1/ota/firmware/walkie-v1/0.12.0")
    assert response.status_code == 500
    assert response.json() == {"detail": "firmware storage integrity error"}


def test_complete_download(client: TestClient, published_firmware: bytes) -> None:
    response = client.get("/api/v1/ota/firmware/walkie-v1/0.12.0")
    assert response.status_code == 200
    assert response.content == published_firmware
    assert response.headers["content-type"].startswith("application/octet-stream")
    assert response.headers["content-length"] == str(len(published_firmware))
    assert response.headers["accept-ranges"] == "bytes"
    assert "content-range" not in response.headers


@pytest.mark.parametrize(
    ("range_value", "start", "end"),
    [
        ("bytes=0-99", 0, 99),
        ("bytes=50000-50099", 50000, 50099),
        ("bytes=127900-128013", 127900, 128013),
        ("bytes=127989-", 127989, 128013),
        ("bytes=-16", 127998, 128013),
    ],
)
def test_single_range_forms(
    client: TestClient,
    published_firmware: bytes,
    range_value: str,
    start: int,
    end: int,
) -> None:
    assert len(published_firmware) == 128014
    response = client.get(
        "/api/v1/ota/firmware/walkie-v1/0.12.0",
        headers={"Range": range_value},
    )
    assert response.status_code == 206
    assert response.content == published_firmware[start : end + 1]
    assert response.headers["content-range"] == (
        f"bytes {start}-{end}/{len(published_firmware)}"
    )
    assert response.headers["content-length"] == str(end - start + 1)
    assert response.headers["accept-ranges"] == "bytes"


@pytest.mark.parametrize(
    "range_value",
    [
        "items=0-1",
        "bytes=abc-def",
        "bytes=10-9",
        "bytes=0-1,4-5",
        "bytes=128014-",
        "bytes=-0",
        "bytes=",
    ],
)
def test_invalid_and_out_of_bounds_ranges_return_416(
    client: TestClient, published_firmware: bytes, range_value: str
) -> None:
    response = client.get(
        "/api/v1/ota/firmware/walkie-v1/0.12.0",
        headers={"Range": range_value},
    )
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(published_firmware)}"
    assert response.headers["accept-ranges"] == "bytes"


def test_path_traversal_is_rejected(
    client: TestClient, published_firmware: bytes
) -> None:
    assert client.get("/api/v1/ota/firmware/%2E%2E/0.12.0").status_code in {
        404,
        422,
    }
    assert client.get(
        "/api/v1/ota/firmware/bad.hardware/0.12.0"
    ).status_code == 422


def test_chunk_route_does_not_exist(client: TestClient) -> None:
    response = client.get(
        "/api/v1/ota/chunk/walkie-v1/0.12.0",
        params={"offset": 0, "length": 100},
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "report_status",
    [
        "download_started",
        "verified",
        "rebooting",
        "success",
        "failed",
        "rolled_back",
    ],
)
def test_all_report_statuses_are_saved(
    client: TestClient, settings: Settings, report_status: str
) -> None:
    payload: dict[str, object] = {
        "device_id": "esp32-001",
        "hardware": "walkie-v1",
        "from_version": "0.11.2",
        "to_version": "0.12.0",
        "network": "wifi",
        "status": report_status,
        "bytes_written": 128014,
    }
    if report_status in {"failed", "rolled_back"}:
        payload.update(error_code="download_error", error_message="test failure")
    response = client.post("/api/v1/ota/report", json=payload)
    assert response.status_code == 201
    assert response.json()["accepted"] is True
    assert response.headers["location"].startswith("/api/v1/ota/report/")
    with sqlite3.connect(settings.database_path) as connection:
        row = connection.execute(
            "SELECT network, status, bytes_written, created_at "
            "FROM ota_reports ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row[:3] == ("wifi", report_status, 128014)
    assert row[3].endswith("Z")


def test_report_only_allows_wifi(client: TestClient) -> None:
    response = client.post(
        "/api/v1/ota/report",
        json={
            "device_id": "esp32-001",
            "hardware": "walkie-v1",
            "from_version": "0.11.2",
            "to_version": "0.12.0",
            "network": "ml307c",
            "status": "success",
        },
    )
    assert response.status_code == 422


def test_removed_token_and_chunk_environment_is_not_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OTA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OTA_DEVICE_TOKEN", "ignored")
    monkeypatch.setenv("OTA_ALLOW_TOKEN_QUERY", "true")
    monkeypatch.setenv("OTA_MAX_CHUNK_SIZE", "1")
    settings = Settings.from_env()
    assert settings.public_base_url == "http://139.129.17.67:18082"
    assert not hasattr(settings, "device_token")
    assert not hasattr(settings, "allow_token_query")
    assert not hasattr(settings, "max_chunk_size")

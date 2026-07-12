from __future__ import annotations

import hashlib
import sqlite3

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_does_not_expose_configuration(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "service": "wkt-ota-server",
        "version": "1.0.0",
        "status": "healthy",
    }


def test_no_update_without_release(client: TestClient) -> None:
    response = client.get(
        "/api/v1/ota/check",
        params={
            "device_id": "esp32-001",
            "hardware": "walkie-v1",
            "current_version": "0.11.2",
            "network": "wifi",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"update": False}


def test_update_contract_and_sha256(
    client: TestClient, published_firmware: bytes
) -> None:
    response = client.get(
        "/api/v1/ota/check",
        params={
            "device_id": "esp32-001",
            "hardware": "walkie-v1",
            "current_version": "0.11.2",
            "network": "ml307c",
            "channel": "stable",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "update": True,
        "version": "0.12.0",
        "hardware": "walkie-v1",
        "channel": "stable",
        "size": len(published_firmware),
        "sha256": hashlib.sha256(published_firmware).hexdigest(),
        "mandatory": False,
        "min_battery": 40,
        "release_notes": "first OTA release",
        "firmware_url": "https://ota.example.com/api/v1/ota/firmware/walkie-v1/0.12.0",
        "chunk_url": "https://ota.example.com/api/v1/ota/chunk/walkie-v1/0.12.0",
        "chunk_size": 49152,
    }


def test_semver_check_is_not_lexicographic(client: TestClient, settings: Settings, tmp_path) -> None:
    source = tmp_path / "new.bin"
    source.write_bytes(b"new")
    from app.cli import main as cli_main

    assert cli_main([
        "publish", "--hardware", "walkie-v2", "--version", "0.10.0",
        "--file", str(source),
    ], settings) == 0
    response = client.get("/api/v1/ota/check", params={
        "device_id": "esp32-002", "hardware": "walkie-v2",
        "current_version": "0.9.9", "network": "wifi",
    })
    assert response.json()["update"] is True


def test_no_update_when_current_is_same_or_newer(client: TestClient, published_firmware: bytes) -> None:
    for current in ("0.12.0", "0.13.0"):
        response = client.get("/api/v1/ota/check", params={
            "device_id": "esp32-001", "hardware": "walkie-v1",
            "current_version": current, "network": "wifi",
        })
        assert response.json() == {"update": False}


def test_missing_firmware_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/ota/firmware/walkie-v1/9.9.9")
    assert response.status_code == 404


def test_complete_download(client: TestClient, published_firmware: bytes) -> None:
    response = client.get("/api/v1/ota/firmware/walkie-v1/0.12.0")
    assert response.status_code == 200
    assert response.content == published_firmware
    assert response.headers["content-length"] == str(len(published_firmware))
    assert response.headers["accept-ranges"] == "bytes"


def test_range_first_middle_and_last(client: TestClient, published_firmware: bytes) -> None:
    cases = [
        ("bytes=0-99", 0, 99),
        ("bytes=50000-50099", 50000, 50099),
        (f"bytes={len(published_firmware) - 25}-", len(published_firmware) - 25, len(published_firmware) - 1),
    ]
    for range_value, start, end in cases:
        response = client.get(
            "/api/v1/ota/firmware/walkie-v1/0.12.0", headers={"Range": range_value}
        )
        assert response.status_code == 206
        assert response.content == published_firmware[start : end + 1]
        assert response.headers["content-range"] == f"bytes {start}-{end}/{len(published_firmware)}"
        assert response.headers["content-length"] == str(end - start + 1)


def test_suffix_range(client: TestClient, published_firmware: bytes) -> None:
    response = client.get(
        "/api/v1/ota/firmware/walkie-v1/0.12.0", headers={"Range": "bytes=-16"}
    )
    assert response.status_code == 206
    assert response.content == published_firmware[-16:]


def test_invalid_ranges_return_416(client: TestClient, published_firmware: bytes) -> None:
    for range_value in (
        "items=0-1", "bytes=abc-def", "bytes=10-9", "bytes=0-1,4-5",
        f"bytes={len(published_firmware)}-",
    ):
        response = client.get(
            "/api/v1/ota/firmware/walkie-v1/0.12.0", headers={"Range": range_value}
        )
        assert response.status_code == 416
        assert response.headers["content-range"] == f"bytes */{len(published_firmware)}"


def test_ml307c_first_middle_and_last_chunks(client: TestClient, published_firmware: bytes) -> None:
    chunk_size = 49152
    offsets = (0, chunk_size, chunk_size * 2)
    for offset in offsets:
        response = client.get(
            "/api/v1/ota/chunk/walkie-v1/0.12.0",
            params={"offset": offset, "length": chunk_size},
        )
        expected = published_firmware[offset : offset + chunk_size]
        assert response.status_code == 200
        assert response.content == expected
        assert response.headers["content-type"].startswith("application/octet-stream")
        assert response.headers["x-firmware-size"] == str(len(published_firmware))
        assert response.headers["x-chunk-offset"] == str(offset)
        assert response.headers["x-chunk-length"] == str(len(expected))


def test_chunk_offset_out_of_bounds(client: TestClient, published_firmware: bytes) -> None:
    response = client.get(
        "/api/v1/ota/chunk/walkie-v1/0.12.0",
        params={"offset": len(published_firmware), "length": 100},
    )
    assert response.status_code == 416
    assert response.headers["x-firmware-size"] == str(len(published_firmware))


def test_chunk_length_limit(client: TestClient, published_firmware: bytes) -> None:
    response = client.get(
        "/api/v1/ota/chunk/walkie-v1/0.12.0",
        params={"offset": 0, "length": 49153},
    )
    assert response.status_code == 422


def test_path_traversal_is_rejected(client: TestClient, published_firmware: bytes) -> None:
    response = client.get("/api/v1/ota/firmware/%2E%2E/0.12.0")
    assert response.status_code in {404, 422}
    response = client.get("/api/v1/ota/firmware/bad.hardware/0.12.0")
    assert response.status_code == 422


def test_header_token_authentication(settings: Settings) -> None:
    protected = Settings(
        public_base_url=settings.public_base_url,
        data_dir=settings.data_dir,
        device_token="secret-device-token",
        allow_token_query=False,
        max_chunk_size=settings.max_chunk_size,
        log_level=settings.log_level,
    )
    with TestClient(create_app(protected)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/ota/check", params={
            "device_id": "esp32-1", "hardware": "walkie-v1",
            "current_version": "0.11.2", "network": "wifi",
        }).status_code == 401
        response = client.get("/api/v1/ota/check", params={
            "device_id": "esp32-1", "hardware": "walkie-v1",
            "current_version": "0.11.2", "network": "wifi",
        }, headers={"X-Device-Token": "secret-device-token"})
        assert response.status_code == 200


def test_optional_query_token_for_ml307c(settings: Settings) -> None:
    protected = Settings(
        public_base_url=settings.public_base_url,
        data_dir=settings.data_dir,
        device_token="secret",
        allow_token_query=True,
        max_chunk_size=settings.max_chunk_size,
        log_level=settings.log_level,
    )
    with TestClient(create_app(protected)) as client:
        response = client.get("/api/v1/ota/check", params={
            "device_id": "esp32-1", "hardware": "walkie-v1",
            "current_version": "0.11.2", "network": "ml307c", "token": "secret",
        })
        assert response.status_code == 200


def test_result_report_is_saved_with_utc_time(client: TestClient, settings: Settings) -> None:
    payload = {
        "device_id": "esp32-001",
        "hardware": "walkie-v1",
        "from_version": "0.11.2",
        "to_version": "0.12.0",
        "network": "wifi",
        "status": "success",
        "bytes_written": 128014,
    }
    response = client.post("/api/v1/ota/report", json=payload)
    assert response.status_code == 201
    assert response.json()["accepted"] is True
    with sqlite3.connect(settings.database_path) as connection:
        row = connection.execute(
            "SELECT device_id, status, bytes_written, created_at FROM ota_reports"
        ).fetchone()
    assert row[:3] == ("esp32-001", "success", 128014)
    assert row[3].endswith("Z")


def test_report_validation(client: TestClient) -> None:
    response = client.post("/api/v1/ota/report", json={
        "device_id": "esp32-001", "hardware": "walkie-v1",
        "from_version": "0.11.2", "to_version": "0.12.0",
        "network": "wifi", "status": "unknown",
    })
    assert response.status_code == 422

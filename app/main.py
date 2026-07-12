from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Path as ApiPath, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from . import __version__
from .config import Settings
from .db import Database
from .models import OtaReport
from .security import verify_device_token
from .semver import SemVer
from .storage import firmware_path, iter_file
from .validation import validate_channel, validate_device_id, validate_hardware, validate_version


SERVICE_NAME = "wkt-ota-server"


def _validated(value: str, validator) -> str:
    try:
        return validator(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _parse_range(range_header: str, size: int) -> tuple[int, int]:
    if not range_header.startswith("bytes=") or "," in range_header:
        raise ValueError("unsupported range")
    value = range_header[6:].strip()
    if "-" not in value:
        raise ValueError("malformed range")
    start_text, end_text = value.split("-", 1)
    if not start_text:
        if not end_text.isdigit() or int(end_text) <= 0:
            raise ValueError("invalid suffix range")
        length = min(int(end_text), size)
        return size - length, size - 1
    if not start_text.isdigit() or (end_text and not end_text.isdigit()):
        raise ValueError("invalid range numbers")
    start = int(start_text)
    end = int(end_text) if end_text else size - 1
    if start >= size or start > end:
        raise ValueError("range outside resource")
    return start, min(end, size - 1)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        database.initialize()
        yield

    app = FastAPI(title=SERVICE_NAME, version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database

    def authorize(request: Request) -> None:
        verify_device_token(request, settings)

    def find_firmware(hardware: str, version: str) -> tuple[dict, Path]:
        hardware = _validated(hardware, validate_hardware)
        version = _validated(version, validate_version)
        release = database.get_release(hardware, version)
        if release is None:
            raise HTTPException(status_code=404, detail="firmware not found")
        try:
            path = firmware_path(settings, hardware, version)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid firmware path") from exc
        if not path.is_file():
            raise HTTPException(status_code=404, detail="firmware not found")
        actual_size = path.stat().st_size
        if actual_size != release["size"]:
            logging.getLogger(__name__).error(
                "firmware size mismatch for hardware=%s version=%s", hardware, version
            )
            raise HTTPException(status_code=500, detail="firmware storage integrity error")
        return release, path

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"service": SERVICE_NAME, "version": __version__, "status": "healthy"}

    @app.get("/api/v1/ota/check", dependencies=[Depends(authorize)])
    def check_update(
        device_id: Annotated[str, Query(min_length=1, max_length=128)],
        hardware: Annotated[str, Query(min_length=1, max_length=64)],
        current_version: Annotated[str, Query(min_length=1, max_length=128)],
        network: Literal["wifi", "ml307c"],
        channel: Annotated[str, Query(min_length=1, max_length=32)] = "stable",
    ) -> dict:
        _validated(device_id, validate_device_id)
        hardware = _validated(hardware, validate_hardware)
        channel = _validated(channel, validate_channel)
        current = SemVer.parse(_validated(current_version, validate_version))
        candidates = database.enabled_releases(hardware, channel)
        if not candidates:
            return {"update": False}
        latest = max(candidates, key=lambda release: SemVer.parse(release["version"]))
        if SemVer.parse(latest["version"]) <= current:
            return {"update": False}
        encoded_hardware = quote(latest["hardware"], safe="")
        encoded_version = quote(latest["version"], safe="")
        base = settings.public_base_url
        return {
            "update": True,
            "version": latest["version"],
            "hardware": latest["hardware"],
            "channel": latest["channel"],
            "size": latest["size"],
            "sha256": latest["sha256"],
            "mandatory": bool(latest["mandatory"]),
            "min_battery": latest["min_battery"],
            "release_notes": latest["release_notes"],
            "firmware_url": f"{base}/api/v1/ota/firmware/{encoded_hardware}/{encoded_version}",
            "chunk_url": f"{base}/api/v1/ota/chunk/{encoded_hardware}/{encoded_version}",
            "chunk_size": settings.max_chunk_size,
        }

    @app.get(
        "/api/v1/ota/firmware/{hardware}/{version}",
        dependencies=[Depends(authorize)],
    )
    def download_firmware(
        request: Request,
        hardware: Annotated[str, ApiPath(min_length=1, max_length=64)],
        version: Annotated[str, ApiPath(min_length=1, max_length=128)],
    ) -> StreamingResponse:
        _, path = find_firmware(hardware, version)
        size = path.stat().st_size
        range_header = request.headers.get("Range")
        headers = {"Accept-Ranges": "bytes", "Content-Type": "application/octet-stream"}
        if range_header is None:
            headers["Content-Length"] = str(size)
            return StreamingResponse(iter_file(path, 0, size), status_code=200, headers=headers)
        try:
            start, end = _parse_range(range_header, size)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
                detail="invalid byte range",
                headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"},
            ) from exc
        length = end - start + 1
        headers.update(
            {"Content-Length": str(length), "Content-Range": f"bytes {start}-{end}/{size}"}
        )
        return StreamingResponse(iter_file(path, start, length), status_code=206, headers=headers)

    @app.get(
        "/api/v1/ota/chunk/{hardware}/{version}",
        dependencies=[Depends(authorize)],
    )
    def download_chunk(
        hardware: Annotated[str, ApiPath(min_length=1, max_length=64)],
        version: Annotated[str, ApiPath(min_length=1, max_length=128)],
        offset: Annotated[int, Query(ge=0)],
        length: Annotated[int, Query(ge=1)],
    ) -> StreamingResponse:
        if length > settings.max_chunk_size:
            raise HTTPException(status_code=422, detail=f"length must not exceed {settings.max_chunk_size}")
        _, path = find_firmware(hardware, version)
        size = path.stat().st_size
        if offset >= size:
            raise HTTPException(
                status_code=416,
                detail="offset outside firmware",
                headers={"X-Firmware-Size": str(size)},
            )
        actual_length = min(length, size - offset)
        headers = {
            "Content-Type": "application/octet-stream",
            "Content-Length": str(actual_length),
            "X-Firmware-Size": str(size),
            "X-Chunk-Offset": str(offset),
            "X-Chunk-Length": str(actual_length),
        }
        return StreamingResponse(iter_file(path, offset, actual_length), headers=headers)

    @app.post("/api/v1/ota/report", status_code=201, dependencies=[Depends(authorize)])
    def report_result(report: OtaReport, response: Response) -> dict[str, int | bool]:
        report_id = database.insert_report(report.model_dump())
        response.headers["Location"] = f"/api/v1/ota/report/{report_id}"
        return {"accepted": True, "report_id": report_id}

    return app


app = create_app()

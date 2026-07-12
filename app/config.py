from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    public_base_url: str
    data_dir: Path
    device_token: str | None
    allow_token_query: bool
    max_chunk_size: int
    log_level: str

    @property
    def database_path(self) -> Path:
        return self.data_dir / "ota.db"

    @property
    def firmware_dir(self) -> Path:
        return self.data_dir / "firmware"

    @classmethod
    def from_env(cls) -> "Settings":
        public_base_url = os.getenv("OTA_PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
        parsed = urlparse(public_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("OTA_PUBLIC_BASE_URL must be an absolute HTTP(S) URL")

        max_chunk_size = int(os.getenv("OTA_MAX_CHUNK_SIZE", "49152"))
        if not 1 <= max_chunk_size <= 65535:
            raise ValueError("OTA_MAX_CHUNK_SIZE must be between 1 and 65535")

        token = os.getenv("OTA_DEVICE_TOKEN") or None
        return cls(
            public_base_url=public_base_url,
            data_dir=Path(os.getenv("OTA_DATA_DIR", "data")).resolve(),
            device_token=token,
            allow_token_query=_as_bool(os.getenv("OTA_ALLOW_TOKEN_QUERY", "false")),
            max_chunk_size=max_chunk_size,
            log_level=os.getenv("OTA_LOG_LEVEL", "INFO").upper(),
        )

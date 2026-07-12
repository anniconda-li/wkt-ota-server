from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class Settings:
    public_base_url: str
    data_dir: Path
    log_level: str

    @property
    def database_path(self) -> Path:
        return self.data_dir / "ota.db"

    @property
    def firmware_dir(self) -> Path:
        return self.data_dir / "firmware"

    @classmethod
    def from_env(cls) -> "Settings":
        public_base_url = os.getenv(
            "OTA_PUBLIC_BASE_URL", "http://139.129.17.67:18082"
        ).rstrip("/")
        parsed = urlparse(public_base_url)
        if parsed.scheme != "http" or not parsed.netloc:
            raise ValueError("OTA_PUBLIC_BASE_URL must be an absolute HTTP URL")

        return cls(
            public_base_url=public_base_url,
            data_dir=Path(os.getenv("OTA_DATA_DIR", "data")).resolve(),
            log_level=os.getenv("OTA_LOG_LEVEL", "INFO").upper(),
        )

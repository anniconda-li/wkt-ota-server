from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .validation import validate_device_id, validate_hardware, validate_version


Network = Literal["wifi"]
ReportStatus = Literal[
    "download_started", "verified", "rebooting", "success", "failed", "rolled_back"
]


class OtaReport(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    device_id: str
    hardware: str
    from_version: str
    to_version: str
    network: Network
    status: ReportStatus
    bytes_written: int | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=1024)

    @field_validator("device_id")
    @classmethod
    def valid_device_id(cls, value: str) -> str:
        return validate_device_id(value)

    @field_validator("hardware")
    @classmethod
    def valid_hardware(cls, value: str) -> str:
        return validate_hardware(value)

    @field_validator("from_version", "to_version")
    @classmethod
    def valid_version(cls, value: str) -> str:
        return validate_version(value)

    @model_validator(mode="after")
    def failure_details_only_for_failure(self) -> "OtaReport":
        if self.status not in {"failed", "rolled_back"} and (self.error_code or self.error_message):
            raise ValueError("error details are only valid for failed or rolled_back reports")
        return self

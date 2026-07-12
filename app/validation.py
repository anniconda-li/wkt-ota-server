from __future__ import annotations

import re

from .semver import SemVer


HARDWARE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
CHANNEL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def validate_hardware(value: str) -> str:
    if not HARDWARE_RE.fullmatch(value):
        raise ValueError("invalid hardware")
    return value


def validate_channel(value: str) -> str:
    if not CHANNEL_RE.fullmatch(value):
        raise ValueError("invalid channel")
    return value


def validate_version(value: str) -> str:
    SemVer.parse(value)
    return value


def validate_device_id(value: str) -> str:
    if not DEVICE_ID_RE.fullmatch(value):
        raise ValueError("invalid device_id")
    return value

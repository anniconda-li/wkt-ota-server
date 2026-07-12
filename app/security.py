from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status

from .config import Settings


def verify_device_token(request: Request, settings: Settings) -> None:
    expected = settings.device_token
    if expected is None:
        return
    supplied = request.headers.get("X-Device-Token")
    if supplied is None and settings.allow_token_query:
        supplied = request.query_params.get("token")
    if supplied is None or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid device credentials",
            headers={"WWW-Authenticate": "DeviceToken"},
        )

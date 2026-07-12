from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hardware TEXT NOT NULL,
    version TEXT NOT NULL,
    channel TEXT NOT NULL,
    size INTEGER NOT NULL CHECK (size >= 0),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    release_notes TEXT NOT NULL DEFAULT '',
    mandatory INTEGER NOT NULL DEFAULT 0 CHECK (mandatory IN (0, 1)),
    min_battery INTEGER NOT NULL DEFAULT 40 CHECK (min_battery BETWEEN 0 AND 100),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE (hardware, version)
);
CREATE INDEX IF NOT EXISTS idx_releases_lookup
    ON releases (hardware, channel, enabled);

CREATE TABLE IF NOT EXISTS ota_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    hardware TEXT NOT NULL,
    from_version TEXT NOT NULL,
    to_version TEXT NOT NULL,
    network TEXT NOT NULL,
    status TEXT NOT NULL,
    bytes_written INTEGER,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_device_time
    ON ota_reports (device_id, created_at);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)

    def create_release(self, release: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO releases
                    (hardware, version, channel, size, sha256, release_notes,
                     mandatory, min_battery, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    release["hardware"], release["version"], release["channel"],
                    release["size"], release["sha256"], release["release_notes"],
                    int(release["mandatory"]), release["min_battery"], utc_now(),
                ),
            )

    def release_exists(self, hardware: str, version: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM releases WHERE hardware = ? AND version = ?",
                (hardware, version),
            ).fetchone()
        return row is not None

    def get_release(self, hardware: str, version: str, *, enabled_only: bool = True) -> dict[str, Any] | None:
        enabled_clause = " AND enabled = 1" if enabled_only else ""
        with self.connect() as connection:
            row = connection.execute(
                f"SELECT * FROM releases WHERE hardware = ? AND version = ?{enabled_clause}",
                (hardware, version),
            ).fetchone()
        return dict(row) if row else None

    def list_releases(self, hardware: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM releases"
        params: tuple[Any, ...] = ()
        if hardware:
            query += " WHERE hardware = ?"
            params = (hardware,)
        query += " ORDER BY created_at DESC, id DESC"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def enabled_releases(self, hardware: str, channel: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM releases WHERE hardware = ? AND channel = ? AND enabled = 1",
                (hardware, channel),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_enabled(self, hardware: str, version: str, enabled: bool) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE releases SET enabled = ? WHERE hardware = ? AND version = ?",
                (int(enabled), hardware, version),
            )
        return cursor.rowcount == 1

    def insert_report(self, report: dict[str, Any]) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO ota_reports
                    (device_id, hardware, from_version, to_version, network, status,
                     bytes_written, error_code, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report["device_id"], report["hardware"], report["from_version"],
                    report["to_version"], report["network"], report["status"],
                    report.get("bytes_written"), report.get("error_code"),
                    report.get("error_message"), utc_now(),
                ),
            )
            report_id = int(cursor.lastrowid)
        return report_id

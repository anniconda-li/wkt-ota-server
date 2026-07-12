from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from .config import Settings
from .db import Database
from .storage import atomic_copy, firmware_path, hash_file
from .validation import validate_channel, validate_hardware, validate_version


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Manage OTA releases")
    commands = parser.add_subparsers(dest="command", required=True)

    publish = commands.add_parser("publish", help="publish a locally built firmware binary")
    publish.add_argument("--hardware", required=True)
    publish.add_argument("--version", required=True)
    publish.add_argument("--channel", default="stable")
    publish.add_argument("--file", required=True, type=Path)
    publish.add_argument("--notes", default="")
    publish.add_argument("--mandatory", action="store_true")
    publish.add_argument("--min-battery", type=int, default=40)

    list_parser = commands.add_parser("list", help="list releases")
    list_parser.add_argument("--hardware")

    for name in ("enable", "disable"):
        command = commands.add_parser(name, help=f"{name} a release")
        command.add_argument("--hardware", required=True)
        command.add_argument("--version", required=True)
    return parser


def _validate_release_args(hardware: str, version: str, channel: str | None = None) -> None:
    validate_hardware(hardware)
    validate_version(version)
    if channel is not None:
        validate_channel(channel)


def run(args: argparse.Namespace, settings: Settings) -> int:
    database = Database(settings.database_path)
    database.initialize()

    if args.command == "publish":
        _validate_release_args(args.hardware, args.version, args.channel)
        if not 0 <= args.min_battery <= 100:
            raise ValueError("min-battery must be between 0 and 100")
        source = args.file.resolve()
        if not source.is_file():
            raise FileNotFoundError(f"firmware file not found: {source}")
        if database.release_exists(args.hardware, args.version):
            raise FileExistsError(f"release already exists: {args.hardware} {args.version}")
        destination = firmware_path(settings, args.hardware, args.version)
        size, sha256 = hash_file(source)
        if size == 0:
            raise ValueError("firmware file must not be empty")
        atomic_copy(source, destination)
        try:
            database.create_release(
                {
                    "hardware": args.hardware,
                    "version": args.version,
                    "channel": args.channel,
                    "size": size,
                    "sha256": sha256,
                    "release_notes": args.notes,
                    "mandatory": args.mandatory,
                    "min_battery": args.min_battery,
                }
            )
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        print(f"published {args.hardware} {args.version} ({size} bytes, sha256={sha256})")
        return 0

    if args.command == "list":
        if args.hardware:
            validate_hardware(args.hardware)
        releases = database.list_releases(args.hardware)
        if not releases:
            print("no releases")
            return 0
        for release in releases:
            state = "enabled" if release["enabled"] else "disabled"
            print(
                f"{release['hardware']}\t{release['version']}\t{release['channel']}\t"
                f"{state}\t{release['size']}\t{release['sha256']}"
            )
        return 0

    _validate_release_args(args.hardware, args.version)
    enabled = args.command == "enable"
    if not database.set_enabled(args.hardware, args.version, enabled):
        raise LookupError(f"release not found: {args.hardware} {args.version}")
    print(f"{args.command}d {args.hardware} {args.version}")
    return 0


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args, settings or Settings.from_env())
    except (ValueError, FileNotFoundError, FileExistsError, LookupError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

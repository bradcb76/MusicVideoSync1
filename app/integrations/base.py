from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ServerInfo:
    ok: bool
    name: str = ""
    version: str = ""
    error: str = ""


@dataclass
class Library:
    id: str
    name: str
    path: str = ""


def mapped_path(local_path: Path, local_prefix: Path, remote_prefix: str) -> str:
    resolved = local_path.resolve()
    prefix = local_prefix.resolve()
    if resolved != prefix and prefix not in resolved.parents:
        raise ValueError("Path is outside the configured video library")
    relative = resolved.relative_to(prefix).as_posix()
    return remote_prefix.rstrip("/\\") + (f"/{relative}" if relative else "")

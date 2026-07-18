from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path


def safe_component(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", " ", value).strip().rstrip(" .")
    return value[:150] or "Unknown"


def ensure_within(path: Path, root: Path) -> Path:
    resolved, resolved_root = path.resolve(), root.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError("Unsafe path outside configured root")
    return resolved


def atomic_publish(source: Path, destination: Path, destination_root: Path) -> None:
    ensure_within(destination, destination_root)
    if destination.exists():
        raise FileExistsError(str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.partial")
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def validate_ffmpeg(timeout: float = 10) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, text=True, timeout=timeout, check=False
        )
        first_line = (result.stdout or result.stderr).splitlines()[0]
        return result.returncode == 0, first_line[:200]
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, type(error).__name__

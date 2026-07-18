from pathlib import Path

import pytest

from app.services.media import atomic_publish, ensure_within, safe_component


def test_path_containment_rejects_source_escape(tmp_path: Path):
    root = tmp_path / "videos"
    root.mkdir()
    with pytest.raises(ValueError):
        ensure_within(tmp_path / "music" / "song.mp3", root)


def test_atomic_publish_never_overwrites_existing(tmp_path: Path):
    root = tmp_path / "videos"
    root.mkdir()
    source = tmp_path / "new.mp4"
    source.write_bytes(b"new")
    destination = root / "existing.mp4"
    destination.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        atomic_publish(source, destination, root)
    assert destination.read_bytes() == b"original"
    assert source.read_bytes() == b"new"


def test_safe_component_blocks_traversal():
    value = safe_component("../../Artist: Name")
    assert "/" not in value
    assert "\\" not in value
    assert value != ".."


def test_compose_keeps_music_read_only():
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    assert 'D:/Music:/music:ro' in compose

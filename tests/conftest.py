from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.security import hash_password


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    music = tmp_path / "music"
    videos = tmp_path / "videos"
    staging = tmp_path / "staging"
    processing = tmp_path / "processing"
    for path in (music, videos, staging, processing):
        path.mkdir()
    return Settings(
        music_library=music,
        music_video_library=videos,
        database_path=tmp_path / "data" / "test.db",
        staging_path=staging,
        processing_path=processing,
        timezone="Australia/Sydney",
        daily_limit=250,
        dry_run=True,
        allow_downloads=False,
        session_secret="test-session-secret-that-is-long-enough",
        admin_password_hash=hash_password("correct horse battery staple", iterations=1_000),
        docs_enabled=False,
        log_level="WARNING",
        video_quality=720,
        external_timeout=0.1,
        retry_delay_seconds=0,
        plex_enabled=False,
        plex_url="",
        plex_token="",
        plex_library="",
        plex_path_prefix="",
        plex_verify_ssl=True,
        plex_auto_refresh=True,
        emby_enabled=False,
        emby_url="",
        emby_api_key="",
        emby_library_id="",
        emby_path_prefix="",
        emby_verify_ssl=True,
        emby_auto_refresh=True,
    )


@pytest.fixture
def client(test_settings: Settings):
    with TestClient(create_app(test_settings)) as test_client:
        yield test_client


@pytest.fixture
def authenticated(client: TestClient) -> tuple[TestClient, str]:
    response = client.post(
        "/api/auth/login", json={"password": "correct horse battery staple"}
    )
    assert response.status_code == 200
    return client, response.json()["csrf"]

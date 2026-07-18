from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    music_library: Path
    music_video_library: Path
    database_path: Path
    staging_path: Path
    processing_path: Path
    timezone: str
    daily_limit: int
    dry_run: bool
    allow_downloads: bool
    session_secret: str
    admin_password_hash: str
    docs_enabled: bool
    log_level: str
    video_quality: int
    external_timeout: float
    retry_delay_seconds: float
    plex_enabled: bool
    plex_url: str
    plex_token: str
    plex_library: str
    plex_path_prefix: str
    plex_verify_ssl: bool
    plex_auto_refresh: bool
    emby_enabled: bool
    emby_url: str
    emby_api_key: str
    emby_library_id: str
    emby_path_prefix: str
    emby_verify_ssl: bool
    emby_auto_refresh: bool

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            music_library=Path(os.getenv("MUSIC_LIBRARY", "/music")).resolve(),
            music_video_library=Path(os.getenv("MUSIC_VIDEO_LIBRARY", "/music-videos")).resolve(),
            database_path=Path(os.getenv("DATABASE_PATH", "/data/music-video-sync.db")).resolve(),
            staging_path=Path(os.getenv("STAGING_PATH", "/staging")).resolve(),
            processing_path=Path(os.getenv("PROCESSING_PATH", "/processing")).resolve(),
            timezone=os.getenv("APP_TIMEZONE", "Australia/Sydney"),
            daily_limit=int(os.getenv("DAILY_DOWNLOAD_LIMIT", "250")),
            dry_run=_bool("DRY_RUN", True),
            allow_downloads=_bool("ALLOW_DOWNLOADS", False),
            session_secret=os.getenv("SESSION_SECRET", "change-me-before-production"),
            admin_password_hash=os.getenv("ADMIN_PASSWORD_HASH", ""),
            docs_enabled=_bool("DOCS_ENABLED", False),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            video_quality=int(os.getenv("VIDEO_QUALITY", "720")),
            external_timeout=float(os.getenv("EXTERNAL_TIMEOUT_SECONDS", "30")),
            retry_delay_seconds=float(os.getenv("RETRY_DELAY_SECONDS", "5")),
            plex_enabled=_bool("PLEX_ENABLED"),
            plex_url=os.getenv("PLEX_URL", "").rstrip("/"),
            plex_token=os.getenv("PLEX_TOKEN", ""),
            plex_library=os.getenv("PLEX_MUSIC_VIDEO_LIBRARY", ""),
            plex_path_prefix=os.getenv("PLEX_PATH_PREFIX", ""),
            plex_verify_ssl=_bool("PLEX_VERIFY_SSL", True),
            plex_auto_refresh=_bool("PLEX_AUTO_REFRESH", True),
            emby_enabled=_bool("EMBY_ENABLED"),
            emby_url=os.getenv("EMBY_URL", "").rstrip("/"),
            emby_api_key=os.getenv("EMBY_API_KEY", ""),
            emby_library_id=os.getenv("EMBY_LIBRARY_ID", ""),
            emby_path_prefix=os.getenv("EMBY_PATH_PREFIX", ""),
            emby_verify_ssl=_bool("EMBY_VERIFY_SSL", True),
            emby_auto_refresh=_bool("EMBY_AUTO_REFRESH", True),
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.daily_limit < 1:
            errors.append("DAILY_DOWNLOAD_LIMIT must be positive")
        if self.music_library == self.music_video_library:
            errors.append("Music source and video destination must be different")
        if self.music_library in self.music_video_library.parents:
            errors.append("Video destination must not be inside the original music library")
        if not self.dry_run and not self.allow_downloads:
            errors.append("Live mode requires ALLOW_DOWNLOADS=true")
        return errors


settings = Settings.from_env()

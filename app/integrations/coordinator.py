from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.database import Database
from app.integrations.emby import EmbyClient
from app.integrations.plex import PlexClient

logger = logging.getLogger(__name__)


class IntegrationCoordinator:
    def __init__(self, database: Database, settings: Settings):
        self.database, self.settings = database, settings

    def clients(self):
        return {
            "plex": PlexClient(
                self.settings.plex_url, self.settings.plex_token,
                self.settings.plex_verify_ssl, self.settings.external_timeout,
            ),
            "emby": EmbyClient(
                self.settings.emby_url, self.settings.emby_api_key,
                self.settings.emby_verify_ssl, self.settings.external_timeout,
            ),
        }

    def enabled(self, provider: str) -> bool:
        return self.settings.plex_enabled if provider == "plex" else self.settings.emby_enabled

    def test(self, provider: str):
        if not self.enabled(provider):
            return {"ok": False, "error": f"{provider.title()} is disabled"}
        result = self.clients()[provider].test()
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as db:
            db.execute(
                """INSERT INTO integration_status(provider,server_name,server_version,status,
                   last_test_at,last_result) VALUES(?,?,?,?,?,?)
                   ON CONFLICT(provider) DO UPDATE SET server_name=excluded.server_name,
                   server_version=excluded.server_version,status=excluded.status,
                   last_test_at=excluded.last_test_at,last_result=excluded.last_result""",
                (
                    provider, result.name, result.version, "online" if result.ok else "offline",
                    now, "Connected" if result.ok else result.error,
                ),
            )
        return result.__dict__

    def libraries(self, provider: str):
        if not self.enabled(provider):
            return []
        return [item.__dict__ for item in self.clients()[provider].libraries()]

    def refresh(self, provider: str, local_path: Path | None = None) -> dict:
        if not self.enabled(provider):
            return {"ok": False, "error": f"{provider.title()} is disabled"}
        client = self.clients()[provider]
        try:
            if provider == "plex":
                library = self.settings.plex_library
                mapped = (
                    client.map_path(local_path, self.settings.music_video_library, self.settings.plex_path_prefix)
                    if local_path and self.settings.plex_path_prefix else None
                )
            else:
                library = self.settings.emby_library_id
                mapped = (
                    client.map_path(local_path, self.settings.music_video_library, self.settings.emby_path_prefix)
                    if local_path and self.settings.emby_path_prefix else None
                )
            if not library:
                raise ValueError("No library is configured")
            client.refresh(library, mapped)
            result = {"ok": True, "message": f"{provider.title()} refresh requested"}
        except Exception as error:
            result = {"ok": False, "error": f"{provider.title()} refresh failed: {type(error).__name__}"}
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as db:
            db.execute(
                """INSERT INTO integration_status(provider,status,last_refresh_at,last_result)
                   VALUES(?,?,?,?) ON CONFLICT(provider) DO UPDATE SET status=excluded.status,
                   last_refresh_at=excluded.last_refresh_at,last_result=excluded.last_result""",
                (provider, "online" if result["ok"] else "offline", now, result.get("message") or result["error"]),
            )
        return result

    def refresh_all(self, local_path: Path | None = None) -> dict:
        # Intentionally isolated: one provider's exception/result never blocks the other.
        configured = {
            "plex": self.settings.plex_auto_refresh,
            "emby": self.settings.emby_auto_refresh,
        }
        return {
            provider: self.refresh(provider, local_path)
            for provider in ("plex", "emby")
            if self.enabled(provider) and configured[provider]
        }

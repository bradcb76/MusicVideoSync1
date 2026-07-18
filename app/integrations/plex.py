from __future__ import annotations

from pathlib import Path

import httpx

from .base import Library, ServerInfo, mapped_path


class PlexClient:
    def __init__(self, url: str, token: str, verify_ssl: bool = True, timeout: float = 30):
        self.url, self.token, self.verify_ssl, self.timeout = (
            url.rstrip("/"),
            token,
            verify_ssl,
            timeout,
        )

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.url,
            headers={"X-Plex-Token": self.token, "Accept": "application/json"},
            verify=self.verify_ssl,
            timeout=self.timeout,
        )

    def test(self) -> ServerInfo:
        try:
            with self._client() as client:
                response = client.get("/")
                response.raise_for_status()
                container = response.json().get("MediaContainer", {})
                return ServerInfo(True, container.get("friendlyName", ""), container.get("version", ""))
        except Exception as error:
            return ServerInfo(False, error=f"Plex connection failed: {type(error).__name__}")

    def libraries(self) -> list[Library]:
        with self._client() as client:
            response = client.get("/library/sections")
            response.raise_for_status()
            directories = response.json().get("MediaContainer", {}).get("Directory", [])
            return [
                Library(str(item["key"]), item.get("title", ""), item.get("Location", [{}])[0].get("path", ""))
                for item in directories
                if item.get("type") in {"movie", "other", "music"}
            ]

    def refresh(self, library_id: str, path: str | None = None) -> None:
        params = {"path": path} if path else {}
        with self._client() as client:
            response = client.get(f"/library/sections/{library_id}/refresh", params=params)
            response.raise_for_status()

    @staticmethod
    def map_path(local_path: Path, local_prefix: Path, plex_prefix: str) -> str:
        return mapped_path(local_path, local_prefix, plex_prefix)

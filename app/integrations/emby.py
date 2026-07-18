from __future__ import annotations

from pathlib import Path

import httpx

from .base import Library, ServerInfo, mapped_path


class EmbyClient:
    def __init__(self, url: str, api_key: str, verify_ssl: bool = True, timeout: float = 30):
        self.url, self.api_key, self.verify_ssl, self.timeout = (
            url.rstrip("/"),
            api_key,
            verify_ssl,
            timeout,
        )

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.url,
            headers={"X-Emby-Token": self.api_key},
            verify=self.verify_ssl,
            timeout=self.timeout,
        )

    def test(self) -> ServerInfo:
        try:
            with self._client() as client:
                response = client.get("/System/Info/Public")
                response.raise_for_status()
                info = response.json()
                return ServerInfo(True, info.get("ServerName", ""), info.get("Version", ""))
        except Exception as error:
            return ServerInfo(False, error=f"Emby connection failed: {type(error).__name__}")

    def libraries(self) -> list[Library]:
        with self._client() as client:
            response = client.get("/Library/VirtualFolders")
            response.raise_for_status()
            return [
                Library(str(item.get("ItemId", "")), item.get("Name", ""), (item.get("Locations") or [""])[0])
                for item in response.json()
            ]

    def refresh(self, library_id: str, path: str | None = None) -> None:
        del library_id, path
        with self._client() as client:
            response = client.post("/Library/Refresh")
            response.raise_for_status()

    @staticmethod
    def map_path(local_path: Path, local_prefix: Path, emby_prefix: str) -> str:
        return mapped_path(local_path, local_prefix, emby_prefix)

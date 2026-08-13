from __future__ import annotations

import httpx

from odrclone.config import ServarrEndpoint


class ServarrClient:
    def __init__(self, config: ServarrEndpoint, kind: str):
        self.config = config
        self.kind = kind.lower()

    @property
    def headers(self):
        return {"X-Api-Key": self.config.api_key, "Content-Type": "application/json"}

    async def test(self):
        async with httpx.AsyncClient(timeout=15, headers=self.headers) as client:
            response = await client.get(self.config.url.rstrip("/") + "/api/v3/system/status")
            response.raise_for_status()
            return response.json()

    async def missing(self, page_size: int = 100):
        async with httpx.AsyncClient(timeout=30, headers=self.headers) as client:
            response = await client.get(self.config.url.rstrip("/") + "/api/v3/wanted/missing", params={"page": 1, "pageSize": page_size, "sortDirection": "ascending", "sortKey": "id"})
            response.raise_for_status()
            return response.json()

    async def downloaded_scan(self, path: str, download_client_id: str = "od-rclone", import_mode: str | None = None):
        name = "DownloadedEpisodesScan" if self.kind == "sonarr" else "DownloadedMoviesScan"
        body = {"name": name, "path": path, "downloadClientId": download_client_id, "importMode": import_mode or self.config.import_mode}
        async with httpx.AsyncClient(timeout=30, headers=self.headers) as client:
            response = await client.post(self.config.url.rstrip("/") + "/api/v3/command", json=body)
            response.raise_for_status()
            return response.json()

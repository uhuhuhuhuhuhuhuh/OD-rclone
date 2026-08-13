from __future__ import annotations

from abc import ABC, abstractmethod

import asyncio
from urllib.parse import urlparse

import httpx

from odrclone.net import ftp_stat
from odrclone.schemas import Candidate, SearchRequest


class ProviderError(RuntimeError):
    pass


class SearchProvider(ABC):
    name: str

    def __init__(self, config):
        self.config = config

    @abstractmethod
    async def search(self, request: SearchRequest) -> list[Candidate]:
        raise NotImplementedError

    async def validate(self, candidate: Candidate) -> Candidate:
        scheme = urlparse(candidate.url).scheme.lower()
        if scheme in {"ftp", "ftps"}:
            try:
                info = await asyncio.to_thread(ftp_stat, candidate.url, self.config.timeout_seconds)
                candidate.alive = True
                candidate.range_supported = info.range_supported
                if info.size is not None:
                    candidate.size = info.size
            except Exception:
                candidate.alive = False
            return candidate

        timeout = httpx.Timeout(self.config.timeout_seconds)
        headers = {"User-Agent": self.config.user_agent, "Accept-Encoding": "identity"}
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            try:
                response = await client.head(candidate.url)
                if response.status_code in (405, 403) or response.status_code >= 500:
                    response = await client.get(candidate.url, headers={"Range": "bytes=0-0"})
                candidate.alive = response.status_code < 400
                if response.status_code == 206:
                    candidate.range_supported = True
                    cr = response.headers.get("content-range", "")
                    if "/" in cr:
                        total = cr.rsplit("/", 1)[-1]
                        if total.isdigit():
                            candidate.size = int(total)
                else:
                    candidate.range_supported = response.headers.get("accept-ranges", "").lower() == "bytes"
                    cl = response.headers.get("content-length")
                    if cl and cl.isdigit() and candidate.size is None:
                        candidate.size = int(cl)
            except httpx.HTTPError:
                candidate.alive = False
        return candidate

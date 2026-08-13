from __future__ import annotations

from abc import ABC, abstractmethod

import asyncio
from urllib.parse import urlparse

import httpx

from odrclone.net import ftp_stat
from odrclone.schemas import Candidate, SearchRequest


class ProviderError(RuntimeError):
    pass


def _looks_like_html(data: bytes) -> bool:
    sample = data[:4096].lstrip(b"\xef\xbb\xbf\x00\t\r\n ").lower()
    return sample.startswith(b"<!doctype html") or sample.startswith(b"<html")


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
                candidate.alive = response.status_code < 400

                if candidate.alive:
                    async with client.stream("GET", candidate.url, headers={"Range": "bytes=0-4095"}) as probe:
                        if probe.status_code >= 400:
                            candidate.alive = False
                            return candidate

                        content_type = probe.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                        if content_type in {"text/html", "application/xhtml+xml"}:
                            candidate.alive = False
                            candidate.range_supported = False
                            return candidate

                        first_bytes = b""
                        async for chunk in probe.aiter_bytes():
                            first_bytes += chunk
                            if len(first_bytes) >= 4096:
                                break
                        if _looks_like_html(first_bytes):
                            candidate.alive = False
                            candidate.range_supported = False
                            return candidate

                        if probe.status_code == 206:
                            candidate.range_supported = True
                            cr = probe.headers.get("content-range", "")
                            if "/" in cr:
                                total = cr.rsplit("/", 1)[-1]
                                if total.isdigit():
                                    candidate.size = int(total)
                        else:
                            candidate.range_supported = probe.headers.get("accept-ranges", "").lower() == "bytes"
                            cl = probe.headers.get("content-length")
                            if cl and cl.isdigit() and candidate.size is None:
                                candidate.size = int(cl)
                else:
                    candidate.range_supported = False
            except httpx.HTTPError:
                candidate.alive = False
        return candidate

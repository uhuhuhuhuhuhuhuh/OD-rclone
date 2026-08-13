from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from odrclone.providers.base import ProviderError, SearchProvider
from odrclone.schemas import Candidate, SearchRequest

_SIZE_RE = re.compile(r"(?P<n>[\d.,]+)\s*(?P<u>[KMGT]?i?B|bytes?)", re.I)


def parse_size(text: str) -> int | None:
    match = _SIZE_RE.search(text)
    if not match:
        return None
    number = float(match.group("n").replace(",", ""))
    unit = match.group("u").lower()
    powers = {"b": 0, "byte": 0, "bytes": 0, "kb": 1, "kib": 1, "mb": 2, "mib": 2, "gb": 3, "gib": 3, "tb": 4, "tib": 4}
    return int(number * (1024 ** powers.get(unit, 0)))


class EyeDexProvider(SearchProvider):
    name = "eyedex"

    async def search(self, request: SearchRequest) -> list[Candidate]:
        params = {"q": request.query}
        if len(request.extensions) == 1:
            params["t"] = request.extensions[0].lstrip(".")
        headers = {"User-Agent": self.config.user_agent, "Accept": "text/html,application/xhtml+xml"}
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds, headers=headers, follow_redirects=True) as client:
                response = await client.get(urljoin(self.config.base_url, "/search/"), params=params)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(str(exc)) from exc

        soup = BeautifulSoup(response.text, "html.parser")
        results: list[Candidate] = []
        allowed = {x.lower().lstrip(".") for x in request.extensions}
        for row in soup.select("tr"):
            cells = row.find_all(["td", "th"])
            if not cells or row.find("th"):
                continue
            direct = None
            for anchor in row.find_all("a", href=True):
                href = anchor.get("href", "")
                if href.startswith(("http://", "https://", "ftp://", "ftps://")):
                    host = urlparse(href).hostname or ""
                    if host and "eyedex.org" not in host:
                        direct = href
                        break
            if not direct:
                continue
            filename = httpx.URL(direct).path.rstrip("/").rsplit("/", 1)[-1] or direct.rstrip("/").rsplit("/", 1)[-1]
            text = " ".join(c.get_text(" ", strip=True) for c in cells)
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else None
            if allowed and ext not in allowed:
                continue
            results.append(Candidate(provider=self.name, filename=filename, url=direct, extension=ext, size=parse_size(text), metadata={"row": text}).normalize())

        if not results:
            for anchor in soup.find_all("a", href=True):
                href = anchor["href"]
                if not href.startswith(("http://", "https://", "ftp://", "ftps://")):
                    continue
                host = urlparse(href).hostname or ""
                if "eyedex.org" in host:
                    continue
                filename = urlparse(href).path.rstrip("/").rsplit("/", 1)[-1]
                if not filename:
                    continue
                ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else None
                if allowed and ext not in allowed:
                    continue
                results.append(Candidate(provider=self.name, filename=filename, url=href, extension=ext).normalize())
        return results[: min(request.limit, self.config.max_results)]

from __future__ import annotations

import re
from urllib.parse import unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from odrclone.providers.base import ProviderError, SearchProvider
from odrclone.schemas import Candidate, SearchRequest


class MMNTProvider(SearchProvider):
    name = "mmnt"

    async def search(self, request: SearchRequest) -> list[Candidate]:
        headers = {"User-Agent": self.config.user_agent, "Accept": "text/html,application/xhtml+xml"}
        attempts = [(self.config.search_url, {"q": request.query}), (urljoin(self.config.base_url, "/"), {"search": request.query})]
        html = None
        last_error = None
        response = None
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds, headers=headers, follow_redirects=True) as client:
            for url, params in attempts:
                try:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    if request.query.lower() in response.text.lower() or "/db/" in response.text:
                        html = response.text
                        break
                except httpx.HTTPError as exc:
                    last_error = exc
        if html is None:
            if last_error:
                raise ProviderError(str(last_error))
            return []

        soup = BeautifulSoup(html, "html.parser")
        allowed = {x.lower().lstrip(".") for x in request.extensions}
        page_text = soup.get_text(" ", strip=True)
        ftp_urls = set(re.findall(r"ftp://[^\s\"'<>]+", page_text, flags=re.I))
        for anchor in soup.find_all("a", href=True):
            href = unquote(anchor["href"])
            if href.startswith("ftp://"):
                ftp_urls.add(href)
            if response is not None and "/db/" in str(response.url) and not href.startswith(("http://", "https://", "ftp://", "#", "/")):
                heading = soup.find(["h1", "title"])
                if heading:
                    match = re.search(r"ftp://([^\s/]+)(/[^\s]*)?", heading.get_text(" ", strip=True))
                    if match:
                        base = f"ftp://{match.group(1)}{match.group(2) or '/'}"
                        ftp_urls.add(base.rstrip("/") + "/" + href.lstrip("/"))
        query = request.query.lower()
        results: list[Candidate] = []
        for url in ftp_urls:
            filename = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
            if not filename or (query not in unquote(filename).lower() and query not in unquote(url).lower()):
                continue
            filename = unquote(filename)
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else None
            if allowed and ext not in allowed:
                continue
            results.append(Candidate(provider=self.name, filename=filename, url=url, extension=ext).normalize())
        return results[: min(request.limit, self.config.max_results)]

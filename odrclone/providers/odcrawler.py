from __future__ import annotations

import httpx

from odrclone.providers.base import ProviderError, SearchProvider
from odrclone.schemas import Candidate, SearchRequest


class ODCrawlerProvider(SearchProvider):
    name = "odcrawler"

    async def search(self, request: SearchRequest) -> list[Candidate]:
        body = {
            "size": min(request.limit, self.config.max_results),
            "from": 0,
            "highlight": {"fields": {"url": {}, "filename": {}}},
            "query": {"bool": {"should": [{"match_phrase": {"filename": request.query}}, {"match_phrase": {"url": request.query}}], "minimum_should_match": 1}},
        }
        headers = {"User-Agent": self.config.user_agent, "Origin": "https://odcrawler.xyz", "Referer": "https://odcrawler.xyz/", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds, headers=headers) as client:
                response = await client.post(self.config.search_url, json=body)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(str(exc)) from exc

        results: list[Candidate] = []
        allowed = {x.lower().lstrip(".") for x in request.extensions}
        for hit in data.get("hits", {}).get("hits", []):
            src = hit.get("_source", {})
            url = src.get("url")
            filename = src.get("filename") or (url.rsplit("/", 1)[-1] if url else "")
            ext_raw = src.get("extension") or (filename.rsplit(".", 1)[-1] if "." in filename else "")
            ext = str(ext_raw).lower()
            if not url or not filename or (allowed and ext not in allowed):
                continue
            size = src.get("size")
            try:
                size = int(size) if size is not None else None
            except (TypeError, ValueError):
                size = None
            results.append(Candidate(provider=self.name, filename=filename, url=url, extension=ext or None, size=size, score=float(hit.get("_score") or 0.0), metadata={"index_score": hit.get("_score"), "source": src}).normalize())
        return results

    async def batch_alive(self, candidates: list[Candidate]) -> list[Candidate]:
        if not candidates or not self.config.batch_alive_checks:
            return candidates
        headers = {"User-Agent": self.config.user_agent, "Origin": "https://odcrawler.xyz", "Referer": "https://odcrawler.xyz/", "Content-Type": "application/json"}
        urls = [c.url for c in candidates[:40]]
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds, headers=headers) as client:
                response = await client.post(self.config.alive_url, json={"urls": urls})
                response.raise_for_status()
                data = response.json()
        except Exception:
            return candidates
        state: dict[str, bool] = {}
        if isinstance(data, dict):
            payload = data.get("results", data)
            if isinstance(payload, dict):
                for url, value in payload.items():
                    if isinstance(value, bool):
                        state[url] = value
                    elif isinstance(value, dict):
                        state[url] = bool(value.get("alive", value.get("ok", False)))
            elif isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict) and item.get("url"):
                        state[item["url"]] = bool(item.get("alive", item.get("ok", False)))
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("url"):
                    state[item["url"]] = bool(item.get("alive", item.get("ok", False)))
        for candidate in candidates:
            if candidate.url in state:
                candidate.alive = state[candidate.url]
        return candidates

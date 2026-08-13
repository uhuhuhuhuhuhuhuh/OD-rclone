from __future__ import annotations

import asyncio
import re

from odrclone.providers.base import SearchProvider
from odrclone.providers.odcrawler import ODCrawlerProvider
from odrclone.schemas import Candidate, SearchRequest, SearchResponse
from odrclone.search.ranking import score_candidate


class SearchCoordinator:
    def __init__(self, providers: list[SearchProvider]):
        self.providers = {p.name: p for p in providers}

    async def search(self, request: SearchRequest) -> SearchResponse:
        selected = [p for p in self.providers.values() if p.config.enabled and (not request.providers or p.name in request.providers)]
        tasks = {p.name: asyncio.create_task(p.search(request)) for p in selected}
        errors: dict[str, str] = {}
        merged: list[Candidate] = []
        for name, task in tasks.items():
            try:
                items = await task
                if isinstance(self.providers[name], ODCrawlerProvider):
                    items = await self.providers[name].batch_alive(items)
                merged.extend(items)
            except Exception as exc:
                errors[name] = str(exc)

        if request.regex:
            try:
                rx = re.compile(request.regex, re.I)
                merged = [c for c in merged if rx.search(c.filename)]
            except re.error as exc:
                errors["regex"] = str(exc)
        if request.min_size is not None:
            merged = [c for c in merged if c.size is None or c.size >= request.min_size]
        if request.max_size is not None:
            merged = [c for c in merged if c.size is None or c.size <= request.max_size]

        if request.validate_results:
            semaphore = asyncio.Semaphore(12)

            async def validate(candidate: Candidate):
                async with semaphore:
                    try:
                        return await self.providers[candidate.provider].validate(candidate)
                    except Exception:
                        return candidate

            merged = await asyncio.gather(*(validate(candidate) for candidate in merged))
            merged = [candidate for candidate in merged if candidate.alive is not False]

        by_key: dict[tuple, Candidate] = {}
        for candidate in merged:
            candidate.normalize()
            key = (candidate.url,) if candidate.url else (candidate.filename.lower(), candidate.size)
            if key not in by_key or candidate.score > by_key[key].score:
                by_key[key] = candidate
        merged = list(by_key.values())
        for candidate in merged:
            candidate.score = score_candidate(candidate, request)
        merged.sort(key=lambda candidate: candidate.score, reverse=True)
        return SearchResponse(query=request.query, results=merged[: request.limit], provider_errors=errors)

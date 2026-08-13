from __future__ import annotations

import re

from odrclone.schemas import SearchRequest


def safe_component(text: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text).strip(" .")
    return text[:180] or "Unknown"


def query_for_missing(kind: str, item: dict) -> tuple[str | None, str | None]:
    kind = kind.lower()
    if kind == "sonarr":
        series = item.get("series") or {}
        title = series.get("title") or item.get("seriesTitle") or item.get("title")
        season = item.get("seasonNumber")
        episode = item.get("episodeNumber")
        if not title or season is None or episode is None:
            return None, None
        query = f"{title} S{int(season):02d}E{int(episode):02d}"
        return query, f"/TV/{safe_component(str(title))}/Season {int(season):02d}"
    movie = item.get("movie") or item
    title = movie.get("title") or item.get("title")
    year = movie.get("year") or item.get("year")
    if not title:
        return None, None
    query = f"{title} {year}" if year else str(title)
    folder = f"{safe_component(str(title))} ({year})" if year else safe_component(str(title))
    return query, f"/Movies/{folder}"


async def find_candidates_for_missing(state, kind: str, missing_payload: dict, request):
    records = missing_payload.get("records", missing_payload if isinstance(missing_payload, list) else [])
    output = []
    for item in list(records)[: request.limit]:
        query, virtual_dir = query_for_missing(kind, item)
        if not query:
            output.append({"item": item, "error": "could not derive title/episode query"})
            continue
        result = await state.search.search(SearchRequest(query=query, media_type="tv" if kind == "sonarr" else "movie", extensions=request.extensions, validate=request.validate_results, limit=50))
        candidate = next((candidate for candidate in result.results if candidate.alive is not False and candidate.score >= request.min_score), None)
        output.append({"item": item, "query": query, "virtual_dir": virtual_dir, "candidate": candidate, "errors": result.provider_errors})
    return output

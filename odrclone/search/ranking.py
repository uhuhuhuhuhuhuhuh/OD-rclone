from __future__ import annotations

import re

from odrclone.schemas import Candidate, SearchRequest
from odrclone.search.media_parser import parse_media_name


def score_candidate(candidate: Candidate, request: SearchRequest) -> float:
    name = candidate.filename.lower()
    query_tokens = [token for token in re.split(r"[^a-z0-9]+", request.query.lower()) if len(token) > 1]
    score = candidate.score + sum(1 for token in query_tokens if token in name) * 8
    parsed = parse_media_name(candidate.filename)
    requested = parse_media_name(request.query)
    if requested.season is not None and requested.episode is not None:
        if parsed.season == requested.season and parsed.episode == requested.episode:
            score += 100
        elif parsed.season is not None or parsed.episode is not None:
            score -= 200
    if requested.year and parsed.year:
        score += 30 if requested.year == parsed.year else -80
    if parsed.sample or parsed.trailer:
        score -= 500
    if candidate.alive is True:
        score += 20
    elif candidate.alive is False:
        score -= 1000
    if candidate.range_supported is True:
        score += 10
    if candidate.size:
        if request.min_size and candidate.size < request.min_size:
            score -= 1000
        if request.max_size and candidate.size > request.max_size:
            score -= 1000
    return score

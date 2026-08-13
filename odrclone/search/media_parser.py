from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ParsedMedia:
    season: int | None = None
    episode: int | None = None
    year: int | None = None
    resolution: str | None = None
    codec: str | None = None
    source: str | None = None
    hdr: bool = False
    sample: bool = False
    trailer: bool = False


_EPISODE_PATTERNS = [re.compile(r"(?i)\bS(?P<s>\d{1,2})E(?P<e>\d{1,3})\b"), re.compile(r"(?i)\b(?P<s>\d{1,2})x(?P<e>\d{1,3})\b")]


def parse_media_name(name: str) -> ParsedMedia:
    normalized = name.replace("_", " ").replace(".", " ")
    parsed = ParsedMedia()
    for pattern in _EPISODE_PATTERNS:
        match = pattern.search(normalized)
        if match:
            parsed.season = int(match.group("s"))
            parsed.episode = int(match.group("e"))
            break
    years = re.findall(r"\b(?:19|20)\d{2}\b", normalized)
    parsed.year = int(years[-1]) if years else None
    res = re.search(r"(?i)\b(2160p|1080p|720p|480p)\b", normalized)
    parsed.resolution = res.group(1).lower() if res else None
    codec = re.search(r"(?i)\b(x265|h\.?265|hevc|x264|h\.?264|avc|av1)\b", normalized)
    parsed.codec = codec.group(1).lower().replace(".", "") if codec else None
    source = re.search(r"(?i)\b(WEB[- .]?DL|WEBRip|BluRay|BDRip|HDTV|DVDRip)\b", normalized)
    parsed.source = source.group(1).lower().replace(" ", "").replace(".", "") if source else None
    parsed.hdr = bool(re.search(r"(?i)\b(HDR10\+?|HDR|DV|Dolby[ .]?Vision)\b", normalized))
    parsed.sample = bool(re.search(r"(?i)(^|[ ._-])sample([ ._-]|$)", name))
    parsed.trailer = bool(re.search(r"(?i)(^|[ ._-])trailer([ ._-]|$)", name))
    return parsed

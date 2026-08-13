from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


def parse_range_header(value: str | None, size: int) -> ByteRange | None:
    if not value:
        return None
    if not value.lower().startswith("bytes="):
        raise ValueError("unsupported range unit")
    raw = value.split("=", 1)[1].strip()
    if "," in raw:
        raise ValueError("multiple ranges are not supported")
    start_s, end_s = raw.split("-", 1)
    if not start_s:
        suffix = int(end_s)
        if suffix <= 0:
            raise ValueError("invalid suffix range")
        start = max(size - suffix, 0)
        return ByteRange(start, size - 1)
    start = int(start_s)
    if start >= size:
        raise IndexError("range not satisfiable")
    end = int(end_s) if end_s else size - 1
    end = min(end, size - 1)
    if end < start:
        raise ValueError("invalid range")
    return ByteRange(start, end)

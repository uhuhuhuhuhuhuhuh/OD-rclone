from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field


class Candidate(BaseModel):
    provider: str
    filename: str
    url: str
    extension: str | None = None
    size: int | None = None
    host: str | None = None
    score: float = 0.0
    alive: bool | None = None
    range_supported: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def normalize(self) -> "Candidate":
        self.filename = self.filename.strip().replace("\\", "_").replace("/", "_")
        if not self.host:
            self.host = urlparse(self.url).hostname
        if not self.extension and "." in self.filename:
            self.extension = self.filename.rsplit(".", 1)[-1].lower()
        return self


class SearchRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    query: str
    media_type: str | None = None
    extensions: list[str] = Field(default_factory=list)
    min_size: int | None = None
    max_size: int | None = None
    regex: str | None = None
    providers: list[str] = Field(default_factory=list)
    validate_results: bool = Field(default=False, alias="validate")
    limit: int = 200


class SearchResponse(BaseModel):
    query: str
    results: list[Candidate]
    provider_errors: dict[str, str] = Field(default_factory=dict)


class VirtualizeRequest(BaseModel):
    candidate: Candidate
    virtual_path: str | None = None
    media_type: str | None = None
    cache_mode: str | None = None


class DownloadRequest(BaseModel):
    virtual_file_id: int
    target_directory: str | None = None
    servarr: str | None = None


class ServarrScanRequest(BaseModel):
    path: str
    download_client_id: str = "od-rclone"
    import_mode: str = "Move"


class ServarrAutofillRequest(BaseModel):
    limit: int = 10
    download: bool = False
    validate_results: bool = True
    extensions: list[str] = Field(default_factory=lambda: ["mkv", "mp4", "m4v", "avi", "ts", "m2ts"])
    min_score: float = 20.0

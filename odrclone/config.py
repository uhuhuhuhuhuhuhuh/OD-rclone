from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    enabled: bool = True
    timeout_seconds: float = 20.0
    priority: int = 100
    max_results: int = 200
    user_agent: str = "OD-rclone/0.1 (+https://github.com/uhuhuhuhuhuhuhuh/OD-rclone)"


class ODCrawlerConfig(ProviderConfig):
    search_url: str = "https://search.odcrawler.xyz/elastic/links/_search"
    alive_url: str = "https://odcrawler.xyz/.netlify/functions/checkLinkAlive"
    batch_alive_checks: bool = True


class EyeDexConfig(ProviderConfig):
    base_url: str = "https://www.eyedex.org"


class MMNTConfig(ProviderConfig):
    base_url: str = "https://www.mmnt.net"
    search_url: str = "https://www.mmnt.net"


class CacheConfig(BaseModel):
    directory: str = "./data/cache"
    block_size: int = 8 * 1024 * 1024
    read_ahead_blocks: int = 4
    max_bytes: int = 100 * 1024**3
    min_free_bytes: int = 5 * 1024**3
    default_mode: str = "TEMP"


class DownloadConfig(BaseModel):
    directory: str = "./data/downloads"
    backend: str = "native"
    aria2_rpc_url: str = "http://127.0.0.1:6800/jsonrpc"
    aria2_secret: str | None = None
    max_concurrent: int = 2


class ServarrEndpoint(BaseModel):
    enabled: bool = False
    url: str = ""
    api_key: str = ""
    import_mode: str = "Move"


class AuthConfig(BaseModel):
    api_token: str | None = None
    webdav_username: str | None = None
    webdav_password: str | None = None


class Settings(BaseModel):
    bind: str = "0.0.0.0"
    port: int = 8008
    database_url: str = "sqlite:///./data/odrclone.db"
    virtual_root: str = "/"
    cache: CacheConfig = Field(default_factory=CacheConfig)
    downloads: DownloadConfig = Field(default_factory=DownloadConfig)
    odcrawler: ODCrawlerConfig = Field(default_factory=ODCrawlerConfig)
    eyedex: EyeDexConfig = Field(default_factory=EyeDexConfig)
    mmnt: MMNTConfig = Field(default_factory=MMNTConfig)
    sonarr: ServarrEndpoint = Field(default_factory=ServarrEndpoint)
    radarr: ServarrEndpoint = Field(default_factory=ServarrEndpoint)
    auth: AuthConfig = Field(default_factory=AuthConfig)

    @classmethod
    def load(cls, path: str | None = None) -> "Settings":
        config_path = Path(path or os.getenv("ODRCLONE_CONFIG", "./config.yml"))
        data: dict[str, Any] = {}
        if config_path.exists():
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        env_overrides = {
            "bind": os.getenv("ODRCLONE_BIND"),
            "port": os.getenv("ODRCLONE_PORT"),
            "database_url": os.getenv("ODRCLONE_DATABASE_URL"),
        }
        for key, value in env_overrides.items():
            if value is not None:
                data[key] = int(value) if key == "port" else value
        return cls.model_validate(data)

    def ensure_directories(self) -> None:
        Path(self.cache.directory).mkdir(parents=True, exist_ok=True)
        Path(self.downloads.directory).mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///./"):
            Path(self.database_url.removeprefix("sqlite:///./")).parent.mkdir(parents=True, exist_ok=True)

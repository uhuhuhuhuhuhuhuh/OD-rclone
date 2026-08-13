from __future__ import annotations

from dataclasses import dataclass

import uvicorn
from fastapi import FastAPI

from odrclone.api.router import create_api_router
from odrclone.config import Settings
from odrclone.database import Database
from odrclone.downloads.manager import DownloadManager
from odrclone.newznab import create_newznab_router
from odrclone.providers.eyedex import EyeDexProvider
from odrclone.providers.mmnt import MMNTProvider
from odrclone.providers.odcrawler import ODCrawlerProvider
from odrclone.sabnzbd import create_sabnzbd_router
from odrclone.search.coordinator import SearchCoordinator
from odrclone.servarr.client import ServarrClient
from odrclone.vfs.cache import SparseCache
from odrclone.vfs.catalog import Catalog
from odrclone.webdav.router import create_webdav_router
from odrclone.webui.router import create_webui_router


@dataclass
class AppState:
    settings: Settings
    db: Database
    catalog: Catalog
    cache: SparseCache
    search: SearchCoordinator
    downloads: DownloadManager
    servarr: dict[str, ServarrClient]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()
    settings.ensure_directories()
    db = Database(settings.database_url)
    db.create_all()
    catalog = Catalog(db, settings.cache.default_mode)
    cache = SparseCache(db, settings.cache.directory, settings.cache.block_size, settings.cache.read_ahead_blocks, settings.cache.max_bytes, settings.cache.min_free_bytes)
    providers = [ODCrawlerProvider(settings.odcrawler), EyeDexProvider(settings.eyedex), MMNTProvider(settings.mmnt)]
    state = AppState(settings=settings, db=db, catalog=catalog, cache=cache, search=SearchCoordinator(providers), downloads=DownloadManager(db, settings.downloads), servarr={"sonarr": ServarrClient(settings.sonarr, "sonarr"), "radarr": ServarrClient(settings.radarr, "radarr")})
    app = FastAPI(title="OD-rclone", version="0.1.0")
    app.state.odrclone = state
    app.include_router(create_sabnzbd_router(state))
    app.include_router(create_newznab_router(state))
    app.include_router(create_webui_router())
    app.include_router(create_api_router(state))
    app.include_router(create_webdav_router(catalog, cache, settings.auth))
    return app


app = create_app()


def run() -> None:
    settings = Settings.load()
    uvicorn.run("odrclone.main:app", host=settings.bind, port=settings.port, reload=False)


if __name__ == "__main__":
    run()

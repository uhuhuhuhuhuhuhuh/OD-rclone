from __future__ import annotations

import posixpath
from pathlib import PurePosixPath
from urllib.parse import urlparse

from sqlalchemy import select

from odrclone.database import Database, Source, VirtualFile
from odrclone.schemas import Candidate


def normalize_virtual_path(path: str) -> str:
    path = "/" + path.lstrip("/")
    normalized = posixpath.normpath(path)
    if normalized.startswith("/../") or normalized == "/..":
        raise ValueError("invalid virtual path")
    return normalized


class Catalog:
    def __init__(self, db: Database, default_cache_mode: str = "TEMP"):
        self.db = db
        self.default_cache_mode = default_cache_mode

    def add_candidate(self, candidate: Candidate, virtual_path: str | None = None, media_type: str | None = None, cache_mode: str | None = None) -> VirtualFile:
        candidate.normalize()
        path = normalize_virtual_path(virtual_path or f"/Virtual/{candidate.filename}")
        with self.db.Session() as session:
            vf = session.scalar(select(VirtualFile).where(VirtualFile.virtual_path == path))
            if vf is None:
                vf = VirtualFile(virtual_path=path, filename=PurePosixPath(path).name, size=candidate.size, media_type=media_type, cache_mode=cache_mode or self.default_cache_mode)
                session.add(vf)
                session.flush()
            elif vf.size is None and candidate.size is not None:
                vf.size = candidate.size
            exists = session.scalar(select(Source).where(Source.virtual_file_id == vf.id, Source.url == candidate.url))
            if exists is None:
                session.add(Source(virtual_file_id=vf.id, provider=candidate.provider, url=candidate.url, host=candidate.host or urlparse(candidate.url).hostname, size=candidate.size, range_supported=candidate.range_supported, alive=candidate.alive, score=candidate.score))
            session.commit()
            session.refresh(vf)
            _ = list(vf.sources)
            return vf

    def get_file_by_path(self, path: str) -> VirtualFile | None:
        path = normalize_virtual_path(path)
        with self.db.Session() as session:
            vf = session.scalar(select(VirtualFile).where(VirtualFile.virtual_path == path))
            if vf:
                _ = list(vf.sources)
            return vf

    def get_file(self, file_id: int) -> VirtualFile | None:
        with self.db.Session() as session:
            vf = session.get(VirtualFile, file_id)
            if vf:
                _ = list(vf.sources)
            return vf

    def list_files(self) -> list[VirtualFile]:
        with self.db.Session() as session:
            files = list(session.scalars(select(VirtualFile).order_by(VirtualFile.virtual_path)))
            for vf in files:
                _ = list(vf.sources)
            return files

    def list_directory(self, path: str) -> tuple[list[str], list[VirtualFile]]:
        path = normalize_virtual_path(path).rstrip("/") or "/"
        prefix = "/" if path == "/" else path + "/"
        dirs: set[str] = set()
        files: list[VirtualFile] = []
        for vf in self.list_files():
            if not vf.virtual_path.startswith(prefix):
                continue
            remainder = vf.virtual_path[len(prefix):]
            if "/" in remainder:
                dirs.add(remainder.split("/", 1)[0])
            elif remainder:
                files.append(vf)
        return sorted(dirs, key=str.lower), files

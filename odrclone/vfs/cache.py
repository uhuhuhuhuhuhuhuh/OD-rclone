from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from odrclone.database import CacheBlock, Database, HostHealth, Source, VirtualFile, utcnow
from odrclone.net import ftp_fetch_range


class SourceUnavailable(RuntimeError):
    pass


class SparseCache:
    def __init__(self, db: Database, directory: str, block_size: int, read_ahead_blocks: int = 4, max_bytes: int = 100 * 1024**3, min_free_bytes: int = 5 * 1024**3):
        self.db = db
        self.root = Path(directory)
        self.block_size = block_size
        self.read_ahead_blocks = read_ahead_blocks
        self.max_bytes = max_bytes
        self.min_free_bytes = min_free_bytes
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[tuple[int, int], asyncio.Lock] = {}

    def _block_path(self, file_id: int, index: int) -> Path:
        path = self.root / str(file_id)
        path.mkdir(parents=True, exist_ok=True)
        return path / f"{index:016d}.blk"

    def cached_bytes(self, file_id: int) -> int:
        with self.db.Session() as session:
            return sum(x.bytes_present for x in session.scalars(select(CacheBlock).where(CacheBlock.virtual_file_id == file_id)))

    def _choose_sources(self, file_id: int) -> list[Source]:
        with self.db.Session() as session:
            sources = list(session.scalars(select(Source).where(Source.virtual_file_id == file_id).order_by(Source.alive.desc(), Source.score.desc())))
            for source in sources:
                session.expunge(source)
            return sources

    async def ensure_block(self, vf: VirtualFile, block_index: int) -> Path:
        key = (vf.id, block_index)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            path = self._block_path(vf.id, block_index)
            start = block_index * self.block_size
            expected = self.block_size if vf.size is None else min(self.block_size, max(vf.size - start, 0))
            if expected <= 0:
                raise IndexError("block beyond end of file")
            if path.exists() and path.stat().st_size == expected:
                return path
            end = start + expected - 1
            errors: list[str] = []
            for source in self._choose_sources(vf.id):
                if source.alive is False:
                    continue
                try:
                    await self._fetch_range(source.url, start, end, path)
                    if path.stat().st_size != expected:
                        raise SourceUnavailable(f"short block: expected {expected}, got {path.stat().st_size}")
                    with self.db.Session() as session:
                        row = session.scalar(select(CacheBlock).where(CacheBlock.virtual_file_id == vf.id, CacheBlock.block_index == block_index))
                        if row is None:
                            row = CacheBlock(virtual_file_id=vf.id, block_index=block_index, bytes_present=expected, path=str(path))
                            session.add(row)
                        else:
                            row.bytes_present = expected
                            row.path = str(path)
                        src = session.get(Source, source.id)
                        if src:
                            src.alive = True
                            src.range_supported = True if start > 0 else src.range_supported
                        session.commit()
                    self._record_host(source.host, True, True)
                    self.enforce_limits(exclude_file_id=vf.id if vf.pinned else None)
                    return path
                except Exception as exc:
                    errors.append(f"{source.host or source.url}: {exc}")
                    with self.db.Session() as session:
                        src = session.get(Source, source.id)
                        if src:
                            src.alive = False
                        session.commit()
                    self._record_host(source.host, False, None)
                    path.unlink(missing_ok=True)
            raise SourceUnavailable("; ".join(errors) or "no usable source")

    async def _fetch_range(self, url: str, start: int, end: int, target: Path) -> None:
        scheme = urlparse(url).scheme.lower()
        if scheme in {"ftp", "ftps"}:
            tmp = target.with_suffix(".part")
            tmp.unlink(missing_ok=True)
            await asyncio.to_thread(ftp_fetch_range, url, start, end, str(tmp), 90.0)
            os.replace(tmp, target)
            return
        headers = {"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity", "User-Agent": "OD-rclone/0.1"}
        timeout = httpx.Timeout(30.0, read=90.0)
        tmp = target.with_suffix(".part")
        tmp.unlink(missing_ok=True)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", url, headers=headers) as response:
                if response.status_code not in (200, 206):
                    raise SourceUnavailable(f"HTTP {response.status_code}")
                if start > 0 and response.status_code != 206:
                    raise SourceUnavailable("origin does not honor byte ranges")
                remaining = end - start + 1
                with tmp.open("wb") as handle:
                    async for chunk in response.aiter_bytes(256 * 1024):
                        if not chunk:
                            continue
                        if len(chunk) > remaining:
                            chunk = chunk[:remaining]
                        handle.write(chunk)
                        remaining -= len(chunk)
                        if remaining <= 0:
                            break
        os.replace(tmp, target)

    async def iter_range(self, vf: VirtualFile, start: int, end: int):
        first = start // self.block_size
        last = end // self.block_size
        if vf.cache_mode.upper() in {"FULL_ON_PLAY", "PIN"} and start == 0:
            asyncio.create_task(self.prefetch_full(vf))
        for index in range(first, last + 1):
            path = await self.ensure_block(vf, index)
            block_start = index * self.block_size
            local_start = max(start - block_start, 0)
            local_end = min(end - block_start, path.stat().st_size - 1)
            with path.open("rb") as handle:
                handle.seek(local_start)
                remaining = local_end - local_start + 1
                while remaining > 0:
                    chunk = handle.read(min(256 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
            if vf.cache_mode.upper() == "REMOTE_ONLY":
                self._block_path(vf.id, index).unlink(missing_ok=True)
                with self.db.Session() as session:
                    row = session.scalar(select(CacheBlock).where(CacheBlock.virtual_file_id == vf.id, CacheBlock.block_index == index))
                    if row:
                        session.delete(row)
                        session.commit()
            if index == first and self.read_ahead_blocks > 0:
                for ahead in range(1, self.read_ahead_blocks + 1):
                    if vf.size is not None and (index + ahead) * self.block_size >= vf.size:
                        break
                    asyncio.create_task(self._safe_prefetch(vf, index + ahead))

    async def _safe_prefetch(self, vf: VirtualFile, index: int) -> None:
        try:
            await self.ensure_block(vf, index)
        except Exception:
            pass

    def _record_host(self, host: str | None, success: bool, range_supported: bool | None) -> None:
        if not host:
            return
        with self.db.Session() as session:
            row = session.scalar(select(HostHealth).where(HostHealth.host == host))
            if row is None:
                row = HostHealth(host=host)
                session.add(row)
            row.requests += 1
            if success:
                row.successes += 1
                row.last_success = utcnow()
            else:
                row.failures += 1
            if range_supported is not None:
                row.range_supported = range_supported
            session.commit()

    def total_cached_bytes(self) -> int:
        return sum(path.stat().st_size for path in self.root.glob("*/*.blk") if path.is_file())

    def enforce_limits(self, exclude_file_id: int | None = None) -> int:
        total = self.total_cached_bytes()
        free = shutil.disk_usage(self.root).free
        if total <= self.max_bytes and free >= self.min_free_bytes:
            return 0
        with self.db.Session() as session:
            blocks = list(session.scalars(select(CacheBlock).order_by(CacheBlock.touched_at.asc())))
            pinned_ids = {vf.id for vf in session.scalars(select(VirtualFile).where(VirtualFile.pinned.is_(True)))}
            freed = 0
            for block in blocks:
                if block.virtual_file_id in pinned_ids or block.virtual_file_id == exclude_file_id:
                    continue
                path = Path(block.path)
                size = path.stat().st_size if path.exists() else block.bytes_present
                path.unlink(missing_ok=True)
                session.delete(block)
                freed += size
                total -= size
                free += size
                if total <= self.max_bytes and free >= self.min_free_bytes:
                    break
            session.commit()
            return freed

    async def prefetch_full(self, vf: VirtualFile) -> None:
        if vf.size is None:
            return
        blocks = (vf.size + self.block_size - 1) // self.block_size
        for index in range(blocks):
            try:
                await self.ensure_block(vf, index)
            except Exception:
                return

    def clear_file(self, file_id: int) -> int:
        path = self.root / str(file_id)
        freed = 0
        if path.exists():
            freed = sum(item.stat().st_size for item in path.glob("*.blk") if item.is_file())
            shutil.rmtree(path, ignore_errors=True)
        with self.db.Session() as session:
            for row in session.scalars(select(CacheBlock).where(CacheBlock.virtual_file_id == file_id)):
                session.delete(row)
            session.commit()
        return freed

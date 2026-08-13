from __future__ import annotations

import asyncio
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from odrclone.database import Database, DownloadJob
from odrclone.net import ftp_download


class NativeDownloader:
    def __init__(self, db: Database, max_concurrent: int = 2):
        self.db = db
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.tasks: dict[int, asyncio.Task] = {}

    def enqueue(self, job: DownloadJob) -> None:
        self.tasks[job.id] = asyncio.create_task(self._run(job.id))

    async def _run(self, job_id: int) -> None:
        async with self.semaphore:
            with self.db.Session() as session:
                job = session.get(DownloadJob, job_id)
                if not job:
                    return
                job.status = "downloading"
                session.commit()
                url, target = job.url, Path(job.target_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_suffix(target.suffix + ".part")
            resume = part.stat().st_size if part.exists() else 0
            started = time.monotonic()
            try:
                if urlparse(url).scheme.lower() in {"ftp", "ftps"}:
                    def progress(done: int, total: int | None) -> None:
                        elapsed = max(time.monotonic() - started, 0.01)
                        with self.db.Session() as session:
                            row = session.get(DownloadJob, job_id)
                            if row:
                                row.bytes_done = done
                                row.bytes_total = total
                                row.speed_bps = max(done - resume, 0) / elapsed
                                session.commit()
                    await asyncio.to_thread(ftp_download, url, str(part), resume, 90.0, progress)
                else:
                    await self._http_download(job_id, url, part, resume, started)
                part.replace(target)
                with self.db.Session() as session:
                    row = session.get(DownloadJob, job_id)
                    if row:
                        row.status = "complete"
                        row.bytes_done = target.stat().st_size
                        row.bytes_total = target.stat().st_size
                        session.commit()
            except asyncio.CancelledError:
                with self.db.Session() as session:
                    row = session.get(DownloadJob, job_id)
                    if row:
                        row.status = "cancelled"
                        session.commit()
                raise
            except Exception as exc:
                with self.db.Session() as session:
                    row = session.get(DownloadJob, job_id)
                    if row:
                        row.status = "failed"
                        row.error = str(exc)
                        session.commit()

    async def _http_download(self, job_id: int, url: str, part: Path, resume: int, started: float) -> tuple[int, int | None]:
        headers = {"User-Agent": "OD-rclone/0.1", "Accept-Encoding": "identity"}
        if resume:
            headers["Range"] = f"bytes={resume}-"
        done = resume
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=None), follow_redirects=True) as client:
            async with client.stream("GET", url, headers=headers) as response:
                if response.status_code >= 400:
                    raise RuntimeError(f"HTTP {response.status_code}")
                if resume and response.status_code != 206:
                    resume = 0
                    done = 0
                    part.unlink(missing_ok=True)
                total = None
                content_range = response.headers.get("content-range", "")
                if "/" in content_range and content_range.rsplit("/", 1)[-1].isdigit():
                    total = int(content_range.rsplit("/", 1)[-1])
                elif response.headers.get("content-length", "").isdigit():
                    total = int(response.headers["content-length"]) + resume
                mode = "ab" if resume else "wb"
                with part.open(mode) as handle:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        handle.write(chunk)
                        done += len(chunk)
                        elapsed = max(time.monotonic() - started, 0.01)
                        with self.db.Session() as session:
                            row = session.get(DownloadJob, job_id)
                            if row:
                                row.bytes_done = done
                                row.bytes_total = total
                                row.speed_bps = max(done - resume, 0) / elapsed
                                session.commit()
        return done, total

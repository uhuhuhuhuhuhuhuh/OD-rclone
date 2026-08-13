from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from odrclone.config import DownloadConfig
from odrclone.database import Database, DownloadJob
from odrclone.downloads.aria2 import Aria2Client
from odrclone.downloads.native import NativeDownloader


class DownloadManager:
    def __init__(self, db: Database, config: DownloadConfig):
        self.db = db
        self.config = config
        self.native = NativeDownloader(db, config.max_concurrent)
        self.aria2 = Aria2Client(config.aria2_rpc_url, config.aria2_secret)

    async def create(self, vf, source, target_directory: str | None = None) -> DownloadJob:
        target_dir = Path(target_directory or self.config.directory)
        target = target_dir / vf.filename
        with self.db.Session() as session:
            job = DownloadJob(virtual_file_id=vf.id, filename=vf.filename, url=source.url, target_path=str(target), bytes_total=vf.size)
            session.add(job)
            session.commit()
            session.refresh(job)
        if self.config.backend.lower() == "aria2":
            gid = await self.aria2.add_uri(source.url, str(target_dir), vf.filename)
            with self.db.Session() as session:
                row = session.get(DownloadJob, job.id)
                row.status = "downloading"
                row.external_id = gid
                session.commit()
        else:
            self.native.enqueue(job)
        return job

    def list(self) -> list[DownloadJob]:
        with self.db.Session() as session:
            return list(session.scalars(select(DownloadJob).order_by(DownloadJob.id.desc())))

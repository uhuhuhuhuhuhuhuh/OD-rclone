from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VirtualFile(Base):
    __tablename__ = "virtual_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    virtual_path: Mapped[str] = mapped_column(String(2048), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(1024))
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cache_mode: Mapped[str] = mapped_column(String(32), default="TEMP")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    sources: Mapped[list["Source"]] = relationship(back_populates="virtual_file", cascade="all, delete-orphan")


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("virtual_file_id", "url", name="uq_source_file_url"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    virtual_file_id: Mapped[int] = mapped_column(ForeignKey("virtual_files.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(Text)
    host: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    range_supported: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    alive: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    virtual_file: Mapped[VirtualFile] = relationship(back_populates="sources")


class CacheBlock(Base):
    __tablename__ = "cache_blocks"
    __table_args__ = (UniqueConstraint("virtual_file_id", "block_index", name="uq_cache_block"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    virtual_file_id: Mapped[int] = mapped_column(ForeignKey("virtual_files.id", ondelete="CASCADE"), index=True)
    block_index: Mapped[int] = mapped_column(Integer)
    bytes_present: Mapped[int] = mapped_column(Integer, default=0)
    path: Mapped[str] = mapped_column(Text)
    touched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DownloadJob(Base):
    __tablename__ = "download_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    virtual_file_id: Mapped[int | None] = mapped_column(ForeignKey("virtual_files.id", ondelete="SET NULL"), nullable=True)
    filename: Mapped[str] = mapped_column(String(1024))
    url: Mapped[str] = mapped_column(Text)
    target_path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    bytes_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes_done: Mapped[int] = mapped_column(Integer, default=0)
    speed_bps: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class HostHealth(Base):
    __tablename__ = "host_health"
    id: Mapped[int] = mapped_column(primary_key=True)
    host: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    successes: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    avg_ttfb_ms: Mapped[float] = mapped_column(Float, default=0.0)
    avg_speed_bps: Mapped[float] = mapped_column(Float, default=0.0)
    range_supported: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Database:
    def __init__(self, url: str):
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, connect_args=connect_args, future=True)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

from __future__ import annotations

import ftplib
from dataclasses import dataclass
from urllib.parse import unquote, urlparse


@dataclass
class FTPInfo:
    size: int | None
    range_supported: bool


def _connect(url: str, timeout: float = 30.0):
    p = urlparse(url)
    if p.scheme not in {"ftp", "ftps"}:
        raise ValueError("not an FTP URL")
    host = p.hostname
    if not host:
        raise ValueError("FTP URL has no host")
    port = p.port or (990 if p.scheme == "ftps" else 21)
    cls = ftplib.FTP_TLS if p.scheme == "ftps" else ftplib.FTP
    ftp = cls()
    ftp.connect(host, port, timeout=timeout)
    user = unquote(p.username) if p.username else "anonymous"
    password = unquote(p.password) if p.password else "od-rclone@example.invalid"
    ftp.login(user, password)
    if isinstance(ftp, ftplib.FTP_TLS):
        ftp.prot_p()
    return ftp, unquote(p.path)


def ftp_stat(url: str, timeout: float = 30.0) -> FTPInfo:
    ftp, path = _connect(url, timeout)
    try:
        size = None
        try:
            size = ftp.size(path)
        except ftplib.all_errors:
            pass
        range_supported = False
        try:
            response = ftp.sendcmd("REST 0")
            range_supported = str(response).startswith("350")
        except ftplib.all_errors:
            range_supported = False
        return FTPInfo(size=size, range_supported=range_supported)
    finally:
        try:
            ftp.quit()
        except ftplib.all_errors:
            ftp.close()


def ftp_fetch_range(url: str, start: int, end: int, target: str, timeout: float = 60.0) -> int:
    ftp, path = _connect(url, timeout)
    remaining = end - start + 1
    written = 0
    out = open(target, "wb")

    def callback(data: bytes):
        nonlocal remaining, written
        if remaining <= 0:
            return
        chunk = data[:remaining]
        out.write(chunk)
        written += len(chunk)
        remaining -= len(chunk)
        if remaining <= 0:
            raise StopIteration

    try:
        try:
            ftp.retrbinary(f"RETR {path}", callback, blocksize=256 * 1024, rest=start if start else None)
        except StopIteration:
            pass
        return written
    finally:
        out.close()
        try:
            ftp.quit()
        except ftplib.all_errors:
            ftp.close()


def ftp_download(url: str, target: str, resume: int = 0, timeout: float = 60.0, progress=None) -> tuple[int, int | None]:
    ftp, path = _connect(url, timeout)
    total = None
    try:
        try:
            total = ftp.size(path)
        except ftplib.all_errors:
            pass
        mode = "ab" if resume else "wb"
        done = resume
        with open(target, mode) as out:
            def callback(data: bytes):
                nonlocal done
                out.write(data)
                done += len(data)
                if progress:
                    progress(done, total)
            ftp.retrbinary(f"RETR {path}", callback, blocksize=1024 * 1024, rest=resume if resume else None)
        return done, total
    finally:
        try:
            ftp.quit()
        except ftplib.all_errors:
            ftp.close()

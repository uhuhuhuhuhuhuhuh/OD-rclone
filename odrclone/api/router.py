from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request, Response

from odrclone.database import DownloadJob
from odrclone.schemas import DownloadRequest, SearchRequest, ServarrAutofillRequest, ServarrScanRequest, VirtualizeRequest
from odrclone.servarr.automation import find_candidates_for_missing
from odrclone.vfs.streamer import stream_virtual_file


def create_api_router(state):
    router = APIRouter(prefix="/api")

    def check_token(authorization: str | None):
        token = state.settings.auth.api_token
        if token and authorization != f"Bearer {token}":
            raise HTTPException(401, "invalid API token")

    @router.get("/health")
    async def health():
        return {"status": "ok", "version": "0.1.0", "providers": list(state.search.providers)}

    @router.post("/search")
    async def search(request: SearchRequest, authorization: str | None = Header(default=None)):
        check_token(authorization)
        return await state.search.search(request)

    @router.post("/virtualize")
    async def virtualize(request: VirtualizeRequest, authorization: str | None = Header(default=None)):
        check_token(authorization)
        vf = state.catalog.add_candidate(request.candidate, request.virtual_path, request.media_type, request.cache_mode)
        return serialize_file(state, vf)

    @router.get("/files")
    async def files(authorization: str | None = Header(default=None)):
        check_token(authorization)
        return [serialize_file(state, vf) for vf in state.catalog.list_files()]

    @router.get("/files/{file_id}")
    async def file_detail(file_id: int, authorization: str | None = Header(default=None)):
        check_token(authorization)
        vf = state.catalog.get_file(file_id)
        if not vf:
            raise HTTPException(404)
        return serialize_file(state, vf)

    @router.delete("/files/{file_id}/cache")
    async def clear_cache(file_id: int, authorization: str | None = Header(default=None)):
        check_token(authorization)
        return {"freed_bytes": state.cache.clear_file(file_id)}

    @router.post("/downloads")
    async def download(req: DownloadRequest, authorization: str | None = Header(default=None)):
        check_token(authorization)
        vf = state.catalog.get_file(req.virtual_file_id)
        if not vf or not vf.sources:
            raise HTTPException(404, "virtual file/source not found")
        source = sorted(vf.sources, key=lambda source: (source.alive is True, source.score), reverse=True)[0]
        job = await state.downloads.create(vf, source, req.target_directory)
        return serialize_job(job)

    @router.get("/downloads")
    async def downloads(authorization: str | None = Header(default=None)):
        check_token(authorization)
        return [serialize_job(job) for job in state.downloads.list()]

    @router.get("/servarr/{kind}/status")
    async def servarr_status(kind: str, authorization: str | None = Header(default=None)):
        check_token(authorization)
        client = state.servarr.get(kind)
        if not client or not client.config.enabled:
            raise HTTPException(400, f"{kind} not enabled")
        return await client.test()

    @router.get("/servarr/{kind}/missing")
    async def servarr_missing(kind: str, authorization: str | None = Header(default=None)):
        check_token(authorization)
        client = state.servarr.get(kind)
        if not client or not client.config.enabled:
            raise HTTPException(400, f"{kind} not enabled")
        return await client.missing()

    @router.post("/servarr/{kind}/scan")
    async def servarr_scan(kind: str, req: ServarrScanRequest, authorization: str | None = Header(default=None)):
        check_token(authorization)
        client = state.servarr.get(kind)
        if not client or not client.config.enabled:
            raise HTTPException(400, f"{kind} not enabled")
        return await client.downloaded_scan(req.path, req.download_client_id, req.import_mode)

    @router.post("/servarr/{kind}/autofill")
    async def servarr_autofill(kind: str, req: ServarrAutofillRequest, authorization: str | None = Header(default=None)):
        check_token(authorization)
        client = state.servarr.get(kind)
        if not client or not client.config.enabled:
            raise HTTPException(400, f"{kind} not enabled")
        missing = await client.missing(page_size=req.limit)
        matches = await find_candidates_for_missing(state, kind, missing, req)
        output = []
        for match in matches:
            candidate = match.get("candidate")
            row = {**match, "candidate": candidate.model_dump() if candidate else None}
            if req.download and candidate:
                virtual_path = match["virtual_dir"].rstrip("/") + "/" + candidate.filename
                vf = state.catalog.add_candidate(candidate, virtual_path, "tv" if kind == "sonarr" else "movie")
                source = sorted(vf.sources, key=lambda source: (source.alive is True, source.score), reverse=True)[0]
                job = await state.downloads.create(vf, source)
                asyncio.create_task(_import_when_complete(state, kind, job.id))
                row["virtual_file_id"] = vf.id
                row["download_job_id"] = job.id
            output.append(row)
        return {"kind": kind, "matches": output}

    @router.api_route("/stream/{path:path}", methods=["GET", "HEAD"])
    async def api_stream(request: Request, path: str):
        vf = state.catalog.get_file_by_path("/" + path)
        if not vf:
            raise HTTPException(404)
        if request.method == "HEAD":
            if vf.size is None:
                raise HTTPException(409)
            return Response(status_code=200, headers={"Content-Length": str(vf.size), "Accept-Ranges": "bytes"})
        return await stream_virtual_file(request, vf, state.cache)

    return router


async def _import_when_complete(state, kind: str, job_id: int) -> None:
    for _ in range(60 * 24 * 7):
        await asyncio.sleep(1)
        with state.db.Session() as session:
            job = session.get(DownloadJob, job_id)
            if not job:
                return
            status = job.status
            target = job.target_path
        if status == "complete":
            try:
                await state.servarr[kind].downloaded_scan(str(Path(target).parent), "od-rclone")
            except Exception:
                pass
            return
        if status in {"failed", "cancelled"}:
            return


def serialize_file(state, vf):
    return {"id": vf.id, "virtual_path": vf.virtual_path, "filename": vf.filename, "size": vf.size, "media_type": vf.media_type, "cache_mode": vf.cache_mode, "cached_bytes": state.cache.cached_bytes(vf.id), "sources": [{"id": source.id, "provider": source.provider, "host": source.host, "size": source.size, "alive": source.alive, "range_supported": source.range_supported, "score": source.score, "url": source.url} for source in vf.sources]}


def serialize_job(job):
    return {"id": job.id, "filename": job.filename, "target_path": job.target_path, "status": job.status, "bytes_total": job.bytes_total, "bytes_done": job.bytes_done, "speed_bps": job.speed_bps, "error": job.error, "external_id": job.external_id}

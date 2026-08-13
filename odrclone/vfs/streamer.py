from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from odrclone.vfs.cache import SparseCache
from odrclone.vfs.ranges import parse_range_header


async def stream_virtual_file(request: Request, vf, cache: SparseCache):
    if vf.size is None:
        raise HTTPException(409, "Virtual file size is unknown. Validate the source first.")
    try:
        byte_range = parse_range_header(request.headers.get("range"), vf.size)
    except IndexError:
        raise HTTPException(416, headers={"Content-Range": f"bytes */{vf.size}"})
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    start = byte_range.start if byte_range else 0
    end = byte_range.end if byte_range else vf.size - 1
    status = 206 if byte_range else 200
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1), "Content-Disposition": f'inline; filename="{vf.filename.replace(chr(34), "")}"', "ETag": f'W/"odrclone-{vf.id}-{vf.size}"'}
    if byte_range:
        headers["Content-Range"] = f"bytes {start}-{end}/{vf.size}"
    return StreamingResponse(cache.iter_range(vf, start, end), status_code=status, headers=headers, media_type="application/octet-stream")

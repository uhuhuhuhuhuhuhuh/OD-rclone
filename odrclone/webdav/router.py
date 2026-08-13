from __future__ import annotations

import base64
import hmac
import html
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response

from odrclone.vfs.catalog import normalize_virtual_path
from odrclone.vfs.streamer import stream_virtual_file


def _dav_response(href: str, display_name: str, is_dir: bool, size: int | None = None) -> str:
    resource_type = "<D:collection/>" if is_dir else ""
    length = "" if is_dir or size is None else f"<D:getcontentlength>{size}</D:getcontentlength>"
    return f"""<D:response><D:href>{html.escape(href)}</D:href><D:propstat><D:prop><D:displayname>{html.escape(display_name)}</D:displayname><D:resourcetype>{resource_type}</D:resourcetype>{length}</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>"""


def create_webdav_router(catalog, cache, auth=None):
    router = APIRouter(prefix="/webdav")

    def check_auth(request: Request):
        if not auth or not auth.webdav_username:
            return
        raw = request.headers.get("authorization", "")
        if not raw.startswith("Basic "):
            raise HTTPException(401, headers={"WWW-Authenticate": 'Basic realm="OD-rclone"'})
        try:
            userpass = base64.b64decode(raw[6:]).decode("utf-8")
            user, password = userpass.split(":", 1)
        except Exception:
            raise HTTPException(401, headers={"WWW-Authenticate": 'Basic realm="OD-rclone"'})
        if not (hmac.compare_digest(user, auth.webdav_username or "") and hmac.compare_digest(password, auth.webdav_password or "")):
            raise HTTPException(401, headers={"WWW-Authenticate": 'Basic realm="OD-rclone"'})

    @router.api_route("/{path:path}", methods=["OPTIONS", "PROPFIND", "GET", "HEAD"])
    @router.api_route("", methods=["OPTIONS", "PROPFIND", "GET", "HEAD"])
    async def webdav(request: Request, path: str = ""):
        check_auth(request)
        virtual_path = normalize_virtual_path(path)
        if request.method == "OPTIONS":
            return Response(status_code=200, headers={"DAV": "1", "Allow": "OPTIONS, PROPFIND, GET, HEAD"})
        vf = catalog.get_file_by_path(virtual_path)
        if request.method in ("GET", "HEAD") and vf:
            if request.method == "HEAD":
                if vf.size is None:
                    raise HTTPException(409, "unknown size")
                return Response(status_code=200, headers={"Content-Length": str(vf.size), "Accept-Ranges": "bytes", "ETag": f'W/"odrclone-{vf.id}-{vf.size}"'})
            return await stream_virtual_file(request, vf, cache)
        if request.method in ("GET", "HEAD"):
            dirs, files = catalog.list_directory(virtual_path)
            if not dirs and not files and virtual_path != "/":
                raise HTTPException(404)
            return Response("\n".join(dirs + [file.filename for file in files]), media_type="text/plain")
        if request.method == "PROPFIND":
            dirs, files = catalog.list_directory(virtual_path)
            if vf:
                entries = [_dav_response(request.url.path, vf.filename, False, vf.size)]
            else:
                if not dirs and not files and virtual_path != "/":
                    raise HTTPException(404)
                base_href = request.url.path.rstrip("/") + "/"
                name = virtual_path.rstrip("/").rsplit("/", 1)[-1] or "OD-rclone"
                entries = [_dav_response(base_href, name, True)]
                if request.headers.get("depth", "1") != "0":
                    for directory in dirs:
                        entries.append(_dav_response(base_href + quote(directory) + "/", directory, True))
                    for file in files:
                        entries.append(_dav_response(base_href + quote(file.filename), file.filename, False, file.size))
            xml = '<?xml version="1.0" encoding="utf-8"?><D:multistatus xmlns:D="DAV:">' + "".join(entries) + "</D:multistatus>"
            return Response(xml, status_code=207, media_type="application/xml")
        raise HTTPException(405)

    return router

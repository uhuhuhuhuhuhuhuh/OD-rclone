from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import quote
from xml.etree import ElementTree as ET

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from odrclone.schemas import Candidate, SearchRequest


NEWZNAB_NS = "http://www.newznab.com/DTD/2010/feeds/attributes/"
NZB_NS = "http://www.newzbin.com/DTD/2003/nzb"
ET.register_namespace("newznab", NEWZNAB_NS)


def create_newznab_router(state):
    router = APIRouter(prefix="/newznab")

    def valid_api_key(value: str | None) -> bool:
        configured = {
            credential
            for credential in (
                state.settings.auth.api_token,
                state.settings.auth.webdav_username,
                state.settings.auth.webdav_password,
            )
            if credential
        }
        if not configured:
            return True
        return bool(value) and value in configured

    def xml_response(root: ET.Element, status_code: int = 200) -> Response:
        payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return Response(payload, status_code=status_code, media_type="application/xml")

    def error_response(code: str, description: str, status_code: int = 200) -> Response:
        root = ET.Element("error", {"code": code, "description": description})
        return xml_response(root, status_code)

    def caps_response() -> Response:
        root = ET.Element("caps")
        ET.SubElement(root, "server", {"version": "1.0", "title": "OD-rclone"})
        ET.SubElement(root, "limits", {"max": "100", "default": "100"})

        searching = ET.SubElement(root, "searching")
        ET.SubElement(searching, "search", {"available": "yes", "supportedParams": "q"})
        ET.SubElement(
            searching,
            "tv-search",
            {"available": "yes", "supportedParams": "q,title,season,ep"},
        )
        ET.SubElement(
            searching,
            "movie-search",
            {"available": "yes", "supportedParams": "q"},
        )

        categories = ET.SubElement(root, "categories")
        movies = ET.SubElement(categories, "category", {"id": "2000", "name": "Movies"})
        ET.SubElement(movies, "subcat", {"id": "2040", "name": "Movies HD"})
        ET.SubElement(movies, "subcat", {"id": "2045", "name": "Movies UHD"})

        tv = ET.SubElement(categories, "category", {"id": "5000", "name": "TV"})
        ET.SubElement(tv, "subcat", {"id": "5040", "name": "TV HD"})
        ET.SubElement(tv, "subcat", {"id": "5045", "name": "TV UHD"})

        return xml_response(root)

    def build_query(request: Request, mode: str) -> str:
        params = request.query_params
        query = (params.get("q") or params.get("title") or "").strip()
        if mode == "tvsearch" and query:
            season = (params.get("season") or "").strip()
            episode = (params.get("ep") or "").strip()
            if season and episode and season.isdigit() and episode.isdigit():
                query = f"{query} S{int(season):02d}E{int(episode):02d}"
            elif season and season.isdigit():
                query = f"{query} S{int(season):02d}"
        return query

    def encode_candidate(candidate: Candidate) -> str:
        raw = json.dumps(candidate.model_dump(), separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def decode_candidate(token: str) -> Candidate:
        try:
            padded = token + "=" * (-len(token) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
            return Candidate.model_validate(data).normalize()
        except Exception as exc:
            raise HTTPException(400, "invalid OD-rclone Newznab token") from exc

    def feed_response(request: Request, mode: str, candidates: list[Candidate]) -> Response:
        rss = ET.Element("rss", {"version": "2.0"})
        channel = ET.SubElement(rss, "channel")
        ET.SubElement(channel, "title").text = "OD-rclone"
        ET.SubElement(channel, "description").text = "OD-rclone virtual open-directory index"
        ET.SubElement(channel, "link").text = str(request.base_url).rstrip("/") + "/newznab/api"
        ET.SubElement(
            channel,
            f"{{{NEWZNAB_NS}}}response",
            {"offset": request.query_params.get("offset", "0"), "total": str(len(candidates))},
        )

        category_id = "2000" if mode == "movie" else "5000"
        category_name = "Movies" if mode == "movie" else "TV"
        api_key = request.query_params.get("apikey") or ""
        now = format_datetime(datetime.now(timezone.utc))

        for candidate in candidates:
            token = encode_candidate(candidate)
            download_url = str(request.base_url).rstrip("/") + "/newznab/download/" + quote(token)
            if api_key:
                download_url += "?apikey=" + quote(api_key)

            item = ET.SubElement(channel, "item")
            ET.SubElement(item, "title").text = candidate.filename
            ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = "odrclone:" + token
            ET.SubElement(item, "link").text = download_url
            ET.SubElement(item, "pubDate").text = now
            ET.SubElement(item, "category").text = category_name
            ET.SubElement(item, "description").text = (
                f"Provider: {candidate.provider}; host: {candidate.host or 'unknown'}; score: {candidate.score:.2f}"
            )
            ET.SubElement(
                item,
                "enclosure",
                {
                    "url": download_url,
                    "length": str(int(candidate.size or 0)),
                    "type": "application/x-nzb",
                },
            )
            ET.SubElement(item, f"{{{NEWZNAB_NS}}}attr", {"name": "category", "value": category_id})
            ET.SubElement(
                item,
                f"{{{NEWZNAB_NS}}}attr",
                {"name": "size", "value": str(int(candidate.size or 0))},
            )

        return xml_response(rss)

    @router.get("/api")
    async def newznab_api(request: Request):
        mode = (request.query_params.get("t") or "search").lower()
        api_key = request.query_params.get("apikey")

        if not valid_api_key(api_key):
            return error_response("100", "Incorrect user credentials")

        if mode == "caps":
            return caps_response()

        if mode not in {"search", "tvsearch", "movie"}:
            return error_response("202", f"No such function: {mode}")

        query = build_query(request, mode)
        if not query:
            return feed_response(request, mode, [])

        try:
            limit = max(1, min(int(request.query_params.get("limit", "100")), 100))
        except ValueError:
            limit = 100

        extensions = ["mkv", "mp4", "m4v", "avi", "ts", "m2ts"]
        result = await state.search.search(
            SearchRequest(
                query=query,
                media_type="movie" if mode == "movie" else "tv",
                extensions=extensions,
                limit=limit,
            )
        )
        return feed_response(request, mode, result.results)

    @router.get("/download/{token}")
    async def download_nzb(token: str, request: Request):
        if not valid_api_key(request.query_params.get("apikey")):
            return error_response("100", "Incorrect user credentials")

        candidate = decode_candidate(token)
        payload = json.dumps(candidate.model_dump(), separators=(",", ":"))

        nzb = ET.Element("nzb", {"xmlns": NZB_NS})
        head = ET.SubElement(nzb, "head")
        ET.SubElement(head, "meta", {"type": "odrclone:candidate"}).text = payload
        file_node = ET.SubElement(
            nzb,
            "file",
            {
                "poster": "odrclone@localhost",
                "date": str(int(datetime.now(timezone.utc).timestamp())),
                "subject": candidate.filename,
            },
        )
        groups = ET.SubElement(file_node, "groups")
        ET.SubElement(groups, "group").text = "odrclone.virtual"
        segments = ET.SubElement(file_node, "segments")
        ET.SubElement(segments, "segment", {"bytes": "1", "number": "1"}).text = "odrclone@localhost"

        body = ET.tostring(nzb, encoding="utf-8", xml_declaration=True)
        headers = {"Content-Disposition": f'attachment; filename="{candidate.filename}.nzb"'}
        return Response(body, media_type="application/x-nzb", headers=headers)

    return router

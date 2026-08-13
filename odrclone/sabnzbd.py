from __future__ import annotations

import hmac
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from odrclone.schemas import Candidate


SAB_VERSION = "5.0.4"
DEFAULT_CATEGORIES = ["*", "sonarr", "radarr", "tv", "movies"]


def create_sabnzbd_router(state):
    router = APIRouter()

    def credentials_valid(request: Request) -> bool:
        params = request.query_params
        supplied_key = params.get("apikey")
        expected_key = state.settings.auth.api_token
        if supplied_key:
            if expected_key and hmac.compare_digest(supplied_key, expected_key):
                return True
            fallback_keys = {
                value
                for value in (
                    state.settings.auth.webdav_username,
                    state.settings.auth.webdav_password,
                )
                if value
            }
            return supplied_key in fallback_keys

        expected_user = state.settings.auth.webdav_username
        expected_password = state.settings.auth.webdav_password
        if not expected_user:
            return True

        supplied_user = params.get("ma_username", "")
        supplied_password = params.get("ma_password", "")
        return hmac.compare_digest(supplied_user, expected_user) and hmac.compare_digest(
            supplied_password,
            expected_password or "",
        )

    def auth_error() -> JSONResponse:
        return JSONResponse({"status": False, "error": "API Key Incorrect"})

    def clean_category(value: str | None) -> str:
        value = (value or "*").strip()
        if value == "*":
            return ""
        return re.sub(r"[^A-Za-z0-9._-]+", "_", value)[:64]

    def category_for_job(job) -> str:
        root = Path(state.settings.downloads.directory)
        parent = Path(job.target_path).parent
        try:
            relative = parent.relative_to(root)
            first = relative.parts[0] if relative.parts else ""
            return first or "*"
        except ValueError:
            return "*"

    def config_payload() -> dict:
        complete_dir = str(Path(state.settings.downloads.directory))
        categories = [
            {
                "priority": 0,
                "pp": "",
                "name": name,
                "script": "None",
                "dir": "" if name == "*" else name,
            }
            for name in DEFAULT_CATEGORIES
        ]
        return {
            "config": {
                "misc": {
                    "complete_dir": complete_dir,
                    "tv_categories": [],
                    "enable_tv_sorting": False,
                    "movie_categories": [],
                    "enable_movie_sorting": False,
                    "date_categories": [],
                    "enable_date_sorting": False,
                    "pre_check": False,
                    "history_retention": "all",
                    "history_retention_option": "all",
                    "history_retention_number": 0,
                },
                "categories": categories,
                "servers": [],
                "sorters": [],
            }
        }

    def job_id(job) -> str:
        return job.external_id or f"odrclone-{job.id}"

    def queue_payload() -> dict:
        slots = []
        for index, job in enumerate(state.downloads.list()):
            if job.status not in {"queued", "downloading"}:
                continue
            total = int(job.bytes_total or 0)
            done = int(job.bytes_done or 0)
            left = max(total - done, 0)
            percent = int((done / total) * 100) if total else 0
            speed = float(job.speed_bps or 0)
            seconds = int(left / speed) if speed > 0 else 0
            slots.append(
                {
                    "status": "Downloading" if job.status == "downloading" else "Queued",
                    "index": index,
                    "timeleft": f"0:00:{seconds:02d}" if seconds < 60 else "0:00:00",
                    "mb": total / 1048576,
                    "filename": job.filename,
                    "priority": "Normal",
                    "cat": category_for_job(job),
                    "mbleft": left / 1048576,
                    "percentage": percent,
                    "nzo_id": job_id(job),
                }
            )
        return {
            "queue": {
                "paused": False,
                "slots": slots,
                "noofslots": len(slots),
                "status": "Downloading" if slots else "Idle",
                "speed": "0",
                "mbleft": sum(float(slot["mbleft"]) for slot in slots),
                "mb": sum(float(slot["mb"]) for slot in slots),
                "my_home": str(Path(state.settings.downloads.directory).parent),
            }
        }

    def history_payload() -> dict:
        slots = []
        for job in state.downloads.list():
            if job.status not in {"complete", "failed", "cancelled"}:
                continue
            status = "Completed" if job.status == "complete" else "Failed"
            slots.append(
                {
                    "fail_message": job.error or "",
                    "bytes": int(job.bytes_total or job.bytes_done or 0),
                    "category": category_for_job(job),
                    "nzb_name": job.filename,
                    "download_time": 0,
                    "storage": str(Path(job.target_path).parent),
                    "status": status,
                    "nzo_id": job_id(job),
                    "name": job.filename,
                }
            )
        return {"history": {"paused": False, "slots": slots, "noofslots": len(slots)}}

    def extract_candidate(nzb_bytes: bytes) -> Candidate:
        try:
            root = ET.fromstring(nzb_bytes)
        except ET.ParseError as exc:
            raise ValueError("invalid NZB XML") from exc

        payload = None
        for node in root.iter():
            local_name = node.tag.rsplit("}", 1)[-1]
            if local_name == "meta" and node.attrib.get("type") == "odrclone:candidate":
                payload = node.text
                break

        if not payload:
            raise ValueError("NZB is not an OD-rclone release descriptor")

        try:
            data = json.loads(payload)
            return Candidate.model_validate(data).normalize()
        except Exception as exc:
            raise ValueError("invalid OD-rclone candidate metadata") from exc

    async def addfile(request: Request):
        try:
            form = await request.form()
            upload = form.get("name")
            if upload is None:
                return JSONResponse(
                    {"status": False, "error": "No NZB file supplied"},
                    status_code=400,
                )
            if hasattr(upload, "read"):
                nzb_bytes = await upload.read()
            else:
                nzb_bytes = str(upload).encode("utf-8")
            candidate = extract_candidate(nzb_bytes)
        except Exception as exc:
            return JSONResponse(
                {"status": False, "error": str(exc)},
                status_code=400,
            )

        category = clean_category(request.query_params.get("cat"))
        media_type = "movie" if category in {"movies", "radarr"} else "tv"
        virtual_category = category or "uncategorized"
        virtual_path = f"/Downloads/{virtual_category}/{candidate.filename}"

        vf = state.catalog.add_candidate(candidate, virtual_path, media_type)
        if not vf.sources:
            return JSONResponse(
                {"status": False, "error": "No usable source was attached to the virtual release"},
                status_code=400,
            )

        source = sorted(
            vf.sources,
            key=lambda item: (item.alive is True, item.score),
            reverse=True,
        )[0]
        target_dir = Path(state.settings.downloads.directory)
        if category:
            target_dir = target_dir / category
        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            job = await state.downloads.create(vf, source, str(target_dir))
        except Exception as exc:
            return JSONResponse(
                {"status": False, "error": f"Unable to create OD-rclone download job: {exc}"},
                status_code=500,
            )

        return {"status": True, "nzo_ids": [job_id(job)]}

    @router.api_route("/api", methods=["GET", "POST"])
    async def sabnzbd_api(request: Request):
        mode = request.query_params.get("mode", "").lower()

        if mode == "version":
            return {"version": SAB_VERSION}
        if mode == "auth":
            return {"auth": "login" if state.settings.auth.webdav_username else "none"}

        if not credentials_valid(request):
            return auth_error()

        if mode == "get_config":
            return config_payload()
        if mode == "get_cats":
            return {"categories": DEFAULT_CATEGORIES}
        if mode == "fullstatus":
            return {"status": {"completedir": str(Path(state.settings.downloads.directory))}}
        if mode == "addfile":
            return await addfile(request)
        if mode == "queue":
            if request.query_params.get("name") in {"delete", "pause", "resume"}:
                return {"status": True}
            return queue_payload()
        if mode == "history":
            if request.query_params.get("name") == "delete":
                return {"status": True}
            return history_payload()
        if mode in {"pause", "resume"}:
            return {"status": True}

        return JSONResponse(
            {"status": False, "error": f"Unsupported SABnzbd API mode: {mode or '(empty)'}"},
            status_code=400,
        )

    return router

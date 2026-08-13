from __future__ import annotations

import hmac
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


SAB_VERSION = "5.0.4"
DEFAULT_CATEGORIES = ["*", "sonarr", "radarr", "tv", "movies"]


def create_sabnzbd_router(state):
    router = APIRouter()

    def credentials_valid(request: Request) -> bool:
        params = request.query_params
        supplied_key = params.get("apikey")
        expected_key = state.settings.auth.api_token
        if supplied_key:
            return bool(expected_key) and hmac.compare_digest(supplied_key, expected_key)

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

    def config_payload() -> dict:
        complete_dir = str(Path(state.settings.downloads.directory))
        categories = [
            {
                "priority": 0,
                "pp": "",
                "name": name,
                "script": "None",
                "dir": "",
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
                    "cat": "*",
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
                    "category": "*",
                    "nzb_name": job.filename,
                    "download_time": 0,
                    "storage": str(Path(job.target_path).parent),
                    "status": status,
                    "nzo_id": job_id(job),
                    "name": job.filename,
                }
            )
        return {"history": {"paused": False, "slots": slots, "noofslots": len(slots)}}

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

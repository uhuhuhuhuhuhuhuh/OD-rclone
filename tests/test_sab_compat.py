from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from odrclone.sabnzbd import create_sabnzbd_router


class Downloads:
    def __init__(self, directory: Path):
        self.config = SimpleNamespace(directory=str(directory))

    def list(self):
        return []


def make_client(tmp_path, username="Zark", password="Zark"):
    state = SimpleNamespace(
        settings=SimpleNamespace(
            auth=SimpleNamespace(
                api_token=None,
                webdav_username=username,
                webdav_password=password,
            ),
            downloads=SimpleNamespace(directory=str(tmp_path / "downloads")),
        ),
        downloads=Downloads(tmp_path / "downloads"),
    )
    app = FastAPI()
    app.include_router(create_sabnzbd_router(state))
    return TestClient(app)


def test_version_does_not_require_auth(tmp_path):
    response = make_client(tmp_path).get("/api", params={"mode": "version", "output": "json"})
    assert response.status_code == 200
    assert response.json()["version"] == "5.0.4"


def test_get_config_accepts_servarr_ma_credentials(tmp_path):
    response = make_client(tmp_path).get(
        "/api",
        params={
            "mode": "get_config",
            "ma_username": "Zark",
            "ma_password": "Zark",
            "output": "json",
        },
    )
    assert response.status_code == 200
    payload = response.json()["config"]
    assert payload["misc"]["complete_dir"].endswith("downloads")
    assert {row["name"] for row in payload["categories"]} >= {"*", "sonarr", "radarr"}


def test_get_config_rejects_wrong_credentials(tmp_path):
    response = make_client(tmp_path).get(
        "/api",
        params={"mode": "get_config", "ma_username": "bad", "ma_password": "bad"},
    )
    assert response.status_code == 200
    assert response.json()["status"] is False


def test_queue_and_history_are_servarr_parseable_shapes(tmp_path):
    client = make_client(tmp_path)
    auth = {"ma_username": "Zark", "ma_password": "Zark", "output": "json"}
    queue = client.get("/api", params={"mode": "queue", **auth}).json()["queue"]
    history = client.get("/api", params={"mode": "history", **auth}).json()["history"]
    assert queue["slots"] == []
    assert queue["paused"] is False
    assert history["slots"] == []
    assert history["paused"] is False
